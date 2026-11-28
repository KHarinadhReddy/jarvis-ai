package ai.jarvis.mobile.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class ToolFunction(val name: String, val arguments: String = "{}")

@Serializable
data class ToolCall(
    val id: String = "",
    val type: String = "function",
    val function: ToolFunction = ToolFunction(""),
)

@Serializable
data class ApiMessage(
    val role: String,
    val content: String? = null,
    @SerialName("tool_calls") val toolCalls: List<ToolCall>? = null,
    @SerialName("tool_call_id") val toolCallId: String? = null,
    val name: String? = null,
)

@Serializable
data class ChatRequest(
    val messages: List<ApiMessage>,
    val thinking: Boolean = false,
    val voice: Boolean = true,
    val model: String? = null,
    @SerialName("max_tokens") val maxTokens: Int = 2048,
    val tools: List<JsonElement> = emptyList(),
    val context: String = "",
)

@Serializable
data class ChatEvent(
    val type: String,
    val text: String? = null,
    val message: String? = null,
    @SerialName("tool_call") val toolCall: ToolCall? = null,
)

@Serializable
data class HealthInfo(
    val status: String = "unknown",
    val version: String = "",
    val provider: String = "",
    val model: String = "",
    val vision: Boolean = false,
    val tts: String = "",
    val telugu_tts: Boolean = false,
    val configured: Boolean = false,
)

@Serializable
data class SpeechRequest(
    val text: String,
    val language: String? = null,
    val voice: String? = null,
    val gender: String = "male",
    val rate: String? = null,
    val pitch: String? = null,
)

@Serializable
data class SpeechClip(
    val text: String = "",
    val voice: String = "",
    @SerialName("audio_b64") val audioB64: String = "",
    @SerialName("pause_after_ms") val pauseAfterMs: Int = 300,
    @SerialName("breath_after") val breathAfter: Boolean = false,
)

@Serializable
data class SpeechBundle(
    val language: String = "en-IN",
    val normalized: String = "",
    val clips: List<SpeechClip> = emptyList(),
)

@Serializable
data class VisionObject(val label: String = "", val details: String = "")

@Serializable
data class VisionAnalysis(
    val description: String = "",
    val objects: List<VisionObject> = emptyList(),
    val text: String = "",
    val translation: String = "",
    val answer: String = "",
    val safety: String = "",
)

@Serializable
data class VisionResponse(
    val mode: String = "",
    val result: VisionAnalysis = VisionAnalysis(),
    val provider: String = "",
    val model: String = "",
)

class ApiException(message: String, val code: Int = 0) : Exception(message)
