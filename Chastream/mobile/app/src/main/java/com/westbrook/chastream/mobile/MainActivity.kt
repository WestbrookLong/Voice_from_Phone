package com.westbrook.chastream.mobile

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.westbrook.chastream.mobile.data.RecordEntity
import com.westbrook.chastream.mobile.ui.DetailActivity
import com.westbrook.chastream.mobile.ui.ConversationSetupActivity
import com.westbrook.chastream.mobile.ui.QuickRecordActivity
import com.westbrook.chastream.mobile.ui.VoiceprintManagerActivity

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
        Scaffold(
            bottomBar = {
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
            },
        ) { padding ->
            if (tab == 2) {
                SettingsPanel(Modifier.padding(padding))
                return@Scaffold
            }
            Column(Modifier.fillMaxSize().padding(padding).padding(18.dp)) {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        if (tab == 0) "最近想法" else "完整对话",
                        style = MaterialTheme.typography.headlineSmall,
                    )
                    Button(onClick = { launchRecorder(tab) }) {
                        Text(if (tab == 0) "快速录音" else "新建对话")
                    }
                }
                RecordList(if (tab == 0) quickNotes else conversations)
            }
        }
    }

    @Composable
    private fun SettingsPanel(modifier: Modifier = Modifier) {
        val preferences = remember {
            getSharedPreferences("server", MODE_PRIVATE)
        }
        var baseUrl by remember {
            mutableStateOf(
                preferences.getString(
                    "baseUrl",
                    "http://106.53.94.254/chastream/",
                ).orEmpty(),
            )
        }
        var apiToken by remember {
            mutableStateOf(preferences.getString("apiToken", "").orEmpty())
        }
        Column(modifier.fillMaxSize().padding(20.dp)) {
            Text("服务器设置", style = MaterialTheme.typography.headlineSmall)
            Button(
                onClick = {
                    startActivity(Intent(this@MainActivity, VoiceprintManagerActivity::class.java))
                },
                modifier = Modifier.padding(top = 16.dp),
            ) {
                Text("管理声纹集合")
            }
            OutlinedTextField(
                value = baseUrl,
                onValueChange = { baseUrl = it },
                modifier = Modifier.fillMaxWidth().padding(top = 18.dp),
                label = { Text("API 地址") },
                singleLine = true,
            )
            OutlinedTextField(
                value = apiToken,
                onValueChange = { apiToken = it },
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                label = { Text("API Token") },
                singleLine = true,
            )
            Button(
                onClick = {
                    preferences.edit()
                        .putString(
                            "baseUrl",
                            if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/",
                        )
                        .putString("apiToken", apiToken.trim())
                        .apply()
                    (application as ChastreamApplication).repository.enqueueUpload()
                },
                modifier = Modifier.padding(top = 16.dp),
            ) {
                Text("保存并重试待上传任务")
            }
        }
    }

    @Composable
    private fun RecordList(records: List<RecordEntity>) {
        LazyColumn(Modifier.padding(top = 14.dp)) {
            items(records, key = { it.id }) { record ->
                Column(
                    Modifier.fillMaxWidth().clickable {
                        startActivity(Intent(this@MainActivity, DetailActivity::class.java).apply {
                            putExtra("noteId", record.id)
                        })
                    }.padding(vertical = 13.dp),
                ) {
                    Text(record.title.ifBlank { if (record.status == "done") "未命名" else "正在整理…" })
                    Text(
                        record.summary.ifBlank { record.status },
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                HorizontalDivider()
            }
        }
    }

    private fun launchRecorder(tab: Int) {
        if (tab == 1) {
            startActivity(Intent(this, ConversationSetupActivity::class.java))
            return
        }
        startActivity(Intent(this, QuickRecordActivity::class.java).apply {
            putExtra("autoStart", true)
            putExtra("source", "app")
            putExtra("kind", "quick_note")
        })
    }
}
