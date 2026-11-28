package ai.jarvis.mobile.core.system

import java.util.Locale
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject

data class ToolOutcome(
    val tool: String,
    val success: Boolean,
    val message: String,
    val resultJson: String,
    val consequential: Boolean = false,
    val confirmationLabel: String = "",
)

data class LocalAction(
    val tool: String,
    val args: JsonObject,
    val label: String,
)

class ToolRegistry(private val device: DeviceController) {

    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    private val consequentialTools = setOf("phone_call", "phone_sms", "calendar_create")

    fun schemas(): List<JsonElement> = listOf(
        tool(
            "device_status",
            "Read the real battery, charging, network, storage, volume, brightness, temperature, and accessibility state of this phone.",
        ),
        tool(
            "app_open",
            "Open an installed Android app by its visible name. Use a short name such as YouTube, WhatsApp, or Settings.",
            props = buildJsonObject {
                putJsonObject("name") { put("type", "string"); put("description", "Visible app name") }
            },
            required = listOf("name"),
        ),
        tool(
            "settings_open",
            "Open an Android settings panel. Android does not allow apps to silently toggle Wi-Fi or Bluetooth, so this opens the correct panel.",
            props = buildJsonObject {
                putJsonObject("panel") {
                    put("type", "string")
                    put(
                        "enum",
                        buildJsonArray {
                            listOf(
                                "wifi", "bluetooth", "battery", "display", "sound", "location",
                                "apps", "accessibility", "developer", "home", "notifications", "data", "airplane",
                            ).forEach { add(kotlinx.serialization.json.JsonPrimitive(it)) }
                        },
                    )
                }
            },
            required = listOf("panel"),
        ),
        tool(
            "system_flashlight",
            "Turn the camera torch on or off.",
            props = buildJsonObject {
                putJsonObject("on") { put("type", "boolean") }
            },
            required = listOf("on"),
        ),
        tool(
            "system_brightness",
            "Set screen brightness from 1 to 100 percent. Requires the Modify system settings permission.",
            props = buildJsonObject {
                putJsonObject("percent") { put("type", "integer"); put("minimum", 1); put("maximum", 100) }
            },
            required = listOf("percent"),
        ),
        tool(
            "system_volume",
            "Set a volume stream from 0 to 100 percent.",
            props = buildJsonObject {
                putJsonObject("percent") { put("type", "integer"); put("minimum", 0); put("maximum", 100) }
                putJsonObject("stream") {
                    put("type", "string")
                    put("enum", buildJsonArray {
                        listOf("music", "ring", "alarm", "notification").forEach {
                            add(kotlinx.serialization.json.JsonPrimitive(it))
                        }
                    })
                }
            },
            required = listOf("percent"),
        ),
        tool(
            "media_control",
            "Send a media key to the active media app. The app decides whether it responds.",
            props = buildJsonObject {
                putJsonObject("action") {
                    put("type", "string")
                    put("enum", buildJsonArray {
                        listOf("play_pause", "next", "previous", "stop").forEach {
                            add(kotlinx.serialization.json.JsonPrimitive(it))
                        }
                    })
                }
            },
            required = listOf("action"),
        ),
        tool(
            "phone_call",
            "Open the dialer and place a call. This is consequential and needs user confirmation.",
            props = buildJsonObject {
                putJsonObject("number") { put("type", "string"); put("description", "Phone number, including country code if needed") }
            },
            required = listOf("number"),
        ),
        tool(
            "phone_sms",
            "Send or draft a text message. This is consequential and needs user confirmation.",
            props = buildJsonObject {
                putJsonObject("number") { put("type", "string") }
                putJsonObject("message") { put("type", "string") }
            },
            required = listOf("number", "message"),
        ),
        tool(
            "calendar_create",
            "Create a calendar event. This is consequential and needs user confirmation.",
            props = buildJsonObject {
                putJsonObject("title") { put("type", "string") }
                putJsonObject("begin_iso") { put("type", "string"); put("description", "Local ISO date-time, e.g. 2026-11-27T18:30") }
                putJsonObject("duration_minutes") { put("type", "integer"); put("minimum", 5); put("maximum", 1440) }
            },
            required = listOf("title", "begin_iso"),
        ),
        tool(
            "alarm_set",
            "Ask the clock app to set an alarm at a 24-hour time.",
            props = buildJsonObject {
                putJsonObject("hour") { put("type", "integer"); put("minimum", 0); put("maximum", 23) }
                putJsonObject("minute") { put("type", "integer"); put("minimum", 0); put("maximum", 59) }
                putJsonObject("label") { put("type", "string") }
            },
            required = listOf("hour", "minute"),
        ),
        tool(
            "timer_set",
            "Ask the clock app to start a timer.",
            props = buildJsonObject {
                putJsonObject("seconds") { put("type", "integer"); put("minimum", 1); put("maximum", 86400) }
                putJsonObject("label") { put("type", "string") }
            },
            required = listOf("seconds"),
        ),
        tool(
            "web_open",
            "Open a web page in the browser.",
            props = buildJsonObject {
                putJsonObject("url") { put("type", "string") }
            },
            required = listOf("url"),
        ),
        tool(
            "share_text",
            "Open the Android share sheet with text.",
            props = buildJsonObject {
                putJsonObject("text") { put("type", "string") }
            },
            required = listOf("text"),
        ),
        tool(
            "ui_global_action",
            "Perform a global system gesture through the enabled Accessibility service.",
            props = buildJsonObject {
                putJsonObject("action") {
                    put("type", "string")
                    put("enum", buildJsonArray {
                        listOf("home", "back", "recents", "notifications", "quick_settings", "power_dialog", "split_screen").forEach {
                            add(kotlinx.serialization.json.JsonPrimitive(it))
                        }
                    })
                }
            },
            required = listOf("action"),
        ),
        tool(
            "contacts_search",
            "Search the user's contacts by name and return matching phone numbers.",
            props = buildJsonObject {
                putJsonObject("query") { put("type", "string") }
            },
            required = listOf("query"),
        ),
        tool(
            "apps_list",
            "List installed launchable apps. Useful when the user asks what is on the phone.",
        ),
    )

    fun installedApps(): List<AppEntry> = device.launchableApps()

    fun isConsequential(name: String): Boolean = name in consequentialTools

    /**
     * Human-readable description of a consequential action without running it.
     * The caller must show this and get approval before calling [execute].
     */
    fun confirmationFor(name: String, arguments: String): String {
        val args = parseArgs(arguments)
        fun string(key: String, fallback: String = ""): String =
            args[key]?.jsonPrimitive?.contentOrNullSafe() ?: fallback
        fun int(key: String, fallback: Int): Int =
            args[key]?.jsonPrimitive?.contentOrNullSafe()?.toIntOrNull() ?: fallback
        return confirmationLabel(
            name,
            { key, fallback -> string(key, fallback) },
            { key, fallback -> int(key, fallback) },
        )
    }

    private fun parseArgs(arguments: String): JsonObject =
        runCatching { json.parseToJsonElement(arguments.ifBlank { "{}" }).jsonObject }
            .getOrElse { JsonObject(emptyMap()) }

    suspend fun execute(name: String, arguments: String): ToolOutcome {
        val args = parseArgs(arguments)
        fun string(key: String, fallback: String = ""): String =
            args[key]?.jsonPrimitive?.contentOrNullSafe() ?: fallback
        fun int(key: String, fallback: Int): Int =
            args[key]?.jsonPrimitive?.contentOrNullSafe()?.toIntOrNull() ?: fallback
        fun boolean(key: String, fallback: Boolean): Boolean =
            args[key]?.jsonPrimitive?.contentOrNullSafe()?.toBooleanStrictOrNull() ?: fallback

        val result: ActionResult = when (name) {
            "device_status" -> {
                val status = device.status()
                ActionResult(true, device.statusSummary(status))
            }
            "app_open" -> device.openApp(string("name"))
            "settings_open" -> device.openSettings(string("panel"))
            "system_flashlight" -> device.setFlashlight(boolean("on", false))
            "system_brightness" -> device.setBrightness(int("percent", 50))
            "system_volume" -> device.setVolume(int("percent", 50), string("stream", "music"))
            "media_control" -> device.media(string("action", "play_pause"))
            "phone_call" -> device.call(string("number"))
            "phone_sms" -> device.sendSms(string("number"), string("message"))
            "calendar_create" -> device.createCalendarEvent(
                string("title"),
                string("begin_iso"),
                int("duration_minutes", 60),
            )
            "alarm_set" -> device.setAlarm(int("hour", 7), int("minute", 0), string("label"))
            "timer_set" -> device.setTimer(int("seconds", 300), string("label"))
            "web_open" -> device.openUrl(string("url"))
            "share_text" -> device.shareText(string("text"))
            "ui_global_action" -> device.globalAction(string("action"))
            "contacts_search" -> device.searchContacts(string("query"))
            "apps_list" -> device.listApps()
            else -> ActionResult(false, "Unknown tool: $name")
        }
        val resultJson = buildJsonObject {
            put("tool", name)
            put("success", result.success)
            put("message", result.message)
            if (result.data.isNotEmpty()) {
                putJsonObject("data") { result.data.forEach { (key, value) -> put(key, value) } }
            }
        }.toString()
        return ToolOutcome(
            tool = name,
            success = result.success,
            message = result.message,
            resultJson = resultJson,
            consequential = name in consequentialTools,
            confirmationLabel = confirmationLabel(
                name,
                { key, fallback -> string(key, fallback) },
                { key, fallback -> int(key, fallback) },
            ),
        )
    }

    fun parseLocalAction(text: String): LocalAction? {
        val raw = text.trim()
        if (raw.isEmpty() || raw.length > 180) return null
        val lower = raw.lowercase(Locale.US)

        Regex("^(?:turn|switch) (on|off) (?:the )?(?:flashlight|torch)$").find(lower)?.let { match ->
            val on = match.groupValues[1] == "on"
            return local("system_flashlight", buildJsonObject { put("on", on) }, if (on) "Flashlight on" else "Flashlight off")
        }

        if (lower in setOf("battery", "battery status", "what's my battery", "what is my battery", "device status", "phone status")) {
            return local("device_status", buildJsonObject { }, "Read device status")
        }

        Regex("^(?:set )?(?:the )?volume (?:to )?(\\d{1,3})(?: percent)?$").find(lower)?.let { match ->
            val percent = match.groupValues[1].toIntOrNull() ?: return null
            return local("system_volume", buildJsonObject { put("percent", percent); put("stream", "music") }, "Volume $percent percent")
        }

        Regex("^(?:set )?(?:the )?brightness (?:to )?(\\d{1,3})(?: percent)?$").find(lower)?.let { match ->
            val percent = match.groupValues[1].toIntOrNull() ?: return null
            return local("system_brightness", buildJsonObject { put("percent", percent) }, "Brightness $percent percent")
        }

        if (lower in setOf("play music", "play", "pause", "pause music", "resume music")) {
            return local("media_control", buildJsonObject { put("action", "play_pause") }, "Media play or pause")
        }
        if (lower in setOf("next song", "next track", "skip song")) {
            return local("media_control", buildJsonObject { put("action", "next") }, "Next track")
        }
        if (lower in setOf("previous song", "previous track", "last song")) {
            return local("media_control", buildJsonObject { put("action", "previous") }, "Previous track")
        }

        if (lower in setOf("home", "go home", "press home")) {
            return local("ui_global_action", buildJsonObject { put("action", "home") }, "Home")
        }
        if (lower in setOf("back", "go back", "press back")) {
            return local("ui_global_action", buildJsonObject { put("action", "back") }, "Back")
        }
        if (lower in setOf("recents", "recent apps", "show recents")) {
            return local("ui_global_action", buildJsonObject { put("action", "recents") }, "Recent apps")
        }
        if (lower in setOf("open notifications", "show notifications", "notification shade")) {
            return local("ui_global_action", buildJsonObject { put("action", "notifications") }, "Notification shade")
        }

        Regex("^(?:set )?(?:a )?timer for (\\d{1,5}) ?(seconds?|minutes?|hours?)$").find(lower)?.let { match ->
            val amount = match.groupValues[1].toIntOrNull() ?: return null
            val seconds = when {
                match.groupValues[2].startsWith("hour") -> amount * 3600
                match.groupValues[2].startsWith("minute") -> amount * 60
                else -> amount
            }
            return local(
                "timer_set",
                buildJsonObject { put("seconds", seconds); put("label", "J.A.R.V.I.S. timer") },
                "Timer for $amount ${match.groupValues[2]}",
            )
        }

        Regex("^(?:set )?(?:an )?alarm (?:for )?(\\d{1,2})(?::(\\d{2}))? ?(am|pm)?$").find(lower)?.let { match ->
            var hour = match.groupValues[1].toIntOrNull() ?: return null
            val minute = match.groupValues[2].toIntOrNull() ?: 0
            val meridiem = match.groupValues[3]
            if (meridiem == "pm" && hour < 12) hour += 12
            if (meridiem == "am" && hour == 12) hour = 0
            if (hour !in 0..23 || minute !in 0..59) return null
            return local(
                "alarm_set",
                buildJsonObject { put("hour", hour); put("minute", minute); put("label", "J.A.R.V.I.S.") },
                "Alarm at %02d:%02d".format(hour, minute),
            )
        }

        Regex("^call ([+\\d][\\d\\s-]{5,})$").find(lower)?.let { match ->
            val number = match.groupValues[1].trim()
            return local("phone_call", buildJsonObject { put("number", number) }, "Call $number")
        }

        Regex("^open (.+)$").find(lower)?.let { match ->
            val target = match.groupValues[1].trim()
            val panels = setOf(
                "wifi", "wi-fi", "bluetooth", "battery", "display", "sound", "volume", "location",
                "apps", "accessibility", "developer", "home settings", "notifications", "airplane mode",
            )
            if (target in panels) {
                val panel = if (target == "wi-fi") "wifi" else target
                return local("settings_open", buildJsonObject { put("panel", panel) }, "Open $target settings")
            }
            val apps = installedApps()
            val hit = apps.firstOrNull { it.label.lowercase(Locale.US) == target }
                ?: apps.firstOrNull { it.label.lowercase(Locale.US).startsWith(target) }
                ?: apps.firstOrNull { it.label.lowercase(Locale.US).contains(target) }
            if (hit != null) {
                return local("app_open", buildJsonObject { put("name", hit.label) }, "Open ${hit.label}")
            }
        }

        return null
    }

    private fun local(tool: String, args: JsonObject, label: String) = LocalAction(tool, args, label)

    private fun confirmationLabel(
        name: String,
        string: (String, String) -> String,
        int: (String, Int) -> Int,
    ): String = when (name) {
        "phone_call" -> "Call ${string("number", "")}"
        "phone_sms" -> "Send SMS to ${string("number", "")}: ${string("message", "").take(80)}"
        "calendar_create" -> "Create event \"${string("title", "Untitled")}\" at ${string("begin_iso", "")}"
        else -> name
    }

    private fun tool(
        name: String,
        description: String,
        props: JsonObject = JsonObject(emptyMap()),
        required: List<String> = emptyList(),
    ): JsonElement = buildJsonObject {
        put("type", "function")
        putJsonObject("function") {
            put("name", name)
            put("description", description)
            putJsonObject("parameters") {
                put("type", "object")
                put("properties", props)
                if (required.isNotEmpty()) {
                    put("required", buildJsonArray { required.forEach { add(kotlinx.serialization.json.JsonPrimitive(it)) } })
                }
            }
        }
    }

    private fun kotlinx.serialization.json.JsonPrimitive.contentOrNullSafe(): String? =
        runCatching { content }.getOrNull()
}
