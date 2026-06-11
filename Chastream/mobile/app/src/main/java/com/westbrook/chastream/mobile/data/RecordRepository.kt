package com.westbrook.chastream.mobile.data

import android.content.Context
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.westbrook.chastream.mobile.sync.UploadWorker
import com.westbrook.chastream.mobile.widget.RecentNotesWidget
import java.util.UUID

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
    ): RecordEntity {
        val record = RecordEntity(
            id = UUID.randomUUID().toString(),
            kind = kind,
            title = title,
            audioPath = audioPath,
            source = source,
            style = style,
            metadataJson = metadataJson,
        )
        dao.upsert(record)
        enqueueUpload()
        RecentNotesWidget.updateAll(context)
        return record
    }

    suspend fun get(id: String) = dao.get(id)
    suspend fun pending() = dao.nextPending()
    suspend fun save(record: RecordEntity) = dao.upsert(record)
    suspend fun recentNotes(limit: Int) = dao.recentNotes(limit)

    fun enqueueUpload() {
        WorkManager.getInstance(context).enqueueUniqueWork(
            "chastream-upload",
            ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<UploadWorker>().build(),
        )
    }
}
