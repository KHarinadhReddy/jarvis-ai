package ai.jarvis.mobile.core.system

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Optional, user-enabled service for approved global actions and gestures.
 * It deliberately does not retrieve window content or read password fields.
 */
class JarvisAccessibilityService : AccessibilityService() {

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        connected.value = true
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        if (instance === this) instance = null
        connected.value = false
        super.onDestroy()
    }

    companion object {
        @Volatile
        private var instance: JarvisAccessibilityService? = null
        private val connected = MutableStateFlow(false)
        val isConnected: StateFlow<Boolean> = connected

        fun globalAction(action: Int): Boolean = instance?.performGlobalAction(action) ?: false
    }
}
