package ai.jarvis.mobile.ui.control

import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.system.ActionResult
import ai.jarvis.mobile.core.system.AppEntry
import ai.jarvis.mobile.core.system.DeviceStatus
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class ControlViewModel(private val app: JarvisApp) : ViewModel() {

    val device = app.container.device

    private val _status = MutableStateFlow<DeviceStatus?>(null)
    val status: StateFlow<DeviceStatus?> = _status.asStateFlow()

    private val _apps = MutableStateFlow<List<AppEntry>>(emptyList())
    val apps: StateFlow<List<AppEntry>> = _apps.asStateFlow()

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice.asStateFlow()

    init {
        refresh()
        loadApps()
    }

    fun refresh() {
        viewModelScope.launch {
            _status.value = withContext(Dispatchers.IO) { runCatching { device.status() }.getOrNull() }
        }
    }

    fun loadApps() {
        viewModelScope.launch {
            _apps.value = withContext(Dispatchers.IO) { runCatching { device.launchableApps() }.getOrDefault(emptyList()) }
        }
    }

    fun hasPermission(permission: String): Boolean = device.hasPermission(permission)

    fun toggleTorch() {
        perform { device.setFlashlight(!(_status.value?.torchOn ?: false)) }
    }

    fun setBrightness(percent: Int) {
        perform { device.setBrightness(percent) }
    }

    fun adjustVolume(delta: Int) {
        perform {
            val next = (device.volumePercent() + delta).coerceIn(0, 100)
            device.setVolume(next)
        }
    }

    fun media(action: String) {
        perform { device.media(action) }
    }

    fun global(action: String) {
        perform { device.globalAction(action) }
    }

    fun openApp(entry: AppEntry) {
        perform { device.launchApp(entry) }
    }

    fun openSettings(panel: String) {
        perform { device.openSettings(panel) }
    }

    fun showNotice(message: String) {
        _notice.value = message
    }

    fun dismissNotice() {
        _notice.value = null
    }

    private fun perform(block: () -> ActionResult) {
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching(block).getOrElse {
                    ActionResult(false, "Action failed: ${it.message ?: "unknown error"}")
                }
            }
            _notice.value = result.message
            _status.value = withContext(Dispatchers.IO) { runCatching { device.status() }.getOrNull() }
        }
    }
}
