package it.assistente.vocale

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Manda l'audio al Mac. Il telefono parla con il proprio localhost: il comando
 * `adb reverse` (eseguito dal Mac all'avvio) lo porta fino al Mac via USB.
 */
class ClientMac(private val indirizzo: String = "http://127.0.0.1:8765") {

    /** Restituisce la frase da leggere, oppure null se il Mac non risponde. */
    fun inviaComando(wav: ByteArray): String? {
        val connessione = URL("$indirizzo/comando").openConnection() as HttpURLConnection
        return try {
            connessione.requestMethod = "POST"
            connessione.doOutput = true
            connessione.connectTimeout = 3_000
            // L'agente che usa lo schermo può impiegare più di un minuto.
            connessione.readTimeout = 180_000
            connessione.setRequestProperty("Content-Type", "audio/wav")
            connessione.setFixedLengthStreamingMode(wav.size)
            connessione.outputStream.use { it.write(wav) }
            if (connessione.responseCode != 200) return null
            val corpo = connessione.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            JSONObject(corpo).optString("risposta", "")
        } catch (e: Exception) {
            null
        } finally {
            connessione.disconnect()
        }
    }

    /** Frasi di avanzamento a partire dalla numero `da` (vuota se errore). */
    fun avanzamento(da: Int): List<String> {
        val connessione = URL("$indirizzo/avanzamento?da=$da").openConnection() as HttpURLConnection
        return try {
            connessione.connectTimeout = 1_000
            connessione.readTimeout = 2_000
            if (connessione.responseCode != 200) return emptyList()
            val corpo = connessione.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            val frasi = JSONObject(corpo).optJSONArray("frasi") ?: return emptyList()
            List(frasi.length()) { frasi.optString(it) }
        } catch (e: Exception) {
            emptyList()
        } finally {
            connessione.disconnect()
        }
    }

    fun raggiungibile(): Boolean {
        val connessione = URL("$indirizzo/stato").openConnection() as HttpURLConnection
        return try {
            connessione.connectTimeout = 2_000
            connessione.readTimeout = 2_000
            connessione.responseCode == 200
        } catch (e: Exception) {
            false
        } finally {
            connessione.disconnect()
        }
    }
}
