package com.escossio.careerbrain

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    private val viewModel: CareerBrainViewModel by viewModels { CareerBrainViewModel.factory(applicationContext) }
    private val pdf = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@registerForActivityResult
        val bytes = contentResolver.openInputStream(uri)?.use(::readPdfAtMost)
        if (bytes == null) viewModel.rejectOversizedPdf() else viewModel.upload(bytes)
    }
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState)
        setContent { MaterialTheme { CareerBrainScreen(viewModel.state.value, viewModel, onLogin = {
            if (!viewModel.usesGoogleLogin()) viewModel.login()
            else viewModel.beginGoogleLogin { challenge -> lifecycleScope.launch {
                when (val token = GoogleIdentityProvider(this@MainActivity).idToken(BuildConfig.CAREERBRAIN_GOOGLE_WEB_CLIENT_ID, challenge.nonce)) {
                    is ApiResult.Ok -> viewModel.completeGoogleLogin(token.value, challenge.id)
                    is ApiResult.Http -> viewModel.state.value = viewModel.state.value.copy(message = "Autenticação recusada")
                    ApiResult.Offline -> viewModel.state.value = viewModel.state.value.copy(message = "Login Google indisponível")
                }
            } }
        }) { pdf.launch(arrayOf("application/pdf")) } } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun CareerBrainScreen(state: ScreenState, model: CareerBrainViewModel, onLogin: () -> Unit, choosePdf: () -> Unit) {
    var confirmDelete by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    var confirmUpload by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    Scaffold(topBar = { TopAppBar(title = { Text("CareerBrain Next") }) }) { padding ->
        Column(Modifier.padding(padding).padding(16.dp).fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(state.message, modifier = Modifier.semantics { contentDescription = "Estado: ${state.message}" })
            if (state.session == null) Button(onClick = onLogin, modifier = Modifier.fillMaxWidth()) { Text(if (model.usesGoogleLogin()) "Entrar com Google" else "Entrar com identidade sintética") }
            else {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { confirmUpload = true }) { Text("Selecionar PDF") }
                    OutlinedButton(onClick = model::synchronize) { Text("Sincronizar") }
                }
                state.resume?.let { progress ->
                    Card(Modifier.fillMaxWidth().semantics { contentDescription =
                        "Andamento do currículo: ${resumeProgressText(progress, state.resumeElapsedSeconds)}" }) {
                        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("Andamento do currículo", style = MaterialTheme.typography.titleMedium)
                            Text(resumeProgressText(progress, state.resumeElapsedSeconds))
                            if (progress.status in setOf("PENDING", "PROCESSING")) {
                                if (state.resumePolling) {
                                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                                    Text("Consultando o servidor automaticamente a cada 3 segundos",
                                         style = MaterialTheme.typography.bodySmall)
                                } else Text("Acompanhamento pausado; o processamento pode continuar",
                                            style = MaterialTheme.typography.bodySmall)
                            }
                            state.resumeCheckError?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                            if (progress.status in setOf("PENDING", "PROCESSING")) {
                                OutlinedButton(onClick = model::checkResumeProgress) { Text("Verificar andamento") }
                            }
                        }
                    }
                } ?: run {
                    state.resumeCheckError?.let { Text(it) }
                    OutlinedButton(onClick = model::checkResumeProgress) { Text("Consultar último currículo") }
                }
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.weight(1f)) {
                    if (state.items.isEmpty()) {
                        item {
                            Text(if (state.resume?.status == "UNCERTAIN")
                                "Ainda não há recomendações: a análise do currículo não identificou qualificações suficientes."
                                else "Nenhuma oportunidade disponível nesta consulta.")
                        }
                    }
                    items(state.items, key = { it.id }) { item -> RecommendationCard(item, state.applications[item.id], model::setApplication) }
                    state.recommendationCursor?.let { item {
                        OutlinedButton(onClick = { model.refreshRecommendations() }, modifier = Modifier.fillMaxWidth()) { Text("Carregar próxima oportunidade") }
                    } }
                }
                OutlinedButton(onClick = { confirmDelete = true }, modifier = Modifier.fillMaxWidth()) { Text("Excluir conta") }
            }
            state.deleting?.let { Text("Exclusão: ${it.state}. Backup pendente até ${it.backupDeadline}") }
        }
    }
    if (confirmDelete) AlertDialog(onDismissRequest = { confirmDelete = false }, title = { Text("Excluir conta?") }, text = { Text("A sessão e os dados locais serão removidos. A exclusão no servidor pode ainda ter pendências de backup.") }, confirmButton = { Button(onClick = { confirmDelete = false; model.delete() }) { Text("Confirmar exclusão") } }, dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancelar") } })
    if (confirmUpload) AlertDialog(onDismissRequest = { confirmUpload = false }, title = { Text("Enviar currículo?") }, text = { Text("O PDF será processado temporariamente para gerar o perfil. Prossiga somente se concordar com a política de privacidade aplicável.") }, confirmButton = { Button(onClick = { confirmUpload = false; choosePdf() }) { Text("Concordar e selecionar PDF") } }, dismissButton = { TextButton(onClick = { confirmUpload = false }) { Text("Cancelar") } })
}

@Composable private fun RecommendationCard(item: Recommendation, application: Application?, setApplication: (Recommendation, ApplicationState) -> Unit) {
    var statesOpen by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    Card(Modifier.fillMaxWidth().semantics { contentDescription = "Oportunidade ${item.title}" }) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(item.title, style = MaterialTheme.typography.titleMedium)
            Text(item.organization)
            Text(item.access)
            Text(if (item.uncertain) "Compatibilidade incerta: ${item.reason}" else "Justificativa comprovada: ${item.reason}")
            application?.let { Text("Estado atual: ${it.state} (${it.version})") }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { setApplication(item, ApplicationState.SAVED) }) { Text("Salvar oportunidade") }
                OutlinedButton(onClick = { statesOpen = true }) { Text("Definir estado") }
                DropdownMenu(expanded = statesOpen, onDismissRequest = { statesOpen = false }) {
                    ApplicationState.values().forEach { next -> DropdownMenuItem(text = { Text(next.name) }, onClick = { statesOpen = false; setApplication(item, next) }) }
                }
            }
        }
    }
}
