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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.westbrook.chastream.mobile.ChastreamApplication
import com.westbrook.chastream.mobile.recording.PcmWavRecorder
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File

class QuickRecordActivity : ComponentActivity() {
    private val recorder = PcmWavRecorder()
    private lateinit var output: File

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        output = File(filesDir, "recordings/${System.currentTimeMillis()}.wav")
        val autoStart = intent.getBooleanExtra("autoStart", false)
        val source = intent.getStringExtra("source") ?: "app"
        val kind = intent.getStringExtra("kind") ?: "quick_note"
        val style = intent.getStringExtra("style")
            ?: if (kind == "conversation") "chat" else "formal_paragraph"
        val title = intent.getStringExtra("title").orEmpty()
        val metadataJson = intent.getStringExtra("metadataJson")
            ?: if (kind == "conversation") {
                """{"speakerMode":"two","selectedSpeakerIds":[]}"""
            } else {
                "{}"
            }
        setContent {
            MaterialTheme {
                RecorderScreen(autoStart) { isRecording ->
                    if (isRecording) {
                        recorder.start(output)
                    } else {
                        recorder.stop()
                        lifecycleScope.launch {
                            val app = application as ChastreamApplication
                            app.repository.createLocal(
                                kind = kind,
                                audioPath = output.absolutePath,
                                source = source,
                                style = style,
                                metadataJson = metadataJson,
                                title = title,
                            )
                            finish()
                        }
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        recorder.stop()
        super.onDestroy()
    }

    @Composable
    private fun RecorderScreen(autoStart: Boolean, onRecordingChange: (Boolean) -> Unit) {
        var recording by remember { mutableStateOf(false) }
        var startedAt by remember { mutableLongStateOf(0L) }
        var elapsed by remember { mutableLongStateOf(0L) }
        val permission = rememberLauncherForActivityResult(
            ActivityResultContracts.RequestPermission(),
        ) { granted ->
            if (granted) {
                recording = true
                startedAt = System.currentTimeMillis()
                onRecordingChange(true)
            }
        }
        fun start() {
            if (ContextCompat.checkSelfPermission(
                    this,
                    Manifest.permission.RECORD_AUDIO,
                ) == PackageManager.PERMISSION_GRANTED
            ) {
                recording = true
                startedAt = System.currentTimeMillis()
                onRecordingChange(true)
            } else {
                permission.launch(Manifest.permission.RECORD_AUDIO)
            }
        }
        LaunchedEffect(autoStart) {
            if (autoStart && !recording) start()
        }
        LaunchedEffect(recording) {
            while (recording) {
                elapsed = System.currentTimeMillis() - startedAt
                delay(250)
            }
        }
        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(if (recording) "正在录音" else "准备录音", style = MaterialTheme.typography.headlineMedium)
            Spacer(Modifier.height(12.dp))
            Text("%02d:%02d".format(elapsed / 60_000, elapsed / 1_000 % 60))
            Spacer(Modifier.height(28.dp))
            Button(
                onClick = {
                    if (recording) {
                        recording = false
                        onRecordingChange(false)
                    } else {
                        start()
                    }
                },
            ) {
                Icon(if (recording) Icons.Default.Stop else Icons.Default.Mic, null)
                Text(if (recording) " 停止并整理" else " 开始录音")
            }
        }
    }
}
