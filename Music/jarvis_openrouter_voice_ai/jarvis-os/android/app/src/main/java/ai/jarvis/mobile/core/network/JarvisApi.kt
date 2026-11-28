package ai.jarvis.mobile.core.network

import ai.jarvis.mobile.core.data.SettingsStore
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

class JarvisApi(
    private val settingsStore: SettingsStore,
    private val client: OkHttpClient = defaultClient(),
) {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        encodeDefaults = true
        isLenient = true
    }

    private suspend fun baseUrl(): String {
        val value = settingsStore.snapshot().backendUrl.trim().trimEnd('/')
        if (value.isBlank()) throw ApiException("Backend URL is not set. Open Settings and enter your server address.")
        return value
    }

    private suspend fun authHeader(): String {
        val token = settingsStore.snapshot().deviceToken.trim()
        if (token.isBlank()) throw ApiException("Device token is not set. Open Settings and enter the pairing token.")
        return "Bearer $token"
    }

    suspend fun health(): HealthInfo = withContext(Dispatchers.IO) {
        val url = "${baseUrl()}/v1/health"
        val request = Request.Builder().url(url).get().build()
        try {
            client.newCall(request).execute().use { response ->
                val body = response.body.string()
                if (!response.isSuccessful) {
                    throw ApiException("Health check failed (HTTP ${response.code})", response.code)
                }
                json.decodeFromString(HealthInfo.serializer(), body)
            }
        } catch (error: ApiException) {
            throw error
        } catch (error: IOException) {
            throw ApiException("Cannot reach the backend at ${baseUrl()}. Check Wi-Fi, the URL, and that the server is running.")
        } catch (error: Exception) {
            throw ApiException("Backend returned an unreadable health response: ${error.message}")
        }
    }

    fun streamChat(
        messages: List<ApiMessage>,
        thinking: Boolean,
        voice: Boolean,
        tools: List<JsonElement>,
        context: String,
    ): Flow<ChatEvent> = callbackFlow {
        val base = runCatching { baseUrl() }.getOrElse {
            trySend(ChatEvent(type = "error", message = it.message ?: "Backend URL is not set"))
            close()
            return@callbackFlow
        }
        val auth = runCatching { authHeader() }.getOrElse {
            trySend(ChatEvent(type = "error", message = it.message ?: "Device token is not set"))
            close()
            return@callbackFlow
        }
        val payload = ChatRequest(
            messages = messages,
            thinking = thinking,
            voice = voice,
            tools = tools,
            context = context,
        )
        val body = json.encodeToString(ChatRequest.serializer(), payload)
            .toRequestBody("application/json; charset=utf-8".toMediaType())
        val request = Request.Builder()
            .url("$base/v1/chat/stream")
            .header("Authorization", auth)
            .header("Accept", "text/event-stream")
            .post(body)
            .build()
        val call = client.newCall(request)
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, error: IOException) {
                trySend(ChatEvent(type = "error", message = "Connection lost: ${error.message ?: "network error"}"))
                close()
            }

            override fun onResponse(call: Call, response: Response) {
                response.use { res ->
                    if (!res.isSuccessful) {
                        val text = runCatching { res.body.string() }.getOrDefault("")
                        trySend(
                            ChatEvent(
                                type = "error",
                                message = "Backend error ${res.code}: ${text.take(300).ifBlank { "no details" }}",
                            )
                        )
                        close()
                        return
                    }
                    val source = res.body.source()
                    try {
                        while (!source.exhausted()) {
                            val line = source.readUtf8Line() ?: break
                            if (!line.startsWith("data:")) continue
                            val data = line.removePrefix("data:").trim()
                            if (data.isEmpty()) continue
                            val event = runCatching {
                                json.decodeFromString(ChatEvent.serializer(), data)
                            }.getOrNull() ?: continue
                            if (event.type == "error") {
                                trySend(event)
                                close()
                                return
                            }
                            trySend(event)
                        }
                        close()
                    } catch (error: IOException) {
                        trySend(ChatEvent(type = "error", message = "Stream interrupted: ${error.message}"))
                        close()
                    }
                }
            }
        })
        awaitClose { call.cancel() }
    }

    suspend fun speechSegments(
        text: String,
        language: String?,
        gender: String,
    ): SpeechBundle = withContext(Dispatchers.IO) {
        val payload = SpeechRequest(text = text.take(1600), language = language, gender = gender)
        val body = json.encodeToString(SpeechRequest.serializer(), payload)
            .toRequestBody("application/json; charset=utf-8".toMediaType())
        val request = Request.Builder()
            .url("${baseUrl()}/v1/tts/segments")
            .header("Authorization", authHeader())
            .post(body)
            .build()
        try {
            client.newCall(request).execute().use { response ->
                val raw = response.body.string()
                if (!response.isSuccessful) {
                    throw ApiException("Speech failed (HTTP ${response.code}): ${raw.take(300)}", response.code)
                }
                json.decodeFromString(SpeechBundle.serializer(), raw)
            }
        } catch (error: ApiException) {
            throw error
        } catch (error: IOException) {
            throw ApiException("Speech backend unreachable: ${error.message}")
        }
    }

    suspend fun analyzeImage(
        bytes: ByteArray,
        mime: String,
        mode: String,
        question: String,
    ): VisionResponse = withContext(Dispatchers.IO) {
        val imageBody = bytes.toRequestBody(mime.toMediaType())
        val multipart = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("image", "capture.jpg", imageBody)
            .addFormDataPart("mode", mode)
            .addFormDataPart("question", question)
            .build()
        val request = Request.Builder()
            .url("${baseUrl()}/v1/vision/analyze")
            .header("Authorization", authHeader())
            .post(multipart)
            .build()
        try {
            client.newCall(request).execute().use { response ->
                val raw = response.body.string()
                if (!response.isSuccessful) {
                    throw ApiException("Vision failed (HTTP ${response.code}): ${raw.take(300)}", response.code)
                }
                json.decodeFromString(VisionResponse.serializer(), raw)
            }
        } catch (error: ApiException) {
            throw error
        } catch (error: IOException) {
            throw ApiException("Vision backend unreachable: ${error.message}")
        }
    }

    companion object {
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(150, TimeUnit.SECONDS)
            .writeTimeout(45, TimeUnit.SECONDS)
            .callTimeout(180, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }
}
