package ai.jarvis.mobile.core.tasks

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.MainActivity
import ai.jarvis.mobile.R

class TaskReminderWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val app = applicationContext as? JarvisApp ?: return Result.success()
        val dao = app.container.database.taskDao()
        val due = runCatching { dao.dueUnnotified(System.currentTimeMillis()) }.getOrDefault(emptyList())
        if (due.isEmpty()) return Result.success()
        if (!NotificationManagerCompat.from(applicationContext).areNotificationsEnabled()) {
            return Result.success()
        }
        val intent = Intent(applicationContext, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pending = PendingIntent.getActivity(
            applicationContext,
            7,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        due.forEach { task ->
            val notification = NotificationCompat.Builder(applicationContext, JarvisApp.TASK_CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_jarvis)
                .setContentTitle("Task due")
                .setContentText(task.title.take(140))
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .setAutoCancel(true)
                .setContentIntent(pending)
                .build()
            runCatching {
                NotificationManagerCompat.from(applicationContext).notify(task.id.toInt(), notification)
            }
            runCatching { dao.markNotified(task.id) }
        }
        return Result.success()
    }
}
