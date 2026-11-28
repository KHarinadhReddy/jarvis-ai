package ai.jarvis.mobile.core.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import java.util.Locale
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow

sealed interface VoiceState {
    data object Idle : VoiceState
    data object Listening : VoiceState
    data object Processing : VoiceState
    data class Error(val message: String) : VoiceState
}

class VoiceRecognizer(private val context: Context) {

    private var recognizer: SpeechRecognizer? = null
    private val _state = MutableStateFlow<VoiceState>(VoiceState.Idle)
    val state: StateFlow<VoiceState> = _state.asStateFlow()

    private val _partial = MutableStateFlow("")
    val partial: StateFlow<String> = _partial.asStateFlow()

    private val _amplitude = MutableStateFlow(0f)
    val amplitude: StateFlow<Float> = _amplitude.asStateFlow()

    private val _finalResults = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val finalResults: SharedFlow<String> = _finalResults.asSharedFlow()

    fun isAvailable(): Boolean = SpeechRecognizer.isRecognitionAvailable(context)

    fun start(languageTag: String) {
        if (!isAvailable()) {
            _state.value = VoiceState.Error(
                "No speech recognition service is installed. Use the keyboard, or install Google speech services.",
            )
            return
        }
        cancelInternal()
        _partial.value = ""
        val instance = SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = instance
        instance.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {
                _state.value = VoiceState.Listening
            }

            override fun onBeginningOfSpeech() {
                _state.value = VoiceState.Listening
            }

            override fun onRmsChanged(rmsdB: Float) {
                val normalized = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f)
                _amplitude.value = normalized
            }

            override fun onBufferReceived(buffer: ByteArray?) = Unit

            override fun onEndOfSpeech() {
                _state.value = VoiceState.Processing
                _amplitude.value = 0f
            }

            override fun onError(error: Int) {
                _amplitude.value = 0f
                _state.value = VoiceState.Error(errorMessage(error))
            }

            override fun onResults(results: Bundle?) {
                _amplitude.value = 0f
                val text = results
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    ?.trim()
                    .orEmpty()
                if (text.isNotEmpty()) {
                    _partial.value = text
                    _finalResults.tryEmit(text)
                    _state.value = VoiceState.Idle
                } else {
                    _state.value = VoiceState.Error("I did not catch any words. Try again a little closer to the mic.")
                }
            }

            override fun onPartialResults(partialResults: Bundle?) {
                val text = partialResults
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    ?.trim()
                    .orEmpty()
                if (text.isNotEmpty()) {
                    _partial.value = text
                    _state.value = VoiceState.Listening
                }
            }

            override fun onEvent(eventType: Int, params: Bundle?) = Unit
        })
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, languageTag)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1800L)
        }
        runCatching { instance.startListening(intent) }
            .onFailure {
                _state.value = VoiceState.Error("Could not start listening: ${it.message}")
            }
        _state.value = VoiceState.Listening
    }

    fun stopListening() {
        val instance = recognizer
        if (instance != null && _state.value is VoiceState.Listening) {
            _state.value = VoiceState.Processing
            runCatching { instance.stopListening() }
        }
    }

    fun cancel() {
        cancelInternal()
        _partial.value = ""
        _amplitude.value = 0f
        _state.value = VoiceState.Idle
    }

    fun destroy() {
        cancelInternal()
    }

    private fun cancelInternal() {
        val instance = recognizer
        recognizer = null
        if (instance != null) {
            runCatching { instance.cancel() }
            runCatching { instance.destroy() }
        }
    }

    private fun errorMessage(code: Int): String = when (code) {
        SpeechRecognizer.ERROR_AUDIO -> "The microphone audio stream failed."
        SpeechRecognizer.ERROR_CLIENT -> "The recognizer was interrupted. Try again."
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission is not granted."
        SpeechRecognizer.ERROR_NETWORK -> "Speech recognition needs a network connection right now."
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Speech recognition timed out. Try again."
        SpeechRecognizer.ERROR_NO_MATCH -> "I did not catch that. Try again."
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "The recognizer is busy. Wait a moment and retry."
        SpeechRecognizer.ERROR_SERVER -> "The speech server reported an error."
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "I heard no speech. Tap the mic and speak."
        else -> "Speech recognition error ($code)."
    }
}
