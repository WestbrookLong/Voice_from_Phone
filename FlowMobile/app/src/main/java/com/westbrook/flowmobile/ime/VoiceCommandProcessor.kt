package com.westbrook.flowmobile.ime

import java.util.Locale

enum class VoiceCommand {
    Send,
    SingleBackspace,
    DeleteToBoundary,
    DeleteAll,
}

data class ProcessedTranscript(
    val previewText: String,
    val commands: List<VoiceCommand>,
)

object VoiceCommandProcessor {
    private val trailingCommandPattern =
        Regex(
            pattern = "(?is)^(.*?)(?:\\s*)((delete\\s+all|back\\s*space|back|enter))\\s*$",
        )

    private val spokenPunctuation = mapOf(
        "comma" to ",",
        "period" to ".",
        "full stop" to ".",
        "question mark" to "?",
        "exclamation mark" to "!",
        "colon" to ":",
        "semicolon" to ";",
        "left parenthesis" to "(",
        "right parenthesis" to ")",
    )

    fun process(input: String, settings: FlowSettings): ProcessedTranscript {
        var working = input.trim()
        val commands = mutableListOf<VoiceCommand>()

        if (settings.englishCommandsEnabled) {
            val commandMatch = trailingCommandPattern.matchEntire(working)
            if (commandMatch != null) {
                working = commandMatch.groupValues[1].trimEnd()
                when (commandMatch.groupValues[2].lowercase(Locale.US).replace("\\s+".toRegex(), " ")) {
                    "enter" -> commands += VoiceCommand.Send
                    "back" -> commands += VoiceCommand.SingleBackspace
                    "backspace", "back space" -> commands += VoiceCommand.DeleteToBoundary
                    "delete all" -> commands += VoiceCommand.DeleteAll
                }
            }
        }

        if (settings.spokenPunctuationEnabled) {
            working = convertSpokenPunctuation(working)
        }

        return ProcessedTranscript(previewText = working, commands = commands)
    }

    private fun convertSpokenPunctuation(text: String): String {
        var output = text
        spokenPunctuation.forEach { (spoken, literal) ->
            output = output.replace("\\b${Regex.escape(spoken)}\\b".toRegex(RegexOption.IGNORE_CASE), literal)
        }
        return output
    }
}
