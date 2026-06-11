package com.westbrook.chastream.mobile.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.westbrook.chastream.mobile.ChastreamApplication
import com.westbrook.chastream.mobile.data.RecordEntity

class DetailActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val recordId = intent.getStringExtra("noteId").orEmpty()
        setContent {
            var record by remember { mutableStateOf<RecordEntity?>(null) }
            LaunchedEffect(recordId) {
                record = (application as ChastreamApplication).repository.get(recordId)
            }
            MaterialTheme {
                Column(
                    Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
                ) {
                    Text(record?.title?.ifBlank { "正在整理" } ?: "笔记", style = MaterialTheme.typography.headlineSmall)
                    Text(record?.status.orEmpty(), color = MaterialTheme.colorScheme.primary)
                    Text(record?.content?.ifBlank { record?.summary.orEmpty() }.orEmpty(), modifier = Modifier.padding(top = 18.dp))
                    record?.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                }
            }
        }
    }
}
