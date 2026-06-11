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
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import com.westbrook.chastream.mobile.ChastreamApplication
import com.westbrook.chastream.mobile.MainActivity
import com.westbrook.chastream.mobile.data.RecordEntity
import com.westbrook.chastream.mobile.ui.DetailActivity
import com.westbrook.chastream.mobile.ui.QuickRecordActivity

class RecentNotesWidget : GlanceAppWidget() {
    private val noteIdKey = ActionParameters.Key<String>("noteId")
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
            height < 160.dp -> 2
            height < 240.dp -> 4
            height < 340.dp -> 6
            else -> 8
        }
        val pending = notes.count { it.status != "done" }
        Column(
            modifier = GlanceModifier.fillMaxSize()
                .background(ColorProvider(Color(0xFF17211C)))
                .padding(14.dp),
        ) {
            Row(
                modifier = GlanceModifier.fillMaxWidth().clickable(
                    actionStartActivity<MainActivity>(),
                ),
                horizontalAlignment = Alignment.Horizontal.CenterHorizontally,
            ) {
                Text(
                    "最近想法",
                    style = TextStyle(
                        color = ColorProvider(Color(0xFFE7EFEA)),
                        fontWeight = FontWeight.Bold,
                    ),
                )
                Spacer(GlanceModifier.defaultWeight())
                Text(
                    "未整理 $pending",
                    style = TextStyle(color = ColorProvider(Color(0xFF83C798))),
                )
            }
            Spacer(GlanceModifier.height(8.dp))
            notes.take(count).forEach { note ->
                Text(
                    note.summary.ifBlank {
                        if (note.status == "failed") "处理失败，点击查看" else "正在整理…"
                    },
                    modifier = GlanceModifier.fillMaxWidth()
                        .padding(vertical = 5.dp)
                        .clickable(
                            actionStartActivity<DetailActivity>(
                                actionParametersOf(noteIdKey to note.id),
                            ),
                        ),
                    maxLines = 2,
                    style = TextStyle(color = ColorProvider(Color(0xFFD6E1DA))),
                )
            }
            Spacer(GlanceModifier.defaultWeight())
            Text(
                "🎙 快速录音",
                modifier = GlanceModifier.fillMaxWidth()
                    .background(ColorProvider(Color(0xFF244331)))
                    .padding(10.dp)
                    .clickable(
                        actionStartActivity<QuickRecordActivity>(
                            actionParametersOf(
                                autoStartKey to true,
                                sourceKey to "widget",
                                kindKey to "quick_note",
                            ),
                        ),
                    ),
                style = TextStyle(
                    color = ColorProvider(Color(0xFF7DE3A0)),
                    fontWeight = FontWeight.Bold,
                ),
            )
        }
    }

    companion object {
        suspend fun updateAll(context: Context) {
            val manager = GlanceAppWidgetManager(context)
            manager.getGlanceIds(RecentNotesWidget::class.java).forEach { id ->
                RecentNotesWidget().update(context, id)
            }
        }
    }
}
