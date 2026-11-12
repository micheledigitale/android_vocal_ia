"""Collegamento al servizio di accessibilità dell'app Assistente sul Pixel.

Il servizio (come TalkBack) vede subito i pulsanti e i campi sullo schermo e
può scrivere in un campo qualunque testo, lettere accentate comprese. È molto
più rapido di `uiautomator dump` e del trucco degli appunti.

Il Mac gli parla con `am broadcast`: il ricevitore è protetto dal permesso
DUMP, quindi solo la shell adb (cioè il Mac via cavo) può comandarlo, non le
altre app del telefono. La risposta torna nel campo "data" del broadcast,
codificata in base64.
"""

import base64
import json
import logging
import re
from typing import Any, Callable, Optional

from android_world.env import representation_utils

PACCHETTO = 'it.assistente.vocale'
AZIONE = PACCHETTO + '.ACCESSIBILITA'
SERVIZIO = PACCHETTO + '/' + PACCHETTO + '.ServizioAccessibilita'

Shell = Callable[[list[str] | str], str]

_ESITO = re.compile(r'result=(-?\d+)(?:, data="([^"]*)")?')


def chiedi(shell: Shell, comando: str,
           **extra: str) -> Optional[dict[str, Any]]:
  """Manda un comando al servizio. None se il servizio non è attivo."""
  argomenti = ['am', 'broadcast', '-a', AZIONE, '-p', PACCHETTO,
               '--es', 'comando', comando]
  for chiave, valore in extra.items():
    # In base64 così qualunque carattere arriva intatto.
    argomenti += ['--es', chiave,
                  base64.b64encode(valore.encode('utf-8')).decode('ascii')]
  uscita = shell(argomenti)
  m = _ESITO.search(uscita or '')
  if not m or m.group(1) != '1':
    return None
  if not m.group(2):
    return {}
  try:
    return json.loads(base64.b64decode(m.group(2)).decode('utf-8'))
  except ValueError as e:
    logging.warning('Risposta del servizio di accessibilità illeggibile: %s', e)
    return None


def elementi(shell: Shell) -> Optional[list[representation_utils.UIElement]]:
  """Elementi sullo schermo letti dal servizio, o None se non è attivo."""
  risposta = chiedi(shell, 'albero')
  if risposta is None:
    return None
  return [_elemento(n) for n in risposta.get('nodi', [])]


def scrivi(shell: Shell, testo: str, sostituisci: bool = True) -> bool:
  """Scrive nel campo selezionato. False se il servizio non c'è o non trova
  un campo di testo."""
  risposta = chiedi(shell, 'scrivi', testo=testo,
                    modo='sostituisci' if sostituisci else 'aggiungi')
  return bool(risposta and risposta.get('ok'))


def attivo(shell: Shell) -> bool:
  return chiedi(shell, 'ping') is not None


def attiva(shell: Shell) -> bool:
  """Accende il servizio nelle impostazioni, lasciando attivi gli altri
  (es. TalkBack). Restituisce True se risulta attivo."""
  attuali = shell(['settings', 'get', 'secure',
                   'enabled_accessibility_services']).strip()
  servizi = [s for s in attuali.split(':') if s and s != 'null']
  if not any(s.split('/')[0] == PACCHETTO for s in servizi):
    servizi.append(SERVIZIO)
    shell(['settings', 'put', 'secure', 'enabled_accessibility_services',
           ':'.join(servizi)])
    shell(['settings', 'put', 'secure', 'accessibility_enabled', '1'])
  return attivo(shell)


def _elemento(n: dict[str, Any]) -> representation_utils.UIElement:
  b = n.get('b') or [0, 0, 0, 0]
  bbox = representation_utils.BoundingBox(b[0], b[2], b[1], b[3])
  return representation_utils.UIElement(
      text=n.get('t') or None,
      content_description=n.get('d') or None,
      hint_text=n.get('h') or None,
      class_name=n.get('c') or None,
      bbox=bbox,
      bbox_pixels=bbox,
      is_checked=bool(n.get('ck')),
      is_checkable=bool(n.get('ch')),
      is_clickable=bool(n.get('k')),
      is_editable=bool(n.get('e')),
      is_enabled=bool(n.get('en', True)),
      is_focused=bool(n.get('f')),
      is_focusable=bool(n.get('fo')),
      is_long_clickable=bool(n.get('lk')),
      is_scrollable=bool(n.get('s')),
      is_selected=bool(n.get('se')),
      is_visible=True,
      package_name=n.get('p') or None,
      resource_name=n.get('id') or None,
      resource_id=n.get('id') or None,
  )
