"""Collegamento a un telefono reale via adb.

AndroidWorld si collega solo all'emulatore (porta console + gRPC). Qui
costruiamo lo stesso tipo di oggetti sopra un telefono vero collegato via USB:

* `Dispositivo` esegue i comandi adb ed espone `execute_adb_call`, così tutte
  le funzioni di `android_world.env.adb_utils` funzionano senza modifiche.
* `PixelEnv` implementa `interface.AsyncEnv`, l'interfaccia che usano gli
  agenti M3A/T3A: screenshot, elementi dello schermo ed esecuzione azioni.
"""

import io
import logging
import re
import shlex
import subprocess
import time
from typing import Sequence

from android_env.components import adb_call_parser
from android_env.components import adb_controller
from android_env.components import config_classes
from android_env.proto import adb_pb2
from android_world.env import actuation
from android_world.env import adb_utils
from android_world.env import interface
from android_world.env import json_action
from android_world.env import representation_utils
import numpy as np
from PIL import Image

# App Android del progetto: riceve il testo da incollare (adb non sa scrivere
# lettere accentate) e mostra il pulsante.
PACCHETTO_APP = 'it.assistente.vocale'
AZIONE_INCOLLA = PACCHETTO_APP + '.INCOLLA'
_KEYCODE_PASTE = '279'


class ErroreDispositivo(RuntimeError):
  pass


def elenca_dispositivi(adb_path: str) -> list[str]:
  """Restituisce i numeri di serie dei telefoni collegati e autorizzati."""
  uscita = subprocess.run(
      [adb_path, 'devices'], capture_output=True, text=True, timeout=15
  ).stdout
  seriali = []
  for riga in uscita.splitlines()[1:]:
    parti = riga.split()
    if len(parti) >= 2 and parti[1] == 'device':
      seriali.append(parti[0])
  return seriali


def _solo_ascii(testo: str) -> bool:
  return all(ord(c) < 128 for c in testo)


class Dispositivo:
  """Un telefono collegato via adb."""

  def __init__(self, adb_path: str, seriale: str = ''):
    if not seriale:
      seriali = elenca_dispositivi(adb_path)
      if not seriali:
        raise ErroreDispositivo(
            'Nessun telefono collegato. Collega il Pixel via USB, attiva il'
            ' Debug USB e accetta la richiesta sul telefono.'
        )
      seriale = seriali[0]
    self.seriale = seriale
    self.adb_path = adb_path
    self._controller = adb_controller.AdbController(
        config_classes.AdbControllerConfig(
            adb_path=adb_path, device_name=seriale, default_timeout=30.0
        )
    )
    self._parser = adb_call_parser.AdbCallParser(self._controller)

  # --- Interfaccia usata da android_world.env.adb_utils -------------------

  def execute_adb_call(self, call: adb_pb2.AdbRequest) -> adb_pb2.AdbResponse:
    return self._parser.parse(call)

  # --- Comandi diretti ----------------------------------------------------

  def adb(self, args: Sequence[str], timeout: float = 30.0) -> bytes:
    """Esegue `adb -s <seriale> <args>` e restituisce l'uscita grezza."""
    comando = [self.adb_path, '-s', self.seriale, *args]
    risultato = subprocess.run(comando, capture_output=True, timeout=timeout)
    if risultato.returncode != 0:
      raise ErroreDispositivo(
          f'Comando adb fallito: {" ".join(args)}\n'
          + risultato.stderr.decode('utf-8', 'replace')
      )
    return risultato.stdout

  def shell(self, comando: str | Sequence[str], timeout: float = 30.0) -> str:
    """Esegue un comando nella shell del telefono.

    Se `comando` è una lista, ogni parte viene quotata: così testi con spazi,
    apostrofi o accenti arrivano intatti.
    """
    if not isinstance(comando, str):
      comando = ' '.join(shlex.quote(parte) for parte in comando)
    return self.adb(['shell', comando], timeout=timeout).decode(
        'utf-8', 'replace'
    )

  def screenshot(self) -> np.ndarray:
    png = self.adb(['exec-out', 'screencap', '-p'], timeout=20)
    return np.array(Image.open(io.BytesIO(png)).convert('RGB'))

  def dimensioni_schermo(self) -> tuple[int, int]:
    uscita = self.shell('wm size')
    # "Physical size: 1080x2400" ed eventualmente "Override size: ...".
    trovati = re.findall(r'(\d+)x(\d+)', uscita)
    if not trovati:
      raise ErroreDispositivo(f'Dimensioni schermo non lette: {uscita!r}')
    larghezza, altezza = trovati[-1]
    return int(larghezza), int(altezza)

  def elementi_schermo(self) -> list[representation_utils.UIElement]:
    """Elementi visibili sullo schermo (pulsanti, testi, campi)."""
    try:
      xml = adb_utils.uiautomator_dump(self)
    except Exception as e:  # pylint: disable=broad-exception-caught
      logging.warning('uiautomator dump fallito: %s', e)
      return []
    inizio = xml.find('<?xml')
    if inizio < 0:
      inizio = xml.find('<hierarchy')
    if inizio < 0:
      return []
    try:
      elementi = representation_utils.xml_dump_to_ui_elements(xml[inizio:])
    except Exception as e:  # pylint: disable=broad-exception-caught
      logging.warning('XML dello schermo non valido: %s', e)
      return []
    return filtra_elementi(elementi)

  def scrivi_testo(self, testo: str) -> None:
    """Scrive nel campo selezionato, anche con lettere accentate."""
    if _solo_ascii(testo):
      adb_utils.type_text(testo, self, timeout_sec=15)
      return
    # `adb shell input text` non supporta caratteri non ASCII: l'app
    # dell'assistente mette il testo negli appunti e noi incolliamo.
    self.shell([
        'am', 'broadcast', '-n', f'{PACCHETTO_APP}/.IncollaReceiver',
        '-a', AZIONE_INCOLLA, '--es', 'testo', testo,
    ])
    time.sleep(0.5)
    self.shell(['input', 'keyevent', _KEYCODE_PASTE])

  def inoltra_porta(self, porta: int) -> None:
    """Fa sì che `localhost:<porta>` sul telefono arrivi al Mac (via USB)."""
    self.adb(['reverse', f'tcp:{porta}', f'tcp:{porta}'])


def filtra_elementi(
    elementi: list[representation_utils.UIElement],
) -> list[representation_utils.UIElement]:
  """Tiene solo gli elementi utili all'agente.

  Il dump di uiautomator contiene anche tutti i contenitori vuoti; li
  togliamo, come fa AndroidWorld con l'albero di accessibilità.
  """
  utili = []
  for e in elementi:
    if e.bbox_pixels is None:
      continue
    if e.bbox_pixels.width <= 0 or e.bbox_pixels.height <= 0:
      continue
    if (
        e.text
        or e.content_description
        or e.is_clickable
        or e.is_scrollable
        or e.is_checkable
        or (e.class_name or '').endswith('EditText')
    ):
      utili.append(e)
  return utili


class PixelEnv(interface.AsyncEnv):
  """Ambiente AndroidWorld sopra un telefono reale."""

  interaction_cache = ''

  def __init__(self, dispositivo: Dispositivo):
    self._dispositivo = dispositivo
    self.interaction_cache = ''
    self._dimensioni = None

  @property
  def controller(self):  # pyrefly: ignore[bad-override]
    return self._dispositivo

  def reset(self, go_home: bool = False) -> interface.State:
    if go_home:
      adb_utils.press_home_button(self._dispositivo)
    self.interaction_cache = ''
    return self.get_state()

  def _stato(self) -> interface.State:
    return interface.State(
        pixels=self._dispositivo.screenshot(),
        forest=None,
        ui_elements=self._dispositivo.elementi_schermo(),
        auxiliaries={},
    )

  def get_state(self, wait_to_stabilize: bool = False) -> interface.State:
    if not wait_to_stabilize:
      return self._stato()
    # Aspetta che lo schermo smetta di cambiare (max ~5 secondi).
    precedenti = self._dispositivo.elementi_schermo()
    scadenza = time.time() + 5.0
    while time.time() < scadenza:
      time.sleep(0.5)
      attuali = self._dispositivo.elementi_schermo()
      if attuali == precedenti:
        break
      precedenti = attuali
    return self._stato()

  def execute_action(self, action: json_action.JSONAction) -> None:
    if action.action_type == json_action.ANSWER:
      self.interaction_cache = action.text or ''
      return
    if action.action_type == json_action.STATUS:
      return
    elementi = self._dispositivo.elementi_schermo()
    if action.action_type == json_action.INPUT_TEXT and action.text:
      self._scrivi(action, elementi)
      return
    actuation.execute_adb_action(
        action, elementi, self.logical_screen_size, self._dispositivo
    )

  def _scrivi(self, action: json_action.JSONAction, elementi) -> None:
    if action.index is not None or (
        action.x is not None and action.y is not None
    ):
      tocco = json_action.JSONAction(
          action_type=json_action.CLICK,
          index=action.index,
          x=action.x,
          y=action.y,
      )
      actuation.execute_adb_action(
          tocco, elementi, self.logical_screen_size, self._dispositivo
      )
      time.sleep(0.8)
    if action.clear_text:
      self._dispositivo.shell('input keycombination 113 29 && input keyevent 67')
      time.sleep(0.5)
    self._dispositivo.scrivi_testo(action.text or '')

  def display_message(self, message: str, header: str = '') -> None:
    logging.info('%s %s', header, message)

  def ask_question(
      self, question: str, timeout_seconds: float = -1.0
  ) -> str | None:
    raise NotImplementedError('ask_question non disponibile.')

  @property
  def foreground_activity_name(self) -> str:
    return adb_utils.get_current_activity(self._dispositivo)[0] or ''

  @property
  def device_screen_size(self) -> tuple[int, int]:
    if self._dimensioni is None:
      self._dimensioni = self._dispositivo.dimensioni_schermo()
    return self._dimensioni

  @property
  def logical_screen_size(self) -> tuple[int, int]:
    return self.device_screen_size

  def close(self) -> None:
    pass

  def hide_automation_ui(self) -> None:
    pass

  @property
  def orientation(self) -> int:
    try:
      return adb_utils.get_orientation(self._dispositivo)
    except Exception:  # pylint: disable=broad-exception-caught
      return 0

  @property
  def physical_frame_boundary(self) -> tuple[int, int, int, int]:
    larghezza, altezza = self.device_screen_size
    return (0, 0, larghezza, altezza)
