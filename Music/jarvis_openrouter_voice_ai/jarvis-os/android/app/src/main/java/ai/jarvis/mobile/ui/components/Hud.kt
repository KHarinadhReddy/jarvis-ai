package ai.jarvis.mobile.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
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
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.jarvis.mobile.core.data.PowerMode
import ai.jarvis.mobile.ui.theme.Cyan
import ai.jarvis.mobile.ui.theme.CyanBright
import ai.jarvis.mobile.ui.theme.CyanDim
import ai.jarvis.mobile.ui.theme.Panel
import ai.jarvis.mobile.ui.theme.PanelLight
import ai.jarvis.mobile.ui.theme.TextMuted
import ai.jarvis.mobile.ui.theme.TextPrimary
import ai.jarvis.mobile.ui.theme.TextSecondary
import ai.jarvis.mobile.ui.theme.Void
import kotlinx.coroutines.isActive

@Composable
fun HudBackground(
    powerMode: PowerMode,
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit,
) {
    val scan = remember { Animatable(0f) }
    LaunchedEffect(powerMode) {
        if (powerMode == PowerMode.SAVER) {
            scan.snapTo(0f)
            return@LaunchedEffect
        }
        val duration = if (powerMode == PowerMode.CINEMATIC) 6500 else 14000
        while (isActive) {
            scan.snapTo(0f)
            scan.animateTo(1f, animationSpec = tween(duration, easing = LinearEasing))
        }
    }
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(
                Brush.radialGradient(
                    colors = listOf(Color(0xFF082131), Void, Void),
                    center = Offset(0.5f, 0.18f),
                    radius = 1600f,
                )
            ),
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val step = 56.dp.toPx()
            var x = 0f
            while (x < size.width) {
                drawLine(Cyan.copy(alpha = 0.028f), Offset(x, 0f), Offset(x, size.height), 1f)
                x += step
            }
            var y = 0f
            while (y < size.height) {
                drawLine(Cyan.copy(alpha = 0.028f), Offset(0f, y), Offset(size.width, y), 1f)
                y += step
            }
            if (scan.value > 0f) {
                val scanY = scan.value * size.height
                drawRect(
                    brush = Brush.verticalGradient(
                        colors = listOf(Color.Transparent, Cyan.copy(alpha = 0.075f), Color.Transparent),
                        startY = scanY - 70.dp.toPx(),
                        endY = scanY + 70.dp.toPx(),
                    ),
                    topLeft = Offset(0f, scanY - 70.dp.toPx()),
                    size = Size(size.width, 140.dp.toPx()),
                )
                drawLine(
                    color = Cyan.copy(alpha = 0.16f),
                    start = Offset(0f, scanY),
                    end = Offset(size.width, scanY),
                    strokeWidth = 1.2f,
                )
            }
        }
        content()
    }
}

@Composable
fun HudPanel(
    modifier: Modifier = Modifier,
    title: String? = null,
    accent: Color = Cyan,
    contentPadding: Dp = 16.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .background(
                Brush.verticalGradient(
                    listOf(Panel.copy(alpha = 0.92f), Color(0xFF04121B).copy(alpha = 0.94f)),
                )
            )
            .border(1.dp, accent.copy(alpha = 0.22f), RoundedCornerShape(16.dp)),
    ) {
        Column(Modifier.padding(contentPadding)) {
            if (title != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier
                            .size(width = 18.dp, height = 2.dp)
                            .background(accent, CircleShape)
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        text = title.uppercase(),
                        style = MaterialTheme.typography.labelLarge,
                        color = accent.copy(alpha = 0.9f),
                    )
                }
                Spacer(Modifier.height(12.dp))
            }
            content()
        }
        CornerBrackets(accent)
    }
}

@Composable
private fun BoxScope.CornerBrackets(accent: Color) {
    Canvas(Modifier.matchParentSize().padding(7.dp)) {
        val length = 15.dp.toPx()
        val stroke = 1.6.dp.toPx()
        val color = accent.copy(alpha = 0.55f)
        drawLine(color, Offset(0f, 0f), Offset(length, 0f), stroke, StrokeCap.Round)
        drawLine(color, Offset(0f, 0f), Offset(0f, length), stroke, StrokeCap.Round)
        drawLine(color, Offset(size.width, 0f), Offset(size.width - length, 0f), stroke, StrokeCap.Round)
        drawLine(color, Offset(size.width, 0f), Offset(size.width, length), stroke, StrokeCap.Round)
        drawLine(color, Offset(0f, size.height), Offset(length, size.height), stroke, StrokeCap.Round)
        drawLine(color, Offset(0f, size.height), Offset(0f, size.height - length), stroke, StrokeCap.Round)
        drawLine(color, Offset(size.width, size.height), Offset(size.width - length, size.height), stroke, StrokeCap.Round)
        drawLine(color, Offset(size.width, size.height), Offset(size.width, size.height - length), stroke, StrokeCap.Round)
    }
}

@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier, trailing: @Composable (() -> Unit)? = null) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text.uppercase(),
            style = MaterialTheme.typography.labelMedium,
            color = TextMuted,
        )
        trailing?.invoke()
    }
}

@Composable
fun StatusDot(active: Boolean, color: Color = Cyan, size: Dp = 9.dp) {
    Canvas(Modifier.size(size)) {
        if (active) {
            drawCircle(color.copy(alpha = 0.18f), radius = this.size.minDimension * 0.5f)
            drawCircle(color, radius = this.size.minDimension * 0.28f)
        } else {
            drawCircle(TextMuted.copy(alpha = 0.5f), radius = this.size.minDimension * 0.24f)
        }
    }
}

@Composable
fun MetricTile(
    label: String,
    value: String,
    detail: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    accent: Color = Cyan,
) {
    HudPanel(modifier = modifier, contentPadding = 13.dp) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, contentDescription = null, tint = accent, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(7.dp))
            Text(
                label.uppercase(),
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.height(9.dp))
        Text(
            value,
            style = MaterialTheme.typography.headlineMedium.copy(
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Medium,
                fontSize = 21.sp,
            ),
            color = TextPrimary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            detail,
            style = MaterialTheme.typography.labelSmall,
            color = TextSecondary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
fun HudAction(
    label: String,
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    accent: Color = Cyan,
    enabled: Boolean = true,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(PanelLight.copy(alpha = if (enabled) 0.7f else 0.25f))
            .border(1.dp, accent.copy(alpha = if (enabled) 0.24f else 0.08f), RoundedCornerShape(14.dp))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(vertical = 12.dp, horizontal = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            icon,
            contentDescription = label,
            tint = if (enabled) accent else TextMuted,
            modifier = Modifier.size(22.dp),
        )
        Spacer(Modifier.height(6.dp))
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = if (enabled) TextSecondary else TextMuted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
fun Pill(
    text: String,
    color: Color = Cyan,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    maxLines: Int = 1,
) {
    Row(
        modifier = modifier
            .clip(CircleShape)
            .background(color.copy(alpha = 0.10f))
            .border(1.dp, color.copy(alpha = 0.30f), CircleShape)
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(12.dp))
            Spacer(Modifier.width(5.dp))
        }
        Text(
            text.uppercase(),
            style = MaterialTheme.typography.labelSmall.copy(fontSize = 9.sp),
            color = color,
            maxLines = maxLines,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
fun CyanDivider(modifier: Modifier = Modifier) {
    Box(
        modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(
                Brush.horizontalGradient(
                    listOf(Color.Transparent, CyanDim.copy(alpha = 0.5f), Color.Transparent)
                )
            )
    )
}

@Composable
fun KeyValueRow(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    valueColor: Color = TextPrimary,
) {
    Row(
        modifier.fillMaxWidth().padding(vertical = 5.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = TextSecondary)
        Text(
            value,
            style = MaterialTheme.typography.labelLarge.copy(fontSize = 11.sp),
            color = valueColor,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
fun EmptyState(title: String, detail: String, icon: ImageVector? = null) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 26.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = CyanDim, modifier = Modifier.size(30.dp))
            Spacer(Modifier.height(10.dp))
        }
        Text(title, style = MaterialTheme.typography.titleMedium, color = TextSecondary)
        Spacer(Modifier.height(4.dp))
        Text(detail, style = MaterialTheme.typography.bodyMedium, color = TextMuted)
    }
}
