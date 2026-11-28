package ai.jarvis.mobile.ui.chat

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.VolumeOff
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.data.JarvisSettings
import ai.jarvis.mobile.core.data.MessageEntity
import ai.jarvis.mobile.core.voice.SpeechState
import ai.jarvis.mobile.core.voice.VoiceState
import ai.jarvis.mobile.ui.components.EmptyState
import ai.jarvis.mobile.ui.components.HudNotices
import ai.jarvis.mobile.ui.components.HudPanel
import ai.jarvis.mobile.ui.components.Pill
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
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
fun ChatScreen(
    app: JarvisApp,
    viewModel: ChatViewModel,
    bottomPadding: PaddingValues,
) {
    val messages by viewModel.messages.collectAsStateWithLifecycle()
    val ui by viewModel.ui.collectAsStateWithLifecycle()
    val settings by viewModel.settings.collectAsStateWithLifecycle()
    val partial by viewModel.partial.collectAsStateWithLifecycle()
    val speechState by viewModel.speechState.collectAsStateWithLifecycle()
    val voiceState by viewModel.voiceState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val listState = rememberLazyListState()
    var input by remember { mutableStateOf("") }
    var showClear by remember { mutableStateOf(false) }

    val micPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            viewModel.toggleListening()
        } else {
            HudNotices.show("Microphone permission is required for voice input.")
        }
    }

    LaunchedEffect(messages.size, ui.streamingText, ui.status, ui.busy) {
        val total = listState.layoutInfo.totalItemsCount
        if (total > 0) {
            runCatching { listState.scrollToItem(total - 1) }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp)
            .padding(top = 10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("NEURAL LINK", style = MaterialTheme.typography.labelLarge, color = CyanBright)
                Text(
                    "Reasoning, phone tools, and spoken replies",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
            }
            if (speechState is SpeechState.Speaking) {
                Pill("Speaking", Success, icon = Icons.Filled.VolumeUp)
                Spacer(Modifier.width(4.dp))
            }
            IconButton(onClick = { viewModel.setTtsEnabled(!settings.ttsEnabled) }) {
                Icon(
                    if (settings.ttsEnabled) Icons.Filled.VolumeUp else Icons.Filled.VolumeOff,
                    contentDescription = "Toggle spoken replies",
                    tint = if (settings.ttsEnabled) Cyan else TextMuted,
                )
            }
            IconButton(onClick = { showClear = true }) {
                Icon(Icons.Filled.DeleteSweep, contentDescription = "Clear conversation", tint = TextSecondary)
            }
        }

        Row(
            Modifier.fillMaxWidth().padding(vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            LanguageChip("ENGLISH", ui.listenLanguage == "en-IN") {
                viewModel.setLanguage("en-IN")
            }
            LanguageChip("తెలుగు", ui.listenLanguage == "te-IN") {
                viewModel.setLanguage("te-IN")
            }
            Spacer(Modifier.weight(1f))
            Text(
                when (voiceState) {
                    is VoiceState.Listening -> "MIC LIVE"
                    is VoiceState.Processing -> "TRANSCRIBING"
                    else -> "STT READY"
                },
                style = MaterialTheme.typography.labelSmall,
                color = if (voiceState is VoiceState.Listening) Amber else TextMuted,
            )
        }

        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            state = listState,
            verticalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(bottom = 10.dp),
        ) {
            if (messages.isEmpty() && !ui.busy) {
                item {
                    EmptyState(
                        title = "The link is quiet",
                        detail = "Speak or type. I can answer, reason, and control this phone with real Android actions.",
                        icon = Icons.Filled.GraphicEq,
                    )
                }
            }
            items(messages, key = { it.id }) { message ->
                MessageBubble(
                    message = message,
                    onSpeak = { viewModel.stopSpeaking(); app.container.speech.speak(message.content) },
                )
            }
            if (ui.busy || ui.streamingText.isNotBlank()) {
                item {
                    StreamingBubble(
                        text = ui.streamingText,
                        status = ui.status ?: "Thinking",
                    )
                }
            }
        }

        if (ui.listening || partial.isNotBlank()) {
            HudPanel(accent = Amber, contentPadding = 12.dp, modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    StatusDot(true, Amber)
                    Spacer(Modifier.width(8.dp))
                    Text("LISTENING", style = MaterialTheme.typography.labelSmall, color = Amber)
                    Spacer(Modifier.weight(1f))
                    Text("tap mic to finish", style = MaterialTheme.typography.labelSmall, color = TextMuted)
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    partial.ifBlank { "Speak now..." },
                    style = MaterialTheme.typography.bodyLarge,
                    color = TextPrimary,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }

        if (speechState is SpeechState.Error) {
            Row(
                Modifier.fillMaxWidth().padding(bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = Danger, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text(
                    (speechState as SpeechState.Error).message,
                    style = MaterialTheme.typography.labelSmall,
                    color = Danger,
                    modifier = Modifier.weight(1f),
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                IconButton(onClick = { viewModel.stopSpeaking() }, modifier = Modifier.size(28.dp)) {
                    Icon(Icons.Filled.Close, contentDescription = "Dismiss speech error", tint = Danger, modifier = Modifier.size(14.dp))
                }
            }
        }

        if (ui.error != null) {
            HudPanel(accent = Danger, contentPadding = 11.dp, modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = Danger, modifier = Modifier.size(17.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(
                        ui.error ?: "",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextPrimary,
                        modifier = Modifier.weight(1f),
                        maxLines = 4,
                        overflow = TextOverflow.Ellipsis,
                    )
                    IconButton(onClick = viewModel::dismissError, modifier = Modifier.size(28.dp)) {
                        Icon(Icons.Filled.Close, contentDescription = "Dismiss", tint = TextSecondary, modifier = Modifier.size(15.dp))
                    }
                }
            }
        }

        if (ui.status != null && !ui.busy) {
            Text(
                ui.status ?: "",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
                modifier = Modifier.padding(bottom = 4.dp),
            )
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(bottom = bottomPadding.calculateBottomPadding() + 8.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Ask J.A.R.V.I.S. or give a command", color = TextMuted, fontSize = 14.sp) },
                maxLines = 4,
                shape = RoundedCornerShape(20.dp),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = {
                    if (input.isNotBlank() && !ui.busy) {
                        viewModel.send(input)
                        input = ""
                    }
                }),
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
            Spacer(Modifier.width(6.dp))
            Box(
                modifier = Modifier
                    .size(52.dp)
                    .clip(CircleShape)
                    .background(if (ui.listening) Amber.copy(alpha = 0.18f) else Cyan.copy(alpha = 0.10f))
                    .border(1.dp, if (ui.listening) Amber else CyanDim, CircleShape)
                    .clickable {
                        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                            PackageManager.PERMISSION_GRANTED
                        if (granted) viewModel.toggleListening() else micPermission.launch(Manifest.permission.RECORD_AUDIO)
                    },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    if (ui.listening) Icons.Filled.MicOff else Icons.Filled.Mic,
                    contentDescription = "Voice input",
                    tint = if (ui.listening) Amber else Cyan,
                )
            }
            Spacer(Modifier.width(6.dp))
            IconButton(
                onClick = {
                    if (input.isNotBlank() && !ui.busy) {
                        viewModel.send(input)
                        input = ""
                    }
                },
                enabled = input.isNotBlank() && !ui.busy,
                modifier = Modifier
                    .size(52.dp)
                    .clip(CircleShape)
                    .background(if (input.isNotBlank() && !ui.busy) Cyan.copy(alpha = 0.16f) else Panel)
                    .border(1.dp, CyanDim.copy(alpha = 0.4f), CircleShape),
            ) {
                Icon(Icons.Filled.Send, contentDescription = "Send", tint = if (input.isNotBlank()) Cyan else TextMuted)
            }
        }
    }

    ui.pending?.let { pending ->
        AlertDialog(
            onDismissRequest = { viewModel.resolveConfirmation(false) },
            title = { Text("Confirm device action") },
            text = {
                Column {
                    Text(pending.label, style = MaterialTheme.typography.bodyLarge)
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "This action will run on your phone now. Approve only if you asked for it.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextSecondary,
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = { viewModel.resolveConfirmation(true) }) {
                    Text("Approve", color = Cyan)
                }
            },
            dismissButton = {
                TextButton(onClick = { viewModel.resolveConfirmation(false) }) {
                    Text("Cancel", color = TextSecondary)
                }
            },
            containerColor = Panel,
            titleContentColor = TextPrimary,
            textContentColor = TextPrimary,
        )
    }

    if (showClear) {
        AlertDialog(
            onDismissRequest = { showClear = false },
            title = { Text("Clear conversation?") },
            text = { Text("This removes the visible chat history from this phone. Saved memories and tasks are kept.") },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.clearConversation()
                    showClear = false
                }) { Text("Clear", color = Danger) }
            },
            dismissButton = {
                TextButton(onClick = { showClear = false }) { Text("Cancel", color = TextSecondary) }
            },
            containerColor = Panel,
            titleContentColor = TextPrimary,
            textContentColor = TextPrimary,
        )
    }
}

@Composable
private fun LanguageChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(if (selected) Cyan.copy(alpha = 0.14f) else Color.Transparent)
            .border(
                1.dp,
                if (selected) Cyan.copy(alpha = 0.5f) else CyanDim.copy(alpha = 0.25f),
                RoundedCornerShape(8.dp),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 5.dp),
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = if (selected) Cyan else TextMuted,
        )
    }
}

@Composable
private fun MessageBubble(message: MessageEntity, onSpeak: () -> Unit) {
    val isUser = message.role == "user"
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(
            Modifier
                .widthIn(max = 330.dp)
                .clip(
                    RoundedCornerShape(
                        topStart = 16.dp,
                        topEnd = 16.dp,
                        bottomStart = if (isUser) 16.dp else 4.dp,
                        bottomEnd = if (isUser) 4.dp else 16.dp,
                    )
                )
                .background(if (isUser) Color(0xFF0C3141).copy(alpha = 0.85f) else Panel.copy(alpha = 0.88f))
                .border(
                    1.dp,
                    if (isUser) Cyan.copy(alpha = 0.30f) else CyanDim.copy(alpha = 0.25f),
                    RoundedCornerShape(16.dp),
                )
                .padding(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (isUser) "YOU" else "J.A.R.V.I.S.",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (isUser) CyanBright else Cyan,
                )
                Spacer(Modifier.weight(1f))
                Text(
                    formatTime(message.createdAt),
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
                if (!isUser) {
                    Spacer(Modifier.width(2.dp))
                    Box(
                        Modifier
                            .size(24.dp)
                            .clip(CircleShape)
                            .clickable(onClick = onSpeak),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            Icons.Filled.VolumeUp,
                            contentDescription = "Speak this reply",
                            tint = CyanDim,
                            modifier = Modifier.size(13.dp),
                        )
                    }
                }
            }
            Spacer(Modifier.height(5.dp))
            Text(
                message.content,
                style = MaterialTheme.typography.bodyLarge,
                color = TextPrimary,
            )
        }
    }
}

@Composable
private fun StreamingBubble(text: String, status: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
        Column(
            Modifier
                .widthIn(max = 330.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(Panel.copy(alpha = 0.88f))
                .border(1.dp, Cyan.copy(alpha = 0.30f), RoundedCornerShape(16.dp))
                .padding(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(
                    modifier = Modifier.size(12.dp),
                    strokeWidth = 1.5.dp,
                    color = Cyan,
                )
                Spacer(Modifier.width(7.dp))
                Text(
                    status.uppercase(),
                    style = MaterialTheme.typography.labelSmall,
                    color = Cyan,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (text.isNotBlank()) {
                Spacer(Modifier.height(7.dp))
                Text(text, style = MaterialTheme.typography.bodyLarge, color = TextPrimary)
            }
        }
    }
}

private fun formatTime(epochMillis: Long): String =
    Instant.ofEpochMilli(epochMillis)
        .atZone(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofPattern("HH:mm"))
