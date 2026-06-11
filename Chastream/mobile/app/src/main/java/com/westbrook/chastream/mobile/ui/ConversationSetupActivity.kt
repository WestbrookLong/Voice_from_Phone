package com.westbrook.chastream.mobile.ui

import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.westbrook.chastream.mobile.network.ApiFactory
import com.westbrook.chastream.mobile.network.VoiceprintCollection
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class ConversationSetupActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { SetupScreen() } }
    }

    @Composable
    private fun SetupScreen() {
        var title by remember { mutableStateOf("") }
        var style by remember { mutableStateOf("chat") }
        var speakerMode by remember { mutableStateOf("two") }
        var enableScl by remember { mutableStateOf(true) }
        var matchThreshold by remember { mutableFloatStateOf(0.33f) }
        var marginThreshold by remember { mutableFloatStateOf(0.06f) }
        var sclThreshold by remember { mutableFloatStateOf(0.45f) }
        var collections by remember { mutableStateOf<List<VoiceprintCollection>>(emptyList()) }
        var selectedIds by remember { mutableStateOf<Set<String>>(emptySet()) }
        var loadError by remember { mutableStateOf<String?>(null) }
        val scope = rememberCoroutineScope()
        fun metadataJson(): String = JSONObject()
            .put("speakerMode", speakerMode)
            .put("selectedSpeakerIds", JSONArray(selectedIds.toList()))
            .put("enableScl", enableScl)
            .put("voiceprintThreshold", matchThreshold.toDouble())
            .put("voiceprintMargin", marginThreshold.toDouble())
            .put("sclTriggerThreshold", sclThreshold.toDouble())
            .toString()
        val importAudio = rememberLauncherForActivityResult(
            ActivityResultContracts.OpenDocument(),
        ) { uri ->
            if (uri == null) return@rememberLauncherForActivityResult
            scope.launch {
                runCatching {
                    val imported = withContext(Dispatchers.IO) {
                        val suffix = audioSuffix(contentResolver.getType(uri))
                        File(filesDir, "imports/${System.currentTimeMillis()}$suffix").also { target ->
                            target.parentFile?.mkdirs()
                            contentResolver.openInputStream(uri).use { input ->
                                requireNotNull(input) { "无法读取录音文件" }
                                target.outputStream().use(input::copyTo)
                            }
                        }
                    }
                    (application as com.westbrook.chastream.mobile.ChastreamApplication).repository.createLocal(
                        kind = "conversation",
                        audioPath = imported.absolutePath,
                        source = "import",
                        style = style,
                        metadataJson = metadataJson(),
                        title = title.trim(),
                    )
                }.onSuccess { finish() }
                    .onFailure { loadError = it.message ?: "导入失败" }
            }
        }

        LaunchedEffect(Unit) {
            runCatching {
                withContext(Dispatchers.IO) { ApiFactory.create(this@ConversationSetupActivity).voiceprints().items }
            }.onSuccess {
                collections = it
                selectedIds = it.filter { collection ->
                    collection.elements.any { element -> !element.hidden }
                }.mapTo(mutableSetOf()) { collection -> collection.id }
            }.onFailure { loadError = it.message ?: "无法读取声纹集合" }
        }

        LazyColumn(
            Modifier.fillMaxSize().padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Text(
                    "新建完整对话",
                    style = MaterialTheme.typography.headlineSmall,
                    modifier = Modifier.padding(top = 20.dp),
                )
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    modifier = Modifier.fillMaxWidth().padding(top = 14.dp),
                    label = { Text("标题（可选）") },
                    singleLine = true,
                )
                Text("整理风格", modifier = Modifier.padding(top = 14.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(
                        "chat" to "对话分析",
                        "meeting_note" to "会议纪要",
                        "formal_paragraph" to "正式段落",
                    ).forEach { (value, label) ->
                        FilterChip(
                            selected = style == value,
                            onClick = { style = value },
                            label = { Text(label) },
                        )
                    }
                }
                Text("说话人数模式")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("one" to "单人", "two" to "双人", "multi" to "多人").forEach { (value, label) ->
                        FilterChip(
                            selected = speakerMode == value,
                            onClick = { speakerMode = value },
                            label = { Text(label) },
                        )
                    }
                }
                Text("参与者范围")
                if (collections.isEmpty()) {
                    Text(loadError ?: "正在读取已注册声纹…", style = MaterialTheme.typography.bodySmall)
                }
            }
            items(collections, key = { it.id }) { collection ->
                val usableCount = collection.elements.count { !it.hidden }
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Checkbox(
                        checked = collection.id in selectedIds,
                        enabled = usableCount > 0,
                        onCheckedChange = { checked ->
                            selectedIds = if (checked) {
                                selectedIds + collection.id
                            } else {
                                selectedIds - collection.id
                            }
                        },
                    )
                    Column {
                        Text(collection.name)
                        Text(
                            "$usableCount 个有效声纹元素",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            }
            item {
                ThresholdSlider("匹配阈值", matchThreshold, 0f..1f) { matchThreshold = it }
                ThresholdSlider("领先阈值", marginThreshold, 0f..0.3f) { marginThreshold = it }
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text("启用 SCL 精切分")
                    Switch(checked = enableScl, onCheckedChange = { enableScl = it })
                }
                if (enableScl) {
                    ThresholdSlider("SCL 触发阈值", sclThreshold, 0f..1f) { sclThreshold = it }
                }
                Button(
                    onClick = {
                        startActivity(Intent(this@ConversationSetupActivity, QuickRecordActivity::class.java).apply {
                            putExtra("autoStart", true)
                            putExtra("source", "app")
                            putExtra("kind", "conversation")
                            putExtra("title", title.trim())
                            putExtra("style", style)
                            putExtra("metadataJson", metadataJson())
                        })
                        finish()
                    },
                    enabled = selectedIds.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("开始录音")
                }
                Button(
                    onClick = { importAudio.launch(arrayOf("audio/*")) },
                    enabled = selectedIds.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth().padding(bottom = 24.dp),
                ) {
                    Text("导入已有录音")
                }
            }
        }
    }

    private fun audioSuffix(mimeType: String?): String = when (mimeType) {
        "audio/mpeg" -> ".mp3"
        "audio/mp4", "audio/x-m4a" -> ".m4a"
        "audio/flac", "audio/x-flac" -> ".flac"
        "audio/ogg" -> ".ogg"
        "audio/aac" -> ".aac"
        else -> ".wav"
    }

    @Composable
    private fun ThresholdSlider(
        label: String,
        value: Float,
        range: ClosedFloatingPointRange<Float>,
        onChange: (Float) -> Unit,
    ) {
        Text("$label：${"%.2f".format(value)}")
        Slider(value = value, onValueChange = onChange, valueRange = range)
    }
}
