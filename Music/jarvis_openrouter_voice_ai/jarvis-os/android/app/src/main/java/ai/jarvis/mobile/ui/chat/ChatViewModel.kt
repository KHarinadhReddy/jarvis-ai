package ai.jarvis.mobile.ui.chat

import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.data.JarvisSettings
import ai.jarvis.mobile.core.data.MessageEntity
import ai.jarvis.mobile.core.network.ApiException
import ai.jarvis.mobile.core.system.ToolOutcome
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PendingAction(val tool: String, val label: String)

data class ChatUiState(
    val streamingText: String = "",
    val status: String? = null,
    val busy: Boolean = false,
    val error: String? = null,
    val pending: PendingAction? = null,
    val listening: Boolean = false,
    val listenLanguage: String = "en-IN",
)

class ChatViewModel(private val app: JarvisApp) : ViewModel() {

    private val container = app.container
    private val dao = container.database.messageDao()

    val messages: StateFlow<List<MessageEntity>> = dao.observeAll()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val settings: StateFlow<JarvisSettings> = container.settingsStore.settings
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), JarvisSettings())

    val voiceState = container.voice.state
    val partial = container.voice.partial
    val amplitude = container.voice.amplitude
    val speechState = container.speech.state

    private val _ui = MutableStateFlow(ChatUiState())
    val ui: StateFlow<ChatUiState> = _ui.asStateFlow()

    private var confirmation: CompletableDeferred<Boolean>? = null

    init {
        viewModelScope.launch {
            container.voice.finalResults.collect { text ->
                _ui.update { it.copy(listening = false) }
                if (text.isNotBlank()) {
                    send(text, speakReply = settings.value.ttsEnabled)
                }
            }
        }
        viewModelScope.launch {
            container.voice.state.collect { state ->
                when (state) {
                    is ai.jarvis.mobile.core.voice.VoiceState.Listening ->
                        _ui.update { it.copy(listening = true, error = null) }
                    is ai.jarvis.mobile.core.voice.VoiceState.Processing ->
                        _ui.update { it.copy(listening = false) }
                    is ai.jarvis.mobile.core.voice.VoiceState.Error ->
                        _ui.update { it.copy(listening = false, error = state.message) }
                    ai.jarvis.mobile.core.voice.VoiceState.Idle ->
                        _ui.update { it.copy(listening = false) }
                }
            }
        }
    }

    fun setLanguage(language: String) {
        _ui.update { it.copy(listenLanguage = language) }
    }

    fun toggleListening() {
        if (_ui.value.listening) {
            container.voice.stopListening()
            return
        }
        if (_ui.value.busy) {
            _ui.update { it.copy(error = "Wait for the current response to finish before speaking again.") }
            return
        }
        container.speech.stop()
        val language = _ui.value.listenLanguage
        container.voice.start(language)
    }

    fun reportError(message: String) {
        _ui.update { it.copy(error = message) }
    }

    fun setTtsEnabled(enabled: Boolean) {
        viewModelScope.launch {
            container.settingsStore.save(settings.value.copy(ttsEnabled = enabled))
            if (!enabled) container.speech.stop()
        }
    }

    fun send(text: String, speakReply: Boolean = true) {
        val cleaned = text.trim()
        if (cleaned.isEmpty() || _ui.value.busy) return
        container.voice.cancel()
        _ui.update {
            it.copy(
                busy = true,
                error = null,
                streamingText = "",
                status = "Transmitting",
                listening = false,
            )
        }
        viewModelScope.launch {
            try {
                dao.insert(MessageEntity(role = "user", content = cleaned))
                val history = dao.recent(24).reversed()
                val result = container.agent.run(
                    history = history,
                    userText = cleaned,
                    onToken = { token ->
                        _ui.update { it.copy(streamingText = it.streamingText + token) }
                    },
                    onReset = {
                        _ui.update { it.copy(streamingText = "") }
                    },
                    onStatus = { status ->
                        _ui.update { it.copy(status = status) }
                    },
                    confirm = { outcome -> requestConfirmation(outcome) },
                )
                val reply = result.text.trim()
                if (reply.isNotEmpty()) {
                    dao.insert(MessageEntity(role = "assistant", content = reply))
                }
                _ui.update { it.copy(busy = false, status = null, streamingText = "") }
                if (speakReply && settings.value.ttsEnabled && reply.isNotEmpty()) {
                    container.speech.speak(reply)
                }
            } catch (error: Exception) {
                if (error is kotlinx.coroutines.CancellationException) throw error
                val message = when (error) {
                    is ApiException -> error.message ?: "Backend error"
                    else -> error.message ?: "Unexpected failure"
                }
                _ui.update {
                    it.copy(
                        busy = false,
                        status = null,
                        streamingText = "",
                        error = message,
                    )
                }
            } finally {
                confirmation?.cancel()
                confirmation = null
                _ui.update { it.copy(pending = null) }
            }
        }
    }

    private suspend fun requestConfirmation(outcome: ToolOutcome): Boolean {
        val deferred = CompletableDeferred<Boolean>()
        confirmation = deferred
        _ui.update { it.copy(pending = PendingAction(outcome.tool, outcome.confirmationLabel)) }
        return try {
            deferred.await()
        } finally {
            confirmation = null
            _ui.update { it.copy(pending = null) }
        }
    }

    fun resolveConfirmation(approved: Boolean) {
        confirmation?.complete(approved)
    }

    fun stopSpeaking() {
        container.speech.stop()
    }

    fun dismissError() {
        _ui.update { it.copy(error = null) }
    }

    fun clearConversation() {
        viewModelScope.launch {
            dao.clear()
            _ui.update { it.copy(error = null, streamingText = "", status = null) }
        }
    }

    override fun onCleared() {
        container.voice.cancel()
        container.speech.stop()
        confirmation?.cancel()
        super.onCleared()
    }
}
