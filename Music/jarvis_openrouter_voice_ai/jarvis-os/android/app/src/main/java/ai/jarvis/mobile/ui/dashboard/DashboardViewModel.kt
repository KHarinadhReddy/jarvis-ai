package ai.jarvis.mobile.ui.dashboard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.Network
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.data.MessageEntity
import ai.jarvis.mobile.core.network.ApiException
import ai.jarvis.mobile.core.system.DeviceStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class BackendState(
    val checking: Boolean = false,
    val online: Boolean? = null,
    val configured: Boolean = false,
    val provider: String = "",
    val model: String = "",
    val message: String = "Not checked yet",
)

class DashboardViewModel(private val app: JarvisApp) : ViewModel() {

    val device = app.container.device
    private val dao = app.container.database.messageDao()

    private val _status = MutableStateFlow<DeviceStatus?>(null)
    val status: StateFlow<DeviceStatus?> = _status.asStateFlow()

    private val _backend = MutableStateFlow(BackendState())
    val backend: StateFlow<BackendState> = _backend.asStateFlow()

    val recent: StateFlow<List<MessageEntity>> = dao.observeRecent(3)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val openTasks: StateFlow<Int> = app.container.database.taskDao().observeOpenCount()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), 0)

    private val batteryReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            refreshStatus()
        }
    }

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) = refreshStatus()
        override fun onLost(network: Network) = refreshStatus()
        override fun onCapabilitiesChanged(network: Network, capabilities: android.net.NetworkCapabilities) = refreshStatus()
    }

    private var receiverRegistered = false
    private var networkRegistered = false

    init {
        refreshStatus()
        runCatching {
            ContextCompat.registerReceiver(
                app,
                batteryReceiver,
                IntentFilter(Intent.ACTION_BATTERY_CHANGED),
                ContextCompat.RECEIVER_NOT_EXPORTED,
            )
            receiverRegistered = true
        }
        runCatching {
            val manager = app.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            manager.registerDefaultNetworkCallback(networkCallback)
            networkRegistered = true
        }
        checkBackend()
    }

    fun refreshStatus() {
        _status.value = runCatching { device.status() }.getOrNull()
    }

    fun checkBackend() {
        if (_backend.value.checking) return
        _backend.value = _backend.value.copy(checking = true)
        viewModelScope.launch {
            try {
                val health = app.container.api.health()
                _backend.value = BackendState(
                    checking = false,
                    online = true,
                    configured = health.configured,
                    provider = health.provider,
                    model = health.model,
                    message = if (health.configured) "AI online" else "Backend online; no AI key configured",
                )
            } catch (error: ApiException) {
                _backend.value = BackendState(
                    checking = false,
                    online = false,
                    message = error.message ?: "Backend unreachable",
                )
            } catch (error: Exception) {
                _backend.value = BackendState(
                    checking = false,
                    online = false,
                    message = error.message ?: "Backend unreachable",
                )
            }
        }
    }

    override fun onCleared() {
        if (receiverRegistered) runCatching { app.unregisterReceiver(batteryReceiver) }
        if (networkRegistered) {
            runCatching {
                (app.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager)
                    .unregisterNetworkCallback(networkCallback)
            }
        }
        super.onCleared()
    }
}
