package it.assistente.vocale

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Registra la voce dal microfono e la restituisce come file WAV in memoria. */
class Registratore {

    companion object {
        const val FREQUENZA = 16_000
        private const val SECONDI_MASSIMI = 30
    }

    @Volatile private var attivo = false
    private var thread: Thread? = null
    private val pcm = ByteArrayOutputStream()

    val staRegistrando: Boolean get() = attivo

    @SuppressLint("MissingPermission") // Il permesso è controllato da MainActivity.
    fun avvia() {
        if (attivo) return
        val minimo = AudioRecord.getMinBufferSize(
            FREQUENZA, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        val registratore = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            FREQUENZA,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minimo, FREQUENZA),
        )
        synchronized(pcm) { pcm.reset() }
        attivo = true
        registratore.startRecording()
        thread = Thread {
            val buffer = ByteArray(maxOf(minimo, 4096))
            val limite = FREQUENZA * 2 * SECONDI_MASSIMI
            try {
                while (attivo) {
                    val letti = registratore.read(buffer, 0, buffer.size)
                    if (letti > 0) {
                        synchronized(pcm) {
                            if (pcm.size() < limite) pcm.write(buffer, 0, letti)
                        }
                    }
                }
            } finally {
                registratore.stop()
                registratore.release()
            }
        }.also { it.start() }
    }

    /** Ferma la registrazione e restituisce l'audio in formato WAV. */
    fun ferma(): ByteArray {
        attivo = false
        thread?.join(1000)
        thread = null
        val dati = synchronized(pcm) { pcm.toByteArray() }
        return wav(dati)
    }

    fun durataSecondi(wav: ByteArray): Double = (wav.size - 44).coerceAtLeast(0) / (FREQUENZA * 2.0)

    private fun wav(pcm: ByteArray): ByteArray {
        val intestazione = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray())
            putInt(36 + pcm.size)
            put("WAVE".toByteArray())
            put("fmt ".toByteArray())
            putInt(16) // Dimensione del blocco fmt.
            putShort(1) // PCM.
            putShort(1) // Mono.
            putInt(FREQUENZA)
            putInt(FREQUENZA * 2) // Byte al secondo.
            putShort(2) // Byte per campione.
            putShort(16) // Bit per campione.
            put("data".toByteArray())
            putInt(pcm.size)
        }
        return intestazione.array() + pcm
    }
}
