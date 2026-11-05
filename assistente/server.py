"""Server HTTP sul Mac: l'app del Pixel gli manda l'audio del comando.

L'app parla con `http://127.0.0.1:8765` sul telefono; `adb reverse` porta
quella porta, lungo il cavo USB, fino al Mac.
"""

import logging
from typing import Callable, Optional

import fastapi
import pydantic

from assistente import cervello


class Testo(pydantic.BaseModel):
  testo: str


def crea_app(
    assistente: cervello.Assistente,
    seriale: str = '',
    dopo_comando: Optional[Callable[[cervello.Risposta], None]] = None,
) -> fastapi.FastAPI:
  """`dopo_comando` viene chiamato dopo ogni risposta (es. per riportare
  in primo piano l'app col pulsante)."""
  app = fastapi.FastAPI(title='Assistente vocale')

  def _fine(risposta: cervello.Risposta) -> dict:
    if dopo_comando:
      try:
        dopo_comando(risposta)
      except Exception:  # pylint: disable=broad-exception-caught
        logging.exception('dopo_comando fallito')
    return {'risposta': risposta.testo, 'azioni': risposta.azioni}

  @app.get('/stato')
  def stato():
    return {'ok': True, 'telefono': seriale}

  @app.post('/comando')
  async def comando(request: fastapi.Request):
    """Corpo: audio WAV (mono, 16 bit). Risposta: testo da leggere."""
    audio = await request.body()
    logging.info('Comando vocale: %d byte di audio', len(audio))
    risposta = await _in_thread(assistente.rispondi, audio=audio)
    return _fine(risposta)

  @app.post('/testo')
  async def testo(corpo: Testo):
    """Per provare dal Mac senza parlare: {"testo": "alza il volume"}."""
    risposta = await _in_thread(assistente.rispondi, testo=corpo.testo)
    return _fine(risposta)

  @app.post('/dimentica')
  def dimentica():
    assistente.dimentica()
    return {'ok': True}

  return app


async def _in_thread(funzione, **argomenti):
  # Le azioni sul telefono sono bloccanti: le eseguiamo fuori dal loop async.
  from starlette.concurrency import run_in_threadpool  # pylint: disable=g-import-not-at-top
  return await run_in_threadpool(funzione, **argomenti)
