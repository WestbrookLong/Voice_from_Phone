package com.westbrook.chastream.mobile.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import com.westbrook.chastream.mobile.ChastreamApplication
import com.westbrook.chastream.mobile.data.RecordEntity
import kotlinx.coroutines.launch

class DetailActivity : ComponentActivity() {
    private lateinit var noteId: String
    private var loaded: RecordEntity? = null
    private var titleValue = ""
    private var summaryValue = ""
    private var contentValue = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        noteId = intent.getStringExtra("noteId").orEmpty()
        val isNew = intent.getBooleanExtra("isNew", false)
        setContent { MaterialTheme { EditorScreen(isNew) } }
    }

    override fun onPause() {
        saveCurrent()
        super.onPause()
    }

    @Composable
    private fun EditorScreen(isNew: Boolean) {
        val repository = (application as ChastreamApplication).repository
        var record by remember { mutableStateOf<RecordEntity?>(null) }
        var title by remember { mutableStateOf("") }
        var summary by remember { mutableStateOf("") }
        var content by remember { mutableStateOf("") }
        var showTranscript by remember { mutableStateOf(false) }
        var shareDialog by remember { mutableStateOf(false) }

        LaunchedEffect(noteId) {
            record = repository.get(noteId)
            loaded = record
            title = record?.title.orEmpty()
            summary = record?.summary.orEmpty()
            content = record?.content.orEmpty()
            titleValue = title
            summaryValue = summary
            contentValue = content
        }

        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),
        ) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                IconButton(onClick = {
                    val text = NoteShare.toMarkdown(currentRecord(record, isNew))
                    val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("Chastream note", text))
                }) { Icon(Icons.Default.ContentCopy, "复制") }
                IconButton(onClick = { shareDialog = true }) { Icon(Icons.Default.Share, "分享") }
                if (record == null || record?.kind == "quick_note") {
                    IconButton(onClick = {
                        saveCurrent()
                        startActivity(Intent(this@DetailActivity, QuickRecordActivity::class.java).apply {
                            putExtra("autoStart", true)
                            putExtra("source", "note")
                            putExtra("kind", "quick_note")
                            putExtra("noteId", noteId)
                        })
                        finish()
                    }) { Icon(Icons.Default.Mic, "继续录音") }
                }
            }
            OutlinedTextField(
                value = title,
                onValueChange = { title = it; titleValue = it },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("标题") },
                textStyle = MaterialTheme.typography.headlineSmall,
                singleLine = true,
            )
            OutlinedTextField(
                value = summary,
                onValueChange = { summary = it; summaryValue = it },
                modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                placeholder = { Text("摘要（可选）") },
                shape = RoundedCornerShape(14.dp),
                textStyle = MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
                colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                    unfocusedContainerColor = Color(0xFFF3F2F6),
                    focusedContainerColor = Color(0xFFF3F2F6),
                ),
            )
            OutlinedTextField(
                value = content,
                onValueChange = { content = it; contentValue = it },
                modifier = Modifier.fillMaxWidth().padding(top = 14.dp),
                placeholder = { Text("开始记录你的想法…") },
                minLines = 14,
            )
            record?.let { current ->
                if (current.status !in setOf("done", "manual")) {
                    Text(
                        if (current.status == "failed") current.error ?: "处理失败" else "语音正在后台处理…",
                        color = if (current.status == "failed") MaterialTheme.colorScheme.error
                        else MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(top = 12.dp),
                    )
                }
                if (current.rawTranscript.isNotBlank()) {
                    TextButton(onClick = { showTranscript = !showTranscript }) {
                        Text(if (showTranscript) "收起完整转写" else "查看完整转写")
                    }
                    if (showTranscript) Text(current.rawTranscript, color = Color(0xFF66616F))
                }
            }
        }

        if (shareDialog) {
            AlertDialog(
                onDismissRequest = { shareDialog = false },
                title = { Text("分享笔记") },
                text = { Text("选择分享格式") },
                confirmButton = {
                    Button(onClick = {
                        saveCurrent()
                        NoteShare.shareMarkdown(this, listOf(currentRecord(record, isNew)))
                        shareDialog = false
                    }) { Text("Markdown") }
                },
                dismissButton = {
                    Button(onClick = {
                        saveCurrent()
                        NoteShare.shareLongImage(this, currentRecord(record, isNew))
                        shareDialog = false
                    }) { Text("长截图") }
                },
            )
        }
    }

    private fun currentRecord(record: RecordEntity?, isNew: Boolean): RecordEntity {
        val base = record ?: RecordEntity(
            id = noteId,
            kind = "quick_note",
            audioPath = "",
            status = "manual",
            source = if (isNew) "manual" else "app",
        )
        return base.copy(
            title = titleValue.trim().ifBlank {
                summaryValue.ifBlank { contentValue }.trim().replace("\n", " ").take(10)
            },
            summary = summaryValue,
            content = contentValue,
            status = if (base.status in setOf("local", "uploading", "processing")) base.status else "manual",
            updatedAt = System.currentTimeMillis(),
        )
    }

    private fun saveCurrent() {
        if (!::noteId.isInitialized) return
        lifecycleScope.launch {
            val repository = (application as ChastreamApplication).repository
            val existing = repository.get(noteId)
            val hasText = titleValue.isNotBlank() || summaryValue.isNotBlank() || contentValue.isNotBlank()
            if (!hasText) {
                if (existing != null && existing.audioPath.isBlank()) repository.delete(noteId)
                return@launch
            }
            val fallback = summaryValue.ifBlank { contentValue }
                .trim().replace("\n", " ").take(10)
            val base = existing ?: RecordEntity(
                id = noteId,
                kind = "quick_note",
                audioPath = "",
                status = "manual",
                source = "manual",
            )
            repository.save(
                base.copy(
                    title = titleValue.trim().ifBlank { fallback },
                    summary = summaryValue.trim(),
                    content = contentValue.trim(),
                    status = if (base.status in setOf("local", "uploading", "processing")) {
                        base.status
                    } else {
                        "manual"
                    },
                    updatedAt = System.currentTimeMillis(),
                ),
            )
        }
    }
}
