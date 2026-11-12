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
    self.attiva = 'com.google.android.apps.nexuslauncher/.NexusLauncherActivity'
    self.dopo_indietro = self.attiva

  def shell(self, comando):
    if isinstance(comando, str):
      comando = comando.split()
    self.comandi.append(list(comando))
    testo = ' '.join(comando)
    if 'topResumedActivity' in testo:
      return f'  topResumedActivity=ActivityRecord{{1 u0 {self.attiva} t9}}'
    if comando[-1:] == ['KEYCODE_BACK']:
      self.attiva = self.dopo_indietro
    if comando[-1:] == ['KEYCODE_HOME']:
      self.attiva = 'com.google.android.apps.nexuslauncher/.Launcher'
    if 'contacts/data/phones' in testo:
      return CONTATTI
    if 'content://sms/inbox' in testo:
      return ('Row: 0 address=+393407654321, date=1700000000000,'
              ' body=Arrivo tra dieci minuti\n')
    if 'content://sms/sent' in testo:
      return ''.join(
          f'Row: {i} address=+393331234567, date=1, body={b}\n'
          for i, b in enumerate(reversed(self.sms_inviati)))
    if 'TorciaReceiver' in testo:
      return 'Broadcast completed: result=1'
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

  def scrivi_testo(self, testo, sostituisci=False):
    self.comandi.append(['scrivi', testo, sostituisci])
    for e in self.elementi:
      if e.is_editable:
        e.text = testo if sostituisci else (e.text or '') + testo


def campo(testo, x0=100, y0=2000):
  bbox = representation_utils.BoundingBox(x0, x0 + 700, y0, y0 + 100)
  return representation_utils.UIElement(
      text=testo, bbox=bbox, bbox_pixels=bbox, is_editable=True,
      class_name='android.widget.EditText',
      package_name='com.google.android.apps.messaging')


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

    self.annunci = []
    self.s = strumenti_lib.Strumenti(
        self.tel, agente, lambda d: 'Schermo home.', attesa=lambda s: None,
        annuncia=self.annunci.append)

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

  def test_invia_sms_rilegge_e_corregge_il_testo(self):
    self.tel.elementi = [campo('Ciao come sta'), pulsante('Invia SMS')]
    esito = self.s.esegui('invia_sms', {'destinatario': 'Mario Rossi',
                                        'testo': 'Ciao, come stai?'})
    self.assertIn(['scrivi', 'Ciao, come stai?', True], self.tel.comandi)
    self.assertEqual(esito.parlato, 'SMS inviato a Mario Rossi.')
    self.assertIn('Correggo il testo.', self.annunci)

  def test_invia_sms_testo_giusto_non_riscrive(self):
    self.tel.elementi = [campo('Ciao, come stai?'), pulsante('Invia SMS')]
    self.s.esegui('invia_sms', {'destinatario': 'Mario Rossi',
                                'testo': 'Ciao, come stai?'})
    self.assertFalse(any(c[0] == 'scrivi' for c in self.tel.comandi))

  def test_invia_sms_senza_pulsante_usa_agente(self):
    esito = self.s.esegui('invia_sms', {'destinatario': 'Anna Verdi',
                                        'testo': 'Arrivo'})
    self.assertLen(self.obiettivi_agente, 1)
    self.assertStartsWith(esito, 'PROBABILE')

  def test_invia_sms_contatto_inesistente(self):
    esito = self.s.esegui('invia_sms', {'destinatario': 'Zorro',
                                        'testo': 'x'})
    self.assertStartsWith(esito, 'NON TROVATO')

  def test_leggi_sms_parola_per_parola(self):
    esito = self.s.esegui('leggi_sms', {'quanti': 1})
    self.assertIsInstance(esito, strumenti_lib.Finale)
    self.assertStartsWith(esito.parlato, 'Hai un messaggio. Da Anna Verdi,')
    self.assertEndsWith(esito.parlato, ': Arrivo tra dieci minuti.')

  def test_riassumi_sms_passa_dal_modello(self):
    esito = self.s.esegui('leggi_sms', {'modalita': 'riassumi'})
    self.assertNotIsInstance(esito, strumenti_lib.Finale)
    self.assertIn('Arrivo tra dieci minuti', esito)

  def test_crea_contatto_salva_senza_agente(self):
    self.tel.elementi = [campo('Luca Neri'), campo('347 111 2222', y0=2200),
                         pulsante('Salva', y0=200)]
    orig = self.tel.shell

    def shell(comando):
      if 'contacts/data/phones' in ' '.join(comando) and any(
          c[:2] == ['input', 'tap'] for c in self.tel.comandi):
        return CONTATTI + 'Row: 3 display_name=Luca Neri, data1=3471112222\n'
      return orig(comando)

    self.tel.shell = shell
    esito = self.s.esegui('crea_contatto', {'nome': 'Luca Neri',
                                            'numero': '347 111 2222'})
    self.assertEqual(esito.parlato, 'Ho salvato Luca Neri in rubrica.')
    self.assertEmpty(self.obiettivi_agente)

  def test_crea_contatto_campi_sbagliati_usa_agente(self):
    self.tel.elementi = [campo('Luca'), pulsante('Salva', y0=200)]
    self.s.esegui('crea_contatto', {'nome': 'Luca Neri', 'numero': '347'})
    self.assertLen(self.obiettivi_agente, 1)

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

  def test_torcia(self):
    self.assertEqual(self.s.esegui('torcia', {'accesa': True}),
                     'OK: Torcia accesa.')
    comando = self.tel.comandi[-1]
    self.assertIn('it.assistente.vocale/.TorciaReceiver', comando)
    self.assertEqual(comando[-2:], ['accesa', 'true'])

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

  def test_usa_schermo_non_tocca_altre_app(self):
    self.s.esegui('usa_schermo', {'obiettivo': 'x'})
    self.assertNotIn(['input', 'keyevent', 'KEYCODE_BACK'], self.tel.comandi)

  def test_descrivi_schermo_toglie_assistente(self):
    self.tel.attiva = 'it.assistente.vocale/.MainActivity'
    self.tel.dopo_indietro = 'com.whatsapp/.Main'
    self.s.esegui('descrivi_schermo', {'domanda': 'quante app ci sono?'})
    self.assertIn(['input', 'keyevent', 'KEYCODE_BACK'], self.tel.comandi)
    self.assertNotIn(['input', 'keyevent', 'KEYCODE_HOME'], self.tel.comandi)

  def test_descrivi_schermo_va_alla_home_se_serve(self):
    self.tel.attiva = 'it.assistente.vocale/.MainActivity'
    self.tel.dopo_indietro = self.tel.attiva
    self.s.esegui('descrivi_schermo', {})
    self.assertIn(['input', 'keyevent', 'KEYCODE_HOME'], self.tel.comandi)

  def test_strumento_sconosciuto_e_argomenti_errati(self):
    self.assertStartsWith(self.s.esegui('vola', {}), 'ERRORE')
    self.assertStartsWith(self.s.esegui('wifi', {'x': 1}), 'ERRORE')


if __name__ == '__main__':
  absltest.main()
