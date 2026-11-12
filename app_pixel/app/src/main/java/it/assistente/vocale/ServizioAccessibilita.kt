package it.assistente.vocale

import android.Manifest
import android.accessibilityservice.AccessibilityService
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * Servizio di accessibilità (come TalkBack): vede i pulsanti e i campi sullo
 * schermo e sa scrivere in un campo qualunque testo, accenti compresi.
 *
 * Il Mac lo comanda con `am broadcast -a it.assistente.vocale.ACCESSIBILITA`.
 * Il ricevitore richiede il permesso DUMP, che ha solo la shell adb: le altre
 * app del telefono non possono usarlo. La risposta torna nel "data" del
 * broadcast come JSON in base64.
 */
class ServizioAccessibilita : AccessibilityService() {

    private var registrato = false

    private val ricevitore = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val risposta = try {
                esegui(intent)
            } catch (e: Exception) {
                Log.w(TAG, "Comando non riuscito", e)
                null
            }
            if (risposta == null) {
                resultCode = 2
                return
            }
            resultCode = 1
            resultData = Base64.encodeToString(
                risposta.toString().toByteArray(Charsets.UTF_8), Base64.NO_WRAP
            )
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        val filtro = IntentFilter(AZIONE)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(ricevitore, filtro, Manifest.permission.DUMP, null, Context.RECEIVER_EXPORTED)
        } else {
            registerReceiver(ricevitore, filtro, Manifest.permission.DUMP, null)
        }
        registrato = true
    }

    override fun onDestroy() {
        if (registrato) {
            unregisterReceiver(ricevitore)
            registrato = false
        }
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    private fun esegui(intent: Intent): JSONObject? =
        when (intent.getStringExtra("comando")) {
            "ping" -> JSONObject()
            "albero" -> albero()
            "scrivi" -> scrivi(
                decodifica(intent.getStringExtra("testo")),
                decodifica(intent.getStringExtra("modo")) != "aggiungi",
            )
            else -> null
        }

    private fun decodifica(base64: String?): String =
        if (base64 == null) "" else String(Base64.decode(base64, Base64.DEFAULT), Charsets.UTF_8)

    // --- Lettura dello schermo ---------------------------------------------

    private fun radice(): AccessibilityNodeInfo? =
        rootInActiveWindow ?: windows.firstOrNull { it.type == android.view.accessibility.AccessibilityWindowInfo.TYPE_APPLICATION }?.root

    private fun albero(): JSONObject {
        val nodi = JSONArray()
        radice()?.let { visita(it, nodi, 0) }
        return JSONObject().put("nodi", nodi)
    }

    private fun visita(nodo: AccessibilityNodeInfo, nodi: JSONArray, profondita: Int) {
        if (profondita > 80 || nodi.length() >= 2000) return
        if (nodo.isVisibleToUser) nodi.put(descrivi(nodo))
        for (i in 0 until nodo.childCount) {
            val figlio = nodo.getChild(i) ?: continue
            visita(figlio, nodi, profondita + 1)
        }
    }

    private fun descrivi(nodo: AccessibilityNodeInfo): JSONObject {
        val bordi = Rect().also { nodo.getBoundsInScreen(it) }
        val mostraSuggerimento = Build.VERSION.SDK_INT >= 26 && nodo.isShowingHintText
        return JSONObject().apply {
            if (!mostraSuggerimento) nodo.text?.let { put("t", it.toString()) }
            nodo.contentDescription?.let { put("d", it.toString()) }
            if (Build.VERSION.SDK_INT >= 26) nodo.hintText?.let { put("h", it.toString()) }
            nodo.viewIdResourceName?.let { put("id", it) }
            nodo.className?.let { put("c", it.toString()) }
            nodo.packageName?.let { put("p", it.toString()) }
            put("b", JSONArray(listOf(bordi.left, bordi.top, bordi.right, bordi.bottom)))
            if (nodo.isClickable) put("k", 1)
            if (nodo.isLongClickable) put("lk", 1)
            if (nodo.isEditable) put("e", 1)
            if (nodo.isFocused) put("f", 1)
            if (nodo.isFocusable) put("fo", 1)
            if (nodo.isScrollable) put("s", 1)
            if (nodo.isCheckable) put("ch", 1)
            if (nodo.isChecked) put("ck", 1)
            if (nodo.isSelected) put("se", 1)
            if (!nodo.isEnabled) put("en", 0)
        }
    }

    // --- Scrittura ---------------------------------------------------------

    private fun scrivi(testo: String, sostituisci: Boolean): JSONObject {
        val radice = radice() ?: return JSONObject().put("ok", false)
        val campo = radice.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)?.takeIf { it.isEditable }
            ?: primoCampo(radice)
            ?: return JSONObject().put("ok", false)
        val mostraSuggerimento = Build.VERSION.SDK_INT >= 26 && campo.isShowingHintText
        val attuale = if (mostraSuggerimento) "" else campo.text?.toString().orEmpty()
        val nuovo = if (sostituisci) testo else attuale + testo
        val argomenti = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, nuovo)
        }
        val ok = campo.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, argomenti)
        return JSONObject().put("ok", ok)
    }

    private fun primoCampo(nodo: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (nodo.isEditable && nodo.isVisibleToUser) return nodo
        for (i in 0 until nodo.childCount) {
            val trovato = nodo.getChild(i)?.let { primoCampo(it) }
            if (trovato != null) return trovato
        }
        return null
    }

    companion object {
        private const val TAG = "Assistente"
        const val AZIONE = "it.assistente.vocale.ACCESSIBILITA"
    }
}
