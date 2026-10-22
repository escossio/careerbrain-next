package com.escossio.careerbrain

/** Contract-shaped client boundary. Production HTTP is deliberately injected only in pass 10. */
enum class ApplicationState { SAVED, APPLIED, INTERVIEW, OFFER, REJECTED, WITHDRAWN }
data class Session(val accessToken: String, val refreshToken: String)
data class Recommendation(val id: String, val title: String, val organization: String, val access: String, val reason: String, val uncertain: Boolean, val version: Long = 0)
data class SyncChange(val sequence: Long, val recommendationId: String, val kind: String)
data class Application(val recommendationId: String, val state: ApplicationState, val version: Long)
data class DeletionReceipt(val id: String, val state: String, val activeDeadline: String, val backupDeadline: String)

sealed interface ApiResult<out T> { data class Ok<T>(val value: T): ApiResult<T>; data class Http(val status: Int): ApiResult<Nothing>; data object Offline: ApiResult<Nothing> }
interface CareerBrainApi {
    suspend fun syntheticLogin(): ApiResult<Session>
    suspend fun refresh(session: Session): ApiResult<Session>
    suspend fun uploadPdf(bytes: ByteArray): ApiResult<String>
    suspend fun recommendations(cursor: String?): ApiResult<Pair<List<Recommendation>, String?>>
    suspend fun changes(cursor: String?): ApiResult<Pair<List<SyncChange>, String>>
    suspend fun acknowledge(ids: List<String>, requestId: String): ApiResult<Unit>
    suspend fun setApplication(id: String, state: ApplicationState, expectedVersion: Long, requestId: String): ApiResult<Application>
    suspend fun deleteAccount(requestId: String): ApiResult<DeletionReceipt>
}

class FakeCareerBrainApi : CareerBrainApi {
    private val recommendations = linkedMapOf("synthetic-1" to Recommendation("synthetic-1", "Analista de Dados", "Organização sintética", "https://example.org/vaga", "EVIDENCED_AFFINITY", false), "synthetic-2" to Recommendation("synthetic-2", "Técnica de manutenção", "Organização sintética", "jobs@example.org", "REQUIREMENT_UNKNOWN", true))
    private val applications = mutableMapOf<String, Application>()
    private val applicationReplays = mutableMapOf<String, Pair<String, ApiResult<Application>>>()
    private var sequence = 2L
    override suspend fun syntheticLogin() = ApiResult.Ok(Session("synthetic-access", "synthetic-refresh"))
    override suspend fun refresh(session: Session) = if (session.refreshToken == "synthetic-refresh") ApiResult.Ok(session) else ApiResult.Http(401)
    override suspend fun uploadPdf(bytes: ByteArray) = if (bytes.size in 1..5_242_880 && bytes.take(4).toByteArray().decodeToString() == "%PDF") ApiResult.Ok("READY") else ApiResult.Http(422)
    override suspend fun recommendations(cursor: String?): ApiResult<Pair<List<Recommendation>, String?>> {
        val start = cursor?.toIntOrNull() ?: 0
        val page = recommendations.values.drop(start).take(1)
        val next = (start + page.size).takeIf { it < recommendations.size }?.toString()
        return ApiResult.Ok(page to next)
    }
    override suspend fun changes(cursor: String?): ApiResult<Pair<List<SyncChange>, String>> {
        val after = cursor?.toLongOrNull() ?: 0L
        val changes = recommendations.keys.mapIndexed { i, id -> SyncChange((i + 1).toLong(), id, "AVAILABLE") }.filter { it.sequence > after }
        return ApiResult.Ok(changes to sequence.toString())
    }
    override suspend fun acknowledge(ids: List<String>, requestId: String) = ApiResult.Ok(Unit)
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
}
