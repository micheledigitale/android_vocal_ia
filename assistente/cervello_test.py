import json

from absl.testing import absltest
from assistente import cervello
from assistente import openrouter
from assistente import strumenti as strumenti_lib

try:
  from assistente import server  # pylint: disable=g-import-not-at-top
  from fastapi import testclient  # pylint: disable=g-import-not-at-top
except (ImportError, RuntimeError):  # fastapi/httpx non installati.
  testclient = None


def chiamata_strumento(nome, argomenti, id_='c1'):
  return {'role': 'assistant', 'content': None, 'tool_calls': [{
      'id': id_, 'type': 'function',
      'function': {'name': nome, 'arguments': json.dumps(argomenti)}}]}


class ModelloFinto:
  """Restituisce risposte preparate e ricorda i messaggi ricevuti."""

  def __init__(self, risposte):
    self.risposte = list(risposte)
    self.ricevuti = []

  def chat(self, messaggi, strumenti=None, **_):
    self.ricevuti.append([dict(m) for m in messaggi])
    risposta = self.risposte.pop(0)
    if isinstance(risposta, Exception):
      raise risposta
    return risposta


class StrumentiFinti:

  def __init__(self, esiti):
    self.esiti = esiti
    self.eseguiti = []

  def esegui(self, nome, argomenti):
    self.eseguiti.append((nome, argomenti))
    return self.esiti.get(nome, 'OK')


class AssistenteTest(absltest.TestCase):

  def test_comando_vocale_con_strumento(self):
    modello = ModelloFinto([
        chiamata_strumento('invia_sms', {'destinatario': 'Mario Rossi',
                                         'testo': 'Ciao come stai?'}),
        {'role': 'assistant', 'content': 'Messaggio inviato a Mario Rossi.'},
    ])
    strumenti = StrumentiFinti({'invia_sms': 'OK: SMS inviato a Mario Rossi.'})
    a = cervello.Assistente(modello, strumenti, orologio=lambda: 1000.0)

    risposta = a.rispondi(audio=b'RIFF....WAVE')

    self.assertEqual(risposta.testo, 'Messaggio inviato a Mario Rossi.')
    self.assertEqual(strumenti.eseguiti, [
        ('invia_sms', {'destinatario': 'Mario Rossi',
                       'testo': 'Ciao come stai?'})])
    primo = modello.ricevuti[0]
    self.assertEqual(primo[0]['role'], 'system')
    self.assertEqual(primo[-1]['content'][1]['type'], 'input_audio')
    secondo = modello.ricevuti[1]
    self.assertEqual(secondo[-1]['role'], 'tool')
    self.assertEqual(secondo[-1]['tool_call_id'], 'c1')

  def test_ricorda_la_domanda_di_chiarimento(self):
    modello = ModelloFinto([
        chiamata_strumento('chiama', {'destinatario': 'Mario'}),
        {'role': 'assistant', 'content': 'Mario Rossi o Mario Bianchi?'},
        {'role': 'assistant', 'content': 'Chiamo Mario Rossi.'},
    ])
    strumenti = StrumentiFinti({'chiama': 'AMBIGUO: ...'})
    ora = [1000.0]
    a = cervello.Assistente(modello, strumenti, orologio=lambda: ora[0])

    self.assertEqual(a.rispondi(testo='chiama Mario').testo,
                     'Mario Rossi o Mario Bianchi?')
    ora[0] += 20
    a.rispondi(testo='Rossi')

    storia = modello.ricevuti[2]
    contenuti = [m.get('content') for m in storia]
    self.assertIn('chiama Mario', contenuti)
    self.assertIn('Mario Rossi o Mario Bianchi?', contenuti)
    self.assertEqual(storia[-1]['content'], 'Rossi')
    # L'audio non resta nella storia: troppo pesante.
    self.assertNotIn('input_audio', json.dumps(storia[:-1]))

  def test_dimentica_dopo_qualche_minuto(self):
    modello = ModelloFinto([
        {'role': 'assistant', 'content': 'Uno.'},
        {'role': 'assistant', 'content': 'Due.'},
    ])
    ora = [1000.0]
    a = cervello.Assistente(modello, StrumentiFinti({}), orologio=lambda: ora[0])
    a.rispondi(testo='primo')
    ora[0] += 600
    a.rispondi(testo='secondo')
    self.assertLen(modello.ricevuti[1], 2)  # sistema + nuovo comando

  def test_errore_rete(self):
    modello = ModelloFinto([openrouter.ErroreOpenRouter('timeout')])
    a = cervello.Assistente(modello, StrumentiFinti({}))
    self.assertIn('Riprova', a.rispondi(testo='ciao').testo)

  def test_azione_diretta_senza_seconda_chiamata(self):
    modello = ModelloFinto([chiamata_strumento('wifi', {'acceso': False})])
    strumenti = StrumentiFinti(
        {'wifi': strumenti_lib.Finale('OK: Wi-Fi spento.', 'Wi-Fi spento.')})
    passi = iter(range(100))
    a = cervello.Assistente(modello, strumenti,
                            cronometro=lambda: float(next(passi)))

    risposta = a.rispondi(testo='spegni il wifi')

    self.assertEqual(risposta.testo, 'Wi-Fi spento.')
    self.assertLen(modello.ricevuti, 1)  # una sola chiamata al modello
    self.assertEqual(set(risposta.tempi), {'modello 1', 'wifi', 'totale'})
    # La storia resta completa per il comando successivo.
    self.assertEqual(a._turni[-1][-1],
                     {'role': 'assistant', 'content': 'Wi-Fi spento.'})

  def test_niente_audio(self):
    a = cervello.Assistente(ModelloFinto([]), StrumentiFinti({}))
    self.assertIn('Non ho sentito', a.rispondi(audio=b'').testo)


@absltest.skipIf(testclient is None, 'fastapi non installato')
class ServerTest(absltest.TestCase):

  def test_endpoint(self):
    modello = ModelloFinto([
        chiamata_strumento('wifi', {'acceso': True}),
        {'role': 'assistant', 'content': 'Wi-Fi acceso.'},
        {'role': 'assistant', 'content': 'Ciao!'},
    ])
    a = cervello.Assistente(modello, StrumentiFinti({}))
    client = testclient.TestClient(server.crea_app(a, 'ABC123'))

    self.assertEqual(client.get('/stato').json(),
                     {'ok': True, 'telefono': 'ABC123'})
    r = client.post('/comando', content=b'RIFFxxxxWAVE',
                    headers={'Content-Type': 'audio/wav'})
    self.assertEqual(r.json()['risposta'], 'Wi-Fi acceso.')
    r = client.post('/testo', json={'testo': 'ciao'})
    self.assertEqual(r.json()['risposta'], 'Ciao!')
    self.assertIn('totale', r.json()['tempi'])

  def test_avanzamento(self):
    avanzamento = server.Avanzamento()
    a = cervello.Assistente(ModelloFinto([]), StrumentiFinti({}))
    client = testclient.TestClient(
        server.crea_app(a, 'X', avanzamento=avanzamento))
    avanzamento.annuncia('Apro la rubrica.')
    avanzamento.annuncia('Premo Salva.')
    self.assertEqual(client.get('/avanzamento?da=1').json(),
                     {'frasi': ['Premo Salva.']})
    avanzamento.nuovo_comando()
    self.assertEqual(client.get('/avanzamento').json(), {'frasi': []})


if __name__ == '__main__':
  absltest.main()
