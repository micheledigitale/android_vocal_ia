# Assistente vocale per Pixel

Un assistente in italiano per persone non vedenti o con disabilità gravi:
**tieni premuto il pulsante sul Pixel, parla, rilascia**. Il Mac capisce la
richiesta con un modello su OpenRouter e comanda il telefono via cavo.

```
Pixel: app "Assistente"           Mac: python -m assistente            OpenRouter
[tieni premuto] → registra  ──USB──► server :8765 ──audio + strumenti──► gemini-2.5-flash
[rilascia]                          │◄──────────── strumento scelto ────┘
                                    ├─ comando diretto (adb): chiama, SMS, Wi-Fi…
                                    └─ agente M3A di AndroidWorld: guarda lo schermo e tocca
risposta letta a voce  ◄──USB───────┘
```

## Cosa sa fare

| Area | Esempi di frasi | Come lo fa |
|---|---|---|
| Telefonate | "Chiama Mario Rossi", "Chiama il 333 1234567", "Riattacca" | diretto |
| Chi ha chiamato | "Chi mi ha chiamato?", "Ho chiamate perse?" | diretto |
| SMS | "Manda un messaggio a Mario Rossi con scritto ciao come stai" | apre Messaggi già compilato e preme Invia, **senza conferma** |
| Leggere SMS | "Leggimi gli ultimi messaggi", "Cosa mi ha scritto Anna?" | diretto |
| Contatti | "Aggiungi Luca Neri, numero 347…" | modulo compilato + agente preme Salva |
| Notifiche | "Che notifiche ho?" | diretto |
| Calendario | "Cosa ho domani?", "Metti dentista giovedì alle 15" | lettura diretta, creazione con agente |
| Gmail e altro | "Leggimi l'ultima email", "Rispondi a Paolo che va bene" | agente sullo schermo |
| Impostazioni | Wi-Fi, Bluetooth, volume, luminosità, Non disturbare | diretto |
| App | "Apri WhatsApp" | diretto |
| Schermo | "Cosa c'è sullo schermo?" | screenshot descritto dal modello |

Se il nome è ambiguo (due "Mario" in rubrica) o non esiste, l'assistente lo
dice e chiede quale: non tira a indovinare. Ricorda il discorso per 3 minuti,
quindi basta rispondere "Rossi".

## Preparazione (una volta sola)

### 1. Sul Mac

```bash
brew install android-platform-tools python@3.11   # solo adb, niente Android Studio
cd android_vocal_ia
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r assistente/requirements.txt
export OPENROUTER_API_KEY=sk-or-...          # mettilo anche in ~/.zshrc
```

### 2. Sul Pixel

1. Impostazioni › Info telefono › tocca 7 volte **Numero build**.
2. Impostazioni › Sistema › Opzioni sviluppatore › attiva **Debug USB**.
3. Collega il cavo e accetta "Consentire debug USB?" (spunta "Consenti sempre").
4. Sul Mac controlla: `adb devices` deve mostrare il telefono come `device`.

### 3. Installa l'app

Scarica `assistente-apk` dall'ultima esecuzione di **App Pixel (APK)** nella
scheda *Actions* di GitHub, estrai lo zip e:

```bash
adb install -r app-debug.apk
```

Apri l'app "Assistente" e concedi il microfono.

## Uso

```bash
python -m assistente --controlla       # verifica collegamento e permessi
python -m assistente "alza il volume"  # prova un comando scritto, senza voce
python -m assistente                   # avvia il server per l'app
```

Con il server avviato: sul Pixel tieni premuto il pulsante giallo, parla,
rilascia. Senti un bip all'inizio e uno alla fine, poi la risposta a voce.
Con **TalkBack** attivo: doppio tocco per iniziare, doppio tocco per finire.

Variabili utili: `ASSISTENTE_MODELLO` (default `google/gemini-2.5-flash`),
`ASSISTENTE_SERIALE` (se hai più telefoni), `ASSISTENTE_PORTA` (8765),
`ASSISTENTE_MAX_PASSI` (passi massimi dell'agente, 15).

## Cose da sapere

- **Nessuna conferma**: SMS e chiamate partono subito, come richiesto.
- Le richieste (audio, screenshot, testo di SMS e notifiche) vengono inviate
  a OpenRouter e al modello scelto.
- L'agente sullo schermo è lento: qualche secondo per ogni passo.
- Mai lanciare `run.py`, `minimal_task_runner.py` o `--perform_emulator_setup`
  sul telefono personale: il benchmark di AndroidWorld cancella contatti e SMS.

## Da verificare martedì sul telefono vero

Il codice è testato con un telefono simulato, non ancora su un Pixel. Punti
da controllare per primi:

1. `--controlla`: lettura di contatti, SMS, chiamate e notifiche via adb.
2. Il pulsante Invia di Google Messaggi viene trovato (altrimenti interviene
   l'agente, più lento).
3. `svc bluetooth enable` e `cmd media_session volume` sulla versione di
   Android del Pixel.
4. Scrittura di lettere accentate tramite l'app (appunti + incolla).
5. Che OpenRouter accetti l'audio insieme agli strumenti con Gemini 2.5 Flash.

## File

- `dispositivo.py`: collegamento al telefono reale (`PixelEnv` per gli agenti).
- `strumenti.py`: gli strumenti che il modello può usare.
- `rubrica.py`: lettura di contatti, SMS, chiamate, notifiche.
- `cervello.py`: conversazione con il modello e agente sullo schermo.
- `openrouter.py`, `server.py`, `config.py`, `__main__.py`.
- `../app_pixel/`: app Android (Kotlin, nessuna libreria esterna).
