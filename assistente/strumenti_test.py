from absl.testing import absltest
from android_world.env import representation_utils
from assistente import strumenti as strumenti_lib

CONTATTI = """\
Row: 0 display_name=Mario Rossi, data1=+39 333 123 4567
Row: 1 display_name=Mario Bianchi, data1=+39 347 000 1111
Row: 2 display_name=Anna Verdi, data1=+39 340 765 4321
"""


class TelefonoFinto:
  """Simula le risposte di `adb shell` e registra i comandi ricevuti."""

  def __init__(self):
    self.comandi = []
    self.sms_inviati = []
    self.elementi = []

  def shell(self, comando):
    self.comandi.append(list(comando))
    testo = ' '.join(comando)
    if 'contacts/data/phones' in testo:
      return CONTATTI
    if 'content://sms/sent' in testo:
      return ''.join(
          f'Row: {i} address=+393331234567, date=1, body={b}\n'
          for i, b in enumerate(reversed(self.sms_inviati)))
    if 'media_session' in testo and '--get' in testo:
      return 'volume is 5 in range [0..25]'
    if comando[:2] == ['input', 'tap']:
      # Premere Invia "invia" davvero l'ultimo SMS preparato.
      for c in reversed(self.comandi):
        if 'sms_body' in c:
          self.sms_inviati.append(c[c.index('sms_body') + 1])
          break
    return ''

  def elementi_schermo(self):
    return self.elementi


def pulsante(descrizione, x0=900, y0=2000):
  bbox = representation_utils.BoundingBox(x0, x0 + 100, y0, y0 + 100)
  return representation_utils.UIElement(
      content_description=descrizione, bbox=bbox, bbox_pixels=bbox,
      is_clickable=True, package_name='com.google.android.apps.messaging')


class StrumentiTest(absltest.TestCase):

  def setUp(self):
    super().setUp()
    self.tel = TelefonoFinto()
    self.obiettivi_agente = []

    def agente(obiettivo):
      self.obiettivi_agente.append(obiettivo)
      return 'OK: compito completato in 1 passi.'

    self.s = strumenti_lib.Strumenti(
        self.tel, agente, lambda d: 'Schermo home.', attesa=lambda s: None)

  def test_definizioni_hanno_implementazione(self):
    for d in strumenti_lib.DEFINIZIONI:
      nome = d['function']['name']
      self.assertTrue(hasattr(self.s, f'_t_{nome}'), nome)

  def test_chiama_per_nome(self):
    esito = self.s.esegui('chiama', {'destinatario': 'Anna'})
    self.assertStartsWith(esito, 'OK')
    self.assertIn(['am', 'start', '-a', 'android.intent.action.CALL',
                   '-d', 'tel:+393407654321'], self.tel.comandi)

  def test_chiama_numero_mantiene_il_piu(self):
    self.s.esegui('chiama', {'destinatario': '+39 06 1234 5678'})
    self.assertIn('tel:+390612345678', self.tel.comandi[-1])

  def test_chiama_ambiguo_non_chiama(self):
    esito = self.s.esegui('chiama', {'destinatario': 'Mario'})
    self.assertStartsWith(esito, 'AMBIGUO')
    self.assertIn('Mario Rossi', esito)
    self.assertIn('Mario Bianchi', esito)
    self.assertFalse(any('tel:' in ' '.join(c) for c in self.tel.comandi))

  def test_invia_sms_senza_conferma(self):
    self.tel.elementi = [pulsante('Invia SMS')]
    esito = self.s.esegui('invia_sms', {'destinatario': 'Mario Rossi',
                                        'testo': 'Ciao, come stai?'})
    self.assertEqual(esito, 'OK: SMS inviato a Mario Rossi.')
    apertura = next(c for c in self.tel.comandi if 'sms_body' in c)
    self.assertIn('smsto:+393331234567', apertura)
    self.assertIn('Ciao, come stai?', apertura)
    self.assertIn(['input', 'tap', '950', '2050'], self.tel.comandi)
    self.assertEmpty(self.obiettivi_agente)

  def test_invia_sms_senza_pulsante_usa_agente(self):
    esito = self.s.esegui('invia_sms', {'destinatario': 'Anna Verdi',
                                        'testo': 'Arrivo'})
    self.assertLen(self.obiettivi_agente, 1)
    self.assertStartsWith(esito, 'PROBABILE')

  def test_invia_sms_contatto_inesistente(self):
    esito = self.s.esegui('invia_sms', {'destinatario': 'Zorro',
                                        'testo': 'x'})
    self.assertStartsWith(esito, 'NON TROVATO')

  def test_impostazioni(self):
    self.s.esegui('wifi', {'acceso': False})
    self.s.esegui('bluetooth', {'acceso': True})
    self.s.esegui('luminosita', {'percentuale': 50})
    self.s.esegui('non_disturbare', {'attivo': True})
    self.assertIn(['svc', 'wifi', 'disable'], self.tel.comandi)
    self.assertIn(['svc', 'bluetooth', 'enable'], self.tel.comandi)
    self.assertIn(['settings', 'put', 'system', 'screen_brightness', '128'],
                  self.tel.comandi)
    self.assertIn(['cmd', 'notification', 'set_dnd', 'priority'],
                  self.tel.comandi)

  def test_volume_percentuale(self):
    self.s.esegui('volume', {'azione': 'imposta', 'percentuale': 40})
    self.assertIn(['cmd', 'media_session', 'volume', '--stream', '3',
                   '--set', '10'], self.tel.comandi)

  def test_volume_alza(self):
    self.s.esegui('volume', {'azione': 'alza'})
    self.assertIn(['input', 'keyevent', 'KEYCODE_VOLUME_UP'], self.tel.comandi)

  def test_apri_app(self):
    esito = self.s.esegui('apri_app', {'nome': 'Gmail'})
    self.assertStartsWith(esito, 'OK')
    self.assertIn('com.google.android.gm', self.tel.comandi[-1])

  def test_usa_schermo(self):
    self.s.esegui('usa_schermo', {'obiettivo': 'Leggi l\'ultima email'})
    self.assertEqual(self.obiettivi_agente, ['Leggi l\'ultima email'])

  def test_strumento_sconosciuto_e_argomenti_errati(self):
    self.assertStartsWith(self.s.esegui('vola', {}), 'ERRORE')
    self.assertStartsWith(self.s.esegui('wifi', {'x': 1}), 'ERRORE')


if __name__ == '__main__':
  absltest.main()
