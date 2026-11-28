package ai.jarvis.mobile.ui.settings

import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Accessibility
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ai.jarvis.mobile.BuildConfig
import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.data.PowerMode
import ai.jarvis.mobile.core.voice.SpeechState
import ai.jarvis.mobile.ui.components.CyanDivider
import ai.jarvis.mobile.ui.components.HudNotices
import ai.jarvis.mobile.ui.components.HudPanel
import ai.jarvis.mobile.ui.components.Pill
import ai.jarvis.mobile.ui.components.SectionLabel
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
import ai.jarvis.mobile.ui.theme.Void

@Composable
fun SettingsScreen(
    app: JarvisApp,
    viewModel: SettingsViewModel,
    bottomPadding: PaddingValues,
) {
    val settings by viewModel.settings.collectAsStateWithLifecycle()
    val test by viewModel.test.collectAsStateWithLifecycle()
    val speechState by viewModel.speechState.collectAsStateWithLifecycle()
    val context = LocalContext.current

    var backendUrl by remember(settings.backendUrl) { mutableStateOf(settings.backendUrl) }
    var deviceToken by remember(settings.deviceToken) { mutableStateOf(settings.deviceToken) }
    var userName by remember(settings.userName) { mutableStateOf(settings.userName) }
    var language by remember(settings.language) { mutableStateOf(settings.language) }
    var gender by remember(settings.voiceGender) { mutableStateOf(settings.voiceGender) }
    var ttsEnabled by remember(settings.ttsEnabled) { mutableStateOf(settings.ttsEnabled) }
    var thinking by remember(settings.thinking) { mutableStateOf(settings.thinking) }
    var powerMode by remember(settings.powerMode) { mutableStateOf(settings.powerMode) }
    var showToken by remember { mutableStateOf(false) }
    var pendingClear by remember { mutableStateOf<String?>(null) }

    val current = settings.copy(
        backendUrl = backendUrl,
        deviceToken = deviceToken,
        userName = userName,
        language = language,
        voiceGender = gender,
        ttsEnabled = ttsEnabled,
        thinking = thinking,
        powerMode = powerMode,
    )

    val save: () -> Unit = {
        viewModel.save(current)
        HudNotices.show("Configuration saved.")
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {
        Spacer(Modifier.height(10.dp))
        Text("CONFIGURATION", style = MaterialTheme.typography.labelLarge, color = CyanBright)
        Text(
            "Link, voice, intelligence, power, and access.",
            style = MaterialTheme.typography.labelSmall,
            color = TextMuted,
        )

        Spacer(Modifier.height(14.dp))
        HudPanel(title = "Backend link", modifier = Modifier.fillMaxWidth()) {
            OutlinedTextField(
                value = backendUrl,
                onValueChange = { backendUrl = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Backend URL") },
                placeholder = { Text("http://127.0.0.1:8000") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                colors = fieldColors(),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = deviceToken,
                onValueChange = { deviceToken = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Device pairing token") },
                singleLine = true,
                visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    IconButton(onClick = { showToken = !showToken }) {
                        Icon(
                            if (showToken) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                            contentDescription = "Show or hide token",
                            tint = TextSecondary,
                        )
                    }
                },
                colors = fieldColors(),
            )
            Text(
                "The AI key never lives on this phone. The device token only authorizes this app to your backend. Use HTTPS and a long random token outside local testing.",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
                modifier = Modifier.padding(top = 6.dp),
            )
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = save,
                    colors = ButtonDefaults.buttonColors(containerColor = Cyan, contentColor = Void),
                ) { Text("Save") }
                TextButton(onClick = { viewModel.testConnection(current) }) {
                    Text("Test link", color = Cyan)
                }
            }
            if (test.testing) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(13.dp), strokeWidth = 1.5.dp, color = Cyan)
                    Spacer(Modifier.width(8.dp))
                    Text("Testing...", style = MaterialTheme.typography.labelSmall, color = Cyan)
                }
            } else if (test.message.isNotBlank()) {
                Text(
                    test.message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (test.ok == true) Success else if (test.ok == false) Danger else TextSecondary,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        }

        Spacer(Modifier.height(12.dp))
        HudPanel(title = "Voice", modifier = Modifier.fillMaxWidth()) {
            SectionLabel("Voice gender")
            Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                ChoiceChip("Male", gender == "male") { gender = "male" }
                ChoiceChip("Female", gender == "female") { gender = "female" }
            }
            Spacer(Modifier.height(10.dp))
            SectionLabel("Speech language")
            Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                ChoiceChip("Auto", language == "auto") { language = "auto" }
                ChoiceChip("English", language == "en-IN") { language = "en-IN" }
                ChoiceChip("తెలుగు", language == "te-IN") { language = "te-IN" }
            }
            Text(
                "Auto lets the backend detect Telugu script per sentence. Input uses Android speech recognition; switch the language chip in chat to Telugu for Telugu commands.",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
                modifier = Modifier.padding(top = 6.dp),
            )
            Spacer(Modifier.height(6.dp))
            ToggleRow(
                label = "Spoken replies",
                detail = "Stream a human-paced Edge neural voice. Turn off to save battery.",
                checked = ttsEnabled,
                onCheckedChange = { ttsEnabled = it },
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { viewModel.testVoice(current) }) { Text("Test voice", color = Cyan) }
                if (speechState is SpeechState.Speaking || speechState is SpeechState.Preparing) {
                    TextButton(onClick = viewModel::stopVoice) { Text("Stop", color = Danger) }
                }
            }
            if (speechState is SpeechState.Error) {
                Text(
                    (speechState as SpeechState.Error).message,
                    style = MaterialTheme.typography.labelSmall,
                    color = Danger,
                )
            }
            Text(
                "Telugu and Indian English use Edge neural voices. Edge TTS is a free service without an SLA; the app falls back to an installed Android voice for English if it fails.",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
            )
        }

        Spacer(Modifier.height(12.dp))
        HudPanel(title = "Intelligence", modifier = Modifier.fillMaxWidth()) {
            ToggleRow(
                label = "Deep reasoning",
                detail = "Requests the provider's thinking mode for harder tasks. It is slower and uses more tokens. Hidden reasoning text is never displayed.",
                checked = thinking,
                onCheckedChange = { thinking = it },
            )
            Text(
                "The default server model is DeepSeek Flash. If the server has only an OpenRouter key, the backend uses that fallback instead. The app shows the actual provider from the health check.",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
            )
        }

        Spacer(Modifier.height(12.dp))
        HudPanel(title = "Power mode", modifier = Modifier.fillMaxWidth()) {
            Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                ChoiceChip("Cinematic", powerMode == PowerMode.CINEMATIC) { powerMode = PowerMode.CINEMATIC }
                ChoiceChip("Balanced", powerMode == PowerMode.BALANCED) { powerMode = PowerMode.BALANCED }
                ChoiceChip("Saver", powerMode == PowerMode.SAVER) { powerMode = PowerMode.SAVER }
            }
            Spacer(Modifier.height(8.dp))
            Text(
                when (powerMode) {
                    PowerMode.CINEMATIC -> "Full reactor animation, moving scanline, and a one-second clock. Highest visual battery cost."
                    PowerMode.BALANCED -> "Slower reactor and scanline, five-second clock. The default."
                    PowerMode.SAVER -> "Static reactor, no scanline, thirty-second clock. All network work remains event-driven."
                },
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary,
            )
            Text(
                "Battery and network values update from Android broadcasts and callbacks, not polling. WorkManager checks task reminders at most every 15 minutes and skips when the battery is low.",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
            )
        }

        Spacer(Modifier.height(12.dp))
        HudPanel(title = "Personal", modifier = Modifier.fillMaxWidth()) {
            OutlinedTextField(
                value = userName,
                onValueChange = { userName = it.take(60) },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("What should J.A.R.V.I.S. call you?") },
                singleLine = true,
                colors = fieldColors(),
            )
        }

        Spacer(Modifier.height(12.dp))
        HudPanel(title = "System access", modifier = Modifier.fillMaxWidth()) {
            ActionLink(
                "Accessibility device control",
                if (app.container.device.accessibilityEnabled()) "Connected" else "Not connected",
                Icons.Filled.Accessibility,
                if (app.container.device.accessibilityEnabled()) Success else Amber,
            ) {
                runCatching {
                    context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
            }
            ActionLink(
                "Modify system settings",
                if (Settings.System.canWrite(context)) "Granted" else "Needed for brightness",
                Icons.Filled.Visibility,
                if (Settings.System.canWrite(context)) Success else Amber,
            ) {
                runCatching { context.startActivity(app.container.device.writeSettingsIntent()) }
            }
            ActionLink(
                "Home app",
                "Make J.A.R.V.I.S. the launcher",
                Icons.Filled.Home,
                Cyan,
            ) {
                runCatching {
                    val intent = app.container.device.requestHomeRoleIntent()
                    if (intent != null) context.startActivity(intent)
                }
            }
            ActionLink(
                "Notification settings",
                "Task reminders and permissions",
                Icons.Filled.Notifications,
                Cyan,
            ) {
                runCatching {
                    context.startActivity(
                        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                            .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                }
            }
            ActionLink(
                "App permissions",
                "Camera, microphone, phone, SMS, contacts, calendar",
                Icons.Filled.ChevronRight,
                Cyan,
            ) {
                runCatching { context.startActivity(app.container.device.permissionSettingsIntent()) }
            }
        }

        Spacer(Modifier.height(12.dp))
        HudPanel(title = "Local data", modifier = Modifier.fillMaxWidth()) {
            Text(
                "Conversation history, memories, and tasks live in a local Room database. Nothing is backed up by this app.",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
            )
            Spacer(Modifier.height(6.dp))
            DataAction("Clear conversation") { pendingClear = "conversation" }
            DataAction("Clear memories") { pendingClear = "memories" }
            DataAction("Clear tasks") { pendingClear = "tasks" }
            DataAction("Clear completed tasks") { pendingClear = "completed" }
        }

        Spacer(Modifier.height(12.dp))
        HudPanel(title = "About", modifier = Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Pill("v${BuildConfig.VERSION_NAME}", Cyan)
                Spacer(Modifier.width(8.dp))
                Pill("ANDROID ${android.os.Build.VERSION.RELEASE}", CyanDim)
            }
            Spacer(Modifier.height(8.dp))
            Text(
                "J.A.R.V.I.S. is a native Android assistant and optional launcher. It is not a replacement Android operating system and cannot bypass Android's security model.",
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                "What is real: chat with tool calling, vision, Edge neural speech, device actions through public APIs, accessibility gestures when you enable them, local memory and tasks, and power-aware animation. What is limited: apps cannot silently toggle Wi-Fi or Bluetooth, background wake-word listening is off by default, reminders can be up to 15 minutes late, and Edge TTS has no SLA. No confidence score is invented anywhere.",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
            )
            Spacer(Modifier.height(8.dp))
            CyanDivider()
            Spacer(Modifier.height(8.dp))
            Text(
                "Never enter an AI provider key into this app. Keys belong in backend/.env on your server.",
                style = MaterialTheme.typography.labelSmall,
                color = Amber,
            )
        }

        Spacer(Modifier.height(14.dp))
        Button(
            onClick = save,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = Cyan, contentColor = Void),
        ) {
            Text("SAVE CONFIGURATION")
        }

        Spacer(Modifier.height(bottomPadding.calculateBottomPadding() + 26.dp))
    }

    pendingClear?.let { action ->
        AlertDialog(
            onDismissRequest = { pendingClear = null },
            title = { Text("Clear local data?") },
            text = {
                Text(
                    when (action) {
                        "conversation" -> "This deletes the visible chat history from this phone."
                        "memories" -> "This deletes every saved memory."
                        "tasks" -> "This deletes every task and its reminder."
                        else -> "This deletes completed tasks."
                    }
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    when (action) {
                        "conversation" -> viewModel.clearConversation()
                        "memories" -> viewModel.clearMemories()
                        "tasks" -> viewModel.clearTasks()
                        else -> viewModel.clearCompletedTasks()
                    }
                    pendingClear = null
                }) { Text("Clear", color = Danger) }
            },
            dismissButton = {
                TextButton(onClick = { pendingClear = null }) { Text("Cancel", color = TextSecondary) }
            },
            containerColor = Panel,
            titleContentColor = TextPrimary,
            textContentColor = TextPrimary,
        )
    }
}

@Composable
private fun ChoiceChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier
            .clip(RoundedCornerShape(9.dp))
            .background(if (selected) Cyan.copy(alpha = 0.14f) else Panel.copy(alpha = 0.4f))
            .border(
                1.dp,
                if (selected) Cyan.copy(alpha = 0.55f) else CyanDim.copy(alpha = 0.25f),
                RoundedCornerShape(9.dp),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 7.dp),
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = if (selected) Cyan else TextMuted,
        )
    }
}

@Composable
private fun ToggleRow(
    label: String,
    detail: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.titleMedium, color = TextPrimary)
            Text(detail, style = MaterialTheme.typography.labelSmall, color = TextMuted)
        }
        Spacer(Modifier.width(10.dp))
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = Void,
                checkedTrackColor = Cyan,
                uncheckedThumbColor = TextMuted,
                uncheckedTrackColor = PanelLight,
            ),
        )
    }
}

@Composable
private fun ActionLink(
    label: String,
    value: String,
    icon: ImageVector,
    valueColor: Color,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = Cyan, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(10.dp))
        Text(label, style = MaterialTheme.typography.titleMedium, color = TextPrimary, modifier = Modifier.weight(1f))
        Text(
            value,
            style = MaterialTheme.typography.labelSmall,
            color = valueColor,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Spacer(Modifier.width(4.dp))
        Icon(Icons.Filled.ChevronRight, contentDescription = null, tint = TextMuted, modifier = Modifier.size(16.dp))
    }
}

@Composable
private fun DataAction(label: String, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(9.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 9.dp),
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = Danger)
    }
}

@Composable
private fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = Cyan.copy(alpha = 0.6f),
    unfocusedBorderColor = CyanDim.copy(alpha = 0.35f),
    focusedContainerColor = Color(0xFF04121B),
    unfocusedContainerColor = Color(0xFF04121B),
    cursorColor = Cyan,
    focusedTextColor = TextPrimary,
    unfocusedTextColor = TextPrimary,
    focusedLabelColor = Cyan,
    unfocusedLabelColor = TextMuted,
)
