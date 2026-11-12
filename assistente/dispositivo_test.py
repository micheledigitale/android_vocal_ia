import io

from absl.testing import absltest
from android_world.env import json_action
from android_world.env import representation_utils
from assistente import dispositivo as dispositivo_lib
import numpy as np
from PIL import Image

XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.google.android.apps.messaging" content-desc="" clickable="false" bounds="[0,0][1080,2400]">
    <node index="0" text="" resource-id="" class="android.widget.LinearLayout" package="com.google.android.apps.messaging" content-desc="" clickable="false" bounds="[0,0][1080,200]" />
    <node index="1" text="Mario Rossi" resource-id="" class="android.widget.TextView" package="com.google.android.apps.messaging" content-desc="" clickable="false" bounds="[40,60][600,140]" />
    <node index="2" text="" resource-id="compose" class="android.widget.EditText" package="com.google.android.apps.messaging" content-desc="" clickable="true" bounds="[40,2200][900,2300]" />
    <node index="3" text="" resource-id="" class="android.view.View" package="com.google.android.apps.messaging" content-desc="Invia SMS" clickable="true" bounds="[920,2200][1040,2300]" />
  </node>
</hierarchy>"""


class DispositivoFinto(dispositivo_lib.Dispositivo):
  """Dispositivo con adb simulato."""

  def __init__(self):
    super().__init__('/bin/false', seriale='FINTO')
    self.comandi = []

  def adb(self, args, timeout=30.0):
    self.comandi.append(list(args))
    if args[:3] == ['exec-out', 'screencap', '-p']:
      buf = io.BytesIO()
      Image.new('RGB', (4, 8), 'white').save(buf, format='PNG')
      return buf.getvalue()
    if args[0] == 'shell' and args[1] == 'wm size':
      return b'Physical size: 1080x2400\n'
    return b''

  def execute_adb_call(self, call):
    from android_env.proto import adb_pb2  # pylint: disable=g-import-not-at-top
    self.comandi.append(['adb_call', str(call).strip()])
    risposta = adb_pb2.AdbResponse(status=adb_pb2.AdbResponse.Status.OK)
    if call.HasField('generic') and 'cat' in ' '.join(call.generic.args):
      risposta.generic.output = XML.encode()
    return risposta


class DispositivoTest(absltest.TestCase):

  def test_elementi_filtrati(self):
    d = DispositivoFinto()
    elementi = d.elementi_schermo()
    self.assertEqual(
        [(e.text, e.content_description) for e in elementi],
        [('Mario Rossi', ''), ('', ''), ('', 'Invia SMS')])

  def test_screenshot_e_dimensioni(self):
    d = DispositivoFinto()
    self.assertEqual(d.screenshot().shape, (8, 4, 3))
    self.assertEqual(d.dimensioni_schermo(), (1080, 2400))

  def test_shell_quota_gli_argomenti(self):
    d = DispositivoFinto()
    d.shell(['am', 'start', '--es', 'sms_body', "Ciao, com'è andata?"])
    self.assertEqual(
        d.comandi[-1],
        ['shell', "am start --es sms_body 'Ciao, com'\"'\"'è andata?'"])

  def test_scrivi_testo_accentato_usa_appunti(self):
    d = DispositivoFinto()
    d.scrivi_testo('perché sì')
    broadcast, incolla = d.comandi[-2], d.comandi[-1]
    self.assertIn(dispositivo_lib.AZIONE_INCOLLA, broadcast[1])
    self.assertIn("'perché sì'", broadcast[1])
    self.assertEqual(incolla, ['shell', 'input keyevent 279'])

  def test_scrivi_testo_ascii_usa_input(self):
    d = DispositivoFinto()
    d.scrivi_testo('ciao')
    self.assertTrue(any('input_text' in ' '.join(c) for c in d.comandi))

  def test_pixel_env(self):
    d = DispositivoFinto()
    env = dispositivo_lib.PixelEnv(d)
    stato = env.get_state()
    self.assertIsInstance(stato.pixels, np.ndarray)
    self.assertLen(stato.ui_elements, 3)
    self.assertEqual(env.logical_screen_size, (1080, 2400))

    env.execute_action(json_action.JSONAction(action_type='click', index=2))
    self.assertTrue(any('x: 980' in ' '.join(c) and 'y: 2250' in ' '.join(c)
                        for c in d.comandi))

    env.execute_action(json_action.JSONAction(action_type='answer',
                                              text='Hai 2 email'))
    self.assertEqual(env.interaction_cache, 'Hai 2 email')

  def test_filtra_elementi_scarta_vuoti(self):
    vuoto = representation_utils.UIElement(
        bbox_pixels=representation_utils.BoundingBox(0, 10, 0, 10))
    senza_area = representation_utils.UIElement(
        text='x', bbox_pixels=representation_utils.BoundingBox(5, 5, 0, 10))
    self.assertEmpty(dispositivo_lib.filtra_elementi([vuoto, senza_area]))


class LlmFinto:
  """Risponde come farebbe il modello all'agente M3A."""

  def __init__(self, azioni):
    self.azioni = list(azioni)

  def predict_mm(self, prompt, immagini):
    if self.azioni and 'Action:' in prompt:
      return ('Reason: serve.\nAction: ' + self.azioni.pop(0), True, 'raw')
    return ('Ho premuto il pulsante.', True, 'raw')


class AgenteSchermoTest(absltest.TestCase):

  def test_m3a_su_telefono_reale(self):
    from assistente import cervello  # pylint: disable=g-import-not-at-top
    d = DispositivoFinto()
    env = dispositivo_lib.PixelEnv(d)
    llm = LlmFinto([
        '{"action_type": "click", "index": 2}',
        '{"action_type": "status", "goal_status": "complete"}',
    ])
    agente = cervello.AgenteSchermo(env, llm, max_passi=5)
    esito = agente('Premi Invia')
    self.assertStartsWith(esito, 'OK: compito completato in 2 passi')
    self.assertTrue(any('x: 980' in ' '.join(c) for c in d.comandi))


if __name__ == '__main__':
  absltest.main()
