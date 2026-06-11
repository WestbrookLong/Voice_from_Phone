package com.westbrook.chastream.mobile.ui

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.westbrook.chastream.mobile.network.ApiFactory
import com.westbrook.chastream.mobile.network.ElementPayload
import com.westbrook.chastream.mobile.network.NamePayload
import com.westbrook.chastream.mobile.network.VoiceprintCollection
import kotlinx.coroutines.launch

class VoiceprintManagerActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { VoiceprintScreen() } }
    }

    @Composable
    private fun VoiceprintScreen() {
        val api = remember { ApiFactory.create(this) }
        val scope = rememberCoroutineScope()
        var collections by remember { mutableStateOf<List<VoiceprintCollection>>(emptyList()) }
        var error by remember { mutableStateOf<String?>(null) }
        var addingCollection by remember { mutableStateOf(false) }
        var newName by remember { mutableStateOf("") }

        fun refresh() {
            scope.launch {
                runCatching { api.voiceprints().items }
                    .onSuccess { collections = it; error = null }
                    .onFailure { error = it.message }
            }
        }
        LaunchedEffect(Unit) { refresh() }
        LaunchedEffect(lifecycle.currentState) {
            if (lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.RESUMED)) refresh()
        }

        Column(Modifier.fillMaxSize().padding(20.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("声纹集合", style = MaterialTheme.typography.headlineSmall)
                Button(onClick = { addingCollection = true }) {
                    Icon(Icons.Default.Add, null)
                    Text("新建集合")
                }
            }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            LazyColumn(
                Modifier.fillMaxSize().padding(top = 12.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                items(collections, key = { it.id }) { collection ->
                    Column(Modifier.fillMaxWidth()) {
                        Row(
                            Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column {
                                Text(collection.name, style = MaterialTheme.typography.titleMedium)
                                Text("${collection.elements.size} 个元素", style = MaterialTheme.typography.bodySmall)
                            }
                            Row {
                                IconButton(onClick = {
                                    scope.launch {
                                        runCatching { api.deleteVoiceprintCollection(collection.id) }
                                            .onSuccess { refresh() }
                                            .onFailure { error = it.message }
                                    }
                                }) { Icon(Icons.Default.Delete, "删除集合") }
                                OutlinedButton(onClick = {
                                    startActivity(Intent(
                                        this@VoiceprintManagerActivity,
                                        VoiceprintSampleActivity::class.java,
                                    ).apply {
                                        putExtra("collectionId", collection.id)
                                        putExtra("collectionName", collection.name)
                                    })
                                }) { Text("新建元素") }
                            }
                        }
                        collection.elements.forEach { element ->
                            Row(
                                Modifier.fillMaxWidth().padding(top = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(Modifier.weight(1f)) {
                                    Text(element.name)
                                    Text(
                                        if (element.hidden) "识别时已隐藏" else "参与匹配",
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                }
                                Switch(
                                    checked = !element.hidden,
                                    onCheckedChange = { enabled ->
                                        scope.launch {
                                            runCatching {
                                                api.updateVoiceprintElement(
                                                    collection.id,
                                                    element.id,
                                                    ElementPayload(hidden = !enabled),
                                                )
                                            }.onSuccess { refresh() }
                                                .onFailure { error = it.message }
                                        }
                                    },
                                )
                                IconButton(onClick = {
                                    scope.launch {
                                        runCatching {
                                            api.deleteVoiceprintElement(collection.id, element.id)
                                        }.onSuccess { refresh() }
                                            .onFailure { error = it.message }
                                    }
                                }) { Icon(Icons.Default.Delete, "删除元素") }
                            }
                        }
                    }
                }
            }
        }

        if (addingCollection) {
            AlertDialog(
                onDismissRequest = { addingCollection = false },
                title = { Text("新建声纹集合") },
                text = {
                    OutlinedTextField(
                        value = newName,
                        onValueChange = { newName = it },
                        label = { Text("姓名") },
                        singleLine = true,
                    )
                },
                confirmButton = {
                    TextButton(
                        enabled = newName.isNotBlank(),
                        onClick = {
                            scope.launch {
                                runCatching { api.createVoiceprintCollection(NamePayload(newName.trim())) }
                                    .onSuccess {
                                        newName = ""
                                        addingCollection = false
                                        refresh()
                                    }
                                    .onFailure { error = it.message }
                            }
                        },
                    ) { Text("创建") }
                },
                dismissButton = {
                    TextButton(onClick = { addingCollection = false }) { Text("取消") }
                },
            )
        }
    }
}
