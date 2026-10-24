package com.escossio.careerbrain

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import android.os.SystemClock

interface SyncCursorStore { fun load(): String?; fun save(cursor: String); fun clear() }
class InMemorySyncCursorStore : SyncCursorStore {
    private var cursor: String? = null
    override fun load() = cursor
    override fun save(cursor: String) { this.cursor = cursor }
    override fun clear() { cursor = null }
}

/** Only the opaque sync cursor is retained; encrypted preferences and allowBackup=false protect it. */
class EncryptedSyncCursorStore(context: Context) : SyncCursorStore {
    private val preferences = EncryptedSharedPreferences.create(
        context,
        "careerbrain_sync",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )
    override fun load() = preferences.getString("cursor", null)
    override fun save(cursor: String) { preferences.edit().putString("cursor", cursor).apply() }
    override fun clear() { preferences.edit().clear().apply() }
}

data class SyncOutcome(val items: List<Recommendation>, val message: String)
class SyncCoordinator(private val api: CareerBrainApi, private val cursors: SyncCursorStore) {
    suspend fun synchronize(current: List<Recommendation>): SyncOutcome {
        var cursor = cursors.load()
        val local = current.associateByTo(linkedMapOf()) { it.id }
        repeat(100) {
            val page = when (val result = api.changes(cursor)) {
                is ApiResult.Ok -> result.value
                is ApiResult.Http -> return SyncOutcome(local.values.toList(), "Não foi possível atualizar as oportunidades. Tente novamente.")
                ApiResult.Offline -> return SyncOutcome(local.values.toList(), "Sem conexão; tente sincronizar novamente")
            }
            page.items.forEach { change -> if (change.kind == "REMOVED") local.remove(change.recommendationId) }
            val acknowledgementIds = page.items.map { it.recommendationId }.distinct()
            if (acknowledgementIds.isNotEmpty()) when (val acknowledgement = api.acknowledge(acknowledgementIds, "ack-${page.nextCursor}")) {
                is ApiResult.Http -> return SyncOutcome(local.values.toList(), "Não foi possível confirmar a atualização. Tente novamente.")
                ApiResult.Offline -> return SyncOutcome(local.values.toList(), "Sem conexão; tente sincronizar novamente")
                is ApiResult.Ok -> Unit
            }
            cursors.save(page.nextCursor)
            cursor = page.nextCursor
            if (!page.hasMore) return SyncOutcome(local.values.toList(),
                if (page.snapshotHighWatermark == 0L && local.isEmpty()) "Nenhuma nova oportunidade encontrada"
                else "Atualização concluída")
        }
        return SyncOutcome(local.values.toList(), "Sincronização interrompida; tente novamente")
    }
}

data class ScreenState(
    val session: Session? = null,
    val items: List<Recommendation> = emptyList(),
    val recommendationCursor: String? = null,
    val applications: Map<String, Application> = emptyMap(),
    val message: String = "Entre para ver oportunidades",
    val deleting: DeletionReceipt? = null,
    val resume: ResumeJobStatus? = null,
    val resumeElapsedSeconds: Int = 0,
    val resumePolling: Boolean = false,
    val resumeCheckError: String? = null
)

/** Progress is based only on actual server status, never fabricated percentages. */
fun resumeProgressText(progress: ResumeJobStatus, seconds: Int): String = when (progress.status) {
    "PENDING" -> if (seconds >= 45) "Na fila há cerca de ${seconds}s; está demorando mais que o esperado"
                 else "Currículo recebido • aguardando processamento"
    "PROCESSING" -> if (seconds >= 60) "Processando há cerca de ${seconds}s; ainda sem confirmação de conclusão"
                    else "Currículo em processamento no servidor"
    "READY" -> "Perfil profissional concluído • análise disponível"
    "UNCERTAIN" -> "Processamento concluído • informações profissionais insuficientes"
    "FAILED" -> "Falha no processamento do currículo"
    "EXPIRED" -> "Processamento expirou antes da conclusão"
    "CANCELLED" -> "Processamento cancelado"
    else -> "Estado não reconhecido; verifique novamente"
}
private fun resumeTerminal(status: String) =
    status in setOf("READY", "UNCERTAIN", "FAILED", "EXPIRED", "CANCELLED")

class CareerBrainViewModel(
    private val api: CareerBrainApi = CareerBrainApiFactory.create(),
    private val cursors: SyncCursorStore = InMemorySyncCursorStore()
) : ViewModel() {
    var state = androidx.compose.runtime.mutableStateOf(ScreenState()); private set
    private val sync = SyncCoordinator(api, cursors)
    private var resumePollingJob: Job? = null

    fun usesGoogleLogin() = CareerBrainApiFactory.isGoogleConfigured()
    fun login() = viewModelScope.launch {
        when (val result = api.syntheticLogin()) {
            is ApiResult.Ok -> { state.value = state.value.copy(session = result.value, message = "Sessão sintética ativa"); refreshRecommendations(reset = true); checkResumeProgress() }
            is ApiResult.Http -> state.value = state.value.copy(message = "Serviço temporariamente indisponível. Tente novamente.")
            ApiResult.Offline -> state.value = state.value.copy(message = "Sem conexão; tente novamente")
        }
    }
    fun beginGoogleLogin(onChallenge: (LoginChallenge) -> Unit) = viewModelScope.launch {
        when (val result = api.challenge()) {
            is ApiResult.Ok -> onChallenge(result.value)
            is ApiResult.Http -> state.value = state.value.copy(message = "Serviço temporariamente indisponível. Tente novamente.")
            ApiResult.Offline -> state.value = state.value.copy(message = "Sem conexão; tente novamente")
        }
    }
    fun completeGoogleLogin(idToken: String, challengeId: String) = viewModelScope.launch {
        when (val result = api.googleLogin(idToken, challengeId)) {
            is ApiResult.Ok -> { state.value = state.value.copy(session = result.value, message = "Sessão ativa"); refreshRecommendations(reset = true); checkResumeProgress() }
            is ApiResult.Http -> state.value = state.value.copy(message = if (result.status == 401) "Autenticação recusada" else "Erro HTTP ${result.status}")
            ApiResult.Offline -> state.value = state.value.copy(message = "Sem conexão; tente novamente")
        }
    }
    fun refreshRecommendations(reset: Boolean = false) = viewModelScope.launch {
        val cursor = if (reset) null else state.value.recommendationCursor
        when (val result = api.recommendations(cursor)) {
            is ApiResult.Ok -> {
                val items = if (reset) result.value.first else state.value.items + result.value.first.filter { candidate -> state.value.items.none { it.id == candidate.id } }
                state.value = state.value.copy(items = items, recommendationCursor = result.value.second, message = "Recomendações atualizadas")
            }
            is ApiResult.Http -> state.value = state.value.copy(
                message = when (result.status) {
                    401 -> "Sessão Google expirada. Entre novamente para carregar as vagas."
                    503 -> "Servidor de vagas indisponível. Tente novamente."
                    else -> "Não foi possível consultar as oportunidades."
                },
                session = if (result.status == 401) null else state.value.session
            )
            ApiResult.Offline -> state.value = state.value.copy(message = "Sem conexão; tente novamente")
        }
    }
    fun synchronize() = viewModelScope.launch { sync.synchronize(state.value.items).also { outcome -> state.value = state.value.copy(items = outcome.items, message = outcome.message) } }
    fun setApplication(item: Recommendation, next: ApplicationState) = viewModelScope.launch {
        val current = state.value.applications[item.id]
        val expectedVersion = current?.version ?: 0
        val requestId = "application-${item.id}-${expectedVersion}-${next.name}"
        when (val result = api.setApplication(item.id, next, expectedVersion, requestId)) {
            is ApiResult.Ok -> state.value = state.value.copy(applications = state.value.applications + (item.id to result.value), message = "Estado registrado: ${result.value.state} (${result.value.version})")
            is ApiResult.Http -> state.value = state.value.copy(message = if (result.status == 409) "Conflito: atualize antes de tentar" else "Erro HTTP ${result.status}")
            ApiResult.Offline -> state.value = state.value.copy(message = "Sem conexão; tente novamente")
        }
    }
    fun upload(bytes: ByteArray) = viewModelScope.launch {
        if (bytes.size > MAX_PDF_BYTES) { state.value = state.value.copy(message = "PDF excede 5 MiB"); return@launch }
        state.value = state.value.copy(message = "Enviando currículo • aguardando confirmação")
        when (val result = api.uploadPdf(bytes)) {
            is ApiResult.Ok -> {
                resumePollingJob?.cancel()
                state.value = state.value.copy(message = "Currículo recebido", resume = result.value,
                    resumeElapsedSeconds = 0, resumePolling = false, resumeCheckError = null)
                if (resumeTerminal(result.value.status)) {
                    if (result.value.status in setOf("READY", "UNCERTAIN")) refreshRecommendations(reset = true)
                } else startResumePolling(result.value.jobId)
            }
            is ApiResult.Http -> state.value = state.value.copy(message = "Envio recusado pelo servidor (HTTP ${result.status})")
            ApiResult.Offline -> state.value = state.value.copy(message = "Sem conexão durante o envio; verifique antes de reenviar")
        }
    }

    /** Rechecks the last server-side job after login, restart, or manual action. No PDF is resent. */
    fun checkResumeProgress() = viewModelScope.launch {
        if (state.value.session == null) return@launch
        val known = state.value.resume?.jobId
        val result = if (known == null) api.latestResumeStatus() else api.resumeStatus(known)
        when (result) {
            is ApiResult.Ok -> {
                val same = known == result.value.jobId
                state.value = state.value.copy(resume = result.value,
                    resumeElapsedSeconds = if (same) state.value.resumeElapsedSeconds else 0,
                    resumeCheckError = null)
                if (resumeTerminal(result.value.status)) {
                    resumePollingJob?.cancel()
                    state.value = state.value.copy(resumePolling = false)
                    if (result.value.status in setOf("READY", "UNCERTAIN")) refreshRecommendations(reset = true)
                } else startResumePolling(result.value.jobId)
            }
            is ApiResult.Http -> {
                state.value = state.value.copy(resumeCheckError =
                    if (result.status == 410 && known == null) null
                    else "Consulta de andamento indisponível (HTTP ${result.status}); tente novamente")
            }
            ApiResult.Offline -> state.value = state.value.copy(resumeCheckError =
                "Servidor não respondeu. O trabalho pode continuar; toque Verificar andamento")
        }
    }

    private fun startResumePolling(jobId: String) {
        resumePollingJob?.cancel()
        resumePollingJob = viewModelScope.launch {
            state.value = state.value.copy(resumePolling = true)
            val started = SystemClock.elapsedRealtime() - state.value.resumeElapsedSeconds * 1000L
            repeat(40) {
                delay(3000)
                if (state.value.resume?.jobId != jobId || state.value.session == null) return@launch
                val seconds = ((SystemClock.elapsedRealtime() - started) / 1000).toInt().coerceAtLeast(0)
                when (val result = api.resumeStatus(jobId)) {
                    is ApiResult.Ok -> {
                        state.value = state.value.copy(resume = result.value, resumeElapsedSeconds = seconds,
                            resumeCheckError = null)
                        if (resumeTerminal(result.value.status)) {
                            state.value = state.value.copy(resumePolling = false)
                            if (result.value.status in setOf("READY", "UNCERTAIN")) refreshRecommendations(reset = true)
                            return@launch
                        }
                    }
                    is ApiResult.Http -> state.value = state.value.copy(resumeElapsedSeconds = seconds,
                        resumeCheckError = "Sem confirmação recente (HTTP ${result.status}); consulta automática continua")
                    ApiResult.Offline -> state.value = state.value.copy(resumeElapsedSeconds = seconds,
                        resumeCheckError = "Sem resposta recente da API; processamento ainda não confirmado")
                }
            }
            state.value = state.value.copy(resumePolling = false,
                resumeCheckError = "Acompanhamento automático pausado após 2 minutos. Toque Verificar andamento")
        }
    }

    fun rejectOversizedPdf() { state.value = state.value.copy(message = "PDF excede 5 MiB") }
    fun delete() = viewModelScope.launch {
        resumePollingJob?.cancel()
        when (val result = api.deleteAccount("delete-local")) {
            is ApiResult.Ok -> { cursors.clear(); state.value = ScreenState(message = "Dados locais removidos", deleting = result.value) }
            is ApiResult.Http -> state.value = state.value.copy(message = "Serviço temporariamente indisponível. Tente novamente.")
            ApiResult.Offline -> state.value = state.value.copy(message = "Exclusão não confirmada; sem conexão")
        }
    }

    companion object {
        fun factory(context: Context): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = CareerBrainViewModel(cursors = EncryptedSyncCursorStore(context.applicationContext)) as T
        }
    }
}
