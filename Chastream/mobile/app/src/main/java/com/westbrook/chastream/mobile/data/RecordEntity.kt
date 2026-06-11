package com.westbrook.chastream.mobile.data

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "records")
data class RecordEntity(
    @PrimaryKey val id: String,
    val remoteId: String? = null,
    val kind: String,
    val title: String = "",
    val summary: String = "",
    val content: String = "",
    val rawTranscript: String = "",
    val audioPath: String,
    val status: String = "local",
    val source: String = "app",
    val style: String = "formal_paragraph",
    val metadataJson: String = "{}",
    val error: String? = null,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis(),
)
