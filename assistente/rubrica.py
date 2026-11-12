"""Lettura dei dati del telefono via adb: contatti, SMS, chiamate, notifiche.

Sono tutte funzioni che leggono le "content query" e `dumpsys` di Android:
non serve guardare lo schermo, quindi sono veloci e gratuite.
"""

import dataclasses
import datetime
import re
from typing import Callable, Optional

from thefuzz import fuzz

Shell = Callable[[list[str]], str]


@dataclasses.dataclass(frozen=True)
class Contatto:
  nome: str
  numero: str


def _righe(uscita: str) -> list[str]:
  """Divide l'uscita di `content query` in righe ("Row: N ...")."""
  pezzi = re.split(r'(?m)^Row: \d+ ', uscita)
  return [p.rstrip('\n') for p in pezzi[1:]]


def normalizza_numero(numero: str) -> str:
  numero = numero.strip()
  piu = numero.startswith('+')
  cifre = re.sub(r'\D', '', numero)
  return ('+' if piu else '') + cifre


def stesso_numero(a: str, b: str) -> bool:
  """Confronta due numeri ignorando prefisso internazionale e spazi."""
  ca, cb = re.sub(r'\D', '', a), re.sub(r'\D', '', b)
  if not ca or not cb:
    return False
  n = min(len(ca), len(cb), 9)
  return ca[-n:] == cb[-n:]


def sembra_numero(testo: str) -> bool:
  return bool(re.fullmatch(r'[+\d][\d\s\-./()]{4,}', testo.strip()))


def leggi_contatti(shell: Shell) -> list[Contatto]:
  uscita = shell([
      'content', 'query', '--uri', 'content://com.android.contacts/data/phones',
      '--projection', 'display_name:data1',
  ])
  contatti = []
  visti = set()
  for riga in _righe(uscita):
    m = re.match(r'display_name=(.*), data1=(.*)$', riga, re.S)
    if not m:
      continue
    nome, numero = m.group(1).strip(), m.group(2).strip()
    if nome == 'NULL' or numero == 'NULL':
      continue
    chiave = (nome.lower(), normalizza_numero(numero)[-9:])
    if chiave in visti:
      continue
    visti.add(chiave)
    contatti.append(Contatto(nome, numero))
  return contatti


@dataclasses.dataclass
class EsitoRicerca:
  """Risultato della ricerca di un contatto per nome."""

  trovato: Optional[Contatto] = None
  candidati: list[Contatto] = dataclasses.field(default_factory=list)

  @property
  def ambiguo(self) -> bool:
    return self.trovato is None and len(self.candidati) > 1


def cerca_contatto(
    nome: str, contatti: list[Contatto], soglia: int = 80
) -> EsitoRicerca:
  """Trova il contatto più simile a `nome`.

  Se più persone diverse sono ugualmente probabili (es. due "Mario"),
  restituisce i candidati invece di sceglierne uno a caso.
  """
  richiesta = nome.strip().lower()
  if not richiesta:
    return EsitoRicerca()
  punteggi = []
  for c in contatti:
    nome_c = c.nome.lower()
    if nome_c == richiesta:
      punteggio = 101
    else:
      punteggio = max(
          fuzz.token_set_ratio(richiesta, nome_c),
          fuzz.ratio(richiesta, nome_c),
      )
    punteggi.append((punteggio, c))
  punteggi.sort(key=lambda x: -x[0])
  buoni = [(p, c) for p, c in punteggi if p >= soglia]
  if not buoni:
    return EsitoRicerca()
  migliore = buoni[0][0]
  # Persone diverse con punteggio vicino al migliore.
  vicini: list[Contatto] = []
  nomi_visti = set()
  for p, c in buoni:
    if p >= migliore - 5 and c.nome.lower() not in nomi_visti:
      nomi_visti.add(c.nome.lower())
      vicini.append(c)
  if len(vicini) == 1:
    return EsitoRicerca(trovato=vicini[0], candidati=vicini)
  return EsitoRicerca(candidati=vicini[:5])


def nome_da_numero(numero: str, contatti: list[Contatto]) -> Optional[str]:
  for c in contatti:
    if stesso_numero(numero, c.numero):
      return c.nome
  return None


def _data(ms: str) -> str:
  try:
    quando = datetime.datetime.fromtimestamp(int(ms) / 1000)
  except (ValueError, OSError):
    return ''
  return quando.strftime('%d/%m %H:%M')


@dataclasses.dataclass
class Sms:
  mittente: str
  testo: str
  quando: str


def leggi_sms(
    shell: Shell, contatti: list[Contatto], quanti: int = 5,
    cartella: str = 'inbox',
) -> list[Sms]:
  uscita = shell([
      'content', 'query', '--uri', f'content://sms/{cartella}',
      '--projection', 'address:date:body', '--sort', 'date DESC',
  ])
  messaggi = []
  for riga in _righe(uscita):
    m = re.match(r'address=(.*?), date=(\d+), body=(.*)$', riga, re.S)
    if not m:
      continue
    numero, ms, testo = m.groups()
    nome = nome_da_numero(numero, contatti) or numero
    messaggi.append(Sms(nome, testo.strip(), _data(ms)))
    if len(messaggi) >= quanti:
      break
  return messaggi


_TIPI_CHIAMATA = {
    '1': 'ricevuta',
    '2': 'fatta',
    '3': 'persa',
    '4': 'segreteria',
    '5': 'rifiutata',
    '6': 'bloccata',
}


@dataclasses.dataclass
class Chiamata:
  chi: str
  tipo: str
  quando: str


def leggi_chiamate(
    shell: Shell, contatti: list[Contatto], quante: int = 5
) -> list[Chiamata]:
  uscita = shell([
      'content', 'query', '--uri', 'content://call_log/calls',
      '--projection', 'number:type:date:name', '--sort', 'date DESC',
  ])
  chiamate = []
  for riga in _righe(uscita):
    m = re.match(r'number=(.*?), type=(\d+), date=(\d+), name=(.*)$', riga, re.S)
    if not m:
      continue
    numero, tipo, ms, nome = m.groups()
    nome = nome.strip()
    if not nome or nome == 'NULL':
      nome = nome_da_numero(numero, contatti) or numero or 'numero privato'
    chiamate.append(
        Chiamata(nome, _TIPI_CHIAMATA.get(tipo, 'altro'), _data(ms))
    )
    if len(chiamate) >= quante:
      break
  return chiamate


@dataclasses.dataclass
class Notifica:
  app: str
  titolo: str
  testo: str


_APP_NOTE = {
    'com.whatsapp': 'WhatsApp',
    'com.google.android.gm': 'Gmail',
    'com.google.android.apps.messaging': 'Messaggi',
    'com.google.android.dialer': 'Telefono',
    'com.google.android.calendar': 'Calendar',
    'org.telegram.messenger': 'Telegram',
    'com.instagram.android': 'Instagram',
    'com.facebook.orca': 'Messenger',
    'com.google.android.youtube': 'YouTube',
}

# Notifiche di sistema che non interessano all'utente.
_APP_IGNORATE = (
    'android',
    'com.android.systemui',
    'com.android.providers.downloads',
    'it.assistente.vocale',
)


def _valore_extra(riga: str) -> str:
  """Estrae il testo da righe come `android.title=String (Mario)`."""
  valore = riga.split('=', 1)[1].strip()
  m = re.match(r'^\w+ \((.*)\)$', valore, re.S)
  return (m.group(1) if m else valore).strip()


def leggi_notifiche(shell: Shell) -> list[Notifica]:
  uscita = shell(['dumpsys', 'notification', '--noredact'])
  notifiche: list[Notifica] = []
  corrente: Optional[dict[str, str]] = None

  def chiudi():
    if corrente and (corrente.get('titolo') or corrente.get('testo')):
      pkg = corrente['pkg']
      if pkg not in _APP_IGNORATE:
        notifiche.append(
            Notifica(
                _APP_NOTE.get(pkg, pkg),
                corrente.get('titolo', ''),
                corrente.get('testo', ''),
            )
        )

  for riga in uscita.splitlines():
    riga = riga.strip()
    if riga.startswith('NotificationRecord('):
      chiudi()
      m = re.search(r'pkg=(\S+)', riga)
      corrente = {'pkg': m.group(1) if m else ''}
    elif corrente is None:
      continue
    elif riga.startswith('android.title=') and 'titolo' not in corrente:
      corrente['titolo'] = _valore_extra(riga)
    elif riga.startswith('android.bigText='):
      corrente['testo'] = _valore_extra(riga)
    elif riga.startswith('android.text=') and 'testo' not in corrente:
      corrente['testo'] = _valore_extra(riga)
  chiudi()

  # Togli i doppioni (dumpsys elenca la stessa notifica in più sezioni).
  uniche = []
  viste = set()
  for n in notifiche:
    chiave = (n.app, n.titolo, n.testo)
    if chiave not in viste:
      viste.add(chiave)
      uniche.append(n)
  return uniche
