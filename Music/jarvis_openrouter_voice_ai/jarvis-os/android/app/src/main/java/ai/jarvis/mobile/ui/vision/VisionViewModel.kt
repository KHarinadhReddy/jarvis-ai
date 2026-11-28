package ai.jarvis.mobile.ui.vision

import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.network.ApiException
import ai.jarvis.mobile.core.network.VisionAnalysis
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class VisionUiState(
    val mode: String = "identify",
    val question: String = "",
    val analyzing: Boolean = false,
    val result: VisionAnalysis? = null,
    val provider: String = "",
    val model: String = "",
    val error: String? = null,
)

class VisionViewModel(private val app: JarvisApp) : ViewModel() {

    private val _ui = MutableStateFlow(VisionUiState())
    val ui: StateFlow<VisionUiState> = _ui.asStateFlow()

    private var lastBytes: ByteArray? = null
    private var lastMime: String = "image/jpeg"

    fun setMode(mode: String) {
        _ui.update { it.copy(mode = mode) }
    }

    fun setQuestion(question: String) {
        _ui.update { it.copy(question = question.take(500)) }
    }

    fun analyze(bytes: ByteArray, mime: String) {
        lastBytes = bytes
        lastMime = mime
        _ui.update { it.copy(analyzing = true, error = null) }
        viewModelScope.launch {
            try {
                val response = app.container.api.analyzeImage(bytes, mime, _ui.value.mode, _ui.value.question)
                _ui.update {
                    it.copy(
                        analyzing = false,
                        result = response.result,
                        provider = response.provider,
                        model = response.model,
                        error = null,
                    )
                }
            } catch (error: Exception) {
                if (error is kotlinx.coroutines.CancellationException) throw error
                _ui.update {
                    it.copy(
                        analyzing = false,
                        error = when (error) {
                            is ApiException -> error.message
                            else -> error.message
                        } ?: "Vision request failed",
                    )
                }
            }
        }
    }

    fun retry() {
        val bytes = lastBytes ?: return
        analyze(bytes, lastMime)
    }

    fun clear() {
        _ui.update { it.copy(result = null, error = null) }
    }
}
