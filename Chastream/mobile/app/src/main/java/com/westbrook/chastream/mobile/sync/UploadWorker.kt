package com.westbrook.chastream.mobile.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.westbrook.chastream.mobile.ChastreamApplication
import com.westbrook.chastream.mobile.data.RecordEntity
import com.westbrook.chastream.mobile.network.ApiFactory
import com.westbrook.chastream.mobile.network.RemoteRecord
import com.westbrook.chastream.mobile.widget.RecentNotesWidget
import kotlinx.coroutines.delay
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File

class UploadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as ChastreamApplication
        val repository = app.repository
        val record = repository.pending() ?: return Result.success()
        val file = File(record.audioPath)
        if (!file.exists()) {
            repository.save(record.copy(status = "failed", error = "本地录音文件不存在"))
            return Result.failure()
        }
        repository.save(record.copy(status = "uploading", error = null))
        return try {
            val api = ApiFactory.create(applicationContext)
            val audio = MultipartBody.Part.createFormData(
                "audio",
                file.name,
                file.asRequestBody("audio/wav".toMediaType()),
            )
            val textType = "text/plain".toMediaType()
            val response = if (record.kind == "quick_note") {
                api.createQuickNote(
                    audio,
                    record.style.toRequestBody(textType),
                    record.source.toRequestBody(textType),
                    record.processingMode.toRequestBody(textType),
                    record.title.toRequestBody(textType),
                    record.summary.toRequestBody(textType),
                    record.content.toRequestBody(textType),
                )
            } else {
                api.createConversation(
                    audio,
                    record.title.toRequestBody(textType),
                    record.style.toRequestBody(textType),
                    record.source.toRequestBody(textType),
                    record.metadataJson.toRequestBody(textType),
                )
            }
            var remote = response.record
            repository.save(record.fromRemote(remote))
            repeat(120) {
                if (remote.status in setOf("done", "failed")) return@repeat
                delay(3_000)
                remote = if (record.kind == "quick_note") {
                    api.quickNote(remote.id)
                } else {
                    api.conversation(remote.id)
                }
                repository.save(record.fromRemote(remote))
                RecentNotesWidget.updateAll(applicationContext)
            }
            if (remote.status == "done") {
                file.delete()
                repository.save(record.fromRemote(remote).copy(audioPath = ""))
                repository.enqueueUpload()
                Result.success()
            } else if (remote.status == "failed") {
                Result.failure()
            } else {
                Result.retry()
            }
        } catch (exc: Exception) {
            repository.save(record.copy(status = "failed", error = exc.message))
            Result.retry()
        } finally {
            RecentNotesWidget.updateAll(applicationContext)
        }
    }

    private fun RecordEntity.fromRemote(remote: RemoteRecord): RecordEntity {
        if (remote.status != "done") {
            return copy(
                remoteId = remote.id,
                status = remote.status,
                error = remote.error,
            )
        }
        return copy(
            remoteId = remote.id,
            title = remote.title.ifBlank { title },
            summary = remote.summary,
            content = remote.content,
            rawTranscript = listOf(rawTranscript, remote.raw_transcript)
                .filter { it.isNotBlank() }
                .joinToString("\n\n"),
            status = remote.status,
            error = remote.error,
            updatedAt = System.currentTimeMillis(),
        )
    }
}
