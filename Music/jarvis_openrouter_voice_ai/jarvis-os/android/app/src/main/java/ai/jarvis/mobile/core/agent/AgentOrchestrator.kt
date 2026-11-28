package ai.jarvis.mobile.core.agent

import ai.jarvis.mobile.core.data.JarvisDatabase
import ai.jarvis.mobile.core.data.SettingsStore
import ai.jarvis.mobile.core.network.ApiException
import ai.jarvis.mobile.core.network.ApiMessage
import ai.jarvis.mobile.core.network.JarvisApi
import ai.jarvis.mobile.core.network.ToolCall
import ai.jarvis.mobile.core.system.ToolOutcome
import ai.jarvis.mobile.core.system.ToolRegistry
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.flow.collect

data class AgentResult(
    val text: String,
    val usedTools: List<String> = emptyList(),
)

class AgentOrchestrator(
    private val api: JarvisApi,
    private val tools: ToolRegistry,
    private val settingsStore: SettingsStore,
    private val database: JarvisDatabase,
) {

    suspend fun run(
        history: List<ai.jarvis.mobile.core.data.MessageEntity>,
        userText: String,
        onToken: (String) -> Unit,
        onReset: () -> Unit,
        onStatus: (String) -> Unit,
        confirm: suspend (ToolOutcome) -> Boolean,
    ): AgentResult {
        val local = tools.parseLocalAction(userText)
        if (local != null) {
            onStatus("Direct command: ${local.label}")
            if (tools.isConsequential(local.tool)) {
                onStatus("Confirmation needed: ${local.label}")
                val preview = ToolOutcome(
                    tool = local.tool,
                    success = false,
                    message = local.label,
                    resultJson = "{}",
                    consequential = true,
                    confirmationLabel = local.label,
                )
                if (!confirm(preview)) {
                    return AgentResult("Cancelled. I did not perform that action.")
                }
            }
            val outcome = runCatching { tools.execute(local.tool, local.args.toString()) }
                .getOrElse {
                    ToolOutcome(
                        tool = local.tool,
                        success = false,
                        message = "Command failed: ${it.message}",
                        resultJson = """{"success":false,"message":"Command failed"}""",
                    )
                }
            return AgentResult(outcome.message, listOf(local.tool))
        }

        val settings = settingsStore.snapshot()
        val context = buildContext()
        val messages = history
            .filter { it.role == "user" || it.role == "assistant" }
            .filter { it.content.isNotBlank() }
            .takeLast(24)
            .map { ApiMessage(role = it.role, content = it.content) }
            .toMutableList()

        val used = mutableListOf<String>()
        var lastText = ""

        repeat(3) { round ->
            onReset()
            val builder = StringBuilder()
            val calls = mutableListOf<ToolCall>()
            api.streamChat(
                messages = messages.toList(),
                thinking = settings.thinking,
                voice = true,
                tools = tools.schemas(),
                context = context,
            ).collect { event ->
                when (event.type) {
                    "token" -> {
                        val token = event.text.orEmpty()
                        if (token.isNotEmpty()) {
                            builder.append(token)
                            onToken(token)
                        }
                    }
                    "tool_call" -> event.toolCall?.let { calls += it }
                    "error" -> throw ApiException(event.message ?: "The AI stream returned an error")
                    "done" -> Unit
                }
            }
            val text = builder.toString().trim()
            if (text.isNotBlank()) lastText = text
            if (calls.isEmpty()) {
                return AgentResult(
                    text.ifBlank {
                        "The model returned no text. Nothing was changed on the phone."
                    },
                    used.distinct(),
                )
            }

            val normalized = calls.mapIndexed { index, call ->
                if (call.id.isBlank()) call.copy(id = "call_${round}_$index") else call
            }
            messages += ApiMessage(role = "assistant", content = text, toolCalls = normalized)

            for (call in normalized) {
                val name = call.function.name
                val label = name.replace('.', ' ').replace('_', ' ')
                if (tools.isConsequential(name)) {
                    val preview = ToolOutcome(
                        tool = name,
                        success = false,
                        message = "",
                        resultJson = "{}",
                        consequential = true,
                        confirmationLabel = tools.confirmationFor(name, call.function.arguments),
                    )
                    onStatus("Confirmation needed: ${preview.confirmationLabel}")
                    if (!confirm(preview)) {
                        messages += ApiMessage(
                            role = "tool",
                            content = """{"success":false,"message":"The user declined this action. It did not happen."}""",
                            toolCallId = call.id,
                            name = name,
                        )
                        continue
                    }
                }
                onStatus("Running $label")
                val outcome = runCatching { tools.execute(name, call.function.arguments) }
                    .getOrElse {
                        ToolOutcome(
                            tool = name,
                            success = false,
                            message = "Tool failed: ${it.message}",
                            resultJson = """{"success":false,"message":"Tool failed"}""",
                        )
                    }
                used += name
                onStatus(outcome.message)
                messages += ApiMessage(
                    role = "tool",
                    content = outcome.resultJson,
                    toolCallId = call.id,
                    name = name,
                )
            }
            onStatus("Reviewing the result")
        }

        val summary = used.distinct().joinToString(", ") { it.replace('.', ' ') }
        return AgentResult(
            lastText.ifBlank {
                "I reached the three-step action limit. Completed: ${summary.ifBlank { "nothing" }}. Tell me the next step you want."
            },
            used.distinct(),
        )
    }

    private suspend fun buildContext(): String {
        val settings = settingsStore.snapshot()
        val memories = database.memoryDao().recent(6)
        val tasks = database.taskDao().openTasks()
        val status = runCatching { tools.execute("device_status", "{}") }.getOrNull()
        return buildString {
            appendLine("Current local time: ${LocalDateTime.now().format(DateTimeFormatter.ofPattern("EEEE d MMMM yyyy, h:mm a"))}")
            appendLine("User name: ${settings.userName.ifBlank { "not provided" }}")
            appendLine("Voice reply language preference: ${settings.language}")
            appendLine("Device: Android ${android.os.Build.VERSION.RELEASE}, ${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}")
            status?.let { appendLine("Device state: ${it.message}") }
            if (memories.isNotEmpty()) {
                appendLine("Saved memories:")
                memories.forEach { appendLine("- ${it.text.take(300)}") }
            }
            if (tasks.isNotEmpty()) {
                appendLine("Open tasks:")
                tasks.take(10).forEach { task ->
                    val due = task.dueAt?.let {
                        LocalDateTime.ofInstant(java.time.Instant.ofEpochMilli(it), java.time.ZoneId.systemDefault())
                            .format(DateTimeFormatter.ofPattern("d MMM h:mm a"))
                    } ?: "no due time"
                    appendLine("- ${task.title.take(160)} ($due)")
                }
            }
            appendLine("Rules: use tools for device actions. Never claim an action succeeded unless the tool result says success=true.")
            appendLine("If a tool fails, explain the real failure and the exact permission or setting needed.")
        }
    }
}
