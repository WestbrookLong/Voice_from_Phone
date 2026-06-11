package com.westbrook.chastream.mobile.ui

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import androidx.core.content.FileProvider
import com.westbrook.chastream.mobile.data.RecordEntity
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object NoteShare {
    fun toMarkdown(note: RecordEntity): String = buildString {
        append("# ").append(note.title.ifBlank { "新笔记" }).append("\n\n")
        if (note.summary.isNotBlank()) append("> ").append(note.summary).append("\n\n")
        if (note.content.isNotBlank()) append(note.content).append("\n")
        if (note.rawTranscript.isNotBlank()) {
            append("\n---\n\n## 完整转写\n\n").append(note.rawTranscript).append("\n")
        }
    }

    fun shareMarkdown(context: Context, notes: List<RecordEntity>) {
        val text = notes.joinToString("\n\n---\n\n", transform = ::toMarkdown)
        context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
            type = "text/markdown"
            putExtra(Intent.EXTRA_TEXT, text)
        }, "分享 Markdown"))
    }

    fun shareLongImage(context: Context, note: RecordEntity) {
        val lines = wrap(
            listOfNotNull(
                note.title.ifBlank { "新笔记" },
                note.summary.takeIf { it.isNotBlank() },
                note.content.takeIf { it.isNotBlank() },
                note.rawTranscript.takeIf { it.isNotBlank() }?.let { "完整转写\n$it" },
                SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(Date(note.updatedAt)),
            ).joinToString("\n\n"),
            26,
        )
        val width = 1080
        val padding = 72
        val lineHeight = 58
        val height = (padding * 2 + lines.size * lineHeight).coerceAtMost(16000)
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        canvas.drawColor(Color.rgb(250, 248, 255))
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(35, 31, 47)
            textSize = 38f
        }
        var y = padding + 38f
        lines.forEachIndexed { index, line ->
            if (y < height - padding) {
                if (index == 0) {
                    paint.textSize = 52f
                    paint.isFakeBoldText = true
                } else {
                    paint.textSize = 38f
                    paint.isFakeBoldText = false
                }
                canvas.drawText(line, padding.toFloat(), y, paint)
                y += lineHeight
            }
        }
        val directory = File(context.cacheDir, "shares").apply { mkdirs() }
        val file = File(directory, "chastream-note-${note.id}.png")
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 95, it) }
        bitmap.recycle()
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
        context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
            type = "image/png"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }, "分享长截图"))
    }

    private fun wrap(value: String, length: Int): List<String> =
        value.lines().flatMap { line ->
            if (line.isEmpty()) listOf("") else line.chunked(length)
        }
}
