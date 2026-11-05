"""Il cervello dell'assistente: capisce la richiesta e sceglie gli strumenti."""

import dataclasses
import datetime
import json
import logging
import threading
import time
from typing import Any, Optional

from android_world.agents import m3a
from assistente import openrouter
from assistente import strumenti as strumenti_lib

_GIORNI = ('lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato',
           'domenica')

ISTRUZIONI = """\
Sei un assistente vocale in italiano che comanda il telefono Android \
dell'utente. L'utente può essere una persona non vedente o con una disabilità \
grave: non vede lo schermo e non può toccarlo.

Regole:
- Agisci subito con gli strumenti. Non chiedere mai conferma prima di \
inviare messaggi, chiamare o cambiare impostazioni.
- Chiedi chiarimenti solo se uno strumento risponde AMBIGUO o NON TROVATO, \
o se manca un'informazione indispensabile (es. il testo del messaggio).
- Scrivi il testo dei messaggi esattamente come lo detta l'utente, con \
punteggiatura corretta.
- La risposta finale viene letta ad alta voce: una o due frasi brevi, \
naturali, senza elenchi, simboli, emoji o markdown. Dì sempre l'esito reale \
dell'azione così come lo riporta lo strumento; non inventare mai.
- Quando leggi SMS, notifiche, chiamate o email, riassumi: chi, cosa, quando.
- Per Gmail, WhatsApp e ciò che non ha uno strumento diretto usa \
usa_schermo con un obiettivo completo e preciso.
- Se l'audio non si capisce, chiedi di ripetere.

Ora sono le {ora} di {giorno} {data}.
"""

# Dopo questo tempo senza comandi la conversazione riparte da zero.
_DURATA_MEMORIA_S = 180
_MAX_GIRI = 8


@dataclasses.dataclass
class Risposta:
  testo: str
  azioni: list[str] = dataclasses.field(default_factory=list)


class AgenteSchermo:
  """Usa l'agente M3A di AndroidWorld sul telefono reale."""

  def __init__(self, env, llm, max_passi: int = 15):
    self._env = env
    self._llm = llm
    self._max_passi = max_passi

  def __call__(self, obiettivo: str) -> str:
    agente = m3a.M3A(self._env, self._llm, wait_after_action_seconds=1.5)
    agente.transition_pause = 1.0
    agente.reset(go_home_on_reset=False)
    self._env.interaction_cache = ''
    for passo in range(self._max_passi):
      esito = agente.step(obiettivo)
      if esito.done:
        uscita = str(esito.data.get('action_output') or '')
        if 'infeasible' in uscita:
          return 'NON RIUSCITO: l\'agente dice che non si può fare.'
        risposta = self._env.interaction_cache
        if risposta:
          return f'OK ({passo + 1} passi). Risposta trovata: {risposta}'
        return f'OK: compito completato in {passo + 1} passi.'
    risposta = self._env.interaction_cache
    if risposta:
      return f'INCOMPLETO dopo {self._max_passi} passi. Trovato: {risposta}'
    return f'NON RIUSCITO: non completato in {self._max_passi} passi.'


class Descrittore:
  """Descrive lo schermo a voce."""

  def __init__(self, env, client: openrouter.OpenRouter):
    self._env = env
    self._client = client

  def __call__(self, domanda: str = '') -> str:
    stato = self._env.get_state()
    testi = [
        e.text or e.content_description
        for e in stato.ui_elements
        if e.text or e.content_description
    ]
    richiesta = (
        'Descrivi in italiano, in massimo tre frasi, cosa mostra questo'
        ' schermo di telefono a una persona non vedente: app aperta,'
        ' contenuto principale e azioni possibili. '
        + (f'Domanda dell\'utente: {domanda}. ' if domanda else '')
        + 'Testi sullo schermo: ' + ' | '.join(testi[:80])
    )
    messaggio = self._client.chat([{
        'role': 'user',
        'content': [{'type': 'text', 'text': richiesta},
                    openrouter.parte_immagine(stato.pixels)],
    }])
    return messaggio.get('content') or 'Non riesco a descrivere lo schermo.'


class Assistente:
  """Riceve un comando (audio o testo) e restituisce la risposta da leggere."""

  def __init__(
      self,
      client: openrouter.OpenRouter,
      strumenti: strumenti_lib.Strumenti,
      orologio=time.time,
  ):
    self._client = client
    self._strumenti = strumenti
    self._orologio = orologio
    # Ultimi scambi (ognuno è la lista di messaggi di un comando).
    self._turni: list[list[dict[str, Any]]] = []
    self._ultimo_comando = 0.0
    self._lock = threading.Lock()

  def _sistema(self) -> dict[str, Any]:
    adesso = datetime.datetime.fromtimestamp(self._orologio())
    return {
        'role': 'system',
        'content': ISTRUZIONI.format(
            ora=adesso.strftime('%H:%M'),
            giorno=_GIORNI[adesso.weekday()],
            data=adesso.strftime('%Y-%m-%d'),
        ),
    }

  def dimentica(self) -> None:
    with self._lock:
      self._turni = []

  def rispondi(
      self, audio: Optional[bytes] = None, testo: Optional[str] = None
  ) -> Risposta:
    if not audio and not testo:
      return Risposta('Non ho sentito niente. Tieni premuto e parla.')
    with self._lock:
      return self._rispondi(audio, testo)

  def _rispondi(self, audio: Optional[bytes], testo: Optional[str]) -> Risposta:
    adesso = self._orologio()
    if adesso - self._ultimo_comando > _DURATA_MEMORIA_S:
      self._turni = []
    self._ultimo_comando = adesso

    if audio:
      contenuto = [
          {'type': 'text', 'text': 'Comando vocale dell\'utente:'},
          openrouter.parte_audio(audio),
      ]
      ricordo = {'role': 'user', 'content': '(comando vocale)'}
    else:
      contenuto = testo
      ricordo = {'role': 'user', 'content': testo}

    storia = [m for turno in self._turni for m in turno]
    messaggi = [self._sistema(), *storia,
                {'role': 'user', 'content': contenuto}]
    nuovi: list[dict[str, Any]] = [ricordo]
    azioni: list[str] = []

    for _ in range(_MAX_GIRI):
      try:
        risposta = self._client.chat(
            messaggi, strumenti=strumenti_lib.DEFINIZIONI
        )
      except openrouter.ErroreOpenRouter as e:
        logging.error('OpenRouter non risponde: %s', e)
        return Risposta('Non riesco a contattare il servizio. Riprova tra'
                        ' poco.', azioni)
      chiamate = risposta.get('tool_calls') or []
      if not chiamate:
        finale = (risposta.get('content') or '').strip() or 'Fatto.'
        nuovi.append({'role': 'assistant', 'content': finale})
        self._turni = (self._turni + [nuovi])[-4:]
        return Risposta(finale, azioni)

      assistente_msg = {
          'role': 'assistant',
          'content': risposta.get('content') or '',
          'tool_calls': chiamate,
      }
      messaggi.append(assistente_msg)
      nuovi.append(assistente_msg)
      for chiamata in chiamate:
        nome = chiamata['function']['name']
        try:
          argomenti = json.loads(chiamata['function'].get('arguments') or '{}')
        except json.JSONDecodeError:
          argomenti = {}
        logging.info('Strumento %s %s', nome, argomenti)
        risultato = self._strumenti.esegui(nome, argomenti)
        logging.info(' -> %s', risultato)
        azioni.append(f'{nome}: {risultato}')
        risposta_strumento = {
            'role': 'tool',
            'tool_call_id': chiamata.get('id', nome),
            'name': nome,
            'content': risultato,
        }
        messaggi.append(risposta_strumento)
        nuovi.append(risposta_strumento)

    self._turni = []
    return Risposta('Non sono riuscito a finire. Prova a dirlo in un altro'
                    ' modo.', azioni)
