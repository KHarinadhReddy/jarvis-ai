package ai.jarvis.mobile.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val Void = Color(0xFF02060B)
val DeepNavy = Color(0xFF04101A)
val Panel = Color(0xFF071A26)
val PanelLight = Color(0xFF0B2433)
val Cyan = Color(0xFF35D6FF)
val CyanBright = Color(0xFF9BEAFF)
val CyanDim = Color(0xFF1A7E9E)
val Amber = Color(0xFFFFB454)
val Danger = Color(0xFFFF5A6E)
val Success = Color(0xFF4DFFB8)
val TextPrimary = Color(0xFFE6F8FF)
val TextSecondary = Color(0xFF7FA8B8)
val TextMuted = Color(0xFF4E7180)

private val JarvisScheme = darkColorScheme(
    primary = Cyan,
    onPrimary = Void,
    primaryContainer = CyanDim,
    onPrimaryContainer = TextPrimary,
    secondary = CyanBright,
    onSecondary = Void,
    secondaryContainer = PanelLight,
    onSecondaryContainer = TextPrimary,
    tertiary = Amber,
    onTertiary = Void,
    background = Void,
    onBackground = TextPrimary,
    surface = Panel,
    onSurface = TextPrimary,
    surfaceVariant = PanelLight,
    onSurfaceVariant = TextSecondary,
    outline = CyanDim,
    outlineVariant = Color(0xFF123849),
    error = Danger,
    onError = Color.White,
)

val JarvisTypography = Typography(
    displayLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Light,
        fontSize = 56.sp,
        letterSpacing = 4.sp,
        color = TextPrimary,
    ),
    displayMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Light,
        fontSize = 38.sp,
        letterSpacing = 2.sp,
        color = TextPrimary,
    ),
    headlineLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 26.sp,
        letterSpacing = 1.sp,
        color = TextPrimary,
    ),
    headlineMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 20.sp,
        letterSpacing = 0.6.sp,
        color = TextPrimary,
    ),
    titleLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 17.sp,
        letterSpacing = 0.4.sp,
        color = TextPrimary,
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 14.sp,
        letterSpacing = 0.3.sp,
        color = TextPrimary,
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 15.sp,
        lineHeight = 22.sp,
        color = TextPrimary,
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 13.sp,
        lineHeight = 19.sp,
        color = TextSecondary,
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.Monospace,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        letterSpacing = 1.4.sp,
        color = CyanBright,
    ),
    labelMedium = TextStyle(
        fontFamily = FontFamily.Monospace,
        fontWeight = FontWeight.Normal,
        fontSize = 10.sp,
        letterSpacing = 1.2.sp,
        color = TextSecondary,
    ),
    labelSmall = TextStyle(
        fontFamily = FontFamily.Monospace,
        fontWeight = FontWeight.Normal,
        fontSize = 9.sp,
        letterSpacing = 1.sp,
        color = TextMuted,
    ),
)

@Composable
fun JarvisTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = JarvisScheme,
        typography = JarvisTypography,
        content = content,
    )
}
