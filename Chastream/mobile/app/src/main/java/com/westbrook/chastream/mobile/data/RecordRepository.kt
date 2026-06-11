package com.westbrook.chastream.mobile.data

import android.content.Context
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.westbrook.chastream.mobile.sync.UploadWorker
import com.westbrook.chastream.mobile.widget.RecentNotesWidget
import java.util.UUID
import java.io.File

class RecordRepository(
    private val context: Context,
    private val dao: RecordDao,
) {
    fun observeQuickNotes() = dao.observeKind("quick_note")
    fun observeConversations() = dao.observeKind("conversation")

    suspend fun createLocal(
        kind: String,
        audioPath: String,
        source: String,
        style: String,
        metadataJson: String = "{}",
        title: String = "",
        processingMode: String = "organize",
        existingId: String? = null,
    ): RecordEntity {
        val existing = existingId?.let { dao.get(it) }
        val record = RecordEntity(
            id = existing?.id ?: UUID.randomUUID().toString(),
            remoteId = null,
            kind = kind,
            title = title.ifBlank { existing?.title.orEmpty() },
            summary = existing?.summary.orEmpty(),
            content = existing?.content.orEmpty(),
            rawTranscript = existing?.rawTranscript.orEmpty(),
            audioPath = audioPath,
            source = source,
            style = style,
            processingMode = processingMode,
            metadataJson = metadataJson,
            createdAt = existing?.createdAt ?: System.currentTimeMillis(),
            updatedAt = System.currentTimeMillis(),
        )
        dao.upsert(record)
        enqueueUpload()
        RecentNotesWidget.updateAll(context)
        return record
    }

    suspend fun get(id: String) = dao.get(id)
    fun observe(id: String) = dao.observe(id)
    suspend fun pending() = dao.nextPending()
    suspend fun save(record: RecordEntity) = dao.upsert(record)
    suspend fun delete(id: String) {
        dao.get(id)?.audioPath?.takeIf { it.isNotBlank() }?.let { File(it).delete() }
        dao.delete(id)
        RecentNotesWidget.updateAll(context)
    }
    suspend fun deleteMany(ids: List<String>) {
        ids.forEach { id ->
            dao.get(id)?.audioPath?.takeIf { it.isNotBlank() }?.let { File(it).delete() }
        }
        dao.deleteMany(ids)
        RecentNotesWidget.updateAll(context)
    }
    suspend fun recentNotes(limit: Int) = dao.recentNotes(limit)

    fun enqueueUpload() {
        WorkManager.getInstance(context).enqueueUniqueWork(
            "chastream-upload",
            ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<UploadWorker>().build(),
        )
    }
}
