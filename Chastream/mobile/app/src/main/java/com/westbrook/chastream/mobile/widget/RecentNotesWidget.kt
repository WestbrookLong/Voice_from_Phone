package com.westbrook.chastream.mobile.widget

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.LocalSize
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import com.westbrook.chastream.mobile.ChastreamApplication
import com.westbrook.chastream.mobile.MainActivity
import com.westbrook.chastream.mobile.data.RecordEntity
import com.westbrook.chastream.mobile.ui.DetailActivity
import com.westbrook.chastream.mobile.ui.QuickRecordActivity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

class RecentNotesWidget : GlanceAppWidget() {
    private val noteIdKey = ActionParameters.Key<String>("noteId")
    private val isNewKey = ActionParameters.Key<Boolean>("isNew")
    private val autoStartKey = ActionParameters.Key<Boolean>("autoStart")
    private val sourceKey = ActionParameters.Key<String>("source")
    private val kindKey = ActionParameters.Key<String>("kind")

    override val sizeMode = SizeMode.Responsive(
        setOf(
            DpSize(180.dp, 120.dp),
            DpSize(250.dp, 180.dp),
            DpSize(250.dp, 280.dp),
            DpSize(320.dp, 380.dp),
        ),
    )

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val app = context.applicationContext as ChastreamApplication
        val notes = app.repository.recentNotes(10)
        provideContent { WidgetContent(notes) }
    }

    @Composable
    private fun WidgetContent(notes: List<RecordEntity>) {
        val height = LocalSize.current.height
        val count = when {
            height < 160.dp -> 1
            height < 240.dp -> 2
            height < 340.dp -> 4
            else -> 6
        }
        val pending = notes.count { it.status !in setOf("done", "manual") }
        Column(
            modifier = GlanceModifier.fillMaxSize()
                .background(ColorProvider(Color(0xFFF7F3FF)))
                .padding(14.dp),
        ) {
            Row(
                modifier = GlanceModifier.fillMaxWidth().clickable(actionStartActivity<MainActivity>()),
                verticalAlignment = Alignment.Vertical.CenterVertically,
            ) {
                Column {
                    Text(
                        "最近想法",
                        style = TextStyle(
                            color = ColorProvider(Color(0xFF242031)),
                            fontWeight = FontWeight.Bold,
                        ),
                    )
                    Text(
                        "快速查看你的最新记录",
                        style = TextStyle(color = ColorProvider(Color(0xFF888198))),
                    )
                }
                Spacer(GlanceModifier.defaultWeight())
                if (pending > 0) {
                    Text(
                        "未整理 $pending",
                        modifier = GlanceModifier.background(ColorProvider(Color(0xFFEDE7FF))).padding(7.dp),
                        style = TextStyle(color = ColorProvider(Color(0xFF674DCD))),
                    )
                }
            }
            Spacer(GlanceModifier.height(8.dp))
            notes.take(count).forEach { note ->
                Column(
                    modifier = GlanceModifier.fillMaxWidth()
                        .background(ColorProvider(Color(0xFFFFFFFF)))
                        .padding(10.dp)
                        .clickable(
                            actionStartActivity<DetailActivity>(
                                actionParametersOf(noteIdKey to note.id),
                            ),
                        ),
                ) {
                    Row(GlanceModifier.fillMaxWidth()) {
                        Text(
                            note.title.ifBlank { fallbackTitle(note) },
                            modifier = GlanceModifier.defaultWeight(),
                            maxLines = 1,
                            style = TextStyle(
                                color = ColorProvider(Color(0xFF2E293A)),
                                fontWeight = FontWeight.Bold,
                            ),
                        )
                        Text(
                            SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(note.updatedAt)),
                            style = TextStyle(color = ColorProvider(Color(0xFF9A94A7))),
                        )
                    }
                    if (note.summary.isNotBlank()) {
                        Text(
                            note.summary,
                            maxLines = 2,
                            style = TextStyle(color = ColorProvider(Color(0xFF716A7E))),
                        )
                    }
                }
                Spacer(GlanceModifier.height(7.dp))
            }
            Spacer(GlanceModifier.defaultWeight())
            Row(GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.Vertical.CenterVertically) {
                Text(
                    "＋",
                    modifier = GlanceModifier.size(44.dp)
                        .background(ColorProvider(Color(0xFFE9E3FF)))
                        .padding(12.dp)
                        .clickable(
                            actionStartActivity<DetailActivity>(
                                actionParametersOf(
                                    noteIdKey to UUID.randomUUID().toString(),
                                    isNewKey to true,
                                ),
                            ),
                        ),
                    style = TextStyle(
                        color = ColorProvider(Color(0xFF674DCD)),
                        fontWeight = FontWeight.Bold,
                    ),
                )
                Spacer(GlanceModifier.defaultWeight())
                Text(
                    "🎙",
                    modifier = GlanceModifier.size(52.dp)
                        .background(ColorProvider(Color(0xFF6C50D7)))
                        .padding(14.dp)
                        .clickable(
                            actionStartActivity<QuickRecordActivity>(
                                actionParametersOf(
                                    autoStartKey to true,
                                    sourceKey to "widget",
                                    kindKey to "quick_note",
                                ),
                            ),
                        ),
                    style = TextStyle(color = ColorProvider(Color.White)),
                )
            }
        }
    }

    private fun fallbackTitle(note: RecordEntity): String =
        note.summary.ifBlank { note.content }.trim().replace("\n", " ").take(10).ifBlank { "新笔记" }

    companion object {
        suspend fun updateAll(context: Context) {
            val manager = GlanceAppWidgetManager(context)
            manager.getGlanceIds(RecentNotesWidget::class.java).forEach { id ->
                RecentNotesWidget().update(context, id)
            }
        }
    }
}
