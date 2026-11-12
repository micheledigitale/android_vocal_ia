"""Configurazione letta dalle variabili d'ambiente."""

import dataclasses
import os
import shutil

_PERCORSI_ADB = (
    '/opt/homebrew/bin/adb',  # Homebrew su Mac con chip Apple.
    '/usr/local/bin/adb',  # Homebrew su Mac Intel.
    os.path.expanduser('~/platform-tools/adb'),  # Download diretto da Google.
    os.path.expanduser('~/Library/Android/sdk/platform-tools/adb'),
    os.path.expanduser('~/Android/Sdk/platform-tools/adb'),
)


def trova_adb() -> str:
  """Restituisce il percorso del programma adb."""
  if os.environ.get('ADB_PATH'):
    return os.environ['ADB_PATH']
  trovato = shutil.which('adb')
  if trovato:
    return trovato
  for percorso in _PERCORSI_ADB:
    if os.path.isfile(percorso):
      return percorso
  raise EnvironmentError(
      'adb non trovato. Installalo con "brew install android-platform-tools"'
      ' oppure imposta la variabile ADB_PATH.'
  )


@dataclasses.dataclass
class Config:
  """Impostazioni dell'assistente."""

  openrouter_api_key: str
  # Smistatore: ascolta il comando e sceglie lo strumento. Deve essere
  # veloce e accettare l'audio.
  modello: str = 'google/gemini-3.5-flash-lite'
  # Esperto: agente che guarda lo schermo e descrizioni (deve accettare
  # immagini). Più lento ma più affidabile.
  modello_schermo: str = 'google/gemini-3.5-flash'
  # Ragionamento dello smistatore ('none', 'minimal', 'low', ...).
  ragionamento: str = 'minimal'
  adb_path: str = ''
  # Numero di serie del telefono (vuoto = il primo collegato).
  seriale: str = ''
  porta: int = 8765
  # Passi massimi per l'agente che usa lo schermo.
  max_passi_schermo: int = 15

  @classmethod
  def da_ambiente(cls) -> 'Config':
    chiave = os.environ.get('OPENROUTER_API_KEY', '')
    if not chiave:
      raise EnvironmentError(
          'Manca la chiave OpenRouter: esegui'
          ' export OPENROUTER_API_KEY=la-tua-chiave'
      )
    return cls(
        openrouter_api_key=chiave,
        modello=os.environ.get('ASSISTENTE_MODELLO', cls.modello),
        modello_schermo=os.environ.get(
            'ASSISTENTE_MODELLO_SCHERMO', cls.modello_schermo
        ),
        ragionamento=os.environ.get(
            'ASSISTENTE_RAGIONAMENTO', cls.ragionamento
        ),
        adb_path=trova_adb(),
        seriale=os.environ.get('ASSISTENTE_SERIALE', ''),
        porta=int(os.environ.get('ASSISTENTE_PORTA', cls.porta)),
        max_passi_schermo=int(
            os.environ.get('ASSISTENTE_MAX_PASSI', cls.max_passi_schermo)
        ),
    )
