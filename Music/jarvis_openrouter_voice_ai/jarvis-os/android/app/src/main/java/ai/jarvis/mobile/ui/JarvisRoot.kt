package ai.jarvis.mobile.ui

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
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.data.JarvisSettings
import ai.jarvis.mobile.ui.chat.ChatScreen
import ai.jarvis.mobile.ui.chat.ChatViewModel
import ai.jarvis.mobile.ui.components.HudBackground
import ai.jarvis.mobile.ui.components.HudNoticeHost
import ai.jarvis.mobile.ui.control.ControlScreen
import ai.jarvis.mobile.ui.control.ControlViewModel
import ai.jarvis.mobile.ui.dashboard.DashboardScreen
import ai.jarvis.mobile.ui.dashboard.DashboardViewModel
import ai.jarvis.mobile.ui.settings.SettingsScreen
import ai.jarvis.mobile.ui.settings.SettingsViewModel
import ai.jarvis.mobile.ui.theme.Cyan
import ai.jarvis.mobile.ui.theme.CyanBright
import ai.jarvis.mobile.ui.theme.CyanDim
import ai.jarvis.mobile.ui.theme.Panel
import ai.jarvis.mobile.ui.theme.TextMuted
import ai.jarvis.mobile.ui.theme.Void
import ai.jarvis.mobile.ui.vault.VaultScreen
import ai.jarvis.mobile.ui.vault.VaultViewModel
import ai.jarvis.mobile.ui.vision.VisionScreen
import ai.jarvis.mobile.ui.vision.VisionViewModel

private data class Destination(
    val route: String,
    val label: String,
    val icon: ImageVector,
)

private val destinations = listOf(
    Destination("dashboard", "Bridge", Icons.Filled.Home),
    Destination("chat", "Link", Icons.Filled.GraphicEq),
    Destination("control", "Control", Icons.Filled.Tune),
    Destination("vision", "Optics", Icons.Filled.CameraAlt),
    Destination("vault", "Vault", Icons.Filled.Storage),
)

private const val SETTINGS_ROUTE = "settings"

@Composable
fun JarvisRoot(app: JarvisApp) {
    val navController = rememberNavController()
    val settings by app.container.settingsStore.settings
        .collectAsStateWithLifecycle(initialValue = JarvisSettings())

    // One shared chat engine: the dashboard and the chat screen must not run
    // two collectors against the same microphone session.
    val chatViewModel: ChatViewModel = viewModel(
        factory = viewModelFactory { initializer { ChatViewModel(app) } },
    )

    HudBackground(powerMode = settings.powerMode) {
        Scaffold(
            containerColor = Color.Transparent,
            contentWindowInsets = androidx.compose.foundation.layout.WindowInsets(0, 0, 0, 0),
            bottomBar = {
                HudBottomBar(
                    selectedRoute = navController.currentBackStackEntryAsState().value?.destination?.route,
                    onSelect = { route ->
                        if (route == SETTINGS_ROUTE) {
                            navController.navigate(route) { launchSingleTop = true }
                        } else {
                            navController.navigate(route) {
                                popUpTo(navController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        }
                    },
                )
            },
        ) { innerPadding ->
            Box(Modifier.fillMaxSize()) {
            NavHost(
                navController = navController,
                startDestination = "dashboard",
                modifier = Modifier
                    .fillMaxSize()
                    .statusBarsPadding(),
            ) {
                composable("dashboard") {
                    val viewModel: DashboardViewModel = viewModel(
                        factory = viewModelFactory { initializer { DashboardViewModel(app) } },
                    )
                    DashboardScreen(
                        app = app,
                        viewModel = viewModel,
                        chatViewModel = chatViewModel,
                        onNavigate = { route -> navController.navigate(route) { launchSingleTop = true } },
                    )
                }
                composable("chat") {
                    ChatScreen(
                        app = app,
                        viewModel = chatViewModel,
                        bottomPadding = innerPadding,
                    )
                }
                composable("control") {
                    val viewModel: ControlViewModel = viewModel(
                        factory = viewModelFactory { initializer { ControlViewModel(app) } },
                    )
                    ControlScreen(viewModel = viewModel, bottomPadding = innerPadding)
                }
                composable("vision") {
                    val viewModel: VisionViewModel = viewModel(
                        factory = viewModelFactory { initializer { VisionViewModel(app) } },
                    )
                    VisionScreen(viewModel = viewModel, bottomPadding = innerPadding)
                }
                composable("vault") {
                    val viewModel: VaultViewModel = viewModel(
                        factory = viewModelFactory { initializer { VaultViewModel(app) } },
                    )
                    VaultScreen(
                        viewModel = viewModel,
                        bottomPadding = innerPadding,
                        onOpenSettings = { navController.navigate(SETTINGS_ROUTE) { launchSingleTop = true } },
                    )
                }
                composable(SETTINGS_ROUTE) {
                    val viewModel: SettingsViewModel = viewModel(
                        factory = viewModelFactory { initializer { SettingsViewModel(app) } },
                    )
                    SettingsScreen(
                        app = app,
                        viewModel = viewModel,
                        bottomPadding = innerPadding,
                    )
                }
            }
            HudNoticeHost(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(horizontal = 16.dp)
                    .padding(bottom = innerPadding.calculateBottomPadding() + 12.dp),
            )
            }
        }
    }
}

@Composable
private fun HudBottomBar(selectedRoute: String?, onSelect: (String) -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(Panel.copy(alpha = 0.96f)),
    ) {
        Box(
            Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(
                    Brush.horizontalGradient(
                        listOf(Color.Transparent, CyanDim.copy(alpha = 0.7f), Color.Transparent),
                    )
                )
        )
        Row(
            Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 8.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            destinations.forEach { destination ->
                val selected = selectedRoute == destination.route
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(12.dp))
                        .background(if (selected) Cyan.copy(alpha = 0.10f) else Color.Transparent)
                        .border(
                            1.dp,
                            if (selected) Cyan.copy(alpha = 0.28f) else Color.Transparent,
                            RoundedCornerShape(12.dp),
                        )
                        .clickable { onSelect(destination.route) }
                        .padding(vertical = 7.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Icon(
                        destination.icon,
                        contentDescription = destination.label,
                        tint = if (selected) CyanBright else TextMuted,
                        modifier = Modifier.size(21.dp),
                    )
                    Spacer(Modifier.height(3.dp))
                    Text(
                        destination.label.uppercase(),
                        style = MaterialTheme.typography.labelSmall.copy(
                            fontFamily = FontFamily.Monospace,
                            fontSize = 8.sp,
                            letterSpacing = 1.sp,
                        ),
                        color = if (selected) Cyan else TextMuted,
                    )
                }
            }
        }
    }
}
