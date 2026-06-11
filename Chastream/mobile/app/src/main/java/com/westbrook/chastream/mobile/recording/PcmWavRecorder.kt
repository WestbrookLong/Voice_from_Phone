package com.westbrook.chastream.mobile.recording

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.File
import java.io.RandomAccessFile
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

class PcmWavRecorder {
    private val sampleRate = 16_000
    private val running = AtomicBoolean(false)
    private var recorder: AudioRecord? = null
    private var thread: Thread? = null

    @SuppressLint("MissingPermission")
    fun start(output: File) {
        check(!running.get()) { "Recorder is already running." }
        output.parentFile?.mkdirs()
        val minimum = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val audioRecord = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            minimum * 2,
        )
        check(audioRecord.state == AudioRecord.STATE_INITIALIZED) {
            "无法初始化麦克风。"
        }
        recorder = audioRecord
        running.set(true)
        audioRecord.startRecording()
        thread = thread(name = "chastream-recorder") {
            RandomAccessFile(output, "rw").use { file ->
                file.setLength(0)
                file.write(ByteArray(44))
                val buffer = ByteArray(minimum)
                var pcmBytes = 0L
                while (running.get()) {
                    val read = audioRecord.read(buffer, 0, buffer.size)
                    if (read > 0) {
                        file.write(buffer, 0, read)
                        pcmBytes += read
                    }
                }
                writeHeader(file, pcmBytes)
            }
        }
    }

    fun stop() {
        if (!running.getAndSet(false)) return
        recorder?.stop()
        thread?.join(5_000)
        recorder?.release()
        recorder = null
        thread = null
    }

    private fun writeHeader(file: RandomAccessFile, pcmBytes: Long) {
        val byteRate = sampleRate * 2
        file.seek(0)
        file.writeBytes("RIFF")
        writeInt(file, (pcmBytes + 36).toInt())
        file.writeBytes("WAVEfmt ")
        writeInt(file, 16)
        writeShort(file, 1)
        writeShort(file, 1)
        writeInt(file, sampleRate)
        writeInt(file, byteRate)
        writeShort(file, 2)
        writeShort(file, 16)
        file.writeBytes("data")
        writeInt(file, pcmBytes.toInt())
    }

    private fun writeInt(file: RandomAccessFile, value: Int) {
        file.write(value and 0xff)
        file.write(value shr 8 and 0xff)
        file.write(value shr 16 and 0xff)
        file.write(value shr 24 and 0xff)
    }

    private fun writeShort(file: RandomAccessFile, value: Int) {
        file.write(value and 0xff)
        file.write(value shr 8 and 0xff)
    }
}
