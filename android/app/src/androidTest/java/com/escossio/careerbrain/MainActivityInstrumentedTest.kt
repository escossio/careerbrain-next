package com.escossio.careerbrain

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertExists
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import org.junit.Rule
import org.junit.Test

/** Instrumented Compose-semantic UI checks against a synthetic-only backend. */
class MainActivityInstrumentedTest {
    @get:Rule val composeRule = createAndroidComposeRule<MainActivity>()

    private fun awaitText(text: String) {
        composeRule.waitUntil(timeoutMillis = 15_000) {
            composeRule.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
        }
    }

    @Test fun cleanStartShowsSyntheticSignIn() {
        composeRule.onNodeWithText("Entrar com identidade sintética").assertIsDisplayed()
    }

    @Test fun syntheticFlowShowsSecondPageSavesSyncsAndCleansLocalState() {
        composeRule.onNodeWithText("Entrar com identidade sintética").performClick()
        awaitText("Analista de Dados")
        composeRule.onNodeWithText("Analista de Dados").assertExists()
        composeRule.onNodeWithText("Carregar próxima oportunidade").performClick()
        awaitText("Técnica de manutenção")
        composeRule.onNodeWithText("Técnica de manutenção").assertExists()
        composeRule.onAllNodesWithText("Salvar oportunidade").onFirst().performClick()
        awaitText("Estado registrado: SAVED (1)")
        composeRule.onNodeWithText("Sincronizar").performClick()
        awaitText("Sincronização concluída até 2")
        composeRule.onNodeWithText("Excluir conta").performClick()
        composeRule.onNodeWithText("Confirmar exclusão").performClick()
        awaitText("Dados locais removidos")
        composeRule.onNodeWithText("Entrar com identidade sintética").assertExists()
    }
}
