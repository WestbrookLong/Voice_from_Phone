package com.westbrook.flowmobile.ime

import android.content.Context

class FlowSettings(context: Context) {
    private val prefs = context.getSharedPreferences("flowmobile_settings", Context.MODE_PRIVATE)

    var spokenPunctuationEnabled: Boolean
        get() = prefs.getBoolean("spoken_punctuation_enabled", true)
        set(value) = prefs.edit().putBoolean("spoken_punctuation_enabled", value).apply()

    var englishCommandsEnabled: Boolean
        get() = prefs.getBoolean("english_commands_enabled", true)
        set(value) = prefs.edit().putBoolean("english_commands_enabled", value).apply()
}
