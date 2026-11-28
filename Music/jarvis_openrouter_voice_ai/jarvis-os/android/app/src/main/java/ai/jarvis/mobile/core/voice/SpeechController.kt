package ai.jarvis.mobile.core.voice

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import ai.jarvis.mobile.core.data.SettingsStore
import ai.jarvis.mobile.core.network.JarvisApi
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale
import java.util.Random
import kotlin.math.PI
import kotlin.math.sin
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

sealed interface SpeechState {
    data object Idle : SpeechState
    data object Preparing : SpeechState
    data class Speaking(val text: String) : SpeechState
    data class Error(val message: String) : SpeechState
}

class SpeechController(
    private val context: Context,
    private val api: JarvisApi,
    private val settingsStore: SettingsStore,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val cacheDir = File(context.cacheDir, "jarvis_tts").apply { mkdirs() }

    private val _state = MutableStateFlow<SpeechState>(SpeechState.Idle)
    val state: StateFlow<SpeechState> = _state.asStateFlow()

    private var job: Job? = null
    private var mediaPlayer: MediaPlayer? = null
    private var breathPlayer: MediaPlayer? = null
    private var tts: TextToSpeech? = null
    private val ttsReady = CompletableDeferred<Boolean>()
    private var activeUtterance: CompletableDeferred<Unit>? = null

    private val focusRequest: AudioFocusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        .setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build()
        )
        .setWillPauseWhenDucked(false)
        .setOnAudioFocusChangeListener { }
        .build()

    init {
        tts = TextToSpeech(context) { status ->
            if (!ttsReady.isCompleted) ttsReady.complete(status == TextToSpeech.SUCCESS)
        }
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) = Unit

            override fun onDone(utteranceId: String?) {
                activeUtterance?.complete(Unit)
            }

            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                activeUtterance?.completeExceptionally(IllegalStateException("Android TTS failed"))
            }

            override fun onError(utteranceId: String?, errorCode: Int) {
                activeUtterance?.completeExceptionally(IllegalStateException("Android TTS error $errorCode"))
            }
        })
    }

    fun speak(text: String, languageOverride: String? = null) {
        val cleaned = text.trim()
        if (cleaned.isEmpty()) return
        stop()
        job = scope.launch {
            _state.value = SpeechState.Preparing
            val settings = settingsStore.snapshot()
            val language = languageOverride ?: when (settings.language) {
                "auto" -> null
                else -> settings.language
            }
            try {
                val bundle = api.speechSegments(cleaned, language, settings.voiceGender)
                if (bundle.clips.isEmpty()) {
                    throw IllegalStateException("The backend returned no speech clips")
                }
                requestFocus()
                _state.value = SpeechState.Speaking(cleaned)
                cleanupOldFiles()
                for ((index, clip) in bundle.clips.withIndex()) {
                    val bytes = android.util.Base64.decode(clip.audioB64, android.util.Base64.DEFAULT)
                    val file = File(cacheDir, "clip_${System.nanoTime()}_$index.mp3")
                    file.writeBytes(bytes)
                    playFile(file)
                    file.delete()
                    if (clip.pauseAfterMs > 0) delay(clip.pauseAfterMs.toLong())
                    if (clip.breathAfter) playBreath()
                }
                _state.value = SpeechState.Idle
            } catch (error: Exception) {
                if (error is kotlinx.coroutines.CancellationException) throw error
                try {
                    speakWithAndroid(cleaned, language ?: "en-IN")
                    _state.value = SpeechState.Idle
                } catch (fallbackError: Exception) {
                    _state.value = SpeechState.Error(
                        "Speech failed. ${error.message ?: "Backend unavailable"}. " +
                            "Android TTS also failed: ${fallbackError.message ?: "no voice installed"}",
                    )
                }
            } finally {
                abandonFocus()
                mediaPlayer = null
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        runCatching { mediaPlayer?.stop() }
        runCatching { mediaPlayer?.release() }
        mediaPlayer = null
        runCatching { breathPlayer?.release() }
        breathPlayer = null
        runCatching { tts?.stop() }
        abandonFocus()
        _state.value = SpeechState.Idle
    }

    fun shutdown() {
        stop()
        runCatching { tts?.shutdown() }
        tts = null
    }

    private suspend fun playFile(file: File) {
        suspendCancellableCoroutine<Unit> { continuation ->
            val player = MediaPlayer()
            mediaPlayer = player
            try {
                player.setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                player.setDataSource(file.absolutePath)
                player.setOnPreparedListener { it.start() }
                player.setOnCompletionListener {
                    if (mediaPlayer === player) mediaPlayer = null
                    runCatching { it.release() }
                    if (continuation.isActive) continuation.resume(Unit)
                }
                player.setOnErrorListener { failed, _, _ ->
                    if (mediaPlayer === failed) mediaPlayer = null
                    runCatching { failed.release() }
                    if (continuation.isActive) continuation.resume(Unit)
                    true
                }
                continuation.invokeOnCancellation {
                    if (mediaPlayer === player) mediaPlayer = null
                    runCatching { player.stop() }
                    runCatching { player.release() }
                }
                player.prepareAsync()
            } catch (error: Exception) {
                if (mediaPlayer === player) mediaPlayer = null
                runCatching { player.release() }
                if (continuation.isActive) continuation.resume(Unit)
            }
        }
    }

    private fun playBreath() {
        val file = breathFile()
        runCatching {
            val player = MediaPlayer()
            breathPlayer = player
            player.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            player.setDataSource(file.absolutePath)
            player.setVolume(0.20f, 0.20f)
            player.setOnCompletionListener {
                if (breathPlayer === player) breathPlayer = null
                runCatching { player.release() }
            }
            player.prepare()
            player.start()
        }.onFailure {
            runCatching { breathPlayer?.release() }
            breathPlayer = null
        }
    }

    private suspend fun speakWithAndroid(text: String, language: String) {
        val ready = withTimeoutOrNull(6000) { ttsReady.await() } ?: false
        if (!ready) throw IllegalStateException("Android TTS did not initialize")
        val engine = tts ?: throw IllegalStateException("Android TTS is unavailable")
        val requested = Locale.forLanguageTag(language)
        var result = engine.setLanguage(requested)
        if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
            if (language.startsWith("te", ignoreCase = true)) {
                throw IllegalStateException("No Telugu voice is installed on this phone")
            }
            result = engine.setLanguage(Locale.forLanguageTag("en-IN"))
            if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                result = engine.setLanguage(Locale.US)
            }
        }
        if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
            throw IllegalStateException("No usable Android TTS voice is installed")
        }
        engine.setSpeechRate(0.96f)
        val done = CompletableDeferred<Unit>()
        activeUtterance = done
        val queued = engine.speak(text.take(3000), TextToSpeech.QUEUE_FLUSH, null, "jarvis-${System.nanoTime()}")
        if (queued != TextToSpeech.SUCCESS) {
            throw IllegalStateException("Android TTS rejected the utterance")
        }
        withTimeout(90_000) { done.await() }
        activeUtterance = null
    }

    private fun requestFocus() {
        runCatching { audioManager.requestAudioFocus(focusRequest) }
    }

    private fun abandonFocus() {
        runCatching { audioManager.abandonAudioFocusRequest(focusRequest) }
    }

    private fun cleanupOldFiles() {
        val cutoff = System.currentTimeMillis() - 6 * 60 * 60 * 1000L
        cacheDir.listFiles()?.forEach { file ->
            if (file.lastModified() < cutoff) runCatching { file.delete() }
        }
    }

    private fun breathFile(): File {
        val file = File(cacheDir, "breath.wav")
        if (file.exists() && file.length() > 1000) return file
        val sampleRate = 22050
        val seconds = 0.34
        val sampleCount = (sampleRate * seconds).toInt()
        val dataSize = sampleCount * 2
        val buffer = ByteBuffer.allocate(44 + dataSize).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put("RIFF".toByteArray())
        buffer.putInt(36 + dataSize)
        buffer.put("WAVE".toByteArray())
        buffer.put("fmt ".toByteArray())
        buffer.putInt(16)
        buffer.putShort(1.toShort())
        buffer.putShort(1.toShort())
        buffer.putInt(sampleRate)
        buffer.putInt(sampleRate * 2)
        buffer.putShort(2.toShort())
        buffer.putShort(16.toShort())
        buffer.put("data".toByteArray())
        buffer.putInt(dataSize)
        var filtered = 0f
        val random = Random(7)
        for (index in 0 until sampleCount) {
            val noise = random.nextFloat() * 2f - 1f
            filtered = filtered * 0.86f + noise * 0.14f
            val position = index.toFloat() / sampleCount
            val envelope = (sin(PI * position).toFloat()).let { it * it }
            val value = (filtered * envelope * 0.22f * Short.MAX_VALUE).toInt().coerceIn(-32768, 32767)
            buffer.putShort(value.toShort())
        }
        file.writeBytes(buffer.array())
        return file
    }
}
