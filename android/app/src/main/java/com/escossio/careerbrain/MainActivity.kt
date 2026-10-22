package com.escossio.careerbrain

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.clickable
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
    private val viewModel: CareerBrainViewModel by viewModels()
    private val pdf = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@registerForActivityResult
        contentResolver.openInputStream(uri)?.use { viewModel.upload(it.readBytes()) }
    }
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState)
        setContent { MaterialTheme { CareerBrainScreen(viewModel.state.value, viewModel, { pdf.launch(arrayOf("application/pdf")) }) } }
    }
}

@Composable private fun CareerBrainScreen(state: ScreenState, model: CareerBrainViewModel, choosePdf: () -> Unit) {
    var confirmDelete by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    Scaffold(topBar = { TopAppBar(title = { Text("CareerBrain Next") }) }) { padding ->
        Column(Modifier.padding(padding).padding(16.dp).fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(state.message, modifier = Modifier.semantics { contentDescription = "Estado: ${state.message}" })
            if (state.session == null) Button(onClick = model::login, modifier = Modifier.fillMaxWidth()) { Text("Entrar com identidade sintética") }
            else {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Button(onClick = choosePdf) { Text("Selecionar PDF") }; OutlinedButton(onClick = model::refresh) { Text("Sincronizar") } }
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.weight(1f)) { items(state.items, key = { it.id }) { item -> RecommendationCard(item, { model.save(item) }) } }
                OutlinedButton(onClick = { confirmDelete = true }, modifier = Modifier.fillMaxWidth()) { Text("Excluir conta") }
            }
            state.deleting?.let { Text("Exclusão: ${it.state}. Backup pendente até ${it.backupDeadline}") }
        }
    }
    if (confirmDelete) AlertDialog(onDismissRequest = { confirmDelete = false }, title = { Text("Excluir conta?") }, text = { Text("A sessão e os dados locais serão removidos. A exclusão no servidor pode ainda ter pendências de backup.") }, confirmButton = { Button(onClick = { confirmDelete = false; model.delete() }) { Text("Confirmar exclusão") } }, dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancelar") } })
}

@Composable private fun RecommendationCard(item: Recommendation, save: () -> Unit) = Card(Modifier.fillMaxWidth().semantics { contentDescription = "Oportunidade ${item.title}" }) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) { Text(item.title, style = MaterialTheme.typography.titleMedium); Text(item.organization); Text(item.access); Text(if (item.uncertain) "Compatibilidade incerta: ${item.reason}" else "Justificativa comprovada: ${item.reason}"); Button(onClick = save) { Text("Salvar oportunidade") } } }
