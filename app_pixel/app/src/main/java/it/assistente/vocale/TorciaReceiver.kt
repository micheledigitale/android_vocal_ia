package it.assistente.vocale

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager

/**
 * Accende o spegne la torcia su richiesta del Mac (adb non ha un comando
 * per farlo). Protetto dal permesso DUMP: solo la shell adb può inviarlo.
 */
class TorciaReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val accesa = intent.getBooleanExtra("accesa", true)
        val camere = context.getSystemService(CameraManager::class.java) ?: return
        val id = camere.cameraIdList.firstOrNull { id ->
            camere.getCameraCharacteristics(id)
                .get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
        } ?: run {
            resultCode = 0
            return
        }
        try {
            camere.setTorchMode(id, accesa)
            resultCode = 1
        } catch (e: Exception) {
            resultCode = 0
        }
    }
}
