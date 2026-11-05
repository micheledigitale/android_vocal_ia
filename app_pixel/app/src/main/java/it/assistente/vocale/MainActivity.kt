package it.assistente.vocale

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.util.TypedValue
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityManager
import android.widget.LinearLayout
import android.widget.TextView
import java.util.Locale
import java.util.concurrent.Executors

/**
 * Una sola schermata: un pulsante enorme.
 *
 * Senza TalkBack: tieni premuto mentre parli, al rilascio parte il comando.
 * Con TalkBack: tocca due volte per iniziare, tocca due volte per finire.
 */
class MainActivity : Activity(), TextToSpeech.OnInitListener {

    private enum class Stato { PRONTO, ASCOLTO, LAVORO }

    private val registratore = Registratore()
    private val client = ClientMac()
    private val esecutore = Executors.newSingleThreadExecutor()
    private val principale = Handler(Looper.getMainLooper())
    private var voce: TextToSpeech? = null
    private var vocePronta = false
    private var toni: ToneGenerator? = null
    private var stato = Stato.PRONTO

    private lateinit var pulsante: TextView
    private lateinit var risposta: TextView
    private lateinit var accessibilita: AccessibilityManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        accessibilita = getSystemService(AccessibilityManager::class.java)
        voce = TextToSpeech(this, this)
        toni = try {
            ToneGenerator(AudioManager.STREAM_MUSIC, 80)
        } catch (e: RuntimeException) {
            null
        }
        setContentView(costruisciInterfaccia())
        aggiorna(Stato.PRONTO)
        chiediMicrofono()
    }

    override fun onDestroy() {
        super.onDestroy()
        voce?.shutdown()
        toni?.release()
        esecutore.shutdownNow()
    }

    override fun onInit(esito: Int) {
        if (esito == TextToSpeech.SUCCESS) {
            voce?.language = Locale.ITALIAN
            vocePronta = true
        }
    }

    // --- Interfaccia ------------------------------------------------------

    @SuppressLint("ClickableViewAccessibility")
    private fun costruisciInterfaccia(): View {
        val margine = dp(16)
        pulsante = TextView(this).apply {
            gravity = Gravity.CENTER
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 36f)
            setTextColor(Color.BLACK)
            setPadding(margine, margine, margine, margine)
            isClickable = true
            isFocusable = true
            setOnTouchListener { v, evento -> tocco(v, evento) }
            setOnClickListener { clicConTalkBack() }
        }
        risposta = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f)
            setTextColor(Color.WHITE)
            setPadding(margine, margine, margine, margine)
            gravity = Gravity.CENTER_HORIZONTAL
        }
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.BLACK)
            setPadding(margine, margine * 2, margine, margine)
            addView(
                pulsante,
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
                    .apply { bottomMargin = margine },
            )
            addView(
                risposta,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                ),
            )
        }
    }

    private fun aggiorna(nuovo: Stato) {
        stato = nuovo
        val talkBack = accessibilita.isTouchExplorationEnabled
        val (testo, colore) = when (nuovo) {
            Stato.PRONTO -> getString(
                if (talkBack) R.string.pulsante_pronto_talkback else R.string.pulsante_pronto
            ) to Color.rgb(255, 214, 0)
            Stato.ASCOLTO -> getString(
                if (talkBack) R.string.pulsante_ascolto_talkback else R.string.pulsante_ascolto
            ) to Color.rgb(255, 82, 82)
            Stato.LAVORO -> getString(R.string.pulsante_lavoro) to Color.rgb(120, 120, 120)
        }
        pulsante.text = testo
        pulsante.contentDescription = testo
        pulsante.setBackgroundColor(colore)
    }

    private fun dp(valore: Int): Int =
        TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP, valore.toFloat(), resources.displayMetrics
        ).toInt()

    // --- Gesti ------------------------------------------------------------

    private fun tocco(v: View, evento: MotionEvent): Boolean {
        // Con TalkBack attivo i tocchi passano dal clic (doppio tocco).
        if (accessibilita.isTouchExplorationEnabled) return false
        when (evento.actionMasked) {
            MotionEvent.ACTION_DOWN -> iniziaAscolto(v)
            MotionEvent.ACTION_UP -> {
                v.performClick()
                fineAscolto(v)
            }
            MotionEvent.ACTION_CANCEL -> fineAscolto(v)
        }
        return true
    }

    private fun clicConTalkBack() {
        if (!accessibilita.isTouchExplorationEnabled) return
        when (stato) {
            Stato.PRONTO -> iniziaAscolto(pulsante)
            Stato.ASCOLTO -> fineAscolto(pulsante)
            Stato.LAVORO -> Unit
        }
    }

    private fun iniziaAscolto(v: View) {
        if (stato != Stato.PRONTO) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            parla(getString(R.string.permesso_microfono))
            chiediMicrofono()
            return
        }
        voce?.stop()
        v.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        toni?.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
        // Aspetta la fine del bip, altrimenti finisce nella registrazione.
        principale.postDelayed({ if (stato == Stato.ASCOLTO) registratore.avvia() }, 150)
        aggiorna(Stato.ASCOLTO)
    }

    private fun fineAscolto(v: View) {
        if (stato != Stato.ASCOLTO) return
        v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
        toni?.startTone(ToneGenerator.TONE_PROP_ACK, 120)
        aggiorna(Stato.LAVORO)
        esecutore.execute {
            val wav = registratore.ferma()
            val frase = if (registratore.durataSecondi(wav) < 0.4) {
                getString(R.string.audio_troppo_corto)
            } else {
                client.inviaComando(wav) ?: getString(R.string.mac_non_raggiungibile)
            }
            principale.post {
                risposta.text = frase
                aggiorna(Stato.PRONTO)
                parla(frase)
            }
        }
    }

    // --- Voce e permessi --------------------------------------------------

    private fun parla(frase: String) {
        if (vocePronta) {
            voce?.speak(frase, TextToSpeech.QUEUE_FLUSH, null, "risposta")
        } else {
            pulsante.announceForAccessibility(frase)
        }
    }

    private fun chiediMicrofono() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }
    }
}
