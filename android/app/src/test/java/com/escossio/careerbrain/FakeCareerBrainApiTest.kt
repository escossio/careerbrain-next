package com.escossio.careerbrain

import java.io.ByteArrayInputStream
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class FakeCareerBrainApiTest {
    @Test fun fakeUsesApplicationCasAndNeverSendsExternalApplication() = runBlocking {
        val api = FakeCareerBrainApi(); assertTrue(api.setApplication("synthetic-1", ApplicationState.APPLIED, 0, "one") is ApiResult.Ok)
        assertEquals(409, (api.setApplication("synthetic-1", ApplicationState.OFFER, 0, "two") as ApiResult.Http).status)
    }

    @Test fun replayIsIdempotentAndIncompatibleReuseConflicts() = runBlocking {
        val api = FakeCareerBrainApi()
        val first = api.setApplication("synthetic-1", ApplicationState.SAVED, 0, "request-1") as ApiResult.Ok
        val replay = api.setApplication("synthetic-1", ApplicationState.SAVED, 0, "request-1") as ApiResult.Ok
        assertEquals(first.value, replay.value)
        assertEquals(409, (api.setApplication("synthetic-1", ApplicationState.APPLIED, 1, "request-1") as ApiResult.Http).status)
    }

    @Test fun recommendationsHaveStableSecondPageAndChangesKeepAHighWatermark() = runBlocking {
        val api = FakeCareerBrainApi()
        val first = (api.recommendations(null) as ApiResult.Ok).value
        val second = (api.recommendations(first.second) as ApiResult.Ok).value
        assertNotEquals(first.first.single().id, second.first.single().id)
        val syncFirst = (api.changes(null) as ApiResult.Ok).value
        assertEquals(2, syncFirst.snapshotHighWatermark); assertTrue(syncFirst.hasMore)
        val syncSecond = (api.changes(syncFirst.nextCursor) as ApiResult.Ok).value
        assertEquals(2, syncSecond.snapshotHighWatermark); assertFalse(syncSecond.hasMore)
    }

    @Test fun syncRetriesSamePageAfterOfflineAckAndOnlyThenPersistsCursor() = runBlocking {
        val api = FakeCareerBrainApi(); val cursors = InMemorySyncCursorStore(); val coordinator = SyncCoordinator(api, cursors)
        api.failNextAcknowledledgements()
        val offline = coordinator.synchronize(recommendations(api))
        assertTrue(offline.message.startsWith("Sem conexão")); assertNull(cursors.load())
        val recovered = coordinator.synchronize(offline.items)
        assertEquals("2:2", cursors.load()); assertTrue(recovered.message.startsWith("Sincronização concluída"))
    }

    @Test fun offlineChangesDoNotAdvanceCursorAndCanBeRetried() = runBlocking {
        val api = FakeCareerBrainApi(); val cursors = InMemorySyncCursorStore(); val coordinator = SyncCoordinator(api, cursors)
        api.failNextChanges()
        assertTrue(coordinator.synchronize(recommendations(api)).message.startsWith("Sem conexão")); assertNull(cursors.load())
        coordinator.synchronize(recommendations(api))
        assertEquals("2:2", cursors.load())
    }

    @Test fun removedChangeDeletesLocalRecommendationAndNewCursorIsIncremental() = runBlocking {
        val api = FakeCareerBrainApi(); val cursors = InMemorySyncCursorStore(); cursors.save("2:2")
        api.removeRecommendation("synthetic-1")
        val outcome = SyncCoordinator(api, cursors).synchronize(recommendations(api, includeRemoved = true))
        assertEquals(listOf("synthetic-2"), outcome.items.map { it.id }); assertEquals("3:3", cursors.load())
    }

    @Test fun fakeRejectsNonPdfAndBoundedReaderNeverRetainsMoreThanFiveMiB() = runBlocking {
        assertEquals(422, (FakeCareerBrainApi().uploadPdf("text".encodeToByteArray()) as ApiResult.Http).status)
        assertNull(readPdfAtMost(ByteArrayInputStream(ByteArray(MAX_PDF_BYTES + 1))))
        assertEquals(MAX_PDF_BYTES, readPdfAtMost(ByteArrayInputStream(ByteArray(MAX_PDF_BYTES)))!!.size)
    }

    @Test fun resumeProgressShowsActualStagesAndSlowStateWithoutFictitiousPercentage() {
        val job = ResumeJobStatus("00000000-0000-4000-8000-000000000001", "PENDING")
        assertTrue(resumeProgressText(job, 3).contains("aguardando"))
        assertTrue(resumeProgressText(job, 47).contains("demorando"))
        assertTrue(resumeProgressText(job.copy(status = "PROCESSING"), 8).contains("processamento"))
        assertTrue(resumeProgressText(job.copy(status = "READY"), 90).contains("concluído"))
        assertTrue(resumeProgressText(job.copy(status = "FAILED"), 90).contains("Falha"))
        assertFalse(resumeProgressText(job, 47).contains("%"))
    }

    @Test fun fakeResumeCanBeRecheckedWithoutResendingPdf() = runBlocking {
        val api = FakeCareerBrainApi()
        assertEquals(410, (api.latestResumeStatus() as ApiResult.Http).status)
        val uploaded = api.uploadPdf("%PDF-1.4".encodeToByteArray()) as ApiResult.Ok
        assertEquals("READY", uploaded.value.status)
        assertEquals(uploaded.value, (api.resumeStatus(uploaded.value.jobId) as ApiResult.Ok).value)
        assertEquals(uploaded.value, (api.latestResumeStatus() as ApiResult.Ok).value)
        assertEquals(410, (api.resumeStatus("00000000-0000-4000-8000-000000000099") as ApiResult.Http).status)
    }

    @Test fun clearingCursorRepresentsControlledReinstallBootstrapWithoutPersistingSession() {
        val cursors = InMemorySyncCursorStore(); cursors.save("2:2"); cursors.clear()
        assertNull(cursors.load())
    }

    private suspend fun recommendations(api: CareerBrainApi, includeRemoved: Boolean = false): List<Recommendation> {
        val first = (api.recommendations(null) as ApiResult.Ok).value
        val second = first.second?.let { (api.recommendations(it) as ApiResult.Ok).value.first } ?: emptyList()
        return if (includeRemoved) listOf(
            Recommendation("synthetic-1", "removida", "synthetic", "", "", false),
            Recommendation("synthetic-2", "Técnica de manutenção", "Organização sintética", "jobs@example.org", "REQUIREMENT_UNKNOWN", true)
        ) else first.first + second
    }
}
