package ai.jarvis.mobile.ui.control

import android.Manifest
import android.content.Intent
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Accessibility
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.BatteryFull
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.Brightness6
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Contacts
import androidx.compose.material.icons.filled.FlashlightOn
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.filled.Sms
import androidx.compose.material.icons.filled.VolumeDown
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ai.jarvis.mobile.core.system.AppEntry
import ai.jarvis.mobile.ui.components.CyanDivider
import ai.jarvis.mobile.ui.components.EmptyState
import ai.jarvis.mobile.ui.components.HudAction
import ai.jarvis.mobile.ui.components.HudPanel
import ai.jarvis.mobile.ui.components.KeyValueRow
import ai.jarvis.mobile.ui.components.SectionLabel
import ai.jarvis.mobile.ui.components.StatusDot
import ai.jarvis.mobile.ui.theme.Amber
import ai.jarvis.mobile.ui.theme.Cyan
import ai.jarvis.mobile.ui.theme.CyanBright
import ai.jarvis.mobile.ui.theme.CyanDim
import ai.jarvis.mobile.ui.theme.Danger
import ai.jarvis.mobile.ui.theme.Panel
import ai.jarvis.mobile.ui.theme.PanelLight
import ai.jarvis.mobile.ui.theme.Success
import ai.jarvis.mobile.ui.theme.TextMuted
import ai.jarvis.mobile.ui.theme.TextPrimary
import ai.jarvis.mobile.ui.theme.TextSecondary
import kotlinx.coroutines.delay
import java.util.Locale

@Composable
fun ControlScreen(
    viewModel: ControlViewModel,
    bottomPadding: androidx.compose.foundation.layout.PaddingValues,
) {
    val status by viewModel.status.collectAsStateWithLifecycle()
    val apps by viewModel.apps.collectAsStateWithLifecycle()
    val notice by viewModel.notice.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var query by remember { mutableStateOf("") }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        val granted = result.values.all { it }
        viewModel.showNotice(
            if (granted) "Permission granted." else "Permission was not granted. The related action will stay limited.",
        )
        viewModel.refresh()
    }

    LaunchedEffect(notice) {
        if (notice != null) {
            delay(5_000)
            viewModel.dismissNotice()
        }
    }

    val brightnessValue = (status?.brightnessPercent ?: 50).toFloat()
    var brightness by remember(brightnessValue) { mutableFloatStateOf(brightnessValue) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("SYSTEM CONTROL", style = MaterialTheme.typography.labelLarge, color = CyanBright)
                Text(
                    "Real Android APIs. Every result is reported as it happened.",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
            }
            TextButton(onClick = viewModel::refresh) { Text("Refresh", color = Cyan) }
        }

        if (notice != null) {
            Spacer(Modifier.height(8.dp))
            HudPanel(accent = Cyan, contentPadding = 12.dp, modifier = Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    StatusDot(true, Cyan)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        notice ?: "",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextPrimary,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = viewModel::dismissNotice) { Text("OK", color = Cyan) }
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        HudPanel(title = "Device state", modifier = Modifier.fillMaxWidth()) {
            KeyValueRow("Battery", "${status?.batteryPercent ?: 0}% ${if (status?.charging == true) "charging" else "on battery"}")
            KeyValueRow("Temperature", "${status?.temperatureC ?: 0f} °C")
            KeyValueRow("Current draw", status?.currentMa?.let { "${kotlin.math.abs(it)} mA" } ?: "not reported")
            KeyValueRow("Network", status?.network ?: "checking")
            KeyValueRow("Storage", "%.1f GB free / %.1f GB".format(status?.storageFreeGb ?: 0.0, status?.storageTotalGb ?: 0.0))
            KeyValueRow("Media volume", "${status?.volumePercent ?: 0}%")
            KeyValueRow("Brightness", "${status?.brightnessPercent ?: 0}%")
            KeyValueRow(
                "Accessibility",
                if (status?.accessibility == true) "connected" else "not connected",
                valueColor = if (status?.accessibility == true) Success else Danger,
            )
        }

        Spacer(Modifier.height(14.dp))
        SectionLabel("Permissions")
        Spacer(Modifier.height(8.dp))
        Row(
            Modifier.horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            PermissionChip(
                "Accessibility",
                status?.accessibility == true,
            ) {
                runCatching {
                    context.startActivity(
                        Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                }
            }
            PermissionChip(
                "Write settings",
                Settings.System.canWrite(context),
            ) {
                runCatching { context.startActivity(viewModel.device.writeSettingsIntent()) }
            }
            PermissionChip("Phone", viewModel.hasPermission(Manifest.permission.CALL_PHONE)) {
                permissionLauncher.launch(arrayOf(Manifest.permission.CALL_PHONE))
            }
            PermissionChip("SMS", viewModel.hasPermission(Manifest.permission.SEND_SMS)) {
                permissionLauncher.launch(arrayOf(Manifest.permission.SEND_SMS))
            }
            PermissionChip("Contacts", viewModel.hasPermission(Manifest.permission.READ_CONTACTS)) {
                permissionLauncher.launch(arrayOf(Manifest.permission.READ_CONTACTS))
            }
            PermissionChip(
                "Calendar",
                viewModel.hasPermission(Manifest.permission.WRITE_CALENDAR),
            ) {
                permissionLauncher.launch(
                    arrayOf(Manifest.permission.READ_CALENDAR, Manifest.permission.WRITE_CALENDAR)
                )
            }
            PermissionChip("Camera", viewModel.hasPermission(Manifest.permission.CAMERA)) {
                permissionLauncher.launch(arrayOf(Manifest.permission.CAMERA))
            }
            PermissionChip("Microphone", viewModel.hasPermission(Manifest.permission.RECORD_AUDIO)) {
                permissionLauncher.launch(arrayOf(Manifest.permission.RECORD_AUDIO))
            }
            PermissionChip(
                "Notifications",
                NotificationManagerCompat.from(context).areNotificationsEnabled(),
            ) {
                runCatching {
                    context.startActivity(
                        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                            .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                }
            }
        }
        Text(
            "Android blocks silent Wi-Fi, Bluetooth, and mobile-data toggles for normal apps. J.A.R.V.I.S. opens the correct system panel instead of pretending to toggle them.",
            style = MaterialTheme.typography.labelSmall,
            color = TextMuted,
            modifier = Modifier.padding(top = 6.dp),
        )

        Spacer(Modifier.height(14.dp))
        SectionLabel("Global gestures")
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
            HudAction(
                "Home",
                Icons.Filled.Home,
                { viewModel.global("home") },
                Modifier.weight(1f),
                enabled = status?.accessibility == true,
            )
            HudAction(
                "Back",
                Icons.Filled.ArrowBack,
                { viewModel.global("back") },
                Modifier.weight(1f),
                enabled = status?.accessibility == true,
            )
            HudAction(
                "Recents",
                Icons.Filled.Apps,
                { viewModel.global("recents") },
                Modifier.weight(1f),
                enabled = status?.accessibility == true,
            )
            HudAction(
                "Shade",
                Icons.Filled.Notifications,
                { viewModel.global("notifications") },
                Modifier.weight(1f),
                enabled = status?.accessibility == true,
            )
        }
        if (status?.accessibility != true) {
            Text(
                "Enable J.A.R.V.I.S. Device Control in Accessibility settings to use Home, Back, Recents, and the notification shade.",
                style = MaterialTheme.typography.labelSmall,
                color = Amber,
                modifier = Modifier.padding(top = 6.dp),
            )
        }

        Spacer(Modifier.height(14.dp))
        SectionLabel("Hardware")
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
            HudAction(
                "Torch",
                Icons.Filled.FlashlightOn,
                viewModel::toggleTorch,
                Modifier.weight(1f),
                accent = if (status?.torchOn == true) Amber else Cyan,
            )
            HudAction(
                "Vol -",
                Icons.Filled.VolumeDown,
                { viewModel.adjustVolume(-10) },
                Modifier.weight(1f),
            )
            HudAction(
                "Vol +",
                Icons.Filled.VolumeUp,
                { viewModel.adjustVolume(10) },
                Modifier.weight(1f),
            )
            HudAction(
                "Bright",
                Icons.Filled.Brightness6,
                { viewModel.setBrightness(60) },
                Modifier.weight(1f),
            )
        }

        Spacer(Modifier.height(10.dp))
        HudPanel(title = "Brightness", modifier = Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Slider(
                    value = brightness,
                    onValueChange = { brightness = it },
                    onValueChangeFinished = { viewModel.setBrightness(brightness.toInt()) },
                    valueRange = 1f..100f,
                    modifier = Modifier.weight(1f),
                    colors = SliderDefaults.colors(
                        thumbColor = Cyan,
                        activeTrackColor = Cyan,
                        inactiveTrackColor = PanelLight,
                    ),
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    "${brightness.toInt()}%",
                    style = MaterialTheme.typography.labelLarge,
                    color = Cyan,
                )
            }
            if (!Settings.System.canWrite(context)) {
                Text(
                    "Requires Modify system settings. Tap the permission chip above.",
                    style = MaterialTheme.typography.labelSmall,
                    color = Amber,
                )
            }
        }

        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
            HudAction(
                "Prev",
                Icons.Filled.SkipPrevious,
                { viewModel.media("previous") },
                Modifier.weight(1f),
            )
            HudAction(
                "Play",
                Icons.Filled.PlayArrow,
                { viewModel.media("play_pause") },
                Modifier.weight(1f),
            )
            HudAction(
                "Next",
                Icons.Filled.SkipNext,
                { viewModel.media("next") },
                Modifier.weight(1f),
            )
        }

        Spacer(Modifier.height(16.dp))
        SectionLabel("System panels")
        Spacer(Modifier.height(8.dp))
        Row(
            Modifier.horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            SettingsChip("Wi-Fi", Icons.Filled.Wifi) { viewModel.openSettings("wifi") }
            SettingsChip("Bluetooth", Icons.Filled.Bluetooth) { viewModel.openSettings("bluetooth") }
            SettingsChip("Battery", Icons.Filled.BatteryFull) { viewModel.openSettings("battery") }
            SettingsChip("Display", Icons.Filled.Brightness6) { viewModel.openSettings("display") }
            SettingsChip("Sound", Icons.Filled.VolumeUp) { viewModel.openSettings("sound") }
            SettingsChip("Location", Icons.Filled.LocationOn) { viewModel.openSettings("location") }
            SettingsChip("Apps", Icons.Filled.Apps) { viewModel.openSettings("apps") }
            SettingsChip("Accessibility", Icons.Filled.Accessibility) { viewModel.openSettings("accessibility") }
        }

        Spacer(Modifier.height(16.dp))
        SectionLabel("Installed apps") {
            TextButton(onClick = viewModel::loadApps) { Text("Reload", color = Cyan) }
        }
        Spacer(Modifier.height(6.dp))
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("Search installed apps", color = TextMuted, fontSize = 14.sp) },
            singleLine = true,
            shape = RoundedCornerShape(14.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Cyan.copy(alpha = 0.6f),
                unfocusedBorderColor = CyanDim.copy(alpha = 0.35f),
                focusedContainerColor = Panel.copy(alpha = 0.65f),
                unfocusedContainerColor = Panel.copy(alpha = 0.45f),
                cursorColor = Cyan,
                focusedTextColor = TextPrimary,
                unfocusedTextColor = TextPrimary,
            ),
        )
        Spacer(Modifier.height(6.dp))
        val filtered = apps.filter {
            query.isBlank() || it.label.contains(query, ignoreCase = true)
        }
        if (filtered.isEmpty()) {
            EmptyState(
                title = if (apps.isEmpty()) "Reading the app list" else "No app matches",
                detail = if (apps.isEmpty()) "Android package visibility may take a moment." else "Try a shorter name.",
                icon = Icons.Filled.Apps,
            )
        } else {
            filtered.take(14).forEach { entry ->
                AppRow(entry) { viewModel.openApp(entry) }
            }
            if (filtered.size > 14) {
                Text(
                    "+ ${filtered.size - 14} more apps. Refine the search to narrow the list.",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                    modifier = Modifier.padding(vertical = 6.dp),
                )
            }
        }

        Spacer(Modifier.height(16.dp))
        CyanDivider()
        Spacer(Modifier.height(12.dp))
        SectionLabel("Launcher")
        Text(
            "J.A.R.V.I.S. can be selected as the home app. It opens this dashboard when you press Home, and keeps the app drawer in this screen.",
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary,
            modifier = Modifier.padding(vertical = 6.dp),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TextButton(onClick = {
                runCatching {
                    val intent = viewModel.device.requestHomeRoleIntent()
                    if (intent != null) context.startActivity(intent)
                }
            }) { Text("Set as home app", color = Cyan) }
            TextButton(onClick = {
                runCatching { context.startActivity(viewModel.device.appInfoIntent()) }
            }) { Text("App info", color = TextSecondary) }
        }

        Spacer(Modifier.height(bottomPadding.calculateBottomPadding() + 24.dp))
    }
}

@Composable
private fun PermissionChip(label: String, granted: Boolean, onClick: () -> Unit) {
    Row(
        Modifier
            .clip(CircleShape)
            .background(if (granted) Success.copy(alpha = 0.08f) else Amber.copy(alpha = 0.08f))
            .border(
                1.dp,
                if (granted) Success.copy(alpha = 0.35f) else Amber.copy(alpha = 0.35f),
                CircleShape,
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatusDot(granted, if (granted) Success else Amber, 7.dp)
        Spacer(Modifier.width(6.dp))
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = if (granted) Success else Amber,
            maxLines = 1,
        )
    }
}

@Composable
private fun SettingsChip(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, onClick: () -> Unit) {
    Row(
        Modifier
            .clip(RoundedCornerShape(10.dp))
            .background(PanelLight.copy(alpha = 0.6f))
            .border(1.dp, CyanDim.copy(alpha = 0.3f), RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = Cyan, modifier = Modifier.size(14.dp))
        Spacer(Modifier.width(6.dp))
        Text(label, style = MaterialTheme.typography.labelSmall, color = TextSecondary)
    }
}

@Composable
private fun AppRow(entry: AppEntry, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 8.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .size(30.dp)
                .background(Cyan.copy(alpha = 0.10f), CircleShape)
                .border(1.dp, CyanDim.copy(alpha = 0.35f), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                entry.label.take(1).uppercase(Locale.US),
                style = MaterialTheme.typography.labelLarge,
                color = Cyan,
            )
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(
                entry.label,
                style = MaterialTheme.typography.titleMedium,
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                entry.packageName,
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text("OPEN", style = MaterialTheme.typography.labelSmall, color = CyanDim)
    }
}
