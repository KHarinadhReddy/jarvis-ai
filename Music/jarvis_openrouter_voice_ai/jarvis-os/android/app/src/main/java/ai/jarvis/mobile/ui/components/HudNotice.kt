package ai.jarvis.mobile.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import ai.jarvis.mobile.ui.theme.Cyan
import ai.jarvis.mobile.ui.theme.Panel
import ai.jarvis.mobile.ui.theme.TextPrimary
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * In-app replacement for Android Toasts. The emulator's system toast renders
 * white-on-white, and toasts are easy to miss over the HUD, so notices are
 * drawn inside the app where they stay legible and themed.
 */
object HudNotices {
    private val _messages = MutableSharedFlow<String>(
        extraBufferCapacity = 8,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val messages: SharedFlow<String> = _messages.asSharedFlow()

    fun show(message: String) {
        if (message.isNotBlank()) _messages.tryEmit(message)
    }
}

@Composable
fun HudNoticeHost(modifier: Modifier = Modifier) {
    var message by remember { mutableStateOf<String?>(null) }
    var visible by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        HudNotices.messages.collect { incoming ->
            message = incoming
            visible = true
        }
    }
    LaunchedEffect(message) {
        if (message != null) {
            delay(4_000)
            visible = false
            delay(250)
            message = null
        }
    }

    AnimatedVisibility(
        visible = visible && message != null,
        modifier = modifier.fillMaxWidth(),
        enter = fadeIn() + slideInVertically { it / 2 },
        exit = fadeOut() + slideOutVertically { it / 2 },
    ) {
        message?.let { text ->
            Column(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(Panel.copy(alpha = 0.98f))
                    .border(1.dp, Cyan.copy(alpha = 0.45f), RoundedCornerShape(14.dp))
                    .padding(horizontal = 14.dp, vertical = 10.dp),
            ) {
                Text("SYSTEM NOTICE", style = MaterialTheme.typography.labelSmall, color = Cyan)
                Text(text, style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
            }
        }
    }
}
