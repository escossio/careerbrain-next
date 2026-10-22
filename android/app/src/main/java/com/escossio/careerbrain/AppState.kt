package com.escossio.careerbrain

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch

data class ScreenState(val session: Session? = null, val items: List<Recommendation> = emptyList(), val message: String = "Entre para ver oportunidades", val deleting: DeletionReceipt? = null)
class CareerBrainViewModel(private val api: CareerBrainApi = FakeCareerBrainApi()) : ViewModel() {
    var state = androidx.compose.runtime.mutableStateOf(ScreenState()); private set
    fun login() = viewModelScope.launch { when (val r = api.syntheticLogin()) { is ApiResult.Ok -> { state.value = state.value.copy(session = r.value, message = "Sessão sintética ativa"); refresh() }; else -> state.value = state.value.copy(message = "Não foi possível entrar") } }
    fun refresh() = viewModelScope.launch { when (val r = api.recommendations(null)) { is ApiResult.Ok -> state.value = state.value.copy(items = r.value.first, message = "Recomendações atualizadas"); is ApiResult.Http -> state.value = state.value.copy(message = "Erro HTTP ${r.status}"); ApiResult.Offline -> state.value = state.value.copy(message = "Sem conexão; tente novamente") } }
    fun save(item: Recommendation) = viewModelScope.launch { val current = item.version; when (val r = api.setApplication(item.id, ApplicationState.SAVED, current, "save-${item.id}")) { is ApiResult.Ok -> state.value = state.value.copy(message = "Oportunidade salva (${r.value.version})"); is ApiResult.Http -> state.value = state.value.copy(message = if (r.status == 409) "Conflito: atualize antes de tentar" else "Erro HTTP ${r.status}"); else -> Unit } }
    fun upload(bytes: ByteArray) = viewModelScope.launch { if (bytes.size > 5_242_880) { state.value = state.value.copy(message = "PDF excede 5 MiB"); return@launch }; when (val r = api.uploadPdf(bytes)) { is ApiResult.Ok -> state.value = state.value.copy(message = "Perfil ${r.value}"); else -> state.value = state.value.copy(message = "PDF inválido ou processamento indisponível") } }
    fun delete() = viewModelScope.launch { when (val r = api.deleteAccount("delete-local")) { is ApiResult.Ok -> state.value = ScreenState(message = "Dados locais removidos", deleting = r.value); else -> state.value = state.value.copy(message = "Exclusão não confirmada") } }
}
