package com.escossio.careerbrain

import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.containsString
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withText
import org.junit.Test

class MainActivityInstrumentedTest {
    @Test fun cleanStartShowsSyntheticSignIn() {
        ActivityScenario.launch(MainActivity::class.java).use {
            onView(withText("Entrar com identidade sintética")).check(matches(isDisplayed()))
        }
    }

    @Test fun syntheticFlowShowsSecondPageSavesSyncsAndCleansLocalState() {
        ActivityScenario.launch(MainActivity::class.java).use {
            onView(withText("Entrar com identidade sintética")).perform(click())
            onView(withText("Analista de Dados")).check(matches(isDisplayed()))
            onView(withText("Carregar próxima oportunidade")).perform(click())
            onView(withText("Técnica de manutenção")).check(matches(isDisplayed()))
            onView(withText("Salvar oportunidade")).perform(click())
            onView(withText(containsString("Estado registrado: SAVED"))).check(matches(isDisplayed()))
            onView(withText("Sincronizar")).perform(click())
            onView(withText(containsString("Sincronização concluída"))).check(matches(isDisplayed()))
            onView(withText("Excluir conta")).perform(click())
            onView(withText("Confirmar exclusão")).perform(click())
            onView(withText("Entrar com identidade sintética")).check(matches(isDisplayed()))
            onView(withText(containsString("Dados locais removidos"))).check(matches(isDisplayed()))
        }
    }
}
