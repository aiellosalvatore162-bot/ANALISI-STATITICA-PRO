# CLAUDE.md

Simulatore di pronostici calcistici: app Streamlit (`streamlit_app.py`) con motore
Monte Carlo Dixon-Coles (`engine.py`), parser dell'input testuale (`parser.py`),
catalogo mercati (`market_catalog.py`) e modello storico/backtest su CSV
Football-Data.co.uk (`historical.py`). Test: `test_engine.py`, `test_parser.py`,
`test_historical.py` (pytest).

## Priorità di lavoro

1. **Compressione delle favorite in `engine.py`.** Il modello comprime le favorite
   nette (es. City 63% vs mercato 88%, Roma 62% vs 84%) e genera falsi "VALORE"
   su X e 2. Correggere il modo in cui Elo, forma e xG vengono combinati nelle
   medie gol (`expected_goals`), verificando con `test_engine.py`.
2. **Recupero automatico dei dati da fonti gratuite** al posto dell'inserimento
   manuale: ClubElo per l'Elo; FBref/Understat tramite la libreria `soccerdata`
   per xG, corner, cartellini e arbitri.
3. **Registro delle previsioni** (probabilità stimata, quota, risultato) per
   misurare la calibrazione e il confronto con la quota di chiusura (CLV).

## Modalità di lavoro

- Il piano viene deciso fuori da questa sessione: quando ricevi un prompt di fase,
  ESEGUILO DIRETTAMENTE senza chiedere conferma, prendendo tu le decisioni
  tecniche ragionevoli.
- Fermati e chiedi SOLO se sei bloccato: manca una chiave/credenziale, una fonte
  dati non è più disponibile e non c'è alternativa gratuita, oppure una scelta
  cambierebbe in modo irreversibile i dati o il comportamento dell'app.
- Per ogni fase: crea un ramo git dedicato, commit piccoli con messaggi in
  italiano, test pytest per ogni nuova logica.
- A fine fase, SOLO se tutti i test passano (`python -m pytest -q`) e l'app si
  avvia senza errori (prova di avvio con streamlit in modalità headless), unisci
  il ramo a `main` e fai push. Se qualcosa non va, lascia il lavoro sul ramo e
  spiega il problema.
- Chiudi sempre con un RIEPILOGO in italiano semplice: cosa è cambiato, file
  toccati, numeri prima/dopo (se c'è una misura), limiti e cose da fare a mano.
- Non rompere mai il formato di input testuale attuale del parser.
- Mai chiavi nel codice: `st.secrets` / variabili d'ambiente, file sensibili in
  `.gitignore`.
- Ogni miglioramento del modello va misurato: se non migliora le metriche,
  disattivalo con un'opzione invece di lasciarlo attivo.
- Comunicare in italiano; messaggi, etichette UI ed errori restano in italiano
  come nel codice esistente.

## Convenzioni del progetto

- Nessun valore inventato: il parser fallisce con messaggio esplicito se manca un
  campo (modalità `strict`); niente default nascosti per le squadre. I dati
  recuperati automaticamente devono restare visibili/modificabili e dichiarare
  fonte e data.
- Tutti i mercati derivano dallo stesso campione di punteggi simulati
  (`simulate_match`); non ricampionare i gol per singolo mercato.
- `expected_goals` restituisce un `formula_ledger` leggibile: va aggiornato
  insieme alla formula.
- I parametri del modello gol stanno in `config/goal_model.json` e si rigenerano
  con `python -m tools.calibrate`; ogni modifica al modello va misurata con
  `python -m tools.baseline --label ... --output docs/BASELINE.md`. La formula
  originale resta disponibile come `goal_model="legacy"`.
- Le fonti remote devono degradare con un avviso (come `historical.py` ricade
  al 100% manuale), mai bloccare la simulazione manuale.
