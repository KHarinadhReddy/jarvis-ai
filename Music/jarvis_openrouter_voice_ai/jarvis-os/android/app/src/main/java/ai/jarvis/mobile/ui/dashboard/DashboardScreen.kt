package ai.jarvis.mobile.ui.dashboard

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.filled.BatteryChargingFull
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.FlashlightOn
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.TaskAlt
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.data.PowerMode
import ai.jarvis.mobile.core.voice.SpeechState
import ai.jarvis.mobile.core.voice.VoiceState
import ai.jarvis.mobile.ui.chat.ChatViewModel
import ai.jarvis.mobile.ui.components.EmptyState
import ai.jarvis.mobile.ui.components.HudAction
import ai.jarvis.mobile.ui.components.HudNotices
import ai.jarvis.mobile.ui.components.HudPanel
import ai.jarvis.mobile.ui.components.MetricTile
import ai.jarvis.mobile.ui.components.Pill
import ai.jarvis.mobile.ui.components.Reactor
import ai.jarvis.mobile.ui.components.SectionLabel
import ai.jarvis.mobile.ui.components.StatusDot
import ai.jarvis.mobile.ui.theme.Amber
import ai.jarvis.mobile.ui.theme.Cyan
import ai.jarvis.mobile.ui.theme.CyanBright
import ai.jarvis.mobile.ui.theme.CyanDim
import ai.jarvis.mobile.ui.theme.Danger
import ai.jarvis.mobile.ui.theme.Panel
import ai.jarvis.mobile.ui.theme.Success
import ai.jarvis.mobile.ui.theme.TextMuted
import ai.jarvis.mobile.ui.theme.TextPrimary
import ai.jarvis.mobile.ui.theme.TextSecondary
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun DashboardScreen(
    app: JarvisApp,
    viewModel: DashboardViewModel,
    chatViewModel: ChatViewModel,
    onNavigate: (String) -> Unit,
) {
    val status by viewModel.status.collectAsStateWithLifecycle()
    val backend by viewModel.backend.collectAsStateWithLifecycle()
    val recent by viewModel.recent.collectAsStateWithLifecycle()
    val openTasks by viewModel.openTasks.collectAsStateWithLifecycle()
    val settings by chatViewModel.settings.collectAsStateWithLifecycle()
    val chatUi by chatViewModel.ui.collectAsStateWithLifecycle()
    val partial by chatViewModel.partial.collectAsStateWithLifecycle()
    val amplitude by chatViewModel.amplitude.collectAsStateWithLifecycle()
    val voiceState by chatViewModel.voiceState.collectAsStateWithLifecycle()
    val speechState by chatViewModel.speechState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var now by remember { mutableStateOf(LocalDateTime.now()) }
    LaunchedEffect(settings.powerMode) {
        val interval = when (settings.powerMode) {
            PowerMode.CINEMATIC -> 1_000L
            PowerMode.BALANCED -> 5_000L
            PowerMode.SAVER -> 30_000L
        }
        while (true) {
            now = LocalDateTime.now()
            delay(interval)
        }
    }
    LaunchedEffect(Unit) {
        viewModel.refreshStatus()
        viewModel.checkBackend()
    }

    val micPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            chatViewModel.toggleListening()
            onNavigate("chat")
        } else {
            HudNotices.show("Microphone permission is required for voice commands.")
        }
    }

    val startVoice: () -> Unit = {
        if (chatUi.listening) {
            chatViewModel.toggleListening()
        } else {
            val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
            if (granted) {
                chatViewModel.toggleListening()
                onNavigate("chat")
            } else {
                micPermission.launch(Manifest.permission.RECORD_AUDIO)
            }
        }
    }

    val torchToggle: () -> Unit = {
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                app.container.device.setFlashlight(!(status?.torchOn ?: false))
            }
            HudNotices.show(result.message)
            viewModel.refreshStatus()
        }
    }
    val goHome: () -> Unit = {
        scope.launch {
            val result = withContext(Dispatchers.IO) { app.container.device.globalAction("home") }
            HudNotices.show(result.message)
        }
    }

    val stateLabel = when {
        chatUi.listening || voiceState is VoiceState.Listening -> "Listening"
        speechState is SpeechState.Speaking -> "Speaking"
        chatUi.busy -> "Processing"
        else -> "Standby"
    }
    val online = backend.online

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    "J.A.R.V.I.S.",
                    style = MaterialTheme.typography.headlineLarge.copy(
                        fontFamily = FontFamily.SansSerif,
                        fontWeight = FontWeight.Light,
                        letterSpacing = 4.sp,
                        fontSize = 25.sp,
                    ),
                    color = CyanBright,
                )
                Text(
                    "MOBILE NODE • ${Build.MANUFACTURER.uppercase()} ${Build.MODEL}",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            IconButton(onClick = { onNavigate("settings") }) {
                Icon(Icons.Filled.Settings, contentDescription = "Settings", tint = TextSecondary)
            }
        }

        Row(
            Modifier.fillMaxWidth().padding(top = 2.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (backend.checking) {
                CircularProgressIndicator(modifier = Modifier.size(10.dp), strokeWidth = 1.2.dp, color = Amber)
                Spacer(Modifier.width(6.dp))
                Text("LINKING", style = MaterialTheme.typography.labelSmall, color = Amber)
            } else {
                StatusDot(online == true, if (online == true) Success else if (online == false) Danger else Amber)
                Spacer(Modifier.width(6.dp))
                Text(
                    when (online) {
                        true -> "ONLINE"
                        false -> "OFFLINE"
                        null -> "UNKNOWN"
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = when (online) {
                        true -> Success
                        false -> Danger
                        null -> Amber
                    },
                )
            }
            Spacer(Modifier.width(10.dp))
            Box(Modifier.weight(1f))
            Box(Modifier.clickable { onNavigate("settings") }) {
                Pill(
                    settings.powerMode.name,
                    if (settings.powerMode == PowerMode.SAVER) Amber else Cyan,
                )
            }
        }

        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                now.format(DateTimeFormatter.ofPattern("HH:mm")),
                style = MaterialTheme.typography.displayLarge.copy(
                    fontFamily = FontFamily.Monospace,
                    fontSize = 52.sp,
                    letterSpacing = 1.sp,
                ),
                color = TextPrimary,
            )
            Spacer(Modifier.width(12.dp))
            Column(Modifier.padding(bottom = 7.dp)) {
                Text(
                    now.format(DateTimeFormatter.ofPattern("EEEE")).uppercase(),
                    style = MaterialTheme.typography.labelMedium,
                    color = Cyan,
                )
                Text(
                    now.format(DateTimeFormatter.ofPattern("d MMMM yyyy")),
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
            }
        }

        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            Reactor(
                powerMode = settings.powerMode,
                listening = chatUi.listening || voiceState is VoiceState.Listening,
                speaking = speechState is SpeechState.Speaking,
                amplitude = amplitude,
                stateLabel = stateLabel,
                onClick = { onNavigate("chat") },
            )
        }

        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Box(
                    modifier = Modifier
                        .size(58.dp)
                        .clip(CircleShape)
                        .background(if (chatUi.listening) Amber.copy(alpha = 0.16f) else Cyan.copy(alpha = 0.10f))
                        .border(1.dp, if (chatUi.listening) Amber else CyanDim, CircleShape)
                        .clickable(onClick = startVoice),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        if (chatUi.listening) Icons.Filled.MicOff else Icons.Filled.Mic,
                        contentDescription = "Voice command",
                        tint = if (chatUi.listening) Amber else Cyan,
                        modifier = Modifier.size(25.dp),
                    )
                }
                Spacer(Modifier.height(5.dp))
                Text(
                    if (chatUi.listening) "TAP TO STOP" else "TAP TO SPEAK",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (chatUi.listening) Amber else TextMuted,
                )
            }
        }

        if (partial.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            HudPanel(accent = Amber, contentPadding = 12.dp, modifier = Modifier.fillMaxWidth()) {
                Text(
                    partial,
                    style = MaterialTheme.typography.bodyLarge,
                    color = TextPrimary,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }

        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            MetricTile(
                label = "Battery",
                value = "${status?.batteryPercent ?: 0}%",
                detail = if (status?.charging == true) "charging • ${status?.temperatureC}°C" else "on battery • ${status?.temperatureC}°C",
                icon = Icons.Filled.BatteryChargingFull,
                modifier = Modifier.weight(1f),
                accent = if ((status?.batteryPercent ?: 100) < 20) Danger else Cyan,
            )
            MetricTile(
                label = "Network",
                value = status?.network ?: "Checking",
                detail = if (online == true) "backend reachable" else "backend not checked",
                icon = Icons.Filled.Wifi,
                modifier = Modifier.weight(1f),
            )
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            MetricTile(
                label = "Storage",
                value = "%.1f GB".format(status?.storageFreeGb ?: 0.0),
                detail = "free of %.0f GB".format(status?.storageTotalGb ?: 0.0),
                icon = Icons.Filled.Storage,
                modifier = Modifier.weight(1f),
            )
            MetricTile(
                label = "Open tasks",
                value = openTasks.toString(),
                detail = if (openTasks == 0) "nothing due" else "tap vault to review",
                icon = Icons.Filled.TaskAlt,
                modifier = Modifier.weight(1f),
                accent = Amber,
            )
        }

        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
            HudAction(
                "Torch",
                Icons.Filled.FlashlightOn,
                onClick = torchToggle,
                modifier = Modifier.weight(1f),
                enabled = status?.torchOn != null,
            )
            HudAction(
                "Home",
                Icons.Filled.Home,
                onClick = goHome,
                modifier = Modifier.weight(1f),
                enabled = status?.accessibility == true,
            )
            HudAction(
                "Scan",
                Icons.Filled.CameraAlt,
                onClick = { onNavigate("vision") },
                modifier = Modifier.weight(1f),
            )
            HudAction(
                "Vault",
                Icons.Filled.TaskAlt,
                onClick = { onNavigate("vault") },
                modifier = Modifier.weight(1f),
                accent = Amber,
            )
        }

        if (online == false) {
            Spacer(Modifier.height(14.dp))
            HudPanel(accent = Danger, contentPadding = 13.dp, modifier = Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    StatusDot(false, Danger)
                    Spacer(Modifier.width(8.dp))
                    Text("BACKEND OFFLINE", style = MaterialTheme.typography.labelSmall, color = Danger)
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = viewModel::checkBackend) {
                        Text("Retry", color = Cyan)
                    }
                }
                Text(
                    backend.message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextSecondary,
                )
                Text(
                    "Phone controls still work. Chat, vision, and cloud speech need the backend.",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
            }
        } else if (online == true) {
            Spacer(Modifier.height(12.dp))
            val modelLine = if (backend.configured) {
                if (backend.models.size > 1) {
                    "${backend.provider} • ${backend.model} • ${backend.models.size} models"
                } else {
                    "${backend.provider} • ${backend.model}"
                }
            } else {
                "NO AI KEY"
            }
            Pill(
                modelLine,
                if (backend.configured) Cyan else Amber,
                modifier = Modifier.fillMaxWidth(),
                maxLines = 2,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                if (backend.configured) {
                    if (backend.models.size > 1) {
                        "AI link ready • ${backend.models.joinToString(", ")}"
                    } else {
                        "AI link ready"
                    }
                } else {
                    "Add a key on the server"
                },
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }

        Spacer(Modifier.height(16.dp))
        SectionLabel("Recent transmissions") {
            TextButton(onClick = { onNavigate("chat") }) {
                Text("Open link", color = Cyan, style = MaterialTheme.typography.labelSmall)
            }
        }
        if (recent.isEmpty()) {
            EmptyState(
                title = "No transmissions yet",
                detail = "Your first conversation will appear here.",
                icon = Icons.Filled.GraphicEq,
            )
        } else {
            recent.reversed().forEach { message ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(10.dp))
                        .clickable { onNavigate("chat") }
                        .padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        Modifier
                            .size(6.dp)
                            .background(if (message.role == "user") CyanDim else Cyan, CircleShape)
                    )
                    Spacer(Modifier.width(9.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            if (message.role == "user") "YOU" else "J.A.R.V.I.S.",
                            style = MaterialTheme.typography.labelSmall,
                            color = if (message.role == "user") TextMuted else Cyan,
                        )
                        Text(
                            message.content,
                            style = MaterialTheme.typography.bodyMedium,
                            color = TextSecondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }

        Spacer(Modifier.height(90.dp))
    }
}
