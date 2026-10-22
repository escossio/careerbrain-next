package com.escossio.careerbrain

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class FakeCareerBrainApiTest {
    @Test fun fakeUsesApplicationCasAndNeverSendsExternalApplication() = runBlocking {
        val api = FakeCareerBrainApi(); assertTrue(api.setApplication("synthetic-1", ApplicationState.APPLIED, 0, "one") is ApiResult.Ok)
        assertEquals(409, (api.setApplication("synthetic-1", ApplicationState.OFFER, 0, "two") as ApiResult.Http).status)
    }
    @Test fun fakeRejectsNonPdfOrOversizedUpload() = runBlocking { assertEquals(422, (FakeCareerBrainApi().uploadPdf("text".encodeToByteArray()) as ApiResult.Http).status) }
}
