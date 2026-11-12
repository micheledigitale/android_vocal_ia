import base64
import json

from absl.testing import absltest
from assistente import accessibilita


def risposta(dati):
  b64 = base64.b64encode(json.dumps(dati).encode()).decode()
  return f'Broadcasting: Intent {{ }}\nBroadcast completed: result=1, data="{b64}"\n'


class ServizioFinto:

  def __init__(self, attivo=True, servizi='com.google.android.marvin.talkback/.TalkBackService'):
    self.attivo = attivo
    self.servizi = servizi
    self.comandi = []

  def __call__(self, comando):
    self.comandi.append(comando)
    if comando[:3] == ['settings', 'get', 'secure']:
      return self.servizi + '\n'
    if comando[:3] == ['settings', 'put', 'secure'] and comando[3] == 'enabled_accessibility_services':
      self.servizi = comando[4]
      self.attivo = True
      return ''
    if comando[:2] == ['am', 'broadcast']:
      if not self.attivo:
        return 'Broadcast completed: result=0\n'
      cmd = comando[comando.index('comando') + 1]
      if cmd == 'albero':
        return risposta({'nodi': [
            {'t': 'Perché sì', 'c': 'android.widget.EditText', 'e': 1,
             'f': 1, 'p': 'com.whatsapp', 'b': [10, 20, 110, 70]},
            {'d': 'Invia', 'k': 1, 'b': [900, 2000, 1000, 2100]},
        ]})
      if cmd == 'scrivi':
        testo = base64.b64decode(comando[comando.index('testo') + 1]).decode()
        return risposta({'ok': True, 'testo': testo})
      return risposta({})
    return ''


class AccessibilitaTest(absltest.TestCase):

  def test_elementi(self):
    elementi = accessibilita.elementi(ServizioFinto())
    self.assertLen(elementi, 2)
    campo, invia = elementi
    self.assertEqual(campo.text, 'Perché sì')
    self.assertTrue(campo.is_editable)
    self.assertEqual(campo.bbox_pixels.center, (60.0, 45.0))
    self.assertEqual(invia.content_description, 'Invia')
    self.assertTrue(invia.is_clickable)

  def test_servizio_spento(self):
    self.assertIsNone(accessibilita.elementi(ServizioFinto(attivo=False)))

  def test_scrivi_manda_testo_in_base64(self):
    servizio = ServizioFinto()
    self.assertTrue(accessibilita.scrivi(servizio, 'Città è già lì'))
    comando = servizio.comandi[-1]
    self.assertTrue(all(ord(c) < 128 for c in ' '.join(comando)))

  def test_attiva_lascia_talkback(self):
    servizio = ServizioFinto(attivo=False)
    self.assertTrue(accessibilita.attiva(servizio))
    self.assertEqual(
        servizio.servizi,
        'com.google.android.marvin.talkback/.TalkBackService:'
        + accessibilita.SERVIZIO)

  def test_attiva_non_duplica(self):
    servizio = ServizioFinto(servizi=accessibilita.SERVIZIO)
    accessibilita.attiva(servizio)
    self.assertFalse(any(c[:2] == ['settings', 'put'] for c in servizio.comandi))


if __name__ == '__main__':
  absltest.main()
