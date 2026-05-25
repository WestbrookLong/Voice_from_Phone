package com.westbrook.flowmobile.ime

import android.Manifest
import android.content.pm.PackageManager
import android.inputmethodservice.InputMethodService
import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection
import android.widget.Button
import android.widget.ImageButton
import android.widget.TextView
import android.widget.Toast
import com.westbrook.flowmobile.R
import java.util.Locale
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.RecognitionListener
import org.vosk.android.SpeechService
import org.vosk.android.StorageService

class FlowMobileImeService : InputMethodService(), RecognitionListener {
    private enum class KeyboardMode {
        Letters,
        Symbols,
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    private var model: Model? = null
    private var modelLoadError: String? = null
    private var isModelLoading = false
    private var speechService: SpeechService? = null
    private var isListening = false
    private var currentPreview = ""
    private var statusView: TextView? = null
    private var previewView: TextView? = null
    private var micButton: ImageButton? = null
    private var shiftButton: Button? = null
    private var modeButton: Button? = null
    private var keyBackspaceButton: Button? = null
    private var isShiftEnabled = false
    private var keyboardMode = KeyboardMode.Letters
    private val settings by lazy { FlowSettings(this) }
    private val characterButtons = linkedMapOf<Int, Button>()

    private val letterLayout =
        linkedMapOf(
            R.id.keyQ to "q",
            R.id.keyW to "w",
            R.id.keyE to "e",
            R.id.keyR to "r",
            R.id.keyT to "t",
            R.id.keyY to "y",
            R.id.keyU to "u",
            R.id.keyI to "i",
            R.id.keyO to "o",
            R.id.keyP to "p",
            R.id.keyA to "a",
            R.id.keyS to "s",
            R.id.keyD to "d",
            R.id.keyF to "f",
            R.id.keyG to "g",
            R.id.keyH to "h",
            R.id.keyJ to "j",
            R.id.keyK to "k",
            R.id.keyL to "l",
            R.id.keyZ to "z",
            R.id.keyX to "x",
            R.id.keyC to "c",
            R.id.keyV to "v",
            R.id.keyB to "b",
            R.id.keyN to "n",
            R.id.keyM to "m",
            R.id.keyComma to ",",
            R.id.keyPeriod to ".",
            R.id.keySlash to "/",
        )

    private val symbolLayout =
        linkedMapOf(
            R.id.keyQ to "1",
            R.id.keyW to "2",
            R.id.keyE to "3",
            R.id.keyR to "4",
            R.id.keyT to "5",
            R.id.keyY to "6",
            R.id.keyU to "7",
            R.id.keyI to "8",
            R.id.keyO to "9",
            R.id.keyP to "0",
            R.id.keyA to "@",
            R.id.keyS to "#",
            R.id.keyD to "$",
            R.id.keyF to "%",
            R.id.keyG to "&",
            R.id.keyH to "-",
            R.id.keyJ to "+",
            R.id.keyK to "(",
            R.id.keyL to ")",
            R.id.keyZ to "_",
            R.id.keyX to "=",
            R.id.keyC to ":",
            R.id.keyV to ";",
            R.id.keyB to "\"",
            R.id.keyN to "?",
            R.id.keyM to "!",
            R.id.keyComma to ",",
            R.id.keyPeriod to ".",
            R.id.keySlash to "/",
        )

    override fun onCreate() {
        super.onCreate()
        loadOfflineModel()
    }

    override fun onDestroy() {
        stopListeningLoop(resetPreview = true)
        speechService?.shutdown()
        speechService = null
        model?.close()
        model = null
        super.onDestroy()
    }

    override fun onCreateInputView(): View {
        val view = LayoutInflater.from(this).inflate(R.layout.input_view, null)
        statusView = view.findViewById(R.id.statusText)
        previewView = view.findViewById(R.id.previewText)
        micButton = view.findViewById<ImageButton>(R.id.micButton).apply {
            setOnClickListener {
                if (isListening) stopListeningLoop(resetPreview = true) else startListeningLoop()
            }
        }

        view.findViewById<ImageButton>(R.id.sendButton).setOnClickListener {
            executeCommand(VoiceCommand.Send)
        }
        view.findViewById<ImageButton>(R.id.backspaceButton).setOnClickListener {
            executeCommand(VoiceCommand.SingleBackspace)
        }

        shiftButton = view.findViewById<Button>(R.id.keyShift).apply {
            setOnClickListener {
                isShiftEnabled = !isShiftEnabled
                renderUi()
            }
        }
        modeButton = view.findViewById<Button>(R.id.keyMode).apply {
            setOnClickListener {
                keyboardMode =
                    if (keyboardMode == KeyboardMode.Letters) KeyboardMode.Symbols else KeyboardMode.Letters
                isShiftEnabled = false
                renderUi()
            }
        }
        keyBackspaceButton = view.findViewById<Button>(R.id.keyBackspace).apply {
            setOnClickListener {
                executeCommand(VoiceCommand.SingleBackspace)
            }
        }

        letterLayout.keys.forEach { keyId ->
            val button = view.findViewById<Button>(keyId)
            characterButtons[keyId] = button
            button.setOnClickListener {
                val value = it.tag?.toString().orEmpty()
                handleCharacterKey(value)
            }
        }

        view.findViewById<Button>(R.id.keySpace).setOnClickListener {
            currentInputConnection?.commitText(" ", 1)
        }
        view.findViewById<Button>(R.id.keyEnter).setOnClickListener {
            executeCommand(VoiceCommand.Send)
        }
        view.findViewById<Button>(R.id.keyDeleteWord).setOnClickListener {
            executeCommand(VoiceCommand.DeleteToBoundary)
        }

        renderUi()
        return view
    }

    override fun onStartInput(attribute: EditorInfo?, restarting: Boolean) {
        super.onStartInput(attribute, restarting)
        currentPreview = ""
        isShiftEnabled = false
        keyboardMode = KeyboardMode.Letters
        renderUi()
    }

    override fun onFinishInput() {
        super.onFinishInput()
        stopListeningLoop(resetPreview = true)
    }

    override fun onPartialResult(hypothesis: String?) {
        val transcript = extractVoskText(hypothesis, "partial") ?: return
        runOnMain {
            applyTranscript(transcript, isFinal = false)
        }
    }

    override fun onResult(hypothesis: String?) {
        val transcript = extractVoskText(hypothesis, "text") ?: return
        runOnMain {
            applyTranscript(transcript, isFinal = true)
        }
    }

    override fun onFinalResult(hypothesis: String?) {
        val transcript = extractVoskText(hypothesis, "text") ?: return
        runOnMain {
            applyTranscript(transcript, isFinal = true)
        }
    }

    override fun onError(exception: Exception?) {
        runOnMain {
            isListening = false
            updateStatus(getString(R.string.status_recognition_error, exception?.message ?: "unknown"))
            renderUi()
        }
    }

    override fun onTimeout() {
        runOnMain {
            isListening = false
            renderUi()
        }
    }

    private fun startListeningLoop() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            updateStatus(getString(R.string.status_mic_missing))
            toast(getString(R.string.status_mic_missing))
            return
        }

        val loadedModel = model
        if (loadedModel == null) {
            loadOfflineModel()
            val error = modelLoadError
            updateStatus(
                if (error == null) {
                    getString(R.string.status_model_loading)
                } else {
                    getString(R.string.status_model_failed, error)
                },
            )
            return
        }

        runCatching {
            speechService?.shutdown()
            val recognizer = Recognizer(loadedModel, 16000.0f)
            speechService = SpeechService(recognizer, 16000.0f)
            speechService?.startListening(this)
        }.onSuccess {
            isListening = true
            currentPreview = ""
            renderUi()
        }.onFailure {
            isListening = false
            updateStatus(getString(R.string.status_start_failed))
            toast(it.message ?: getString(R.string.status_start_failed))
            renderUi()
        }
    }

    private fun stopListeningLoop(resetPreview: Boolean) {
        isListening = false
        speechService?.stop()
        if (resetPreview) {
            currentPreview = ""
            currentInputConnection?.finishComposingText()
        }
        renderUi()
    }

    private fun loadOfflineModel() {
        if (model != null || isModelLoading) return

        isModelLoading = true
        modelLoadError = null
        updateStatus(getString(R.string.status_model_loading))
        StorageService.unpack(
            this,
            "model-cn",
            "model-cn",
            { loadedModel ->
                runOnMain {
                    model = loadedModel
                    isModelLoading = false
                    modelLoadError = null
                    renderUi()
                }
            },
            { exception ->
                runOnMain {
                    isModelLoading = false
                    modelLoadError = exception.message ?: exception.javaClass.simpleName
                    updateStatus(getString(R.string.status_model_failed, modelLoadError))
                }
            },
        )
    }

    private fun applyTranscript(rawTranscript: String, isFinal: Boolean) {
        val connection = currentInputConnection ?: return
        val processed = VoiceCommandProcessor.process(rawTranscript, settings)
        currentPreview = processed.previewText
        previewView?.text = processed.previewText.ifBlank { getString(R.string.preview_placeholder) }

        if (!isFinal) {
            connection.setComposingText(processed.previewText, 1)
            return
        }

        connection.finishComposingText()
        if (processed.previewText.isNotBlank()) {
            connection.commitText(processed.previewText, 1)
        }
        processed.commands.forEach(::executeCommand)
        currentPreview = ""
        renderUi()
    }

    private fun executeCommand(command: VoiceCommand) {
        val connection = currentInputConnection ?: return
        when (command) {
            VoiceCommand.Send -> performSend(connection)
            VoiceCommand.SingleBackspace -> connection.deleteSurroundingText(1, 0)
            VoiceCommand.DeleteToBoundary -> deleteToBoundary(connection)
            VoiceCommand.DeleteAll -> deleteAllBeforeCursor(connection)
        }
    }

    private fun handleCharacterKey(rawValue: String) {
        if (rawValue.isBlank()) return
        val connection = currentInputConnection ?: return
        val text =
            if (keyboardMode == KeyboardMode.Letters && isShiftEnabled && rawValue.length == 1 && rawValue[0].isLetter()) {
                rawValue.uppercase(Locale.getDefault())
            } else {
                rawValue
            }
        connection.commitText(text, 1)
        if (keyboardMode == KeyboardMode.Letters && isShiftEnabled && rawValue.length == 1 && rawValue[0].isLetter()) {
            isShiftEnabled = false
            renderUi()
        }
    }

    private fun performSend(connection: InputConnection) {
        val sent =
            sendDefaultEditorAction(true) ||
                connection.performEditorAction(EditorInfo.IME_ACTION_SEND) ||
                FlowAccessibilityService.requestSend()

        if (!sent) {
            connection.commitText("\n", 1)
        }
    }

    private fun deleteToBoundary(connection: InputConnection) {
        val before = connection.getTextBeforeCursor(160, 0)?.toString().orEmpty()
        if (before.isEmpty()) {
            connection.deleteSurroundingText(1, 0)
            return
        }
        val boundaryChars = ".,;:!?，。！？、；：\n"
        val reversed = before.reversed()
        val deleteCount =
            reversed.indexOfFirst { boundaryChars.contains(it) }.let { index ->
                if (index == -1) before.length else index
            }.coerceAtLeast(1)
        connection.deleteSurroundingText(deleteCount, 0)
    }

    private fun deleteAllBeforeCursor(connection: InputConnection) {
        var remaining = connection.getTextBeforeCursor(2000, 0)?.length ?: 0
        while (remaining > 0) {
            val step = minOf(remaining, 128)
            connection.deleteSurroundingText(step, 0)
            remaining -= step
        }
    }

    private fun extractVoskText(hypothesis: String?, key: String): String? {
        if (hypothesis.isNullOrBlank()) return null
        return runCatching {
            JSONObject(hypothesis).optString(key).trim().takeIf { it.isNotBlank() }
        }.getOrNull()
    }

    private fun updateStatus(text: String) {
        statusView?.text = text
    }

    private fun renderUi() {
        updateStatus(
            when {
                isListening -> getString(R.string.status_listening)
                isModelLoading -> getString(R.string.status_model_loading)
                modelLoadError != null -> getString(R.string.status_model_failed, modelLoadError)
                else -> getString(R.string.status_idle)
            },
        )
        previewView?.text = currentPreview.ifBlank { getString(R.string.preview_placeholder) }
        micButton?.setImageResource(if (isListening) R.drawable.ic_stop else R.drawable.ic_mic)
        micButton?.contentDescription =
            if (isListening) getString(R.string.stop_listening) else getString(R.string.start_listening)
        shiftButton?.text = if (isShiftEnabled) getString(R.string.shift_on) else getString(R.string.shift_off)
        modeButton?.text = if (keyboardMode == KeyboardMode.Letters) getString(R.string.mode_symbols) else getString(R.string.mode_letters)
        renderCharacterButtons()
        shiftButton?.visibility = if (keyboardMode == KeyboardMode.Letters) View.VISIBLE else View.INVISIBLE
    }

    private fun renderCharacterButtons() {
        val activeMap = if (keyboardMode == KeyboardMode.Letters) letterLayout else symbolLayout
        activeMap.forEach { (id, raw) ->
            val button = characterButtons[id] ?: return@forEach
            button.tag = raw
            button.text =
                if (keyboardMode == KeyboardMode.Letters && raw.length == 1 && raw[0].isLetter()) {
                    if (isShiftEnabled) raw.uppercase(Locale.getDefault()) else raw.lowercase(Locale.getDefault())
                } else {
                    raw
                }
        }
    }

    private fun runOnMain(action: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            action()
        } else {
            mainHandler.post(action)
        }
    }

    private fun toast(text: String) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show()
    }
}
