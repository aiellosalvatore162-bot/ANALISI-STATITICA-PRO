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
   per xG, corner, cartellini e arbitri. Fatto nella fase D con richieste
   dirette (ClubElo dalle pagine squadra; FBref bloccata; soccerdata tolta
   perché i suoi lettori ClubElo e FBref non funzionano). Il test del
   20/10/2026 usa l'Elo ClubElo reale; PSG-Barcellona e Napoli-Bodø sono
   `xfail` per input stimati.
3. **Registro delle previsioni** (probabilità stimata, quota, risultato) per
   misurare la calibrazione e il confronto con la quota di chiusura (CLV).
   Fatto nella fase H in versione Excel (vedi «Stato del progetto»).

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
- I gol attesi della simulazione sono quelli finali (`final_goal_rates`: modello
  ancorato alle quote 1X2/O-U 2.5); `expected_goals` resta il solo modello.
  Peso del mercato e metodo di margine si ritarano con
  `python -m tools.baseline --tara-ancoraggio`.
- La quota di gol del primo tempo (`primo_tempo` in `config/goal_model.json`) si
  ritara con `python -m tools.calibrate --primo-tempo`; i mercati secondari si
  misurano con `python -m tools.baseline --mercati-secondari`. Ogni script di
  taratura aggiorna solo la propria sezione del file di configurazione.
- Livello dati in `datasources/` (cache SQLite, nomi squadra, ClubElo, Understat,
  football-data.co.uk/.org, statistiche, compilazione del blocco) e interfaccia in
  `ui_data.py`. I test usano solo risposte salvate in `tests/fixtures/sources/`:
  nessuna chiamata di rete nei test. Corner e cartellini si ritarano con
  `python -m tools.calibrate --corner-cartellini` e si misurano con
  `python -m tools.baseline --corner-cartellini`.
- Cartellini in punti del bookmaker: regola in `regola_cartellini` di
  `config/goal_model.json` (`engine.CardRule`, default Eurobet giallo 1, rosso
  2, doppia ammonizione = giallo + rosso). Gialli come prima (arbitro e Claude
  sui gialli), rossi = `card_red_ratio` × gialli attesi; si ritarano con
  `python -m tools.calibrate --cartellini-punti` e si misurano con
  `python -m tools.baseline --cartellini-punti`. Nei dati inglesi/scozzesi la
  doppia ammonizione vale 2 invece di 3 (`SECOND_YELLOW_EXCLUDED_LEAGUES`).
- Fase M: totale corner ridotto verso `corner_shrink_reference` (peso
  `corner_shrink_weight`, ripartizione casa/ospite invariata) e gialli ×
  exp(`card_balance_intercept` + `card_balance_weight`·|ΔElo|/100), con le
  dispersioni della binomiale negativa ristimate insieme. Si ritarano con
  `python -m tools.calibrate --estremi` (dopo `--corner-cartellini` e
  `--cartellini-punti`; sezione `taratura_estremi`) e si misurano con
  `python -m tools.baseline --estremi`. Fuori campione = 2019-24 e 2026-27 (i
  parametri base sono tarati sul 2024-26). Nell'app l'EV sui corner porta
  l'avviso `CORNER_EV_WARNING` finché non ci sono quote corner (fase N).
- Fase N: The Odds API in `datasources/oddsapi.py` (cache 30 minuti, crediti
  da `x-requests-remaining` nella tabella `odds_api_usage`, budget mensile,
  istantanee `odds_snapshots` per le quote di chiusura), interfaccia in
  `ui_odds.py`, impostazioni e costi in `config/odds_api.json`. Chiave solo in
  `st.secrets["ODDS_API_KEY"]`, mai negli URL in cache, nei messaggi o nei test.
  Test con risposte registrate in `tests/fixtures/oddsapi/`. Corner e cartellini
  ancorati alle linee Over/Under quotate (`engine.CountAnchorParams`, sezione
  `ancoraggio_conteggi`, peso 0.8 dichiarato, non tarato); l'ancoraggio sta
  prima del fattore Claude.
- Fase N2 (risparmio crediti, nessun calcolo del modello toccato): profili dei
  mercati mirati in `profili_mercati_evento` (default `profilo_mirato` =
  «risparmio», solo corner e cartellini, 2 crediti a partita); quote per
  campionato solo per le competizioni con partite nel giorno
  (`OddsApi.sports_with_matches`, elenco eventi gratuito); punteggi solo per le
  competizioni con giocate nel registro (`scores_plan`, niente competizioni
  predefinite); budget mensile (`budget_mensile`, `giorni_di_gioco_mese`,
  `soglia_avviso` 0.8, `soglia_conferma` 0.95, `OddsApi.usage`/`budget_level`,
  `allow_high` per la seconda conferma); `day_cost` + `ui_odds.render_day_summary`
  per il riepilogo del costo previsto (da riusare prima di «Analizza tutte»
  nella futura pagina Oggi).
- Fase N3: quote Eurobet incollate in `eurobet.py` (parser a stati guidato dai
  titoli in `SECTIONS`: quota = due decimali dopo l'etichetta, mai slittata;
  linee e parametri con un decimale; sezioni sconosciute elencate), interfaccia
  in `ui_eurobet.py` (incollate per partita in `st.session_state`, scheda
  partita, «Quote del giorno», «Il mio gruppo» dei risultati esatti). Si
  riempiono solo i campi esistenti (chiavi del catalogo e gruppi esatti); i
  campi già valorizzati cambiano solo dopo conferma. `MatchConfig.anchor_odds`
  (None = come prima) separa le quote dell'ancoraggio da quelle dell'EV:
  `eurobet.anchor_odds` = sharp dell'API per i gol (`odds_sharp`), altrimenti
  Eurobet; tutta la scala Eurobet per corner e cartellini. Flag «Combo
  Builder» per mercato (`EurobetPaste.combinable`, `combo_allowed`) da usare
  nel costruttore di multiple (fase S). Test sui 3 esempi reali in
  `tests/fixtures/eurobet/`.
- Risultati esatti: `result["exact_scores"]` (finale, modello, mercato) dallo
  stesso campione; logica dei gruppi in `exact_scores.py` (coerenza e
  correlazione esatte per i mercati che dipendono dal solo punteggio finale),
  interfaccia in `ui_exact.py`. Verifica storica con
  `python -m tools.baseline --risultati-esatti` (sezione `risultati_esatti`).
- Dashboard: schede in `dashboard.py` (solo presentazione, nessun calcolo;
  HTML statico senza JavaScript con `esc` su ogni testo esterno; token colore
  chiaro/scuro, contrasto testo ≥ 4,5:1 verificato in `test_dashboard.py`).
  Tab in `streamlit_app.py`: Panoramica · Gol · Corner e cartellini · Risultati
  esatti · Claude · Registro · Prestazioni. Screenshot con
  `python -m tools.screenshots` in `docs/screenshot/`.
- Profili di stile in `datasources/style.py` (z-score per campionato, cache
  SQLite); archetipi in `config/style_archetypes.json`, rigenerati con
  `python -m tools.style`.
- Avversari simili in `datasources/similar.py` (profilo al momento della
  partita, niente dati futuri); validazione e scelta delle correzioni attive con
  `python -m tools.tactical` (scrive `docs/STILI.md` e la sezione
  `scenario_tattico` della configurazione).
- Integrazione con Claude solo via copia e incolla (`claude_bridge.py`): niente
  SDK anthropic né chiavi API. Le correzioni incollate sui gol si applicano dopo
  l'ancoraggio al mercato (`MatchConfig.claude`).
- Registro delle previsioni unico in `prediction_log.py`: colonne A–S del file
  dell'utente `tests/fixtures/Registro_Previsioni.xlsx` (nomi e ordine esatti),
  probabilità in decimali, nomi mercato fissi (`MARKETS`, i 29 del foglio
  Riepilogo; DNB con probabilità condizionata al non rimborso; cartellini in
  punti con la regola del bookmaker; «Risultati esatti» con Selezione =
  gruppo «1-0/2-0/2-1»), `ID` = data|partita|mercato|selezione come chiave (niente
  doppioni). Misure della pagina Prestazioni in `performance.py` (legge solo
  A–S, ricalcola le colonne grigie), interfaccia in `ui_performance.py`. Gli
  esiti si ricavano con le definizioni degli eventi del motore
  (`engine._event_catalog`); la compilazione automatica non sovrascrive mai
  valori presenti nel file e scrive fonte e data in `Note`.
- Fase K: memoria delle partite analizzate in `match_memory.py` (voce per
  partita con blocco, quote dei campi, incollata Eurobet, risposta di Claude,
  segnalazioni e riassunto; chiave data|casa - ospite) e Excel della giornata
  (fogli Registro A–S, Analisi, Doppio pronostico, Report Analista, Schedine, Schede tattiche, Tecnico nascosto in JSON
  diviso in celle da 30.000 caratteri); interfaccia in `ui_memory.py`
  (`st.session_state["analyzed_matches"]`, barra laterale disegnata in fondo
  allo script, riapertura con `auto_simulate`, «Riprendi da file»). Il registro
  della sessione resta la tabella SQLite `registro` (`PredictionLog.delete`
  per eliminare righe).
- Fase S: pagina «Oggi» (`ui_today.py`, logica in `today.py`, filtri in
  `config/oggi.json`) e costruttore di multiple (`multiples.py`: gambe,
  trappole, singole/doppie/corta/lunga con programmazione dinamica, riga
  «Multipla» del registro). Probabilità congiunte dei Combo Builder in
  `result["joint_pairs"]` (`engine.joint_pair_probabilities`, stesso
  campione). Segnalazioni e Claude multi-partita come `ClaudeAdjustment` dopo
  l'ancoraggio. Esito delle multiple con `performance.settle_multiples`;
  verifica esiti con Claude (`today.outcome_prompt`/`parse_outcomes`) nella
  pagina Prestazioni. Fase S2: quota CB reale (`cb_real_odds` per
  `Leg.key`) o stimata (prodotto × `sconto_cb`), nota «quota CB reale/stimata»
  nella riga Multipla e `performance.observed_cb_discount`; segnalazioni nella
  scheda (`ui_memory.flags_key`, combinate con Claude da
  `today.combined_adjustment`) e blocco Claude per partita
  (`today.split_multi_response`) riaperti da «Apri scheda». Demo per gli screenshot: `python -m tools.screenshots
  --oggi` (quote registrate, dati reali).
- Fase U: doppio pronostico in `dual.py` (scelta del simulatore = singola più
  probabile non trappola; fonti in Note «fonte: simulatore, osservatore,
  unita», una riga per selezione, `Prob_finale` del simulatore anche per
  l'osservatore; classifiche, disaccordi e suggerimenti dopo
  `min_weekend_suggerimento` weekend), sezione in `ui_today._render_dual`, misure
  in `ui_performance._dual_section`, foglio «Doppio pronostico» dell'Excel della
  giornata (`st.session_state["dual_choices"]`).
- Fase W: report dell'Analista in `analyst.py` (blocchi «PARTITA: Casa -
  Ospite | competizione | data» + CORREZIONI_CLAUDE letti con
  `claude_bridge.parse_response`; abbinamento con `datasources.names.match_team`
  e data ±1 giorno, una partita per blocco, motivi dei mancati abbinamenti),
  sezione `ui_today._render_analyst`, report in
  `st.session_state["analyst_reports"]` e nel foglio «Report Analista»
  dell'Excel della giornata. Esempio di test in
  `tests/fixtures/analista/report_esempio.md`.
- Fase X: ricerca rapida in `quick_search.py` (regole sul testo: numero,
  mercato/linea, soglia, fascia oraria; `build` con anti-trappola), frequenza
  storica recente in `recent_form.py` (football-data, solo mercati simmetrici,
  «campione piccolo» sotto 8), schedine salvate in `slips.py`
  (`st.session_state["saved_slips"]`, foglio «Schedine», esiti con
  `update_from_results`), interfaccia in `ui_quick.py`. Marcatori in
  `scorers.py` (quota xG con shrinkage verso `PRIOR_SHARE`, minuti per presenza,
  distribuzione simulata dei gol della squadra; NON verificato fuori campione),
  interfaccia `ui_scorers.py` nella tab Gol. Chiavi del match in `match_keys.py`
  (blocco `CHIAVI_MATCH:`, max 4, fonte obbligatoria, solo informative;
  `claude_bridge.parse_response` si ferma prima delle chiavi), scheda
  `dashboard.keys_card` nella Panoramica. Report con squadre invertite:
  abbinato scambiando correzioni e duelli (`match_keys.swap_text`).
- Fase T: divisione dei cartellini tra le squadre (`engine.CardSplitParams`,
  sezione `divisione_cartellini` di `config/goal_model.json`, `attiva`), verificata
  e scelta con `python -m tools.card_split [--salva] [--output docs/BASELINE.md]`
  (taratura 2024-26, fuori campione 2019-24 e 2026-27; una componente resta solo se
  migliora log-loss ED ECE medie). Accese: ritmo + provocati con shrinkage,
  sfavorita = P(2) − P(1), bilanciamento (binomiale moltiplicativa); spente: Elo,
  casa, beta-binomiale, arbitro. Matematica unica `engine.card_points_joint` /
  `split_log_pmf` (usata anche dallo strumento). Campo facoltativo del blocco
  «Cartellini provocati». Ancoraggio a 1X2 cartellini e linee per squadra con
  peso 0.8 dichiarato. `engine.flag_count_disagreements`: scarto > 10 punti su
  corner/cartellini = avviso e niente verde. Liste e multiple di Oggi escludono
  i cartellini per squadra se l'ECE supera `cartellini_squadra.ece_massimo`.
- Fase O (parte 1): motore minuto per minuto in `timeline.py` (blocchi di 5
  minuti, `MatchConfig.timeline`, sezione `minuto_per_minuto`: `attivo`,
  `componenti` gol_stato/espulsioni/corner_pressione/cartellini_tempo,
  `parametri`). Senza regole sui gol i punteggi restano Dixon-Coles e si
  distribuiscono nei blocchi. Dati: `python -m tools.minute_data` (Understat
  2023-25, StatsBomb Open Data 2015/16, cache `data/cache/minuto`), regole:
  `python -m tools.minute_model --salva`, verifica e scelta:
  `python -m tools.minute_check --salva` (regola: log-loss giù di oltre 2
  errori standard appaiati ED ECE non peggiore). Esito attuale: tutto spento.
- Fase Q: schede tattiche in `tactical_sheets.py` (blocchi `PROFILO_TATTICO:` letti in modo tollerante,
  profilo senza link scartato, conferma in tabella prima del salvataggio; indizi dai profili di stile e
  avvisi di contrasto, mai correzioni), interfaccia in `ui_tactical.py` (pagina Oggi e riquadro della
  Partita, `st.session_state["tactical_sheets"]`, foglio «Schede tattiche» con `SHEET_COLUMNS`).
  Cambio allenatore: `datasources.stats.CoachChange` (gare precedenti ×0.3, riavvicinamento alla media
  sotto 8 gare, avviso «Allenatore nuovo da N partite»). Incroci in `config/tattica.json` (limiti
  0.90-1.12, attenuati dall'adattabilità), applicati con `today.combined_adjustment(tactical=...)` solo
  se `attiva`; stima e verifica con `python -m tools.style_data` + `python -m tools.tactical_cross --salva`
  (oggi tutte spente). Reazioni → `TimelineParams.reactions` (contano solo col motore a blocchi acceso).
  Nota del registro «scheda tattica: sì/no» (`prediction_log.TACTICAL_NOTE`), confronto in
  `performance.tactical_comparison`. Nuovi mercati 6b in `market_catalog.py` (verifica:
  `python -m tools.new_markets`; corner e cartellini per tempo non verificabili). Goleade:
  `python -m tools.goleade --salva` (sezione `goleade`, spenta), riga «Goleada» della Panoramica.
- Fase P (motore v2): ogni punto è una sezione di `config/goal_model.json` con `attiva`, verificata con la
  regola severa sul campione comune `tools/v2common.py` (cache `data/cache/fase_p/`). Forza Dixon-Coles per il
  calendario in `ratings.py` (`forza_calendario`, `python -m tools.strength_check`, builder modo «ingressi»);
  incertezza, pesi del mercato per campionato/tipo (`engine.anchor_goal_rates_split`, `MatchConfig.league`) e
  riposo (`MatchConfig.rest_days`) in `tools/model_v2.py`; ricalibrazione finale per mercato
  (`tools/recalibration_check.py`, metodo in validazione incrociata, correzione di Holm; `engine.apply_recalibration`
  anche sull'EV); soglie EV = errore tipico (`tools/value_thresholds.py`, `soglie_valore`, usate da
  `today.ev_threshold` e da `is_value`). Opzioni lette in `engine.ModelV2Params` (`MatchConfig.v2`). Assenze
  pesate in `absences.py` (righe `assenti_casa`/`assenti_ospite` del blocco di Claude, sezione «Assenze pesate»
  della tab Gol), marcatori v2 in `scorers.py` (sezione `marcatori`); storico giocatori con
  `python -m tools.player_data 2025 2026` e verifica con `python -m tools.player_check --salva`. Accese oggi:
  ricalibrazione di «Over 3.5 cartellini» e marcatori v2 (verificati); il resto è spento.
- Fase Y (dati dell'Analista): report completo in `analyst.parse_full` (blocchi ESITO, PARTITA +
  CORREZIONI_CLAUDE + CHIAVI_MATCH, PROFILO_TATTICO; ogni blocco finisce dove inizia il successivo; esempio
  completo in `tests/fixtures/analista/report_completo.md`). Formato ESITO (casa-ospite, una riga per voce,
  righe facoltative omesse): `ESITO: Casa - Ospite | competizione | gg/mm/aaaa hh:mm`, `risultato`,
  `primo_tempo`, `corner`, `corner_1t`, `gialli` (con il primo giallo di chi è espulso per doppia
  ammonizione), `gialli_1t`, `rossi`, `rossi_1t`, `doppie_ammonizioni`, `fonte: https://...` (obbligatoria).
  Esiti nel registro e nelle schedine con `analyst.fill_registry`/`fill_slips` (mai sovrascritti, fonte in
  Note; mercati per tempo in `performance.settle`), profili con `analyst.merge_profiles` (conferma solo se
  cambia un valore). Storico proprio in `analyst_dataset.py` (tabella SQLite `dataset_analista`, foglio
  «Dataset Analista» + JSON «dataset» nel foglio tecnico, `ui_memory.analyst_records`). Regole dell'Analista
  in `config/tattica.json` sezione `regole_analista` (`tactical_sheets.analyst_adjustment`, solo profili
  PROFILO_TATTICO, limiti 0.95-1.05, stato da verificare/verificata/spenta, nota «regole_analista: sì/no»),
  verifica e mercati per tempo nella pagina Prestazioni (`verify_rules`, `half_calibration`,
  `apply_proposal` dopo conferma). Forza per il calendario solo senza quote 1X2/O-U
  (`forza_calendario.solo_modello`, `MatchConfig.strength_inputs`, `engine.strength_model_config`).
  Eurobet contro sharp in `sharp_value.py` (soglia `eurobet_vs_sharp.soglia_pct` di `config/oggi.json`,
  nota «eurobet_vs_sharp: +x%», `prediction_rows(extra_notes=...)`).
- Blocco facoltativo `FORMA:` nelle partite del report (`match_form.py`: righe `casa:`/`ospite:` con
  ultime 5 V-N-P, `gol_fatti_subiti`, `in_casa`/`in_trasferta`, `fonte` obbligatoria per riga, `nota`;
  lettura tollerante, tolto dal corpo prima di correzioni e chiavi). SOLO informativo: mai nel motore
  (probabilità, gol attesi, EV, semaforo, ancoraggio). Scheda `dashboard.form_card` nella pagina Oggi, colonna
  «Forma» del registro (SQLite e colonna Z dell'Excel, scritta solo se c'è almeno una forma: A–S e le formule
  T–Y del file dell'utente restano intatte) e del foglio Analisi (`ui_memory.with_form`/`form_for`).
- Fase V/L (velocità di Oggi, nessun calcolo del modello cambiato): ClubElo (`datasources/clubelo.py`) rileva il
  blocco (403/502/503 o pagina Cloudflare), si segna «non disponibile» per la giornata nella cache e non si aggira;
  l'Elo si calcola dai risultati (6 stagioni di CSV, `DataProvider._results_elo`), dichiarato «Elo da risultati
  (ClubElo non disponibile)», e resta MANCANTE per le coppe tra campionati diversi (da inserire a mano nel blocco
  CASA/OSPITE). `DataProvider` legge una volta per campionato e stagione (`_remember`, azzerato da `refresh`).
  `today.prepare` (dati, blocco, configurazione, niente simulazione né The Odds API) è usata da «Prepara la
  giornata» e da `today.analyze`; ogni partita non analizzata ha `Analysis.problem` (fase, fonte, messaggio) e
  compare in «Partite non analizzate» (`today.problem_rows`). Cronometro per fase in `timing.py` (`fase`,
  `registra`, `Registro.breakdown`), expander «Tempi» in Oggi. Benchmark: `python -m tools.bench_oggi [--offline]`
  (`docs/bench/oggi_prima.md`, `oggi_dopo.md`). Nessun parallelismo (scelta voluta).
- Fase R («Modifica o completa i dati» in Oggi): `manual_data.py` (store `st.session_state["manual_fields"]`, chiave
  data|Casa - Ospite; per campo valore, origine «manuale», fonte «inserito a mano», momento). Precedenza fissa
  manuale > automatico > proxy/stima (`FieldValue.origin`): `today.prepare(manual=..., auto_sheet=...)` mette i
  manuali sopra la scheda automatica, quindi un nuovo Prepara/Analizza non li tocca; «Ripristina dati
  automatici» li toglie. Blocchi anche parziali con `parser.parse_partial_input` (stesso tokenizer e stessi
  validatori di `parse_match_input`, righe # ignorate; la pagina Partita non cambia); squadre controllate con
  `match_team`, se non corrispondono niente viene applicato. Interfaccia in `ui_manual.py` (expander per partita,
  aperto se mancano dati; anteprima campo | automatico con fonte | blocco | cosa succede; ricalcolo di una sola
  partita senza rete e con una sola simulazione). `Analysis.auto_sheet`/`odds_fields`/`manual`. Scheda partita:
  `provenance_rows` ha la colonna «Origine» e il record in memoria conserva `fields`. Excel: foglio «Manuali» +
  voci «manuale» nel Tecnico (tornano con «Riprendi da file»). Non fatto: «Incolla per più partite».
- Fase Z (quote da qualunque bookmaker): modello neutro `quotes/model.py` (`QuoteMercato`, sospesa = None, mai zero;
  `consolidate`: a mano > sharp `bookmaker_sharp` > mediana, scarto > `scarto_bookmaker` segnalato), pagine incollate in
  `quotes/pages.py` (`split_pages`, `detect_format` per pagina, `assign_pages` abbinata/ambigua/non trovata), adattatori
  in `quotes/adapters/` (eurobet sul parser esistente, generico, oddsapi, csv_chiusura). Archivio unico della giornata
  `day_archive.py` (`st.session_state["day_archive"]`, chiave `match_memory.match_id`; selezione max 8 / «Da giocare»
  max 5 da `config/oggi.json`; conflitti in `pending`, confermati con `resolve_pending`; dati a mano della fase R nelle
  voci, `ui_manual.ManualView`), interfaccia `ui_quotes.py`. Raccolta The Odds API in `quotes/collect.py` (livelli A/B,
  `preconto`, tetto giornaliero, un nuovo tentativo, tabella `quote_crediti`, sezione `raccolta` di
  `config/odds_api.json`); «Analizza tutte» (`ui_today._analyze_day`) usa solo l'archivio. «I miei mercati» in
  `my_markets.py`, combo builder in `combo.py` su `result["event_samples"]` (`MatchConfig.keep_samples`, solo «Da
  giocare»). Test in `test_quotes.py` con fixture `tests/fixtures/quote/`.
- Fase Z2 (report quote): `quote_report.py` legge solo l'archivio unico (nessuna rete, nessuna simulazione): righe =
  partite selezionate («Da giocare» prime), colonne = mercati di «I miei mercati» (risultati esatti in una colonna);
  cella ✓ quota · bookmaker · fonte · ora, oppure ✗ con motivo (sospesa, assente nella pagina incollata, non offerto
  dall'API, fuori livello B, non raccolta). `to_paste`/`paste_text` = lista «Da incollare a mano» con bookmaker suggerito;
  `summary` = quote per fonte/bookmaker, partite complete, crediti dal registro `quote_crediti`, proiezione a 30 giorni.
  Interfaccia `ui_quotes.render_quote_report` (expander in Oggi), foglio «Report quote» dell'Excel (derivato: si
  ricalcola dall'archivio al ripristino). Test in `test_quote_report.py`.
- Fase AD (stile, forma reale, banco walk-forward): `style_profile.py` (ultime 8 gare con media esponenziale, casa e
  trasferta separate, shrinkage n/(n+k) verso il campionato, winsorizzazione ai percentili 2-98 del campionato con avviso;
  xG Understat, altrimenti proxy dai tiri `config/proxy_xg.json` (`python -m tools.proxy_xg --salva`, usato solo se R² ≥ 0.5),
  altrimenti gol; `get_style_params(squadra, data, casa, store)`, `load_store` una volta per campionato al giorno in
  `data/cache/stile/`, foglio «Stile» dell'Excel). Impostazioni in `config/stile.json` (interruttore per componente).
  `engine.StyleModelParams` / `MatchConfig.style`: la forma reale (xG−xGA per gara, centrata sul campionato) sostituisce la
  forma W-D-L con peso `phi` (stimato dal banco: `--salva-phi`) e `k_xg` alza il peso xG con poche gare; voce `forma_reale`
  nel formula_ledger. Nota: il modello calibrato ha `form_weight=0` e `attack_xg_share=1`, quindi la forma reale AGGIUNGE un
  termine e `k_xg` agisce solo sulla difesa. `today.prepare(style_loader=...)` la collega (senza dati resta com'era, con
  avviso). Banco `tools/backtest_wf.py` (`run(config_attuale, config_nuova, campionati, stagioni, mercati)`, 25 mercati, solo
  passato, phi ristimato ogni mese, output `docs/backtest/<nome>.md/.csv`); stato dei lavori in `docs/stato/AD.md`. Test in
  `test_style_profile.py`.
- Fase AL (formazioni e giocatori): `players.py` (tassi npxG/xA/tiri per 90 dalle rose Understat in cache `data/cache/fase_p`,
  decadimento 240 giorni su 2 stagioni, shrinkage n/(n+k) verso la media del RUOLO POR/DIF/CEN/ATT, winsorizzazione ai
  percentili del ruolo con avviso, rigori da `penalties`), `lineup.py` (XI tipo = ultimi 5 undici, formazione/assenti dal report
  dell'Analista via righe facoltative `formazione_casa/ospite: 11 nomi | fonte: url` e `assenti_*` di `claude_bridge`, minuti attesi,
  assenti PESATI, fattore attacco = produzione XI atteso / XI tipo ^ esponente, fattore difesa per ruolo, rigorista con
  sostituto, «sta performando» gol−npxG con shrinkage x/(x+k); `get_lineup_params(casa, ospite, data, store, report=...)`).
  Impostazioni e stime in `config/giocatori.json` (`python -m tools.lineup_check --salva` → `docs/backtest/AL_giocatori.md`).
  Esito del backtest (1606 partite): esponente attacco ≈ 0 (−0.10 ± 0.21), pesi difesa non stimabili → fattori neutri (1.0)
  e difesa solo etichetta; k performando 14.2 (giocatore) e 37.4 (squadra). `MatchConfig.lineup` agisce prima
  dell'ancoraggio (ledger `formazione`); `absences.is_active` è spento se la formazione sposta i gol (niente doppia conta con
  la P). «Sta performando» non entra nei gol attesi (l'attacco è già solo xG; la forma reale della AD è xG−xGA). Riquadro in
  `ui_lineup.py`; stato in `docs/stato/AL.md`; test in `test_lineup.py`.
- Fase AH (stili e report dell'Analista come input del motore): `outcomes.py` unifica gli esiti (CSV > ESITO con fonte >
  ESITI_CLAUDE, campo per campo; conflitti sempre mostrati; `lookup` per la verifica delle gambe; `today.parse_outcomes` delega),
  `tactical_sheets.parse_profiles(origin, day)` è l'unico parser dei profili (`analyst.parse_profiles` lo chiama per regione),
  campi facoltativi in PARTITA letti da `match_extras.py` (ASSENTI_PESATI, RIPOSO, TURNOVER; riga non valida scartata con avviso;
  formato in `docs/formato_analista.md`, esempio `tests/fixtures/analista/report_ah.md`). `match_context.match_context(...)`
  è il contratto verso il motore: stile misurato (AD), profilo qualitativo come PRIOR dei numeri (valore = w·dato + (1−w)·prior,
  w = n/(n+k), `config/stile_prior.json`, prior `null` finché mancano ≥5 squadre con profilo e dati: `python -m tools.stile_prior`),
  adattabilità, reazioni di stato, cambio allenatore, assenti pesati / turnover (nell'AL: un assente noto a Understat conta una
  volta sola; solo gli altri entrano col peso scritto), riposo del report solo se manca il calendario
  (`today.apply_report_context`), CORREZIONI_CLAUDE come prima. `FIELD_STATUS` elenca ogni campo del report come assorbito o
  «solo informativo». Riquadro «Stile» in `ui_style.py` (vista compatta sortabile, foglio «Stile» dell'Excel, voce `contesto` nel
  dataset Analista). Il report resta facoltativo. Test in `test_style_context.py`; stato in `docs/stato/AH.md`.
- Fase AK (motore a eventi, in corso sul ramo `fase-ak-motore-eventi`, stato in `docs/stato/AK.md`): dizionario tattico
  `config/dizionario_tattico.json` + `tactical_dictionary.py`, messa in campo `formation.py`; stima dei parametri con
  `python -m tools.stima_motore` → `config/motore_eventi.json` (tipi di tiro, corner per origine, stato di partita, incroci
  spenti, arbitri da `referee_stats.py`) e beta del dizionario (solo se l'IC 95% esclude lo zero), report `docs/backtest/AK_stima.md`.
  Stadi 3-8 in `event_engine.py` (stato della partita, tiri per tipo a passi di 5 minuti, gol, corner per origine, falli e cartellini con arbitro ed espulsioni; modo «punteggi» = punteggi
  Dixon-Coles fissi con eventi condizionati, modo «libero» = gol dai tiri riscalati su λ/μ). Stadi 9-11: vincolo di coerenza
  `event_engine.coherence` (corner di gioco, gialli, rossi, quota 1T e dispersione gamma riportati alle medie FINALI del motore
  attuale), arresto adattivo `simulate_adaptive` (errore Monte Carlo ≤ `tolleranza_pp`, max 100.000, primi n punteggi per tutti i
  mercati), aggancio `MatchConfig.event_engine` / `event_inputs` (sezione `motore_eventi` di `config/goal_model.json`, `attivo:
  false` finché lo stadio 14 non lo verifica; incompatibile con la fase O accesa), dettagli in `result["event_engine"]`.
  Stadi 12-14: attenuazione degli effetti di stato stimata (`stato_partita.attenuazione`, esponente 0,53), scenari
  `python -m tools.event_sense`, banco `python -m tools.event_check [--salva] [--ricomincia]` (parziali con ripresa in
  `data/cache/event_check/`). Esito del 30/10 su 1.454 partite: SPENTO (corner e combo meglio, cartellini peggio).
  Ultima parte: uomo in meno su falli e gialli stimato tra partite (`stima_motore.fit_men_between`, gialli ×0,87 invece di
  ×0,39), legame cartellini per inferenza indiretta (`python -m tools.event_cards --salva`, sezione
  `stato_partita.legame_cartellini`: esponente di stato dei gialli, partita calda sui rossi), motore per gruppi di mercati
  (`motore_eventi.mercati`: tempi/corner/cartellini, `EventEngineParams.markets`), seconda verifica
  `python -m tools.event_check --campione nuovo [--salva]` (2019/20 + 2023/24, 2.672 partite, variante «eventi solo
  corner»): SPENTO (corner meglio, combo del motore completo pari, cartellini peggio; «solo corner» candidata per un terzo
  campione). Stadio 15 «Vedi come andrà»: `match_story.py` + `ui_story.py` nella Panoramica (andamento per fasce dagli stessi
  percorsi, oppure illustrativo dichiarato col motore spento; `event_engine.timeline_summary`, `result["event_engine"]["andamento"]`).
- Le fonti remote devono degradare con un avviso (come `historical.py` ricade
  al 100% manuale), mai bloccare la simulazione manuale.

## Stato del progetto (29/10/2026, dopo la fase Z)

- Fasi completate e unite a `main`: modello gol log-lineare (1), ancoraggio al
  mercato (2), mercati secondari (C2), livello dati (D), football-data.org,
  profili di stile (E), avversari simili (F, attive le correzioni cartellini
  e, dalla fase M, corner), Claude via copia e incolla (G), registro Excel e pagina
  Prestazioni (H), allineamento ai 19 mercati del Riepilogo (H2), punti
  cartellini con la regola Eurobet (H3), risultati esatti e gruppi (I),
  dashboard a tema calcio (J), taratura corner e cartellini con shrinkage dei
  corner ed equilibrio Elo sui cartellini (M), quote automatiche The Odds API
  con ancoraggio di corner e cartellini (N), risparmio crediti con budget
  mensile (N2), quote Eurobet incollate (N3), registro cumulativo ed Excel della
  giornata (K), pagina Oggi e costruttore di multiple (S), rifiniture delle multiple
  (S2), doppio pronostico Simulatore/Osservatore/Unita (U), report dell'Analista
  del giorno (W), ricerca rapida, schedine salvate, marcatori e chiavi del match (X),
  cartellini per squadra (T), motore minuto per minuto come opzione spenta (O, parte 1), schede
  tattiche, cambio allenatore, incroci di stile (spenti), nuovi mercati e goleade (Q), motore statistico
  v2 con opzioni verificate una per una (P), dati dell'Analista nel modello e storico proprio (Y), modifica
  dei dati in Oggi (R), quote da qualunque bookmaker con archivio unico e combo builder (Z), profilo di stile, forma reale e
  banco walk-forward (AD), formazioni e giocatori (AL), stili e report dell'Analista come input (AH), motore a eventi verificato
  due volte e lasciato spento, con il riquadro «Vedi come andrà» (AK).
- Test: `python -m pytest -q` (solo fixture salvate, nessuna rete); 2 `xfail`
  noti (PSG-Barcellona, Napoli-Bodø, input stimati).

## Prossimi passi

1. Usare il registro per qualche settimana: con almeno 100 selezioni con esito
   per mercato il giudizio della pagina Prestazioni diventa significativo.
2. Quote di chiusura per Multigol e per i mercati senza istantanea (The Odds
   API salva solo le quote per campionato scaricate prima del via).
3. Esiti di corner, cartellini e primo tempo delle coppe: ora arrivano dai blocchi
   ESITO dell'Analista; servono settimane di report per riempire il dataset
   (150 partite per le regole, 100 con i tempi per i mercati per tempo).
4. Se il confronto delle componenti mostra che stile o Claude non migliorano il
   Brier rispetto a modello/mercato, disattivarli con le opzioni esistenti.
