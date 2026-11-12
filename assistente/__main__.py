"""Avvio: `python -m assistente` (server) o `python -m assistente "frase"`.

Esempi:
  python -m assistente                       # avvia il server per l'app
  python -m assistente "alza il volume"      # prova un comando scritto
  python -m assistente --controlla           # verifica collegamento e permessi
"""

import argparse
import logging
import sys
import warnings

# Avvisi delle librerie Google usate da AndroidWorld: non ci riguardano.
warnings.filterwarnings('ignore', category=FutureWarning)

from assistente import cervello
from assistente import config as config_lib
from assistente import dispositivo as dispositivo_lib
from assistente import openrouter
from assistente import server
from assistente import strumenti as strumenti_lib


def costruisci(cfg: config_lib.Config, avanzamento=None):
  d = dispositivo_lib.Dispositivo(cfg.adb_path, cfg.seriale)
  env = dispositivo_lib.PixelEnv(d)
  # Smistatore veloce (capisce il comando) ed esperto (usa lo schermo).
  client = openrouter.OpenRouter(cfg.openrouter_api_key, cfg.modello,
                                 ragionamento=cfg.ragionamento)
  client_schermo = openrouter.OpenRouter(
      cfg.openrouter_api_key, cfg.modello_schermo
  )
  agente = cervello.AgenteSchermo(
      env, openrouter.OpenRouterMm(client_schermo), cfg.max_passi_schermo
  )
  descrittore = cervello.Descrittore(env, client_schermo)
  strumenti = strumenti_lib.Strumenti(
      d, agente, descrittore,
      annuncia=avanzamento.annuncia if avanzamento else None)
  return d, strumenti, cervello.Assistente(client, strumenti)


def riporta_app(d: dispositivo_lib.Dispositivo):
  """Dopo un comando rimette davanti l'app col pulsante.

  Non lo fa se l'utente ha chiesto di aprire un'app o se è partita una
  chiamata, per non coprirle.
  """

  def dopo(risposta: cervello.Risposta) -> None:
    if any(a.startswith(('chiama: OK', 'apri_app: OK'))
           for a in risposta.azioni):
      return
    d.shell(['am', 'start', '-n',
             f'{dispositivo_lib.PACCHETTO_APP}/.MainActivity'])

  return dopo


def controlla(d: dispositivo_lib.Dispositivo, strumenti) -> int:
  """Prova le letture principali e dice cosa funziona."""
  prove = {
      'Telefono collegato': lambda: d.seriale,
      'Schermo': lambda: '%dx%d' % d.dimensioni_schermo(),
      'Elementi sullo schermo': lambda: len(d.elementi_schermo()),
      'Contatti in rubrica': lambda: len(strumenti.contatti(ricarica=True)),
      'SMS': lambda: strumenti.esegui('leggi_sms', {'quanti': 1})[:60],
      'Chiamate': lambda: strumenti.esegui('chiamate_recenti', {'quante': 1})[:60],
      'Notifiche': lambda: strumenti.esegui('leggi_notifiche', {})[:60],
      'Servizio di accessibilità': lambda: (
          'attivo' if d.usa_accessibilita() else 'NON attivo (serve app 0.3)'),
      'App assistente installata': lambda: (
          dispositivo_lib.PACCHETTO_APP in d.shell(['pm', 'list', 'packages'])
      ),
  }
  errori = 0
  for nome, prova in prove.items():
    try:
      print(f'  ✓ {nome}: {prova()}')
    except Exception as e:  # pylint: disable=broad-exception-caught
      errori += 1
      print(f'  ✗ {nome}: {e}')
  return 1 if errori else 0


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description='Assistente vocale per Pixel')
  parser.add_argument('frase', nargs='?', help='Comando scritto da provare.')
  parser.add_argument('--controlla', action='store_true',
                      help='Verifica collegamento e permessi.')
  parser.add_argument('--verboso', action='store_true')
  args = parser.parse_args(argv)
  logging.basicConfig(
      level=logging.INFO if args.verboso else logging.WARNING,
      format='%(asctime)s %(message)s',
  )
  logging.getLogger('assistente').setLevel(logging.INFO)

  try:
    cfg = config_lib.Config.da_ambiente()
    avanzamento = server.Avanzamento()
    d, strumenti, assistente = costruisci(cfg, avanzamento)
  except (EnvironmentError, dispositivo_lib.ErroreDispositivo) as e:
    print(f'Errore: {e}', file=sys.stderr)
    return 1

  if args.controlla:
    return controlla(d, strumenti)

  if args.frase:
    risposta = assistente.rispondi(testo=args.frase)
    for azione in risposta.azioni:
      print(f'  · {azione}')
    print(risposta.testo)
    return 0

  import uvicorn  # pylint: disable=g-import-not-at-top
  d.inoltra_porta(cfg.porta)
  print(f'Assistente pronto sul telefono {d.seriale}.'
        ' Apri l\'app "Assistente" sul Pixel. Ctrl+C per uscire.')
  if d.usa_accessibilita():
    print('Servizio di accessibilità attivo: lettura dello schermo veloce.')
  else:
    print('Servizio di accessibilità NON attivo: installa la versione 0.3'
          ' dell\'app. Funziona lo stesso, ma più lentamente.')
  print(f'Modelli: {cfg.modello} (comandi), {cfg.modello_schermo} (schermo).')
  app = server.crea_app(assistente, d.seriale, dopo_comando=riporta_app(d),
                        avanzamento=avanzamento)
  uvicorn.run(app, host='127.0.0.1',
              port=cfg.porta, log_level='warning')
  return 0


if __name__ == '__main__':
  sys.exit(main())
