package ai.jarvis.mobile.core.voice

import android.app.Service
import android.content.Intent
import android.os.IBinder

/**
 * Placeholder for the optional hands-free voice session. Push-to-talk does not use it.
 * The full implementation is added with the wake-word/foreground voice milestone.
 */
class VoiceSessionService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        stopSelf()
        return START_NOT_STICKY
    }
}
