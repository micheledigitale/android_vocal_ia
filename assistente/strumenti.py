"""Gli strumenti che il modello può usare per agire sul telefono.

Ogni strumento ha una descrizione (per il modello, formato "function calling"
di OpenAI/OpenRouter) e un'implementazione che usa adb. Quando non esiste un
comando diretto, lo strumento `usa_schermo` passa il compito all'agente M3A di
AndroidWorld, che guarda lo schermo e tocca come farebbe una persona.
"""

import datetime
import json
import logging
import re
import time
from typing import Any, Callable, Optional

from assistente import rubrica

AgenteSchermo = Callable[[str], str]
Descrittore = Callable[[str], str]


def _funzione(nome: str, descrizione: str, parametri: dict[str, Any],
              obbligatori: Optional[list[str]] = None) -> dict[str, Any]:
  return {
      'type': 'function',
      'function': {
          'name': nome,
          'description': descrizione,
          'parameters': {
              'type': 'object',
              'properties': parametri,
              'required': obbligatori or [],
          },
      },
  }


_STR = {'type': 'string'}
_INT = {'type': 'integer'}
_BOOL = {'type': 'boolean'}

DEFINIZIONI = [
    _funzione(
        'chiama',
        'Fa partire una telefonata a un contatto della rubrica o a un numero.',
        {'destinatario': {**_STR, 'description': 'Nome in rubrica o numero.'}},
        ['destinatario'],
    ),
    _funzione(
        'chiudi_chiamata', 'Chiude la telefonata in corso.', {},
    ),
    _funzione(
        'invia_sms',
        'Invia subito un SMS, senza chiedere conferma.',
        {
            'destinatario': {**_STR, 'description': 'Nome in rubrica o numero.'},
            'testo': {**_STR, 'description': 'Testo esatto del messaggio.'},
        },
        ['destinatario', 'testo'],
    ),
    _funzione(
        'leggi_sms',
        'Legge gli ultimi SMS ricevuti (o inviati).',
        {
            'quanti': {**_INT, 'description': 'Quanti messaggi (default 5).'},
            'da': {**_STR, 'description': 'Solo quelli di questo contatto.'},
            'inviati': {**_BOOL, 'description': 'True per gli SMS inviati.'},
        },
    ),
    _funzione(
        'chiamate_recenti',
        'Elenca le ultime chiamate: ricevute, fatte e perse.',
        {
            'quante': {**_INT, 'description': 'Quante chiamate (default 5).'},
            'solo_perse': _BOOL,
        },
    ),
    _funzione(
        'cerca_contatto',
        'Cerca un contatto in rubrica e ne restituisce il numero.',
        {'nome': _STR}, ['nome'],
    ),
    _funzione(
        'crea_contatto',
        'Crea un nuovo contatto in rubrica.',
        {'nome': _STR, 'numero': _STR}, ['nome', 'numero'],
    ),
    _funzione(
        'leggi_notifiche', 'Legge le notifiche presenti sul telefono.', {},
    ),
    _funzione(
        'wifi', 'Accende o spegne il Wi-Fi.', {'acceso': _BOOL}, ['acceso'],
    ),
    _funzione(
        'bluetooth', 'Accende o spegne il Bluetooth.',
        {'acceso': _BOOL}, ['acceso'],
    ),
    _funzione(
        'volume',
        'Cambia il volume.',
        {
            'azione': {'type': 'string',
                       'enum': ['alza', 'abbassa', 'imposta', 'muto']},
            'percentuale': {**_INT, 'description': '0-100, solo per imposta.'},
            'tipo': {'type': 'string',
                     'enum': ['media', 'suoneria', 'sveglia', 'chiamata'],
                     'description': 'Default: media.'},
        },
        ['azione'],
    ),
    _funzione(
        'luminosita', 'Imposta la luminosità dello schermo.',
        {'percentuale': {**_INT, 'description': '0-100.'}}, ['percentuale'],
    ),
    _funzione(
        'torcia', 'Accende o spegne la torcia.', {'accesa': _BOOL}, ['accesa'],
    ),
    _funzione(
        'non_disturbare', 'Attiva o disattiva la modalità Non disturbare.',
        {'attivo': _BOOL}, ['attivo'],
    ),
    _funzione(
        'apri_app', 'Apre un\'app (es. Gmail, WhatsApp, Impostazioni).',
        {'nome': _STR}, ['nome'],
    ),
    _funzione(
        'leggi_agenda',
        'Legge gli eventi del calendario in un intervallo di giorni.',
        {
            'da': {**_STR, 'description': 'Data inizio AAAA-MM-GG.'},
            'giorni': {**_INT, 'description': 'Quanti giorni (default 1).'},
        },
        ['da'],
    ),
    _funzione(
        'crea_evento',
        'Crea un evento nel calendario.',
        {
            'titolo': _STR,
            'inizio': {**_STR, 'description': 'AAAA-MM-GGTHH:MM'},
            'fine': {**_STR, 'description': 'AAAA-MM-GGTHH:MM (opzionale).'},
            'luogo': _STR,
        },
        ['titolo', 'inizio'],
    ),
    _funzione(
        'descrivi_schermo',
        'Descrive cosa c\'è ora sullo schermo del telefono.',
        {'domanda': {**_STR, 'description': 'Cosa interessa sapere.'}},
    ),
    _funzione(
        'usa_schermo',
        'Esegue un compito usando le app come farebbe una persona: guarda lo'
        ' schermo, tocca e scrive. Usalo per email (Gmail), WhatsApp e tutto'
        ' ciò che non ha uno strumento diretto. Più lento.',
        {'obiettivo': {**_STR,
                       'description': 'Compito completo e preciso, in italiano.'}},
        ['obiettivo'],
    ),
]

_APP = {
    'gmail': 'com.google.android.gm',
    'posta': 'com.google.android.gm',
    'email': 'com.google.android.gm',
    'messaggi': 'com.google.android.apps.messaging',
    'sms': 'com.google.android.apps.messaging',
    'telefono': 'com.google.android.dialer',
    'contatti': 'com.google.android.contacts',
    'rubrica': 'com.google.android.contacts',
    'calendario': 'com.google.android.calendar',
    'calendar': 'com.google.android.calendar',
    'agenda': 'com.google.android.calendar',
    'impostazioni': 'com.android.settings',
    'fotocamera': 'com.google.android.GoogleCamera',
    'camera': 'com.google.android.GoogleCamera',
    'foto': 'com.google.android.apps.photos',
    'orologio': 'com.google.android.deskclock',
    'sveglia': 'com.google.android.deskclock',
    'chrome': 'com.android.chrome',
    'browser': 'com.android.chrome',
    'mappe': 'com.google.android.apps.maps',
    'maps': 'com.google.android.apps.maps',
    'youtube': 'com.google.android.youtube',
    'whatsapp': 'com.whatsapp',
    'telegram': 'org.telegram.messenger',
    'spotify': 'com.spotify.music',
    'play store': 'com.android.vending',
}

_STREAM = {'chiamata': 0, 'suoneria': 2, 'media': 3, 'sveglia': 4}

_PACCHETTO_MESSAGGI = 'com.google.android.apps.messaging'


class Strumenti:
  """Esegue gli strumenti sul telefono."""

  def __init__(
      self,
      dispositivo,
      agente_schermo: AgenteSchermo,
      descrittore: Descrittore,
      attesa: Callable[[float], None] = time.sleep,
  ):
    self._d = dispositivo
    self._agente = agente_schermo
    self._descrivi = descrittore
    self._dormi = attesa
    self._contatti: Optional[list[rubrica.Contatto]] = None

  # --- Supporto -----------------------------------------------------------

  def _shell(self, comando: list[str]) -> str:
    return self._d.shell(comando)

  def contatti(self, ricarica: bool = False) -> list[rubrica.Contatto]:
    if self._contatti is None or ricarica:
      self._contatti = rubrica.leggi_contatti(self._shell)
    return self._contatti

  def _risolvi(self, destinatario: str) -> tuple[Optional[str], str]:
    """Restituisce (numero, nome) oppure (None, messaggio di errore)."""
    if rubrica.sembra_numero(destinatario):
      numero = rubrica.normalizza_numero(destinatario)
      nome = rubrica.nome_da_numero(numero, self.contatti()) or destinatario
      return numero, nome
    esito = rubrica.cerca_contatto(destinatario, self.contatti())
    if esito.trovato is None and not esito.candidati:
      # Forse il contatto è stato appena aggiunto: rileggi la rubrica.
      esito = rubrica.cerca_contatto(
          destinatario, self.contatti(ricarica=True)
      )
    if esito.trovato:
      return rubrica.normalizza_numero(esito.trovato.numero), esito.trovato.nome
    if esito.ambiguo:
      nomi = ', '.join(c.nome for c in esito.candidati)
      return None, (
          f'AMBIGUO: in rubrica ci sono più persone simili a "{destinatario}":'
          f' {nomi}. Chiedi all\'utente quale intende.'
      )
    return None, f'NON TROVATO: nessun contatto chiamato "{destinatario}".'

  # --- Esecuzione ---------------------------------------------------------

  def esegui(self, nome: str, argomenti: dict[str, Any]) -> str:
    metodo = getattr(self, f'_t_{nome}', None)
    if metodo is None:
      return f'ERRORE: strumento sconosciuto {nome}.'
    try:
      return metodo(**argomenti)
    except TypeError as e:
      return f'ERRORE: argomenti non validi per {nome}: {e}'
    except Exception as e:  # pylint: disable=broad-exception-caught
      logging.exception('Strumento %s fallito', nome)
      return f'ERRORE durante {nome}: {e}'

  def _t_chiama(self, destinatario: str) -> str:
    numero, nome = self._risolvi(destinatario)
    if numero is None:
      return nome
    self._shell(['am', 'start', '-a', 'android.intent.action.CALL',
                 '-d', f'tel:{numero}'])
    return f'OK: sto chiamando {nome} ({numero}).'

  def _t_chiudi_chiamata(self) -> str:
    self._shell(['input', 'keyevent', 'KEYCODE_ENDCALL'])
    return 'OK: chiamata chiusa.'

  def _t_invia_sms(self, destinatario: str, testo: str) -> str:
    numero, nome = self._risolvi(destinatario)
    if numero is None:
      return nome
    prima = self._ultimo_sms_inviato()
    self._shell([
        'am', 'start', '-a', 'android.intent.action.SENDTO',
        '-d', f'smsto:{numero}', '--es', 'sms_body', testo,
        '--ez', 'exit_on_sent', 'true',
    ])
    self._dormi(2.5)
    if not self._premi_invio():
      esito = self._agente(
          'Nella conversazione aperta in Messaggi il testo è già scritto:'
          ' premi soltanto il pulsante per inviarlo, senza modificare nulla.'
      )
      logging.info('Invio tramite agente: %s', esito)
    # Verifica: l'SMS compare tra gli inviati? (con RCS/chat può non comparire)
    for _ in range(6):
      self._dormi(1.0)
      ultimo = self._ultimo_sms_inviato()
      if ultimo and ultimo != prima and ultimo.testo == testo.strip():
        return f'OK: SMS inviato a {nome}.'
    return (
        f'PROBABILE: ho premuto Invia per {nome}, ma non vedo l\'SMS tra gli'
        ' inviati (può essere un messaggio chat/RCS).'
    )

  def _ultimo_sms_inviato(self) -> Optional[rubrica.Sms]:
    try:
      inviati = rubrica.leggi_sms(self._shell, [], quanti=1, cartella='sent')
    except Exception:  # pylint: disable=broad-exception-caught
      return None
    return inviati[0] if inviati else None

  def _premi_invio(self) -> bool:
    """Tocca il pulsante Invia di Google Messaggi, se lo trova."""
    for e in self._d.elementi_schermo():
      if e.package_name and e.package_name != _PACCHETTO_MESSAGGI:
        continue
      etichetta = ' '.join(
          filter(None, [e.content_description, e.resource_id, e.text])
      ).lower()
      if re.search(r'\b(invia|send)\b|send_message_button|compose:draft:send',
                   etichetta) and e.bbox_pixels is not None:
        x, y = e.bbox_pixels.center
        self._shell(['input', 'tap', str(int(x)), str(int(y))])
        return True
    return False

  def _t_leggi_sms(self, quanti: int = 5, da: str = '',
                   inviati: bool = False) -> str:
    contatti = self.contatti()
    messaggi = rubrica.leggi_sms(
        self._shell, contatti, quanti=50 if da else quanti,
        cartella='sent' if inviati else 'inbox',
    )
    if da:
      messaggi = [
          m for m in messaggi
          if rubrica.cerca_contatto(
              da, [rubrica.Contatto(m.mittente, '')]).trovato
          or rubrica.stesso_numero(da, m.mittente)
      ][:quanti]
    if not messaggi:
      return 'Nessun SMS trovato.'
    return json.dumps([m.__dict__ for m in messaggi], ensure_ascii=False)

  def _t_chiamate_recenti(self, quante: int = 5,
                          solo_perse: bool = False) -> str:
    chiamate = rubrica.leggi_chiamate(
        self._shell, self.contatti(), quante=50 if solo_perse else quante
    )
    if solo_perse:
      chiamate = [c for c in chiamate if c.tipo == 'persa'][:quante]
    if not chiamate:
      return 'Nessuna chiamata trovata.'
    return json.dumps([c.__dict__ for c in chiamate], ensure_ascii=False)

  def _t_cerca_contatto(self, nome: str) -> str:
    esito = rubrica.cerca_contatto(nome, self.contatti(ricarica=True))
    if not esito.candidati:
      return f'NON TROVATO: nessun contatto simile a "{nome}".'
    return json.dumps([c.__dict__ for c in esito.candidati], ensure_ascii=False)

  def _t_crea_contatto(self, nome: str, numero: str) -> str:
    self._shell([
        'am', 'start', '-a', 'android.intent.action.INSERT',
        '-t', 'vnd.android.cursor.dir/contact',
        '-e', 'name', nome, '-e', 'phone', numero,
    ])
    self._dormi(2.5)
    esito = self._agente(
        f'Si è aperta la schermata di un nuovo contatto con nome "{nome}" e'
        f' numero "{numero}" già compilati. Controlla e premi Salva.'
    )
    self._contatti = None
    if any(rubrica.stesso_numero(numero, c.numero) for c in self.contatti()):
      return f'OK: contatto {nome} salvato.'
    return f'NON CONFERMATO: non trovo ancora {nome} in rubrica. ({esito})'

  def _t_leggi_notifiche(self) -> str:
    notifiche = rubrica.leggi_notifiche(self._shell)
    if not notifiche:
      return 'Nessuna notifica.'
    return json.dumps([n.__dict__ for n in notifiche[:15]], ensure_ascii=False)

  def _t_wifi(self, acceso: bool) -> str:
    self._shell(['svc', 'wifi', 'enable' if acceso else 'disable'])
    return f'OK: Wi-Fi {"acceso" if acceso else "spento"}.'

  def _t_bluetooth(self, acceso: bool) -> str:
    azione = 'enable' if acceso else 'disable'
    uscita = self._shell(['svc', 'bluetooth', azione])
    if 'unknown' in uscita.lower() or 'usage' in uscita.lower():
      self._shell(['cmd', 'bluetooth_manager', azione])
    return f'OK: Bluetooth {"acceso" if acceso else "spento"}.'

  def _t_volume(self, azione: str, percentuale: Optional[int] = None,
                tipo: str = 'media') -> str:
    stream = _STREAM.get(tipo, 3)
    if azione in ('alza', 'abbassa'):
      tasto = 'KEYCODE_VOLUME_UP' if azione == 'alza' else 'KEYCODE_VOLUME_DOWN'
      for _ in range(2):
        self._shell(['input', 'keyevent', tasto])
      return f'OK: volume {"alzato" if azione == "alza" else "abbassato"}.'
    if azione == 'muto':
      percentuale = 0
    if percentuale is None:
      return 'ERRORE: serve la percentuale.'
    massimo = self._volume_massimo(stream)
    livello = round(max(0, min(100, percentuale)) * massimo / 100)
    self._shell(['cmd', 'media_session', 'volume', '--stream', str(stream),
                 '--set', str(livello)])
    return f'OK: volume {tipo} al {percentuale}%.'

  def _volume_massimo(self, stream: int) -> int:
    uscita = self._shell(['cmd', 'media_session', 'volume', '--stream',
                          str(stream), '--get'])
    m = re.search(r'\[\s*\d+\s*\.\.\s*(\d+)\s*\]', uscita)
    return int(m.group(1)) if m else 15

  def _t_luminosita(self, percentuale: int) -> str:
    valore = round(max(0, min(100, percentuale)) * 255 / 100)
    self._shell(['settings', 'put', 'system', 'screen_brightness_mode', '0'])
    self._shell(['settings', 'put', 'system', 'screen_brightness',
                 str(max(1, valore))])
    return f'OK: luminosità al {percentuale}%.'

  def _t_torcia(self, accesa: bool) -> str:
    uscita = self._shell([
        'am', 'broadcast', '-n', 'it.assistente.vocale/.TorciaReceiver',
        '-a', 'it.assistente.vocale.TORCIA', '--ez', 'accesa',
        'true' if accesa else 'false',
    ])
    if 'result=1' not in uscita:
      return ('ERRORE: la torcia non risponde. Serve la versione 0.2'
              ' dell\'app Assistente sul telefono.')
    return f'OK: torcia {"accesa" if accesa else "spenta"}.'

  def _t_non_disturbare(self, attivo: bool) -> str:
    self._shell(['cmd', 'notification', 'set_dnd',
                 'priority' if attivo else 'off'])
    return f'OK: Non disturbare {"attivo" if attivo else "disattivato"}.'

  def _t_apri_app(self, nome: str) -> str:
    chiave = nome.strip().lower()
    pacchetto = _APP.get(chiave)
    if pacchetto is None:
      pacchetto = self._cerca_pacchetto(chiave)
    if pacchetto is None:
      return f'NON TROVATA: non trovo un\'app chiamata "{nome}".'
    self._shell(['monkey', '-p', pacchetto, '-c',
                 'android.intent.category.LAUNCHER', '1'])
    return f'OK: ho aperto {nome}.'

  def _cerca_pacchetto(self, nome: str) -> Optional[str]:
    uscita = self._shell(['pm', 'list', 'packages'])
    pacchetti = [r.split(':', 1)[1].strip() for r in uscita.splitlines()
                 if r.startswith('package:')]
    parola = re.sub(r'\s+', '', nome)
    candidati = [p for p in pacchetti if parola in p.lower()]
    return min(candidati, key=len) if candidati else None

  def _t_leggi_agenda(self, da: str, giorni: int = 1) -> str:
    inizio = datetime.datetime.fromisoformat(da)
    fine = inizio + datetime.timedelta(days=max(1, giorni))
    uri = (
        'content://com.android.calendar/instances/when/'
        f'{int(inizio.timestamp() * 1000)}/{int(fine.timestamp() * 1000)}'
    )
    uscita = self._shell(['content', 'query', '--uri', uri, '--projection',
                          'begin:end:allDay:title', '--sort', 'begin ASC'])
    if 'Error' in uscita or 'Exception' in uscita:
      return self._agente(
          f'Apri Google Calendar e dimmi gli eventi da {da} per {giorni}'
          ' giorni. Rispondi con titoli e orari.'
      )
    eventi = []
    for riga in uscita.split('Row: ')[1:]:
      m = re.match(r'\d+ begin=(\d+), end=(\d+), allDay=(\d), title=(.*)$',
                   riga.strip(), re.S)
      if not m:
        continue
      b, _, tutto_giorno, titolo = m.groups()
      quando = datetime.datetime.fromtimestamp(int(b) / 1000)
      eventi.append({
          'titolo': titolo.strip(),
          'quando': quando.strftime('%d/%m') + (
              ' (tutto il giorno)' if tutto_giorno == '1'
              else quando.strftime(' %H:%M')),
      })
    if not eventi:
      return 'Nessun evento in agenda.'
    return json.dumps(eventi, ensure_ascii=False)

  def _t_crea_evento(self, titolo: str, inizio: str, fine: str = '',
                     luogo: str = '') -> str:
    t_inizio = datetime.datetime.fromisoformat(inizio)
    t_fine = (datetime.datetime.fromisoformat(fine) if fine
              else t_inizio + datetime.timedelta(hours=1))
    comando = [
        'am', 'start', '-a', 'android.intent.action.INSERT',
        '-d', 'content://com.android.calendar/events',
        '--es', 'title', titolo,
        '--el', 'beginTime', str(int(t_inizio.timestamp() * 1000)),
        '--el', 'endTime', str(int(t_fine.timestamp() * 1000)),
    ]
    if luogo:
      comando += ['--es', 'eventLocation', luogo]
    self._shell(comando)
    self._dormi(2.5)
    esito = self._agente(
        f'Si è aperta la schermata di un nuovo evento "{titolo}" già'
        ' compilato. Premi Salva senza cambiare nulla.'
    )
    return f'Evento "{titolo}" {t_inizio:%d/%m alle %H:%M}: {esito}'

  def _t_descrivi_schermo(self, domanda: str = '') -> str:
    return self._descrivi(domanda)

  def _t_usa_schermo(self, obiettivo: str) -> str:
    return self._agente(obiettivo)
