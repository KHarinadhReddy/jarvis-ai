package ai.jarvis.mobile.ui.settings

import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.data.JarvisSettings
import ai.jarvis.mobile.core.network.ApiException
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class LinkTest(
    val testing: Boolean = false,
    val ok: Boolean? = null,
    val message: String = "",
)

class SettingsViewModel(private val app: JarvisApp) : ViewModel() {

    val settings: StateFlow<JarvisSettings> = app.container.settingsStore.settings
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), JarvisSettings())

    val speechState = app.container.speech.state

    private val _test = MutableStateFlow(LinkTest())
    val test: StateFlow<LinkTest> = _test.asStateFlow()

    fun save(value: JarvisSettings) {
        viewModelScope.launch {
            app.container.settingsStore.save(value)
            _test.value = LinkTest(ok = true, message = "Configuration saved on this phone.")
        }
    }

    fun testConnection(value: JarvisSettings) {
        viewModelScope.launch {
            _test.value = LinkTest(testing = true, message = "Contacting the backend...")
            app.container.settingsStore.save(value)
            try {
                val health = app.container.api.health()
                _test.value = LinkTest(
                    testing = false,
                    ok = health.configured,
                    message = if (health.configured) {
                        "Connected. ${health.provider} / ${health.model}. Vision: ${if (health.vision) "yes" else "no"}. Telugu TTS: ${if (health.telugu_tts) "yes" else "no"}."
                    } else {
                        "Backend is online, but no AI key is configured on the server. Chat and vision will return 503."
                    },
                )
            } catch (error: Exception) {
                _test.value = LinkTest(
                    testing = false,
                    ok = false,
                    message = when (error) {
                        is ApiException -> error.message ?: "Connection failed"
                        else -> error.message ?: "Connection failed"
                    },
                )
            }
        }
    }

    fun testVoice(value: JarvisSettings) {
        viewModelScope.launch {
            app.container.settingsStore.save(value)
            val text = if (value.language == "te-IN") {
                "నమస్కారం. జార్విస్ ఆన్‌లైన్‌లో ఉంది. అన్ని వ్యవస్థలు సిద్ధంగా ఉన్నాయి."
            } else {
                "Good evening. All systems are online. This is the J.A.R.V.I.S. voice test."
            }
            app.container.speech.speak(text, if (value.language == "auto") "en-IN" else value.language)
        }
    }

    fun stopVoice() {
        app.container.speech.stop()
    }

    fun clearConversation() {
        viewModelScope.launch { app.container.database.messageDao().clear() }
    }

    fun clearMemories() {
        viewModelScope.launch { app.container.database.memoryDao().clear() }
    }

    fun clearTasks() {
        viewModelScope.launch { app.container.database.taskDao().clear() }
    }

    fun clearCompletedTasks() {
        viewModelScope.launch { app.container.database.taskDao().clearCompleted() }
    }
}
