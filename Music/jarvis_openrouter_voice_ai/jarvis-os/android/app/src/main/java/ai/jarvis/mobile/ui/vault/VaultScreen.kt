package ai.jarvis.mobile.ui.vault

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.TaskAlt
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ai.jarvis.mobile.core.data.MemoryEntity
import ai.jarvis.mobile.core.data.TaskEntity
import ai.jarvis.mobile.ui.components.EmptyState
import ai.jarvis.mobile.ui.components.HudPanel
import ai.jarvis.mobile.ui.components.SectionLabel
import ai.jarvis.mobile.ui.theme.Amber
import ai.jarvis.mobile.ui.theme.Cyan
import ai.jarvis.mobile.ui.theme.CyanBright
import ai.jarvis.mobile.ui.theme.CyanDim
import ai.jarvis.mobile.ui.theme.Danger
import ai.jarvis.mobile.ui.theme.Panel
import ai.jarvis.mobile.ui.theme.Success
import ai.jarvis.mobile.ui.theme.TextMuted
import ai.jarvis.mobile.ui.theme.TextPrimary
import ai.jarvis.mobile.ui.theme.TextSecondary
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
fun VaultScreen(
    viewModel: VaultViewModel,
    bottomPadding: PaddingValues,
    onOpenSettings: () -> Unit,
) {
    val memories by viewModel.memories.collectAsStateWithLifecycle()
    val tasks by viewModel.tasks.collectAsStateWithLifecycle()
    var tab by remember { mutableIntStateOf(0) }
    var showMemoryDialog by remember { mutableStateOf(false) }
    var memoryText by remember { mutableStateOf("") }
    var showTaskDialog by remember { mutableStateOf(false) }
    var taskTitle by remember { mutableStateOf("") }
    var taskDue by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("VAULT", style = MaterialTheme.typography.labelLarge, color = CyanBright)
                Text(
                    "Saved context and reminders. Stored only on this phone.",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
            }
            IconButton(onClick = onOpenSettings) {
                Icon(Icons.Filled.Settings, contentDescription = "Settings", tint = TextSecondary)
            }
        }

        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            VaultTab("Memory", memories.size, tab == 0) { tab = 0 }
            VaultTab("Tasks", tasks.count { !it.done }, tab == 1) { tab = 1 }
        }

        Spacer(Modifier.height(14.dp))
        if (tab == 0) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                SectionLabel("Saved memories", Modifier.weight(1f))
                TextButton(onClick = { showMemoryDialog = true }) {
                    Icon(Icons.Filled.Add, contentDescription = null, tint = Cyan, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Add", color = Cyan)
                }
            }
            Text(
                "Up to six recent memories are sent as context with each chat request. They are not used as instructions.",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
            )
            Spacer(Modifier.height(8.dp))
            if (memories.isEmpty()) {
                EmptyState(
                    title = "Nothing saved",
                    detail = "Add a preference, a project, or a fact you want J.A.R.V.I.S. to remember.",
                    icon = Icons.Filled.Memory,
                )
            } else {
                memories.forEach { memory ->
                    MemoryRow(memory, onDelete = { viewModel.deleteMemory(memory.id) })
                }
                Spacer(Modifier.height(6.dp))
                TextButton(onClick = viewModel::clearMemories) {
                    Icon(Icons.Filled.DeleteSweep, contentDescription = null, tint = Danger, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Clear all memories", color = Danger)
                }
            }
        } else {
            Row(verticalAlignment = Alignment.CenterVertically) {
                SectionLabel("Tasks", Modifier.weight(1f))
                TextButton(onClick = { showTaskDialog = true }) {
                    Icon(Icons.Filled.Add, contentDescription = null, tint = Cyan, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Add", color = Cyan)
                }
            }
            Text(
                "Reminders are checked by Android WorkManager at most every 15 minutes, so they can arrive a few minutes late. This is a system limit, not a fake timer.",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
            )
            Spacer(Modifier.height(8.dp))
            if (tasks.isEmpty()) {
                EmptyState(
                    title = "No tasks",
                    detail = "Add a task with an optional due time to get a notification.",
                    icon = Icons.Filled.TaskAlt,
                )
            } else {
                tasks.forEach { task ->
                    TaskRow(
                        task = task,
                        onToggle = { viewModel.toggleTask(task) },
                        onDelete = { viewModel.deleteTask(task.id) },
                    )
                }
                if (tasks.any { it.done }) {
                    TextButton(onClick = viewModel::clearCompleted) {
                        Icon(Icons.Filled.DeleteSweep, contentDescription = null, tint = TextMuted, modifier = Modifier.size(15.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("Clear completed", color = TextSecondary)
                    }
                }
            }
        }

        Spacer(Modifier.height(bottomPadding.calculateBottomPadding() + 28.dp))
    }

    if (showMemoryDialog) {
        AlertDialog(
            onDismissRequest = { showMemoryDialog = false },
            title = { Text("Save a memory") },
            text = {
                OutlinedTextField(
                    value = memoryText,
                    onValueChange = { memoryText = it.take(1200) },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("For example: I study computer science and prefer short answers.") },
                    maxLines = 5,
                    colors = dialogFieldColors(),
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.addMemory(memoryText)
                        memoryText = ""
                        showMemoryDialog = false
                    },
                    enabled = memoryText.isNotBlank(),
                ) { Text("Save", color = Cyan) }
            },
            dismissButton = {
                TextButton(onClick = { showMemoryDialog = false }) { Text("Cancel", color = TextSecondary) }
            },
            containerColor = Panel,
            titleContentColor = TextPrimary,
            textContentColor = TextPrimary,
        )
    }

    if (showTaskDialog) {
        AlertDialog(
            onDismissRequest = { showTaskDialog = false },
            title = { Text("Add a task") },
            text = {
                Column {
                    OutlinedTextField(
                        value = taskTitle,
                        onValueChange = { taskTitle = it.take(300) },
                        modifier = Modifier.fillMaxWidth(),
                        placeholder = { Text("What needs to be done?") },
                        colors = dialogFieldColors(),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = taskDue,
                        onValueChange = { taskDue = it.filter { ch -> ch.isDigit() }.take(5) },
                        modifier = Modifier.fillMaxWidth(),
                        placeholder = { Text("Due in minutes (optional)") },
                        singleLine = true,
                        colors = dialogFieldColors(),
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.addTask(taskTitle, taskDue.toIntOrNull())
                        taskTitle = ""
                        taskDue = ""
                        showTaskDialog = false
                    },
                    enabled = taskTitle.isNotBlank(),
                ) { Text("Add", color = Cyan) }
            },
            dismissButton = {
                TextButton(onClick = { showTaskDialog = false }) { Text("Cancel", color = TextSecondary) }
            },
            containerColor = Panel,
            titleContentColor = TextPrimary,
            textContentColor = TextPrimary,
        )
    }
}

@Composable
private fun VaultTab(label: String, count: Int, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier
            .clip(RoundedCornerShape(10.dp))
            .background(if (selected) Cyan.copy(alpha = 0.13f) else Panel.copy(alpha = 0.4f))
            .border(
                1.dp,
                if (selected) Cyan.copy(alpha = 0.5f) else CyanDim.copy(alpha = 0.25f),
                RoundedCornerShape(10.dp),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = if (selected) Cyan else TextMuted)
        Spacer(Modifier.width(7.dp))
        Box(
            Modifier
                .size(18.dp)
                .background(if (selected) Cyan.copy(alpha = 0.18f) else Panel, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Text(count.toString(), style = MaterialTheme.typography.labelSmall, color = if (selected) Cyan else TextMuted)
        }
    }
}

@Composable
private fun MemoryRow(memory: MemoryEntity, onDelete: () -> Unit) {
    HudPanel(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp), contentPadding = 12.dp) {
        Row(verticalAlignment = Alignment.Top) {
            Text(
                memory.text,
                style = MaterialTheme.typography.bodyMedium,
                color = TextPrimary,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onDelete, modifier = Modifier.size(30.dp)) {
                Icon(Icons.Filled.Delete, contentDescription = "Delete memory", tint = TextMuted, modifier = Modifier.size(15.dp))
            }
        }
        Text(
            Instant.ofEpochMilli(memory.createdAt)
                .atZone(ZoneId.systemDefault())
                .format(DateTimeFormatter.ofPattern("d MMM yyyy, h:mm a")),
            style = MaterialTheme.typography.labelSmall,
            color = TextMuted,
        )
    }
}

@Composable
private fun TaskRow(task: TaskEntity, onToggle: () -> Unit, onDelete: () -> Unit) {
    val overdue = !task.done && task.dueAt != null && task.dueAt < System.currentTimeMillis()
    HudPanel(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        contentPadding = 10.dp,
        accent = if (overdue) Amber else Cyan,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(
                checked = task.done,
                onCheckedChange = { onToggle() },
                colors = CheckboxDefaults.colors(
                    checkedColor = Success,
                    uncheckedColor = CyanDim,
                    checkmarkColor = Color(0xFF02110C),
                ),
            )
            Column(Modifier.weight(1f)) {
                Text(
                    task.title,
                    style = MaterialTheme.typography.bodyLarge,
                    color = if (task.done) TextMuted else TextPrimary,
                    textDecoration = if (task.done) TextDecoration.LineThrough else TextDecoration.None,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    task.dueAt?.let {
                        Instant.ofEpochMilli(it)
                            .atZone(ZoneId.systemDefault())
                            .format(DateTimeFormatter.ofPattern("d MMM, h:mm a"))
                    } ?: "no due time",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (overdue) Amber else TextMuted,
                )
            }
            IconButton(onClick = onDelete, modifier = Modifier.size(30.dp)) {
                Icon(Icons.Filled.Delete, contentDescription = "Delete task", tint = TextMuted, modifier = Modifier.size(15.dp))
            }
        }
    }
}

@Composable
private fun dialogFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = Cyan.copy(alpha = 0.6f),
    unfocusedBorderColor = CyanDim.copy(alpha = 0.35f),
    focusedContainerColor = Color(0xFF04121B),
    unfocusedContainerColor = Color(0xFF04121B),
    cursorColor = Cyan,
    focusedTextColor = TextPrimary,
    unfocusedTextColor = TextPrimary,
)
