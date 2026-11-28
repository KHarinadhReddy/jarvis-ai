package ai.jarvis.mobile

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import ai.jarvis.mobile.core.AppContainer
import ai.jarvis.mobile.core.tasks.TaskReminderWorker
import java.util.concurrent.TimeUnit

class JarvisApp : Application() {

    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        createNotificationChannels()
        scheduleTaskReminders()
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java) ?: return
        val tasks = NotificationChannel(
            TASK_CHANNEL,
            "Task reminders",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "Reminders for J.A.R.V.I.S. tasks"
            setShowBadge(true)
        }
        val voice = NotificationChannel(
            VOICE_CHANNEL,
            "Voice sessions",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Shown only while an optional hands-free voice session is active"
        }
        manager.createNotificationChannel(tasks)
        manager.createNotificationChannel(voice)
    }

    private fun scheduleTaskReminders() {
        val request = PeriodicWorkRequestBuilder<TaskReminderWorker>(15, TimeUnit.MINUTES)
            .setConstraints(
                Constraints.Builder()
                    .setRequiresBatteryNotLow(true)
                    .build()
            )
            .build()
        runCatching {
            WorkManager.getInstance(this).enqueueUniquePeriodicWork(
                TASK_WORK_NAME,
                ExistingPeriodicWorkPolicy.UPDATE,
                request,
            )
        }
    }

    companion object {
        const val TASK_CHANNEL = "jarvis_tasks"
        const val VOICE_CHANNEL = "jarvis_voice"
        const val TASK_WORK_NAME = "jarvis_task_reminders"
    }
}
