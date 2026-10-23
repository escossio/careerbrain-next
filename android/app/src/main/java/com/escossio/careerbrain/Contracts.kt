package com.escossio.careerbrain

import android.content.Context
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/** Contract-shaped client boundary. Production HTTP is deliberately injected only in pass 10. */
const val MAX_PDF_BYTES = 5_242_880

enum class ApplicationState { SAVED, APPLIED, INTERVIEW, OFFER, REJECTED, WITHDRAWN }
data class Session(val accessToken: String, val refreshToken: String)
data class LoginChallenge(val id: String, val nonce: String)
data class Recommendation(val id: String, val title: String, val organization: String, val access: String, val reason: String, val uncertain: Boolean, val version: Long = 0)
data class SyncChange(val sequence: Long, val recommendationId: String, val kind: String)
data class SyncPage(val items: List<SyncChange>, val nextCursor: String, val snapshotHighWatermark: Long, val hasMore: Boolean)
data class Application(val recommendationId: String, val state: ApplicationState, val version: Long)
data class DeletionReceipt(val id: String, val state: String, val activeDeadline: String, val backupDeadline: String)

sealed interface ApiResult<out T> { data class Ok<T>(val value: T): ApiResult<T>; data class Http(val status: Int): ApiResult<Nothing>; data object Offline: ApiResult<Nothing> }
interface CareerBrainApi {
    suspend fun syntheticLogin(): ApiResult<Session>
    suspend fun challenge(): ApiResult<LoginChallenge>
    suspend fun googleLogin(idToken: String, challengeId: String): ApiResult<Session>
    suspend fun refresh(session: Session): ApiResult<Session>
    suspend fun uploadPdf(bytes: ByteArray): ApiResult<String>
    suspend fun recommendations(cursor: String?): ApiResult<Pair<List<Recommendation>, String?>>
    suspend fun changes(cursor: String?): ApiResult<SyncPage>
    suspend fun acknowledge(ids: List<String>, requestId: String): ApiResult<Unit>
    suspend fun setApplication(id: String, state: ApplicationState, expectedVersion: Long, requestId: String): ApiResult<Application>
    suspend fun tts(notificationId: String, template: String, count: Int): ApiResult<ByteArray>
    suspend fun deleteAccount(requestId: String): ApiResult<DeletionReceipt>
}

/** Build configuration is intentionally empty in source: an HTTPS endpoint is opted in at build time. */
object CareerBrainApiFactory {
    fun create(): CareerBrainApi = BuildConfig.CAREERBRAIN_API_BASE_URL.takeIf { it.isNotBlank() }
        ?.let(::HttpCareerBrainApi) ?: FakeCareerBrainApi()
    fun isGoogleConfigured() = BuildConfig.CAREERBRAIN_API_BASE_URL.isNotBlank() && BuildConfig.CAREERBRAIN_GOOGLE_WEB_CLIENT_ID.isNotBlank()
}

/** Credential Manager obtains a Google proof only after the backend issued its one-use nonce. */
class GoogleIdentityProvider(private val context: Context) {
    suspend fun idToken(webClientId: String, nonce: String): ApiResult<String> = try {
        val option = GetGoogleIdOption.Builder().setServerClientId(webClientId).setNonce(nonce)
            .setFilterByAuthorizedAccounts(false).build()
        val request = GetCredentialRequest.Builder().addCredentialOption(option).build()
        val credential = CredentialManager.create(context).getCredential(context, request).credential
        if (credential is CustomCredential && credential.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL)
            ApiResult.Ok(GoogleIdTokenCredential.createFrom(credential.data).idToken)
        else ApiResult.Http(401)
    } catch (_: Exception) { ApiResult.Offline }
}

/** HTTPS-only client. It never accepts tenant/user fields and retries only a request that has an idempotency key. */
class HttpCareerBrainApi(baseUrl: String) : CareerBrainApi {
    private val base = URI(baseUrl).normalize().also {
        require(it.scheme == "https" && it.host != null && it.userInfo == null && it.query == null && it.fragment == null)
    }.toString().trimEnd('/')
    private var session: Session? = null

    override suspend fun syntheticLogin(): ApiResult<Session> = ApiResult.Http(401)
    override suspend fun challenge(): ApiResult<LoginChallenge> = json("POST", "/v1/auth/challenges", null).map { LoginChallenge(it.getString("challenge_id"), it.getString("nonce")) }
    override suspend fun googleLogin(idToken: String, challengeId: String): ApiResult<Session> = json("POST", "/v1/auth/google", JSONObject().put("id_token", idToken).put("challenge_id", challengeId)).mapSession()
    override suspend fun refresh(session: Session): ApiResult<Session> = json("POST", "/v1/auth/refresh", JSONObject().put("refresh_token", session.refreshToken)).mapSession()
    override suspend fun uploadPdf(bytes: ByteArray): ApiResult<String> {
        val boundary = "careerbrain-${System.nanoTime()}"
        val metadata = JSONObject().put("schema_version", "careerbrain.resume-upload.v1").put("request_id", "resume-${System.nanoTime()}")
            .put("content_type", "application/pdf").put("content_length", bytes.size).put("consent_version", "privacy-v1")
        val prefix = "--$boundary\r\nContent-Disposition: form-data; name=\"metadata\"\r\n\r\n$metadata\r\n--$boundary\r\nContent-Disposition: form-data; name=\"file\"\r\n\r\n".encodeToByteArray()
        val suffix = "\r\n--$boundary--\r\n".encodeToByteArray()
        return request("POST", "/v1/me/resume", prefix + bytes + suffix, "multipart/form-data; boundary=$boundary", idempotency = metadata.getString("request_id")).map { JSONObject(it.decodeToString()).getString("state") }
    }
    override suspend fun recommendations(cursor: String?): ApiResult<Pair<List<Recommendation>, String?>> = json("GET", "/v1/recommendations" + cursor.query("cursor"), null).map { page ->
        page.getJSONArray("items").toRecommendations() to page.optString("next_cursor").ifBlank { null }
    }
    override suspend fun changes(cursor: String?): ApiResult<SyncPage> = json("GET", "/v1/recommendations/changes" + cursor.query("cursor"), null).map { page ->
        val items = page.getJSONArray("items").let { array -> (0 until array.length()).map { i -> array.getJSONObject(i).let { SyncChange(it.getLong("sequence"), it.getString("recommendation_id"), it.getString("kind")) } } }
        SyncPage(items, page.getString("next_cursor"), page.getLong("snapshot_high_watermark"), page.getBoolean("has_more"))
    }
    override suspend fun acknowledge(ids: List<String>, requestId: String): ApiResult<Unit> = json("POST", "/v1/recommendations/ack", JSONObject().put("schema_version", "careerbrain.sync-ack.v1").put("recommendation_ids", JSONArray(ids)).put("request_id", requestId), requestId).unit()
    override suspend fun setApplication(id: String, state: ApplicationState, expectedVersion: Long, requestId: String): ApiResult<Application> = json("PUT", "/v1/applications", JSONObject().put("schema_version", "careerbrain.application.v1").put("publication_event_id", id).put("state", state.name).put("expected_version", expectedVersion).put("request_id", requestId), requestId).map { Application(id, state, expectedVersion + 1) }
    override suspend fun tts(notificationId: String, template: String, count: Int): ApiResult<ByteArray> = request("POST", "/v1/notifications/tts", JSONObject().put("schema_version", "careerbrain.tts.v1").put("notification_id", notificationId).put("template", template).put("count", count).put("language", "pt-BR").toString().encodeToByteArray(), "application/json")
    override suspend fun deleteAccount(requestId: String): ApiResult<DeletionReceipt> = json("DELETE", "/v1/me", null, requestId).map { DeletionReceipt(it.getString("receipt_id"), it.getString("state"), it.getString("active_data_deadline"), it.getString("backup_expiry_deadline")) }

    private suspend fun json(method: String, path: String, payload: JSONObject?, idempotency: String? = null): ApiResult<JSONObject> = request(method, path, payload?.toString()?.encodeToByteArray(), "application/json", idempotency).map { JSONObject(it.decodeToString()) }
    private suspend fun request(method: String, path: String, body: ByteArray?, contentType: String, idempotency: String? = null): ApiResult<ByteArray> = withContext(Dispatchers.IO) {
        fun execute(access: String?): ApiResult<ByteArray> = try {
            val connection = (URL(base + path).openConnection() as HttpURLConnection).apply {
                requestMethod = method; connectTimeout = 10_000; readTimeout = 20_000; instanceFollowRedirects = false
                setRequestProperty("Accept", "application/json"); if (access != null) setRequestProperty("Authorization", "Bearer $access")
                if (idempotency != null) setRequestProperty("Idempotency-Key", idempotency)
                if (body != null) { doOutput = true; setRequestProperty("Content-Type", contentType); outputStream.use { it.write(body) } }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.use { it.readBytes() } ?: ByteArray(0)
            connection.disconnect(); if (status in 200..299) ApiResult.Ok(response) else ApiResult.Http(status)
        } catch (_: Exception) { ApiResult.Offline }
        val first = execute(session?.accessToken)
        if (first !is ApiResult.Http || first.status != 401 || session == null || (method != "GET" && idempotency == null)) first
        else when (val renewed = refresh(session!!)) {
            is ApiResult.Ok -> execute(renewed.value.accessToken)
            is ApiResult.Http -> ApiResult.Http(renewed.status)
            ApiResult.Offline -> ApiResult.Offline
        }
    }
    private fun ApiResult<JSONObject>.mapSession(): ApiResult<Session> = map { Session(it.getString("access_token"), it.getString("refresh_token")).also { next -> session = next } }
}

private fun String?.query(name: String) = this?.let { "?${name}=${java.net.URLEncoder.encode(it, "UTF-8")}" } ?: ""
private fun JSONArray.toRecommendations(): List<Recommendation> = (0 until length()).map { index -> getJSONObject(index).let { item ->
    val match = item.getJSONObject("match"); val access = item.opt("access")
    Recommendation(item.getString("recommendation_id"), item.getString("title"), item.optString("organization"), if (access is JSONObject) access.optString("value") else "", match.optJSONArray("reasons")?.join(", ") ?: "", match.isNull("affinity"), 0)
} }
private fun <T, R> ApiResult<T>.map(transform: (T) -> R): ApiResult<R> = when (this) { is ApiResult.Ok -> try { ApiResult.Ok(transform(value)) } catch (_: Exception) { ApiResult.Http(422) }; is ApiResult.Http -> this; ApiResult.Offline -> ApiResult.Offline }
private fun ApiResult<JSONObject>.unit(): ApiResult<Unit> = map { Unit }

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
    override suspend fun challenge() = ApiResult.Ok(LoginChallenge("synthetic-challenge", "synthetic-nonce"))
    override suspend fun googleLogin(idToken: String, challengeId: String) = if (idToken == "synthetic-token" && challengeId == "synthetic-challenge") syntheticLogin() else ApiResult.Http(401)
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
    override suspend fun tts(notificationId: String, template: String, count: Int) = ApiResult.Http(503)
    override suspend fun deleteAccount(requestId: String) = ApiResult.Ok(DeletionReceipt("synthetic-receipt", "ACTIVE_DATA_REMOVED", "synthetic+24h", "synthetic+30d"))

    private fun recordChange(id: String, kind: String) { changes += SyncChange(++sequence, id, kind) }
}
