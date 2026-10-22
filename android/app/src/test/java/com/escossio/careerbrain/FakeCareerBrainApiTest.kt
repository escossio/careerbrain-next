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
    @Test fun replayIsIdempotentAndIncompatibleReuseConflicts() = runBlocking {
        val api = FakeCareerBrainApi()
        val first = api.setApplication("synthetic-1", ApplicationState.SAVED, 0, "request-1") as ApiResult.Ok
        val replay = api.setApplication("synthetic-1", ApplicationState.SAVED, 0, "request-1") as ApiResult.Ok
        assertEquals(first.value, replay.value)
        assertEquals(409, (api.setApplication("synthetic-1", ApplicationState.APPLIED, 1, "request-1") as ApiResult.Http).status)
    }
    @Test fun recommendationsAreStablePagesAndChangesUseCursor() = runBlocking {
        val api = FakeCareerBrainApi()
        val first = (api.recommendations(null) as ApiResult.Ok).value
        val second = (api.recommendations(first.second) as ApiResult.Ok).value
        assertNotEquals(first.first.single().id, second.first.single().id)
        assertEquals(2, (api.changes(null) as ApiResult.Ok).value.first.size)
        assertTrue((api.changes("2") as ApiResult.Ok).value.first.isEmpty())
    }
}
