package com.westbrook.chastream.mobile

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.westbrook.chastream.mobile.data.RecordEntity
import com.westbrook.chastream.mobile.ui.ConversationSetupActivity
import com.westbrook.chastream.mobile.ui.DetailActivity
import com.westbrook.chastream.mobile.ui.NoteShare
import com.westbrook.chastream.mobile.ui.QuickRecordActivity
import com.westbrook.chastream.mobile.ui.VoiceprintManagerActivity
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { AppScreen() } }
    }

    @Composable
    private fun AppScreen() {
        var tab by remember { mutableIntStateOf(0) }
        val repository = (application as ChastreamApplication).repository
        val quickNotes by repository.observeQuickNotes().collectAsStateWithLifecycle(emptyList())
        val conversations by repository.observeConversations().collectAsStateWithLifecycle(emptyList())
        val preferences = remember { getSharedPreferences("note_preferences", MODE_PRIVATE) }
        val sortMode = preferences.getString("sortMode", "updated").orEmpty()
        val timeMode = preferences.getString("timeMode", "updated").orEmpty()
        val notes = if (sortMode == "created") {
            quickNotes.sortedByDescending { it.createdAt }
        } else {
            quickNotes.sortedByDescending { it.updatedAt }
        }
        var selected by remember { mutableStateOf<Set<String>>(emptySet()) }
        var confirmDelete by remember { mutableStateOf(false) }
        val scope = rememberCoroutineScope()

        Scaffold(
            bottomBar = {
                if (selected.isEmpty()) {
                    NavigationBar {
                        NavigationBarItem(
                            selected = tab == 0,
                            onClick = { tab = 0 },
                            icon = { Icon(Icons.Default.Mic, null) },
                            label = { Text("想法") },
                        )
                        NavigationBarItem(
                            selected = tab == 1,
                            onClick = { tab = 1 },
                            icon = { Icon(Icons.Default.Add, null) },
                            label = { Text("完整对话") },
                        )
                        NavigationBarItem(
                            selected = tab == 2,
                            onClick = { tab = 2 },
                            icon = { Icon(Icons.Default.Settings, null) },
                            label = { Text("设置") },
                        )
                    }
                }
            },
        ) { padding ->
            when {
                selected.isNotEmpty() -> SelectionScreen(
                    records = notes,
                    selected = selected,
                    onToggle = { id ->
                        selected = if (id in selected) selected - id else selected + id
                    },
                    onClose = { selected = emptySet() },
                    onShare = {
                        NoteShare.shareMarkdown(
                            this,
                            notes.filter { it.id in selected },
                        )
                    },
                    onDelete = { confirmDelete = true },
                    modifier = Modifier.padding(padding),
                )
                tab == 2 -> SettingsPanel(Modifier.padding(padding))
                tab == 0 -> NotesScreen(
                    notes = notes,
                    timeMode = timeMode,
                    onOpen = { openNote(it) },
                    onSelect = { selected = setOf(it) },
                    onRecord = { launchRecorder(0) },
                    onAdd = { openNewNote() },
                    modifier = Modifier.padding(padding),
                )
                else -> ConversationScreen(
                    records = conversations,
                    onOpen = { openNote(it) },
                    onCreate = { launchRecorder(1) },
                    modifier = Modifier.padding(padding),
                )
            }
        }

        if (confirmDelete) {
            AlertDialog(
                onDismissRequest = { confirmDelete = false },
                title = { Text("删除笔记") },
                text = { Text("确定删除已选择的 ${selected.size} 条笔记吗？") },
                confirmButton = {
                    Button(onClick = {
                        scope.launch {
                            repository.deleteMany(selected.toList())
                            selected = emptySet()
                            confirmDelete = false
                        }
                    }) { Text("删除") }
                },
                dismissButton = {
                    Button(onClick = { confirmDelete = false }) { Text("取消") }
                },
            )
        }
    }

    @OptIn(ExperimentalFoundationApi::class)
    @Composable
    private fun NotesScreen(
        notes: List<RecordEntity>,
        timeMode: String,
        onOpen: (String) -> Unit,
        onSelect: (String) -> Unit,
        onRecord: () -> Unit,
        onAdd: () -> Unit,
        modifier: Modifier = Modifier,
    ) {
        val pending = notes.count { it.status !in setOf("done", "manual") }
        Box(modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().padding(horizontal = 18.dp)) {
                Row(
                    Modifier.fillMaxWidth().padding(top = 18.dp, bottom = 14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column {
                        Text("最近想法", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                        Text("快速查看你的最新记录", color = Color(0xFF817C91))
                    }
                    Spacer(Modifier.weight(1f))
                    if (pending > 0) {
                        Text(
                            "未整理 $pending",
                            color = Color(0xFF7057D9),
                            modifier = Modifier.padding(10.dp),
                        )
                    }
                }
                LazyColumn(
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    items(notes, key = { it.id }) { note ->
                        Card(
                            shape = RoundedCornerShape(22.dp),
                            colors = CardDefaults.cardColors(containerColor = Color(0xFFF9F7FF)),
                            elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
                            modifier = Modifier.fillMaxWidth().combinedClickable(
                                onClick = { onOpen(note.id) },
                                onLongClick = { onSelect(note.id) },
                            ),
                        ) {
                            Column(Modifier.padding(18.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        note.title.ifBlank { fallbackTitle(note) },
                                        modifier = Modifier.weight(1f),
                                        fontWeight = FontWeight.Bold,
                                        style = MaterialTheme.typography.titleMedium,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    Text(
                                        formatTime(if (timeMode == "created") note.createdAt else note.updatedAt),
                                        color = Color(0xFF918CA2),
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                }
                                if (note.summary.isNotBlank()) {
                                    Text(
                                        note.summary,
                                        color = Color(0xFF6F697D),
                                        modifier = Modifier.padding(top = 10.dp),
                                        maxLines = 3,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                } else if (note.status !in setOf("done", "manual")) {
                                    Text(
                                        if (note.status == "failed") "处理失败，长按或点入查看" else "正在转写与整理…",
                                        color = Color(0xFF8D78DB),
                                        modifier = Modifier.padding(top = 10.dp),
                                    )
                                }
                            }
                        }
                    }
                    item { Spacer(Modifier.size(100.dp)) }
                }
            }
            Row(
                Modifier.align(Alignment.BottomEnd).padding(22.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                FloatingActionButton(
                    onClick = onAdd,
                    containerColor = Color(0xFFECE7FF),
                    contentColor = Color(0xFF6148CD),
                    shape = CircleShape,
                ) { Icon(Icons.Default.Edit, "添加笔记") }
                FloatingActionButton(
                    onClick = onRecord,
                    containerColor = Color(0xFF6D50D8),
                    contentColor = Color.White,
                    shape = CircleShape,
                ) { Icon(Icons.Default.Mic, "快速录音") }
            }
        }
    }

    @Composable
    private fun SelectionScreen(
        records: List<RecordEntity>,
        selected: Set<String>,
        onToggle: (String) -> Unit,
        onClose: () -> Unit,
        onShare: () -> Unit,
        onDelete: () -> Unit,
        modifier: Modifier,
    ) {
        Column(modifier.fillMaxSize().padding(18.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("已选择 ${selected.size} 条", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.weight(1f))
                IconButton(onClick = onShare) { Icon(Icons.Default.Share, "分享") }
                IconButton(onClick = onDelete) { Icon(Icons.Default.Delete, "删除") }
                Button(onClick = onClose) { Text("完成") }
            }
            LazyColumn {
                items(records, key = { it.id }) { note ->
                    Row(
                        Modifier.fillMaxWidth().combinedClickable(
                            onClick = { onToggle(note.id) },
                            onLongClick = { onToggle(note.id) },
                        ).padding(vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(note.id in selected, onCheckedChange = { onToggle(note.id) })
                        Column {
                            Text(note.title.ifBlank { fallbackTitle(note) }, fontWeight = FontWeight.Bold)
                            if (note.summary.isNotBlank()) Text(note.summary, maxLines = 1)
                        }
                    }
                }
            }
        }
    }

    @Composable
    private fun ConversationScreen(
        records: List<RecordEntity>,
        onOpen: (String) -> Unit,
        onCreate: () -> Unit,
        modifier: Modifier,
    ) {
        Column(modifier.fillMaxSize().padding(18.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("完整对话", style = MaterialTheme.typography.headlineSmall)
                Button(onClick = onCreate) { Text("新建对话") }
            }
            LazyColumn(Modifier.padding(top = 14.dp)) {
                items(records, key = { it.id }) { record ->
                    Card(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp).combinedClickable(
                            onClick = { onOpen(record.id) },
                            onLongClick = {},
                        ),
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Text(record.title.ifBlank { "正在整理…" }, fontWeight = FontWeight.Bold)
                            if (record.summary.isNotBlank()) Text(record.summary, maxLines = 2)
                        }
                    }
                }
            }
        }
    }

    @Composable
    private fun SettingsPanel(modifier: Modifier = Modifier) {
        val server = remember { getSharedPreferences("server", MODE_PRIVATE) }
        val notes = remember { getSharedPreferences("note_preferences", MODE_PRIVATE) }
        var baseUrl by remember {
            mutableStateOf(server.getString("baseUrl", "http://106.53.94.254/chastream/").orEmpty())
        }
        var apiToken by remember { mutableStateOf(server.getString("apiToken", "").orEmpty()) }
        var processingMode by remember { mutableStateOf(notes.getString("processingMode", "organize").orEmpty()) }
        var timeMode by remember { mutableStateOf(notes.getString("timeMode", "updated").orEmpty()) }
        var sortMode by remember { mutableStateOf(notes.getString("sortMode", "updated").orEmpty()) }
        LazyColumn(modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                Text("笔记设置", style = MaterialTheme.typography.headlineSmall)
                SettingChoices(
                    "语音处理",
                    processingMode,
                    listOf("organize" to "转写并整理", "transcribe" to "仅语音转写"),
                ) { processingMode = it }
                SettingChoices(
                    "卡片时间",
                    timeMode,
                    listOf("updated" to "最新修改时间", "created" to "创建时间"),
                ) { timeMode = it }
                SettingChoices(
                    "笔记排序",
                    sortMode,
                    listOf("updated" to "最新修改优先", "created" to "最新创建优先"),
                ) { sortMode = it }
                Text("服务器设置", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(top = 14.dp))
                Button(onClick = {
                    startActivity(Intent(this@MainActivity, VoiceprintManagerActivity::class.java))
                }) { Text("管理声纹集合") }
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it },
                    modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    label = { Text("API 地址") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = apiToken,
                    onValueChange = { apiToken = it },
                    modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    label = { Text("API Token") },
                    singleLine = true,
                )
                Button(onClick = {
                    server.edit()
                        .putString("baseUrl", if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/")
                        .putString("apiToken", apiToken.trim())
                        .apply()
                    notes.edit()
                        .putString("processingMode", processingMode)
                        .putString("timeMode", timeMode)
                        .putString("sortMode", sortMode)
                        .apply()
                    (application as ChastreamApplication).repository.enqueueUpload()
                    recreate()
                }, modifier = Modifier.padding(top = 14.dp)) { Text("保存设置") }
            }
        }
    }

    @Composable
    private fun SettingChoices(
        title: String,
        selected: String,
        options: List<Pair<String, String>>,
        onSelect: (String) -> Unit,
    ) {
        Text(title, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 12.dp))
        options.forEach { (value, label) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                RadioButton(selected == value, onClick = { onSelect(value) })
                Text(label)
            }
        }
    }

    private fun openNote(id: String) {
        startActivity(Intent(this, DetailActivity::class.java).putExtra("noteId", id))
    }

    private fun openNewNote() {
        startActivity(Intent(this, DetailActivity::class.java).apply {
            putExtra("noteId", UUID.randomUUID().toString())
            putExtra("isNew", true)
        })
    }

    private fun launchRecorder(tab: Int) {
        if (tab == 1) {
            startActivity(Intent(this, ConversationSetupActivity::class.java))
        } else {
            startActivity(Intent(this, QuickRecordActivity::class.java).apply {
                putExtra("autoStart", true)
                putExtra("source", "app")
                putExtra("kind", "quick_note")
            })
        }
    }

    private fun formatTime(timestamp: Long): String {
        val sameDay = SimpleDateFormat("yyyyMMdd", Locale.getDefault()).format(Date()) ==
            SimpleDateFormat("yyyyMMdd", Locale.getDefault()).format(Date(timestamp))
        val pattern = if (sameDay) "HH:mm" else "MM-dd"
        return SimpleDateFormat(pattern, Locale.getDefault()).format(Date(timestamp))
    }

    private fun fallbackTitle(note: RecordEntity): String =
        note.summary.ifBlank { note.content }.trim().replace("\n", " ").take(10).ifBlank { "新笔记" }
}
