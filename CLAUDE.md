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
- Le fonti remote devono degradare con un avviso (come `historical.py` ricade
  al 100% manuale), mai bloccare la simulazione manuale.

## Stato del progetto (28/10/2026, dopo la fase Y)

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
  v2 con opzioni verificate una per una (P), dati dell'Analista nel modello e storico proprio (Y).
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
