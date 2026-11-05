package it.assistente.vocale

import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent

/**
 * Riceve dal Mac un testo e lo mette negli appunti, così il Mac può incollarlo.
 * Serve perché `adb shell input text` non sa scrivere lettere accentate.
 * Protetto dal permesso DUMP: solo la shell adb può inviarlo.
 */
class IncollaReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val testo = intent.getStringExtra("testo") ?: return
        val appunti = context.getSystemService(ClipboardManager::class.java) ?: return
        appunti.setPrimaryClip(ClipData.newPlainText("assistente", testo))
        resultCode = 1
    }
}
