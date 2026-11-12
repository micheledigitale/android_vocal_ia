"""Client per OpenRouter (API compatibile con OpenAI)."""

import base64
import logging
import time
from typing import Any, Optional

from android_world.agents import infer
import numpy as np
import requests

URL = 'https://openrouter.ai/api/v1/chat/completions'


class ErroreOpenRouter(RuntimeError):
  pass


class OpenRouter:
  """Chiamate al modello, con strumenti (function calling) e audio."""

  def __init__(
      self,
      api_key: str,
      modello: str,
      timeout: float = 60.0,
      tentativi: int = 3,
      sessione: Optional[requests.Session] = None,
      ragionamento: str = 'low',
  ):
    self.api_key = api_key
    self.modello = modello
    # 'none', 'minimal', 'low', 'medium', 'high': quanto il modello "pensa"
    # prima di rispondere. Meno ragionamento = risposta più rapida.
    self.ragionamento = ragionamento
    self.timeout = timeout
    self.tentativi = max(1, tentativi)
    self._http = sessione or requests.Session()

  def chat(
      self,
      messaggi: list[dict[str, Any]],
      strumenti: Optional[list[dict[str, Any]]] = None,
      temperatura: float = 0.0,
      max_token: int = 4000,
  ) -> dict[str, Any]:
    """Restituisce il messaggio di risposta del modello (dict stile OpenAI)."""
    corpo: dict[str, Any] = {
        'model': self.modello,
        'messages': messaggi,
        'temperature': temperatura,
        'max_tokens': max_token,
        # I modelli che "ragionano" (es. Gemini 3.5) sono più lenti: per un
        # assistente vocale basta un ragionamento breve. Ignorato dagli altri.
        'reasoning': {'effort': self.ragionamento},
    }
    if strumenti:
      corpo['tools'] = strumenti
    intestazioni = {
        'Authorization': f'Bearer {self.api_key}',
        'Content-Type': 'application/json',
        'X-Title': 'Assistente vocale',
    }
    attesa = 2.0
    ultimo_errore = ''
    for _ in range(self.tentativi):
      try:
        risposta = self._http.post(
            URL, headers=intestazioni, json=corpo, timeout=self.timeout
        )
        dati = risposta.json()
        if risposta.ok and dati.get('choices'):
          return dati['choices'][0]['message']
        ultimo_errore = str(dati.get('error', dati))
        if (risposta.status_code == 400 and 'reasoning' in corpo
            and ('reasoning' in ultimo_errore.lower()
                 or 'effort' in ultimo_errore.lower()
                 or 'thinking' in ultimo_errore.lower())):
          # Il modello non accetta questo livello di ragionamento: riprova
          # subito senza.
          logging.warning('OpenRouter: %s. Riprovo senza "reasoning".',
                          ultimo_errore)
          corpo.pop('reasoning')
          continue
      except (requests.RequestException, ValueError) as e:
        ultimo_errore = str(e)
      logging.warning('OpenRouter: %s. Riprovo tra %.0fs', ultimo_errore, attesa)
      time.sleep(attesa)
      attesa *= 2
    raise ErroreOpenRouter(ultimo_errore)


def parte_audio(wav: bytes) -> dict[str, Any]:
  """Contenuto di un messaggio con audio WAV."""
  return {
      'type': 'input_audio',
      'input_audio': {
          'data': base64.b64encode(wav).decode('ascii'),
          'format': 'wav',
      },
  }


def parte_immagine(immagine: np.ndarray) -> dict[str, Any]:
  jpeg = base64.b64encode(infer.array_to_jpeg_bytes(immagine)).decode('ascii')
  return {
      'type': 'image_url',
      'image_url': {'url': f'data:image/jpeg;base64,{jpeg}'},
  }


class OpenRouterMm(infer.LlmWrapper, infer.MultimodalLlmWrapper):
  """Adattatore per gli agenti di AndroidWorld (M3A, T3A)."""

  def __init__(self, client: OpenRouter):
    self._client = client

  def predict(self, text_prompt: str) -> tuple[str, Optional[bool], Any]:
    return self.predict_mm(text_prompt, [])

  def predict_mm(
      self, text_prompt: str, images: list[np.ndarray]
  ) -> tuple[str, Optional[bool], Any]:
    contenuto: list[dict[str, Any]] = [{'type': 'text', 'text': text_prompt}]
    contenuto.extend(parte_immagine(img) for img in images)
    try:
      messaggio = self._client.chat([{'role': 'user', 'content': contenuto}])
    except ErroreOpenRouter as e:
      return infer.ERROR_CALLING_LLM, None, str(e)
    return messaggio.get('content') or '', True, messaggio
