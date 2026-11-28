package ai.jarvis.mobile.ui.vault

import ai.jarvis.mobile.JarvisApp
import ai.jarvis.mobile.core.data.MemoryEntity
import ai.jarvis.mobile.core.data.TaskEntity
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class VaultViewModel(private val app: JarvisApp) : ViewModel() {

    private val memoryDao = app.container.database.memoryDao()
    private val taskDao = app.container.database.taskDao()

    val memories: StateFlow<List<MemoryEntity>> = memoryDao.observeAll()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val tasks: StateFlow<List<TaskEntity>> = taskDao.observeAll()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    fun addMemory(text: String) {
        val cleaned = text.trim()
        if (cleaned.isEmpty()) return
        viewModelScope.launch {
            memoryDao.insert(MemoryEntity(text = cleaned.take(1200)))
        }
    }

    fun deleteMemory(id: Long) {
        viewModelScope.launch { memoryDao.delete(id) }
    }

    fun addTask(title: String, dueInMinutes: Int?) {
        val cleaned = title.trim()
        if (cleaned.isEmpty()) return
        val dueAt = dueInMinutes?.takeIf { it > 0 }?.let {
            System.currentTimeMillis() + it * 60_000L
        }
        viewModelScope.launch {
            taskDao.insert(TaskEntity(title = cleaned.take(300), dueAt = dueAt))
        }
    }

    fun toggleTask(task: TaskEntity) {
        viewModelScope.launch { taskDao.setDone(task.id, !task.done) }
    }

    fun deleteTask(id: Long) {
        viewModelScope.launch { taskDao.delete(id) }
    }

    fun clearCompleted() {
        viewModelScope.launch { taskDao.clearCompleted() }
    }

    fun clearMemories() {
        viewModelScope.launch { memoryDao.clear() }
    }

    fun clearTasks() {
        viewModelScope.launch { taskDao.clear() }
    }
}
