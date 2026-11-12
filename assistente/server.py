"""Server HTTP sul Mac: l'app del Pixel gli manda l'audio del comando.

L'app parla con `http://127.0.0.1:8765` sul telefono; `adb reverse` porta
quella porta, lungo il cavo USB, fino al Mac.
"""

import logging
import threading
from typing import Callable, Optional

import fastapi
import pydantic

from assistente import cervello


class Testo(pydantic.BaseModel):
  testo: str


class Avanzamento:
  """Frasi brevi da leggere mentre il comando è in corso.

  Gli strumenti chiamano `annuncia("Apro la rubrica")`; l'app, mentre aspetta
  la risposta, chiede `GET /avanzamento?da=N` e legge le frasi nuove.
  """

  def __init__(self):
    self._frasi: list[str] = []
    self._lock = threading.Lock()

  def nuovo_comando(self) -> None:
    with self._lock:
      self._frasi = []

  def annuncia(self, frase: str) -> None:
    logging.info('Avviso: %s', frase)
    with self._lock:
      self._frasi.append(frase)

  def da(self, indice: int) -> list[str]:
    with self._lock:
      return self._frasi[max(0, indice):]


def crea_app(
    assistente: cervello.Assistente,
    seriale: str = '',
    dopo_comando: Optional[Callable[[cervello.Risposta], None]] = None,
    avanzamento: Optional[Avanzamento] = None,
) -> fastapi.FastAPI:
  """`dopo_comando` viene chiamato dopo ogni risposta (es. per riportare
  in primo piano l'app col pulsante)."""
  app = fastapi.FastAPI(title='Assistente vocale')
  avanzamento = avanzamento or Avanzamento()

  def _fine(risposta: cervello.Risposta) -> dict:
    if dopo_comando:
      try:
        dopo_comando(risposta)
      except Exception:  # pylint: disable=broad-exception-caught
        logging.exception('dopo_comando fallito')
    return {'risposta': risposta.testo, 'azioni': risposta.azioni,
            'tempi': risposta.tempi}

  @app.get('/stato')
  def stato():
    return {'ok': True, 'telefono': seriale}

  @app.post('/comando')
  async def comando(request: fastapi.Request):
    """Corpo: audio WAV (mono, 16 bit). Risposta: testo da leggere."""
    audio = await request.body()
    avanzamento.nuovo_comando()
    logging.info('Comando vocale: %d byte di audio', len(audio))
    risposta = await _in_thread(assistente.rispondi, audio=audio)
    return _fine(risposta)

  @app.post('/testo')
  async def testo(corpo: Testo):
    """Per provare dal Mac senza parlare: {"testo": "alza il volume"}."""
    avanzamento.nuovo_comando()
    risposta = await _in_thread(assistente.rispondi, testo=corpo.testo)
    return _fine(risposta)

  @app.get('/avanzamento')
  def leggi_avanzamento(da: int = 0):
    return {'frasi': avanzamento.da(da)}

  @app.post('/dimentica')
  def dimentica():
    assistente.dimentica()
    return {'ok': True}

  return app


async def _in_thread(funzione, **argomenti):
  # Le azioni sul telefono sono bloccanti: le eseguiamo fuori dal loop async.
  from starlette.concurrency import run_in_threadpool  # pylint: disable=g-import-not-at-top
  return await run_in_threadpool(funzione, **argomenti)
