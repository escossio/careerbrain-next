package com.escossio.careerbrain

import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withText
import org.junit.Test

class MainActivityInstrumentedTest {
    @Test fun cleanStartShowsSyntheticSignIn() {
        ActivityScenario.launch(MainActivity::class.java).use {
            onView(withText("Entrar com identidade sintética")).check(matches(isDisplayed()))
        }
    }
}
