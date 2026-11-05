from absl.testing import absltest
from assistente import rubrica

CONTATTI_ADB = """\
Row: 0 display_name=Mario Rossi, data1=+39 333 123 4567
Row: 1 display_name=Mario Rossi, data1=3331234567
Row: 2 display_name=Anna Verdi, data1=+39 340 765 4321
Row: 3 display_name=Mamma, data1=0612345678
Row: 4 display_name=Mario Bianchi, data1=+39 347 000 1111
"""


def shell_fissa(uscita):
  return lambda comando: uscita


class ContattiTest(absltest.TestCase):

  def setUp(self):
    super().setUp()
    self.contatti = rubrica.leggi_contatti(shell_fissa(CONTATTI_ADB))

  def test_legge_e_toglie_doppioni(self):
    nomi = [c.nome for c in self.contatti]
    self.assertEqual(nomi, ['Mario Rossi', 'Anna Verdi', 'Mamma',
                            'Mario Bianchi'])

  def test_nome_completo_trovato(self):
    esito = rubrica.cerca_contatto('mario rossi', self.contatti)
    self.assertEqual(esito.trovato.nome, 'Mario Rossi')

  def test_nome_esatto_breve(self):
    esito = rubrica.cerca_contatto('mamma', self.contatti)
    self.assertEqual(esito.trovato.nome, 'Mamma')

  def test_solo_nome_ambiguo(self):
    esito = rubrica.cerca_contatto('Mario', self.contatti)
    self.assertTrue(esito.ambiguo)
    self.assertCountEqual([c.nome for c in esito.candidati],
                          ['Mario Rossi', 'Mario Bianchi'])

  def test_solo_nome_unico(self):
    esito = rubrica.cerca_contatto('Anna', self.contatti)
    self.assertEqual(esito.trovato.nome, 'Anna Verdi')

  def test_non_trovato(self):
    esito = rubrica.cerca_contatto('Giuseppe Garibaldi', self.contatti)
    self.assertIsNone(esito.trovato)
    self.assertEmpty(esito.candidati)

  def test_errore_trascrizione_lieve(self):
    esito = rubrica.cerca_contatto('Ana Verdi', self.contatti)
    self.assertEqual(esito.trovato.nome, 'Anna Verdi')

  def test_numeri(self):
    self.assertTrue(rubrica.stesso_numero('+39 333 123 4567', '3331234567'))
    self.assertFalse(rubrica.stesso_numero('3331234567', '3407654321'))
    self.assertEqual(rubrica.normalizza_numero('+39 333-123 4567'),
                     '+393331234567')
    self.assertTrue(rubrica.sembra_numero('333 123 4567'))
    self.assertFalse(rubrica.sembra_numero('Mario'))
    self.assertEqual(
        rubrica.nome_da_numero('+393407654321', self.contatti), 'Anna Verdi')


class SmsChiamateTest(absltest.TestCase):

  def test_sms_con_virgole_e_a_capo(self):
    uscita = (
        'Row: 0 address=+393407654321, date=1762340000000, body=Ciao, come'
        ' stai?\nTutto bene\n'
        'Row: 1 address=12345, date=1762330000000, body=Codice: 9999\n'
    )
    contatti = [rubrica.Contatto('Anna Verdi', '3407654321')]
    sms = rubrica.leggi_sms(shell_fissa(uscita), contatti, quanti=5)
    self.assertLen(sms, 2)
    self.assertEqual(sms[0].mittente, 'Anna Verdi')
    self.assertEqual(sms[0].testo, 'Ciao, come stai?\nTutto bene')
    self.assertEqual(sms[1].mittente, '12345')

  def test_sms_limite(self):
    uscita = ''.join(
        f'Row: {i} address=1, date=1, body=m{i}\n' for i in range(10))
    self.assertLen(rubrica.leggi_sms(shell_fissa(uscita), [], quanti=3), 3)

  def test_chiamate(self):
    uscita = (
        'Row: 0 number=+393331234567, type=3, date=1762340000000, name=NULL\n'
        'Row: 1 number=0612345678, type=1, date=1762330000000, name=Mamma\n'
        'Row: 2 number=, type=1, date=1762320000000, name=NULL\n'
    )
    contatti = [rubrica.Contatto('Mario Rossi', '3331234567')]
    chiamate = rubrica.leggi_chiamate(shell_fissa(uscita), contatti)
    self.assertEqual(
        [(c.chi, c.tipo) for c in chiamate],
        [('Mario Rossi', 'persa'), ('Mamma', 'ricevuta'),
         ('numero privato', 'ricevuta')])


DUMPSYS = """\
Current Notification Manager state:
  Notification List:
    NotificationRecord(0x0abc: pkg=com.whatsapp user=UserHandle{0} id=1 tag=null importance=4 key=0|com.whatsapp|1|null|10123: Notification(channel=individual))
      uid=10123 userId=0
      extras={
        android.title=String (Mario Rossi)
        android.text=String (Ci vediamo alle 8?)
      }
    NotificationRecord(0x0def: pkg=com.android.systemui user=UserHandle{0} id=2)
      extras={
        android.title=String (USB debugging connected)
      }
    NotificationRecord(0x0123: pkg=com.google.android.gm user=UserHandle{0} id=3)
      extras={
        android.title=SpannableString (Banca)
        android.text=String (Estratto conto)
        android.bigText=String (Il tuo estratto conto di ottobre è disponibile)
      }
  Snoozed notifications:
    NotificationRecord(0x0abc: pkg=com.whatsapp user=UserHandle{0} id=1)
      extras={
        android.title=String (Mario Rossi)
        android.text=String (Ci vediamo alle 8?)
      }
"""


class NotificheTest(absltest.TestCase):

  def test_notifiche(self):
    notifiche = rubrica.leggi_notifiche(shell_fissa(DUMPSYS))
    self.assertEqual(
        [(n.app, n.titolo, n.testo) for n in notifiche],
        [('WhatsApp', 'Mario Rossi', 'Ci vediamo alle 8?'),
         ('Gmail', 'Banca', 'Il tuo estratto conto di ottobre è disponibile')])


if __name__ == '__main__':
  absltest.main()
