package com.westbrook.chastream.mobile.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.westbrook.chastream.mobile.network.ApiFactory
import com.westbrook.chastream.mobile.recording.PcmWavRecorder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File

class VoiceprintSampleActivity : ComponentActivity() {
    private val recorder = PcmWavRecorder()
    private lateinit var output: File

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        output = File(filesDir, "voiceprints/${System.currentTimeMillis()}.wav")
        setContent { MaterialTheme { SampleScreen() } }
    }

    override fun onDestroy() {
        recorder.stop()
        super.onDestroy()
    }

    @Composable
    private fun SampleScreen() {
        val collectionId = intent.getStringExtra("collectionId").orEmpty()
        val collectionName = intent.getStringExtra("collectionName").orEmpty()
        var elementName by remember { mutableStateOf("") }
        var recording by remember { mutableStateOf(false) }
        var hasSample by remember { mutableStateOf(false) }
        var uploading by remember { mutableStateOf(false) }
        var message by remember { mutableStateOf("请自然朗读 15 至 30 秒，尽量保持单人、无背景音乐。") }
        val scope = rememberCoroutineScope()
        val permission = rememberLauncherForActivityResult(
            ActivityResultContracts.RequestPermission(),
        ) { granted ->
            if (granted) {
                recorder.start(output)
                recording = true
            }
        }

        fun startRecording() {
            if (ContextCompat.checkSelfPermission(
                    this,
                    Manifest.permission.RECORD_AUDIO,
                ) == PackageManager.PERMISSION_GRANTED
            ) {
                recorder.start(output)
                recording = true
            } else {
                permission.launch(Manifest.permission.RECORD_AUDIO)
            }
        }

        Column(
            Modifier.fillMaxSize().padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp, Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("为 $collectionName 新建声纹元素", style = MaterialTheme.typography.headlineSmall)
            OutlinedTextField(
                value = elementName,
                onValueChange = { elementName = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("元素名称，例如：日常说话") },
                singleLine = true,
            )
            Text(message)
            Button(
                enabled = !uploading,
                onClick = {
                    if (recording) {
                        recorder.stop()
                        recording = false
                        hasSample = true
                        message = "样本已录制，可以完成注册或重新录制。"
                    } else {
                        hasSample = false
                        startRecording()
                        message = "正在录制声纹样本…"
                    }
                },
            ) {
                Icon(if (recording) Icons.Default.Stop else Icons.Default.Mic, null)
                Text(if (recording) "停止录制" else if (hasSample) "重新录制" else "开始录制")
            }
            Button(
                enabled = hasSample && elementName.isNotBlank() && !uploading,
                onClick = {
                    uploading = true
                    message = "正在清理音频并提取 CAM++ 声纹…"
                    scope.launch {
                        runCatching {
                            withContext(Dispatchers.IO) {
                                val audio = MultipartBody.Part.createFormData(
                                    "samples",
                                    output.name,
                                    output.asRequestBody("audio/wav".toMediaType()),
                                )
                                ApiFactory.create(this@VoiceprintSampleActivity).createVoiceprintElement(
                                    collectionId,
                                    elementName.trim().toRequestBody("text/plain".toMediaType()),
                                    listOf(audio),
                                )
                            }
                        }.onSuccess { finish() }
                            .onFailure {
                                uploading = false
                                message = it.message ?: "注册失败"
                            }
                    }
                },
            ) { Text(if (uploading) "注册中…" else "完成注册") }
        }
    }
}
