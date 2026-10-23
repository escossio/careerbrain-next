package com.escossio.careerbrain

import java.io.ByteArrayOutputStream
import java.io.InputStream

/** Contract-shaped client boundary. Production HTTP is deliberately injected only in pass 10. */
const val MAX_PDF_BYTES = 5_242_880

enum class ApplicationState { SAVED, APPLIED, INTERVIEW, OFFER, REJECTED, WITHDRAWN }
data class Session(val accessToken: String, val refreshToken: String)
data class Recommendation(val id: String, val title: String, val organization: String, val access: String, val reason: String, val uncertain: Boolean, val version: Long = 0)
data class SyncChange(val sequence: Long, val recommendationId: String, val kind: String)
data class SyncPage(val items: List<SyncChange>, val nextCursor: String, val snapshotHighWatermark: Long, val hasMore: Boolean)
data class Application(val recommendationId: String, val state: ApplicationState, val version: Long)
data class DeletionReceipt(val id: String, val state: String, val activeDeadline: String, val backupDeadline: String)

sealed interface ApiResult<out T> { data class Ok<T>(val value: T): ApiResult<T>; data class Http(val status: Int): ApiResult<Nothing>; data object Offline: ApiResult<Nothing> }
interface CareerBrainApi {
    suspend fun syntheticLogin(): ApiResult<Session>
    suspend fun refresh(session: Session): ApiResult<Session>
    suspend fun uploadPdf(bytes: ByteArray): ApiResult<String>
    suspend fun recommendations(cursor: String?): ApiResult<Pair<List<Recommendation>, String?>>
    suspend fun changes(cursor: String?): ApiResult<SyncPage>
    suspend fun acknowledge(ids: List<String>, requestId: String): ApiResult<Unit>
    suspend fun setApplication(id: String, state: ApplicationState, expectedVersion: Long, requestId: String): ApiResult<Application>
    suspend fun deleteAccount(requestId: String): ApiResult<DeletionReceipt>
}

/** Reads one byte past the cap without retaining it, so untrusted documents never fill memory. */
fun readPdfAtMost(input: InputStream, maxBytes: Int = MAX_PDF_BYTES): ByteArray? {
    val output = ByteArrayOutputStream(minOf(maxBytes, 8192))
    val buffer = ByteArray(8192)
    var remaining = maxBytes
    while (remaining > 0) {
        val count = input.read(buffer, 0, minOf(buffer.size, remaining))
        if (count < 0) return output.toByteArray()
        if (count == 0) continue
        output.write(buffer, 0, count)
        remaining -= count
    }
    return if (input.read() == -1) output.toByteArray() else null
}

class FakeCareerBrainApi : CareerBrainApi {
    private val recommendations = linkedMapOf(
        "synthetic-1" to Recommendation("synthetic-1", "Analista de Dados", "Organização sintética", "https://example.org/vaga", "EVIDENCED_AFFINITY", false),
        "synthetic-2" to Recommendation("synthetic-2", "Técnica de manutenção", "Organização sintética", "jobs@example.org", "REQUIREMENT_UNKNOWN", true)
    )
    private val changes = mutableListOf<SyncChange>()
    private val applications = mutableMapOf<String, Application>()
    private val applicationReplays = mutableMapOf<String, Pair<String, ApiResult<Application>>>()
    private var sequence = 0L
    private var offlineChanges = 0
    private var offlineAcknowledgements = 0

    init { recommendations.keys.forEach { recordChange(it, "AVAILABLE") } }

    /** Test-only deterministic network failure; a retry returns the same page and IDs. */
    fun failNextChanges(times: Int = 1) { offlineChanges = times }
    fun failNextAcknowledledgements(times: Int = 1) { offlineAcknowledgements = times }
    fun removeRecommendation(id: String) { if (recommendations.remove(id) != null) recordChange(id, "REMOVED") }

    override suspend fun syntheticLogin() = ApiResult.Ok(Session("synthetic-access", "synthetic-refresh"))
    override suspend fun refresh(session: Session) = if (session.refreshToken == "synthetic-refresh") ApiResult.Ok(session) else ApiResult.Http(401)
    override suspend fun uploadPdf(bytes: ByteArray) = if (bytes.size in 1..MAX_PDF_BYTES && bytes.take(4).toByteArray().decodeToString() == "%PDF") ApiResult.Ok("READY") else ApiResult.Http(422)
    override suspend fun recommendations(cursor: String?): ApiResult<Pair<List<Recommendation>, String?>> {
        val start = cursor?.toIntOrNull() ?: 0
        val page = recommendations.values.drop(start).take(1)
        val next = (start + page.size).takeIf { it < recommendations.size }?.toString()
        return ApiResult.Ok(page to next)
    }
    override suspend fun changes(cursor: String?): ApiResult<SyncPage> {
        if (offlineChanges > 0) { offlineChanges--; return ApiResult.Offline }
        val parsed = cursor?.split(':')?.mapNotNull { it.toLongOrNull() }
        val previousHighWatermark = parsed?.getOrNull(0) ?: 0L
        val previousPosition = parsed?.getOrNull(1) ?: 0L
        val highWatermark = if (previousPosition >= previousHighWatermark) sequence else previousHighWatermark
        val page = changes.filter { it.sequence > previousPosition && it.sequence <= highWatermark }.take(1)
        val position = page.lastOrNull()?.sequence ?: previousPosition
        val hasMore = changes.any { it.sequence > position && it.sequence <= highWatermark }
        return ApiResult.Ok(SyncPage(page, "$highWatermark:$position", highWatermark, hasMore))
    }
    override suspend fun acknowledge(ids: List<String>, requestId: String): ApiResult<Unit> {
        if (offlineAcknowledgements > 0) { offlineAcknowledgements--; return ApiResult.Offline }
        return ApiResult.Ok(Unit)
    }
    override suspend fun setApplication(id: String, state: ApplicationState, expectedVersion: Long, requestId: String): ApiResult<Application> {
        val command = "$id:$state:$expectedVersion"
        applicationReplays[requestId]?.let { return if (it.first == command) it.second else ApiResult.Http(409) }
        val current = applications[id]
        val result: ApiResult<Application> = if ((current?.version ?: 0) != expectedVersion) ApiResult.Http(409)
        else ApiResult.Ok(Application(id, state, expectedVersion + 1).also { applications[id] = it })
        applicationReplays[requestId] = command to result
        return result
    }
    override suspend fun deleteAccount(requestId: String) = ApiResult.Ok(DeletionReceipt("synthetic-receipt", "ACTIVE_DATA_REMOVED", "synthetic+24h", "synthetic+30d"))

    private fun recordChange(id: String, kind: String) { changes += SyncChange(++sequence, id, kind) }
}
