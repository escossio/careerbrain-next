package com.escossio.careerbrain

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
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
        setContent { MaterialTheme { CareerBrainScreen(viewModel.state.value, viewModel) { pdf.launch(arrayOf("application/pdf")) } } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun CareerBrainScreen(state: ScreenState, model: CareerBrainViewModel, choosePdf: () -> Unit) {
    var confirmDelete by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    Scaffold(topBar = { TopAppBar(title = { Text("CareerBrain Next") }) }) { padding ->
        Column(Modifier.padding(padding).padding(16.dp).fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(state.message, modifier = Modifier.semantics { contentDescription = "Estado: ${state.message}" })
            if (state.session == null) Button(onClick = model::login, modifier = Modifier.fillMaxWidth()) { Text("Entrar com identidade sintética") }
            else {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = choosePdf) { Text("Selecionar PDF") }
                    OutlinedButton(onClick = model::synchronize) { Text("Sincronizar") }
                }
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.weight(1f)) {
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
