# Assistente vocale per Pixel

Un assistente in italiano per persone non vedenti o con disabilità gravi:
**tieni premuto il pulsante sul Pixel, parla, rilascia**. Il Mac capisce la
richiesta con un modello su OpenRouter e comanda il telefono via cavo.

```
Pixel: app "Assistente"           Mac: python -m assistente            OpenRouter
[tieni premuto] → registra  ──USB──► server :8765 ──audio + strumenti──► gemini-3.5-flash-lite
[rilascia]                          │◄──────────── strumento scelto ────┘   (smistatore veloce)
                                    ├─ comando diretto (adb + accessibilità): chiama, SMS, Wi-Fi…
                                    └─ agente M3A di AndroidWorld ──────────► gemini-3.5-flash
"Ok", avvisi e risposta a voce ◄─USB┘                                        (esperto, schermo)
```

## Cosa sa fare

| Area | Esempi di frasi | Come lo fa |
|---|---|---|
| Telefonate | "Chiama Mario Rossi", "Chiama il 333 1234567", "Riattacca" | diretto |
| Chi ha chiamato | "Chi mi ha chiamato?", "Ho chiamate perse?" | diretto |
| SMS | "Manda un messaggio a Mario Rossi con scritto ciao come stai" | apre Messaggi già compilato, rilegge il testo e preme Invia, **senza conferma** |
| Leggere SMS | "Leggimi gli ultimi messaggi", "Cosa mi ha scritto Anna?" | diretto, letti parola per parola |
| Riassumere SMS | "Riassumimi i messaggi di oggi" | diretto + riassunto del modello |
| Contatti | "Aggiungi Luca Neri, numero 347…" | modulo compilato, riletto e salvato (agente solo se serve) |
| Notifiche | "Leggimi le notifiche", "Riassumi le notifiche" | diretto |
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
brew install python@3.11
brew install --cask android-platform-tools   # solo adb, niente Android Studio
# Se brew dà errore 404, scarica adb direttamente da Google:
#   cd ~ && curl -LO https://dl.google.com/android/repository/platform-tools-latest-darwin.zip
#   unzip -o platform-tools-latest-darwin.zip
#   echo 'export PATH="$HOME/platform-tools:$PATH"' >> ~/.zshrc && source ~/.zshrc
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

Dalla versione 0.3 l'app ha anche un **servizio di accessibilità** (come
TalkBack) che legge lo schermo e scrive nei campi molto più in fretta. Il Mac
lo accende da solo all'avvio; se non ci riesce, attivalo a mano in
Impostazioni › Accessibilità › Assistente. Comanda solo il Mac via cavo: le
altre app del telefono non possono usarlo.

## Uso

```bash
python -m assistente --controlla       # verifica collegamento e permessi
python -m assistente "alza il volume"  # prova un comando scritto, senza voce
python -m assistente                   # avvia il server per l'app
```

Con il server avviato: sul Pixel tieni premuto il pulsante giallo, parla,
rilascia. Senti un bip all'inizio e uno alla fine. Se la risposta tarda
l'app dice "Ok", poi legge i passi ("Apro la rubrica") e infine la risposta.

Nel terminale del Mac, dopo ogni comando, una riga `Tempi:` dice quanto è
durata ogni fase (modello, strumenti, totale).
Con **TalkBack** attivo: doppio tocco per iniziare, doppio tocco per finire.

Variabili utili: `ASSISTENTE_MODELLO` (smistatore, default
`google/gemini-3.5-flash-lite`), `ASSISTENTE_MODELLO_SCHERMO` (agente sullo
schermo, default `google/gemini-3.5-flash`), `ASSISTENTE_RAGIONAMENTO`
(dello smistatore, default `minimal`),
`ASSISTENTE_SERIALE` (se hai più telefoni), `ASSISTENTE_PORTA` (8765),
`ASSISTENTE_MAX_PASSI` (passi massimi dell'agente, 15).

## Cose da sapere

- **Nessuna conferma**: SMS e chiamate partono subito, come richiesto.
- Le richieste (audio, screenshot, testo di SMS e notifiche) vengono inviate
  a OpenRouter e al modello scelto.
- L'agente sullo schermo è lento: qualche secondo per ogni passo.
- Mai lanciare `run.py`, `minimal_task_runner.py` o `--perform_emulator_setup`
  sul telefono personale: il benchmark di AndroidWorld cancella contatti e SMS.

## Da verificare con la versione 0.3

1. `--controlla` mostra "Servizio di accessibilità: attivo".
2. Flash Lite capisce l'audio. Se risponde sempre "non ho capito":
   `export ASSISTENTE_MODELLO=google/gemini-3.5-flash`.
3. "Leggimi gli SMS" legge il testo esatto; "riassumili" fa un riassunto.
4. SMS con lettere accentate: il testo nel campo viene riletto prima
   dell'invio.
5. "Aggiungi Luca Neri 347…": salva senza usare l'agente.
6. Le righe `Tempi:` nel terminale, da confrontare con la versione 0.2.

## File

- `dispositivo.py`: collegamento al telefono reale (`PixelEnv` per gli agenti).
- `strumenti.py`: gli strumenti che il modello può usare.
- `accessibilita.py`: dialogo con il servizio di accessibilità dell'app.
- `rubrica.py`: lettura di contatti, SMS, chiamate, notifiche.
- `cervello.py`: conversazione con il modello e agente sullo schermo.
- `openrouter.py`, `server.py`, `config.py`, `__main__.py`.
- `../app_pixel/`: app Android (Kotlin, nessuna libreria esterna).
