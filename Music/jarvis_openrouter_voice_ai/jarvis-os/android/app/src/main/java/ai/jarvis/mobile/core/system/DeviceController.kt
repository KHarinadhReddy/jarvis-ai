package ai.jarvis.mobile.core.system

import android.Manifest
import android.app.SearchManager
import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.provider.AlarmClock
import android.provider.CalendarContract
import android.provider.ContactsContract
import android.provider.Settings
import android.telephony.SmsManager
import android.view.KeyEvent
import androidx.core.content.ContextCompat
import java.time.Duration
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.TimeZone
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class ActionResult(
    val success: Boolean,
    val message: String,
    val data: Map<String, String> = emptyMap(),
)

data class AppEntry(
    val label: String,
    val packageName: String,
    val activityName: String,
)

data class DeviceStatus(
    val batteryPercent: Int = 0,
    val charging: Boolean = false,
    val temperatureC: Float = 0f,
    val currentMa: Int? = null,
    val network: String = "Unknown",
    val storageFreeGb: Double = 0.0,
    val storageTotalGb: Double = 0.0,
    val volumePercent: Int = 0,
    val brightnessPercent: Int = 0,
    val torchOn: Boolean = false,
    val accessibility: Boolean = false,
)

class DeviceController(private val context: Context) {

    private val audioManager: AudioManager =
        context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    @Volatile
    private var torchOn: Boolean = false

    fun hasPermission(permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    fun accessibilityEnabled(): Boolean {
        if (JarvisAccessibilityService.isConnected.value) return true
        val enabled = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
        ) ?: return false
        val expected = "${context.packageName}/${JarvisAccessibilityService::class.java.name}"
        return enabled.split(':').any { it.equals(expected, ignoreCase = true) }
    }

    fun status(): DeviceStatus {
        val batteryIntent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = batteryIntent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryIntent?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
        val percent = if (level >= 0 && scale > 0) level * 100 / scale else 0
        val status = batteryIntent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
        val tempTenths = batteryIntent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) ?: 0
        val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val current = runCatching {
            batteryManager.getLongProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW)
        }.getOrDefault(Long.MIN_VALUE)
        val currentMa = if (current == Long.MIN_VALUE || current == 0L) null else (current / 1000L).toInt()

        val stat = StatFs(Environment.getDataDirectory().absolutePath)
        val freeGb = stat.availableBytes.toDouble() / (1024.0 * 1024.0 * 1024.0)
        val totalGb = stat.totalBytes.toDouble() / (1024.0 * 1024.0 * 1024.0)

        val brightness = runCatching {
            Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS, 128)
        }.getOrDefault(128)

        return DeviceStatus(
            batteryPercent = percent,
            charging = charging,
            temperatureC = tempTenths / 10f,
            currentMa = currentMa,
            network = networkLabel(),
            storageFreeGb = freeGb,
            storageTotalGb = totalGb,
            volumePercent = volumePercent(AudioManager.STREAM_MUSIC),
            brightnessPercent = (brightness * 100 / 255).coerceIn(0, 100),
            torchOn = torchOn,
            accessibility = accessibilityEnabled(),
        )
    }

    fun statusSummary(status: DeviceStatus = status()): String {
        val charge = if (status.charging) "charging" else "on battery"
        val current = status.currentMa?.let { "${kotlin.math.abs(it)} milliamps" } ?: "current draw unavailable"
        return buildString {
            append("Battery ${status.batteryPercent} percent, $charge. ")
            append("Network: ${status.network}. ")
            append("Storage: ${"%.1f".format(status.storageFreeGb)} of ${"%.1f".format(status.storageTotalGb)} gigabytes free. ")
            append("Media volume ${status.volumePercent} percent. ")
            append("Brightness ${status.brightnessPercent} percent. ")
            append("Temperature ${status.temperatureC} Celsius. ")
            append("Current draw $current. ")
            append("Accessibility control is ${if (status.accessibility) "connected" else "not connected"}.")
        }
    }

    fun networkLabel(): String {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = manager.activeNetwork ?: return "Offline"
        val caps = manager.getNetworkCapabilities(network) ?: return "Offline"
        val validated = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
        val kind = when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "Mobile data"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "Ethernet"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "VPN"
            else -> "Connected"
        }
        return if (validated) kind else "$kind (no internet)"
    }

    fun volumePercent(stream: Int = AudioManager.STREAM_MUSIC): Int {
        val max = audioManager.getStreamMaxVolume(stream).coerceAtLeast(1)
        return audioManager.getStreamVolume(stream) * 100 / max
    }

    fun setVolume(percent: Int, streamName: String = "music"): ActionResult {
        val stream = when (streamName.lowercase(Locale.US)) {
            "ring", "ringtone" -> AudioManager.STREAM_RING
            "alarm" -> AudioManager.STREAM_ALARM
            "notification" -> AudioManager.STREAM_NOTIFICATION
            else -> AudioManager.STREAM_MUSIC
        }
        val max = audioManager.getStreamMaxVolume(stream)
        val value = (percent.coerceIn(0, 100) * max / 100)
        return try {
            audioManager.setStreamVolume(stream, value, 0)
            ActionResult(true, "${streamName.replaceFirstChar { it.uppercase() }} volume set to ${percent.coerceIn(0, 100)} percent.")
        } catch (error: SecurityException) {
            ActionResult(false, "Android blocked the volume change: ${error.message}")
        }
    }

    fun setBrightness(percent: Int): ActionResult {
        if (!Settings.System.canWrite(context)) {
            return ActionResult(
                false,
                "Brightness control needs the Modify system settings permission. Open Settings, grant it, then retry.",
                mapOf("needs_permission" to "WRITE_SETTINGS"),
            )
        }
        val value = (percent.coerceIn(1, 100) * 255 / 100)
        return try {
            Settings.System.putInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS, value)
            ActionResult(true, "Brightness set to ${percent.coerceIn(1, 100)} percent.")
        } catch (error: Exception) {
            ActionResult(false, "Brightness change failed: ${error.message}")
        }
    }

    fun writeSettingsIntent(): Intent =
        Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS, Uri.parse("package:${context.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    fun setFlashlight(on: Boolean): ActionResult {
        if (!hasPermission(Manifest.permission.CAMERA)) {
            return ActionResult(false, "Camera permission is required to control the torch.")
        }
        val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        return try {
            val cameraId = manager.cameraIdList.firstOrNull { id ->
                manager.getCameraCharacteristics(id)
                    .get(android.hardware.camera2.CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            } ?: return ActionResult(false, "This device reports no camera flash.")
            manager.setTorchMode(cameraId, on)
            torchOn = on
            ActionResult(true, "Flashlight ${if (on) "on" else "off"}.")
        } catch (error: Exception) {
            ActionResult(false, "Torch control failed: ${error.message}")
        }
    }

    fun media(action: String): ActionResult {
        val key = when (action.lowercase(Locale.US)) {
            "play", "pause", "play_pause", "toggle" -> KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
            "next" -> KeyEvent.KEYCODE_MEDIA_NEXT
            "previous", "prev" -> KeyEvent.KEYCODE_MEDIA_PREVIOUS
            "stop" -> KeyEvent.KEYCODE_MEDIA_STOP
            else -> return ActionResult(false, "Unknown media action: $action")
        }
        return try {
            audioManager.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, key))
            audioManager.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, key))
            ActionResult(true, "Sent $action to the active media app. That app decides whether to respond.")
        } catch (error: Exception) {
            ActionResult(false, "Media key failed: ${error.message}")
        }
    }

    fun call(number: String): ActionResult {
        val cleaned = number.trim()
        if (cleaned.isBlank()) return ActionResult(false, "No phone number was provided.")
        val uri = Uri.parse("tel:${Uri.encode(cleaned)}")
        val direct = hasPermission(Manifest.permission.CALL_PHONE)
        val intent = Intent(if (direct) Intent.ACTION_CALL else Intent.ACTION_DIAL, uri)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            context.startActivity(intent)
            if (direct) {
                ActionResult(true, "Placing a call to $cleaned.")
            } else {
                ActionResult(
                    true,
                    "Opened the dialer for $cleaned. Grant the Phone permission to place calls directly.",
                )
            }
        } catch (error: Exception) {
            ActionResult(false, "Could not open the dialer: ${error.message}")
        }
    }

    fun sendSms(number: String, message: String): ActionResult {
        val cleaned = number.trim()
        if (cleaned.isBlank() || message.isBlank()) {
            return ActionResult(false, "A phone number and message are required.")
        }
        if (!hasPermission(Manifest.permission.SEND_SMS)) {
            val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:${Uri.encode(cleaned)}"))
                .putExtra("sms_body", message)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            return try {
                context.startActivity(intent)
                ActionResult(
                    true,
                    "Opened the messaging app with the draft. Grant the SMS permission to send directly.",
                )
            } catch (error: Exception) {
                ActionResult(false, "Could not open the messaging app: ${error.message}")
            }
        }
        return try {
            @Suppress("DEPRECATION")
            val manager = SmsManager.getDefault()
            val parts = manager.divideMessage(message)
            if (parts.size > 1) {
                manager.sendMultipartTextMessage(cleaned, null, parts, null, null)
            } else {
                manager.sendTextMessage(cleaned, null, message, null, null)
            }
            ActionResult(true, "SMS handed to Android for delivery to $cleaned.")
        } catch (error: Exception) {
            ActionResult(false, "SMS failed: ${error.message}")
        }
    }

    fun createCalendarEvent(title: String, beginIso: String, durationMinutes: Int): ActionResult {
        if (!hasPermission(Manifest.permission.WRITE_CALENDAR)) {
            return ActionResult(false, "Calendar write permission is not granted.")
        }
        val start = parseDateTime(beginIso) ?: LocalDateTime.now().plusHours(1).withSecond(0).withNano(0)
        val end = start.plusMinutes(durationMinutes.coerceIn(5, 1440).toLong())
        val zone = ZoneId.systemDefault()
        val calendarId = primaryCalendarId()
            ?: return ActionResult(false, "No writable calendar was found on this device.")
        val values = ContentValues().apply {
            put(CalendarContract.Events.CALENDAR_ID, calendarId)
            put(CalendarContract.Events.TITLE, title.ifBlank { "J.A.R.V.I.S. event" })
            put(CalendarContract.Events.DTSTART, start.atZone(zone).toInstant().toEpochMilli())
            put(CalendarContract.Events.DTEND, end.atZone(zone).toInstant().toEpochMilli())
            put(CalendarContract.Events.EVENT_TIMEZONE, TimeZone.getDefault().id)
        }
        return try {
            val uri = context.contentResolver.insert(CalendarContract.Events.CONTENT_URI, values)
            if (uri != null) {
                ActionResult(
                    true,
                    "Calendar event created for ${start.format(DateTimeFormatter.ofPattern("EEE d MMM, h:mm a"))}.",
                )
            } else {
                ActionResult(false, "The calendar provider rejected the event.")
            }
        } catch (error: Exception) {
            ActionResult(false, "Calendar insert failed: ${error.message}")
        }
    }

    fun setAlarm(hour: Int, minute: Int, label: String): ActionResult {
        if (hour !in 0..23 || minute !in 0..59) {
            return ActionResult(false, "Alarm time must be a valid hour and minute.")
        }
        val intent = Intent(AlarmClock.ACTION_SET_ALARM).apply {
            putExtra(AlarmClock.EXTRA_HOUR, hour)
            putExtra(AlarmClock.EXTRA_MINUTES, minute)
            putExtra(AlarmClock.EXTRA_MESSAGE, label.ifBlank { "J.A.R.V.I.S." })
            putExtra(AlarmClock.EXTRA_SKIP_UI, false)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return startExternal(intent, "Alarm request sent to the clock app for %02d:%02d.".format(hour, minute))
    }

    fun setTimer(seconds: Int, label: String): ActionResult {
        if (seconds <= 0) return ActionResult(false, "Timer length must be positive.")
        val intent = Intent(AlarmClock.ACTION_SET_TIMER).apply {
            putExtra(AlarmClock.EXTRA_LENGTH, seconds)
            putExtra(AlarmClock.EXTRA_MESSAGE, label.ifBlank { "J.A.R.V.I.S. timer" })
            putExtra(AlarmClock.EXTRA_SKIP_UI, false)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val minutes = seconds / 60
        val human = if (minutes >= 1) "$minutes minute${if (minutes == 1) "" else "s"}" else "$seconds seconds"
        return startExternal(intent, "Timer request sent to the clock app for $human.")
    }

    fun openUrl(url: String): ActionResult {
        val normalized = if (url.startsWith("http://") || url.startsWith("https://")) url else "https://$url"
        return startExternal(
            Intent(Intent.ACTION_VIEW, Uri.parse(normalized)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            "Opening $normalized.",
        )
    }

    fun shareText(text: String): ActionResult {
        if (text.isBlank()) return ActionResult(false, "Nothing to share.")
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
        }
        val chooser = Intent.createChooser(send, "Share with").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return startExternal(chooser, "Share sheet opened.")
    }

    fun openApp(query: String): ActionResult {
        val apps = launchableApps()
        val cleaned = query.trim().lowercase(Locale.US)
        if (cleaned.isBlank()) return ActionResult(false, "No app name was provided.")
        val exact = apps.filter { it.label.lowercase(Locale.US) == cleaned }
        val prefix = apps.filter { it.label.lowercase(Locale.US).startsWith(cleaned) }
        val contains = apps.filter { it.label.lowercase(Locale.US).contains(cleaned) }
        val match = (exact + prefix + contains).firstOrNull()
            ?: return ActionResult(
                false,
                "No installed app matches \"$query\".",
                mapOf("available_sample" to apps.take(12).joinToString(", ") { it.label }),
            )
        return launchApp(match)
    }

    fun launchApp(app: AppEntry): ActionResult {
        val intent = Intent(Intent.ACTION_MAIN).apply {
            addCategory(Intent.CATEGORY_LAUNCHER)
            component = ComponentName(app.packageName, app.activityName)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return try {
            context.startActivity(intent)
            ActionResult(true, "Opened ${app.label}.")
        } catch (error: Exception) {
            ActionResult(false, "Could not open ${app.label}: ${error.message}")
        }
    }

    fun launchPackage(packageName: String): ActionResult {
        val intent = context.packageManager.getLaunchIntentForPackage(packageName)
            ?: return ActionResult(false, "That package has no launchable activity.")
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            context.startActivity(intent)
            ActionResult(true, "Opened $packageName.")
        } catch (error: Exception) {
            ActionResult(false, "Could not open $packageName: ${error.message}")
        }
    }

    fun launchableApps(): List<AppEntry> = withContextSync {
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        @Suppress("DEPRECATION")
        val resolved = context.packageManager.queryIntentActivities(intent, 0)
        resolved.mapNotNull { info ->
            val activity = info.activityInfo ?: return@mapNotNull null
            val label = info.loadLabel(context.packageManager).toString().ifBlank { activity.packageName }
            AppEntry(label, activity.packageName, activity.name)
        }.distinctBy { it.packageName to it.activityName }
            .sortedBy { it.label.lowercase(Locale.US) }
    }

    fun openSettings(panel: String): ActionResult {
        val key = panel.lowercase(Locale.US).replace(" ", "_")
        if (key == "notification" || key == "notifications") {
            val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            return startExternal(intent, "Opened this app's notification settings.")
        }
        val action = when (key) {
            "wifi", "wi_fi", "internet" -> Settings.ACTION_WIFI_SETTINGS
            "bluetooth" -> Settings.ACTION_BLUETOOTH_SETTINGS
            "battery" -> Intent.ACTION_POWER_USAGE_SUMMARY
            "display" -> Settings.ACTION_DISPLAY_SETTINGS
            "sound", "volume" -> Settings.ACTION_SOUND_SETTINGS
            "location", "gps" -> Settings.ACTION_LOCATION_SOURCE_SETTINGS
            "apps", "applications" -> Settings.ACTION_APPLICATION_SETTINGS
            "accessibility" -> Settings.ACTION_ACCESSIBILITY_SETTINGS
            "developer" -> Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS
            "home", "launcher" -> Settings.ACTION_HOME_SETTINGS
            "data", "mobile_data" -> Settings.ACTION_DATA_ROAMING_SETTINGS
            "airplane" -> Settings.ACTION_AIRPLANE_MODE_SETTINGS
            else -> Settings.ACTION_SETTINGS
        }
        return startExternal(
            Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            "Opened Android settings: ${panel.ifBlank { "main" }}.",
        )
    }

    fun globalAction(action: String): ActionResult {
        val mapped = when (action.lowercase(Locale.US)) {
            "home" -> android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_HOME
            "back" -> android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK
            "recents", "recent" -> android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_RECENTS
            "notifications", "notification_shade" ->
                android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS
            "quick_settings" -> android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_QUICK_SETTINGS
            "power", "power_dialog" -> android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_POWER_DIALOG
            "split_screen" -> android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_TOGGLE_SPLIT_SCREEN
            else -> return ActionResult(false, "Unknown system gesture: $action")
        }
        if (!JarvisAccessibilityService.isConnected.value) {
            return ActionResult(
                false,
                "Device control is not connected. Enable J.A.R.V.I.S. Device Control in Accessibility settings first.",
            )
        }
        return if (JarvisAccessibilityService.globalAction(mapped)) {
            ActionResult(true, "Performed system gesture: $action.")
        } else {
            ActionResult(false, "Android refused the gesture: $action.")
        }
    }

    fun searchContacts(query: String): ActionResult {
        if (!hasPermission(Manifest.permission.READ_CONTACTS)) {
            return ActionResult(false, "Contacts permission is not granted.")
        }
        if (query.isBlank()) return ActionResult(false, "No contact name was provided.")
        return try {
            val projection = arrayOf(
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER,
            )
            val rows = mutableListOf<String>()
            context.contentResolver.query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                projection,
                "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?",
                arrayOf("%$query%"),
                "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} ASC",
            )?.use { cursor ->
                val nameIndex = cursor.getColumnIndexOrThrow(projection[0])
                val numberIndex = cursor.getColumnIndexOrThrow(projection[1])
                while (cursor.moveToNext() && rows.size < 8) {
                    val name = cursor.getString(nameIndex) ?: continue
                    val number = cursor.getString(numberIndex) ?: continue
                    if (rows.none { it.contains(number) }) rows += "$name: $number"
                }
            }
            if (rows.isEmpty()) {
                ActionResult(false, "No contacts matched \"$query\".")
            } else {
                ActionResult(true, rows.joinToString("\n"), mapOf("count" to rows.size.toString()))
            }
        } catch (error: Exception) {
            ActionResult(false, "Contact search failed: ${error.message}")
        }
    }

    fun listApps(limit: Int = 40): ActionResult {
        val apps = launchableApps()
        val listing = apps.take(limit).joinToString("\n") { "${it.label} (${it.packageName})" }
        return ActionResult(
            true,
            listing.ifBlank { "No launchable apps were found." },
            mapOf("count" to apps.size.toString()),
        )
    }

    fun requestHomeRoleIntent(): Intent? {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val manager = context.getSystemService(android.app.role.RoleManager::class.java)
            if (manager != null && manager.isRoleAvailable(android.app.role.RoleManager.ROLE_HOME)) {
                return manager.createRequestRoleIntent(android.app.role.RoleManager.ROLE_HOME)
            }
        }
        return Intent(Settings.ACTION_HOME_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    fun appInfoIntent(): Intent =
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    fun permissionSettingsIntent(): Intent =
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    private fun startExternal(intent: Intent, successMessage: String): ActionResult = try {
        context.startActivity(intent)
        ActionResult(true, successMessage)
    } catch (error: ActivityNotFoundException) {
        ActionResult(false, "No app on this device can handle that request.")
    } catch (error: SecurityException) {
        ActionResult(false, "Android blocked that request: ${error.message}")
    } catch (error: Exception) {
        ActionResult(false, "Request failed: ${error.message}")
    }

    private fun primaryCalendarId(): Long? {
        val projection = arrayOf(CalendarContract.Calendars._ID, CalendarContract.Calendars.IS_PRIMARY)
        return try {
            context.contentResolver.query(
                CalendarContract.Calendars.CONTENT_URI,
                projection,
                null,
                null,
                "${CalendarContract.Calendars.IS_PRIMARY} DESC",
            )?.use { cursor ->
                if (cursor.moveToFirst()) cursor.getLong(0) else null
            }
        } catch (error: Exception) {
            null
        }
    }

    private fun parseDateTime(value: String): LocalDateTime? {
        if (value.isBlank()) return null
        return runCatching { LocalDateTime.parse(value) }.getOrNull()
            ?: runCatching { OffsetDateTime.parse(value).toLocalDateTime() }.getOrNull()
            ?: runCatching {
                java.time.Instant.parse(value).atZone(ZoneId.systemDefault()).toLocalDateTime()
            }.getOrNull()
    }

    private inline fun <T> withContextSync(block: () -> T): T = block()
}
