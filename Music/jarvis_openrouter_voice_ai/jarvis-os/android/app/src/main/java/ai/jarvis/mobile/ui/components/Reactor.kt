package ai.jarvis.mobile.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.jarvis.mobile.core.data.PowerMode
import ai.jarvis.mobile.ui.theme.Amber
import ai.jarvis.mobile.ui.theme.Cyan
import ai.jarvis.mobile.ui.theme.CyanBright
import ai.jarvis.mobile.ui.theme.Success
import ai.jarvis.mobile.ui.theme.TextMuted
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlinx.coroutines.isActive

@Composable
fun Reactor(
    powerMode: PowerMode,
    listening: Boolean,
    speaking: Boolean,
    amplitude: Float,
    stateLabel: String,
    modifier: Modifier = Modifier,
    onClick: () -> Unit = {},
) {
    val animate = powerMode != PowerMode.SAVER
    val angle = remember { Animatable(0f) }
    LaunchedEffect(animate, powerMode) {
        if (!animate) {
            angle.snapTo(0f)
            return@LaunchedEffect
        }
        val duration = if (powerMode == PowerMode.CINEMATIC) 14000 else 30000
        while (isActive) {
            angle.snapTo(0f)
            angle.animateTo(360f, animationSpec = tween(duration, easing = LinearEasing))
        }
    }
    val accent = when {
        listening -> Amber
        speaking -> Success
        else -> Cyan
    }
    val level = amplitude.coerceIn(0f, 1f)
    val rotation = angle.value

    Box(
        modifier = modifier
            .size(276.dp)
            .clip(CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val center = Offset(size.width / 2f, size.height / 2f)
            val minSide = size.minDimension
            val pulse = 0.5f + 0.5f * sin((rotation / 180f * PI).toFloat())
            val outer = minSide * 0.475f

            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(accent.copy(alpha = 0.13f + 0.05f * pulse), Color.Transparent),
                    center = center,
                    radius = outer * 1.05f,
                ),
                radius = outer * 1.05f,
                center = center,
            )

            drawCircle(
                color = accent.copy(alpha = 0.24f),
                radius = outer,
                center = center,
                style = Stroke(width = 1.1.dp.toPx()),
            )
            drawCircle(
                color = accent.copy(alpha = 0.12f),
                radius = outer * 0.93f,
                center = center,
                style = Stroke(width = 0.8.dp.toPx()),
            )

            repeat(72) { index ->
                val tickAngle = index * 5f
                val major = index % 6 == 0
                val inner = outer * if (major) 0.885f else 0.915f
                val outerTick = outer * 0.955f
                rotate(tickAngle) {
                    drawLine(
                        color = accent.copy(alpha = if (major) 0.62f else 0.22f),
                        start = Offset(center.x, center.y - inner),
                        end = Offset(center.x, center.y - outerTick),
                        strokeWidth = if (major) 1.6.dp.toPx() else 0.8.dp.toPx(),
                        cap = StrokeCap.Round,
                    )
                }
            }

            rotate(rotation) {
                drawArc(
                    brush = Brush.sweepGradient(
                        listOf(Color.Transparent, accent.copy(alpha = 0.85f), Color.Transparent),
                    ),
                    startAngle = 0f,
                    sweepAngle = 74f,
                    useCenter = false,
                    topLeft = Offset(center.x - outer * 0.82f, center.y - outer * 0.82f),
                    size = Size(outer * 1.64f, outer * 1.64f),
                    style = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round),
                )
            }
            rotate(-rotation * 1.35f) {
                drawArc(
                    color = CyanBright.copy(alpha = 0.65f),
                    startAngle = 148f,
                    sweepAngle = 44f,
                    useCenter = false,
                    topLeft = Offset(center.x - outer * 0.72f, center.y - outer * 0.72f),
                    size = Size(outer * 1.44f, outer * 1.44f),
                    style = Stroke(width = 1.7.dp.toPx(), cap = StrokeCap.Round),
                )
            }
            rotate(rotation * 0.55f) {
                drawArc(
                    color = accent.copy(alpha = 0.38f),
                    startAngle = 240f,
                    sweepAngle = 96f,
                    useCenter = false,
                    topLeft = Offset(center.x - outer * 0.63f, center.y - outer * 0.63f),
                    size = Size(outer * 1.26f, outer * 1.26f),
                    style = Stroke(width = 0.9.dp.toPx(), cap = StrokeCap.Round),
                )
            }

            val waveRadius = outer * 0.52f
            val points = 84
            var previous: Offset? = null
            for (index in 0..points) {
                val theta = index.toFloat() / points * 2f * PI.toFloat()
                val wobble = sin(theta * 7f + rotation / 28f) * 0.018f
                val voice = sin(theta * 3f - rotation / 20f) * level * 0.055f
                val radius = waveRadius * (1f + wobble + voice)
                val point = Offset(
                    center.x + cos(theta) * radius,
                    center.y + sin(theta) * radius,
                )
                if (previous != null) {
                    drawLine(
                        color = accent.copy(alpha = 0.28f + 0.30f * level),
                        start = previous!!,
                        end = point,
                        strokeWidth = 1.1.dp.toPx(),
                        cap = StrokeCap.Round,
                    )
                }
                previous = point
            }

            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(accent.copy(alpha = 0.26f), accent.copy(alpha = 0.04f), Color.Transparent),
                    center = center,
                    radius = outer * 0.44f,
                ),
                radius = outer * 0.44f,
                center = center,
            )
            drawCircle(
                color = accent.copy(alpha = 0.18f + 0.10f * pulse),
                radius = outer * 0.22f,
                center = center,
            )
            drawCircle(
                color = accent.copy(alpha = 0.85f),
                radius = outer * 0.115f,
                center = center,
            )
            drawCircle(
                color = Color.White.copy(alpha = 0.9f),
                radius = outer * 0.045f,
                center = center,
            )

            drawLine(
                color = accent.copy(alpha = 0.20f),
                start = Offset(center.x - outer * 0.66f, center.y),
                end = Offset(center.x - outer * 0.30f, center.y),
                strokeWidth = 1f,
            )
            drawLine(
                color = accent.copy(alpha = 0.20f),
                start = Offset(center.x + outer * 0.30f, center.y),
                end = Offset(center.x + outer * 0.66f, center.y),
                strokeWidth = 1f,
            )
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Spacer(Modifier.height(86.dp))
            Text(
                "J.A.R.V.I.S.",
                style = MaterialTheme.typography.labelMedium.copy(
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Medium,
                    fontSize = 10.sp,
                    letterSpacing = 2.6.sp,
                ),
                color = accent.copy(alpha = 0.92f),
            )
            Spacer(Modifier.height(4.dp))
            Text(
                stateLabel.uppercase(),
                style = MaterialTheme.typography.labelSmall.copy(fontSize = 8.sp, letterSpacing = 1.4.sp),
                color = TextMuted,
            )
        }
    }
}
