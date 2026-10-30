# Stato Fase AK (motore a eventi per partita)

Ramo: `fase-ak-motore-eventi` (da `main` dopo la fase AH). `docs/FONTI.md` non esiste: niente scraping di designazioni arbitrali.

## Stadio 0-1 – stato e riuso (FATTO, solo ricognizione, nessun codice cambiato)

### Cosa hanno lasciato O e Q
- `timeline.py` (blocchi di 5 minuti, 18 blocchi, bande 0-30/30-60/60-75/75-90, stati di punteggio −2…+2), agganciato in
  `engine.py` come `MatchConfig.timeline` (circa righe 1956-1997: `_timeline.sample(..., scores=(goals_home, goals_away))`).
- Componenti in `config/goal_model.json` → `minuto_per_minuto`: `gol_stato`, `espulsioni`, `corner_pressione`, `cartellini_tempo`
  (fase O) e `tempi_stato`, `espulsioni_tempi` (fase Q: punteggi finali Dixon-Coles FISSI, lo stato decide solo QUANDO arrivano i
  gol e guida corner e cartellini). TUTTO SPENTO: verifica del 27/10 su 1.754 partite, log-loss 0,6153 (attuale) contro
  0,61528-0,61533, nessuna differenza oltre 2 e.s.
- Con `scores=` (approccio di default) i punteggi restano quelli Dixon-Coles del motore → la correzione sui punteggi bassi resta
  intatta. Con `gol_stato` i gol nascono dal percorso e la correzione NON è garantita: resta spento (decisione: si parte dai punteggi
  Dixon-Coles fissi e si condiziona tutto il resto).
- Reazioni delle schede tattiche → `TimelineParams.reactions` (contano solo col motore a blocchi acceso).

### Dati StatsBomb già su disco (`data/cache/minuto/`, 2,1 MB)
- `statsbomb_<comp>_27.json.gz`: 1.551 partite 2015/16 (Premier, Liga, Serie A, Bundesliga, Ligue 1 parziale 34 partite). Eventi
  RIDOTTI: tiro (minuto, tempo, squadra, xG, gol), corner, fallo (con cartellino), cartellino non da fallo, autogol.
- `stili_statsbomb.json.gz` (fase Q, `tools/style_data.py`): 3.102 righe squadra-partita con passaggi, progressione, altezza media
  delle azioni difensive (`def_x/def_n`), pressioni, cross, passaggi sulle fasce (`wide`), tiri, xG, corner, falli, passaggi avversari.
- MANCANO per i punti 2 e 5-6: tipo di tiro (azione / testa da cross / transizione / fuori area / palla inattiva / rigore),
  esito del tiro (parato, deviato, bloccato) e origine del corner (da tiro deviato/parato o da gioco sulle fasce), zona del fallo.
  → DECISIONE: estendere `tools/minute_data.download_statsbomb` con una cache «dettaglio» separata
  (`statsbomb_dettaglio_<comp>_<season>.json.gz`, solo i campi compatti: `shot.type`, `body_part`, `play_pattern`, `outcome`,
  posizione in zone/corsie, `pass.cross`, origine del corner = evento precedente nello stesso possesso, fallo con zona). Una sola
  volta, ~1.551 file grezzi da 3-4 MB letti e scartati (qualche GB di traffico, ~decine di MB salvati). Le cache attuali restano.

### Altro da riusare
- Banco walk-forward della AD: `tools/backtest_wf.run(config_attuale, config_nuova, campionati, stagioni, mercati)` con 25 mercati
  (da estendere con corner per squadra 3.5/5.5, cartellini per squadra 1.5/2.5 e combo gol+corner, gol+cartellini).
- `style_profile.get_style_params` (AD), `lineup.get_lineup_params` (AL: XI atteso, minuti, rigorista, conversione),
  `match_context.match_context` (AH: profilo come prior, reazioni, adattabilità, assenti, riposo, turnover).
- Combo builder: `result["event_samples"]` (`MatchConfig.keep_samples`) e `combo.evaluate` (fase Z): il motore a eventi deve
  riempire gli stessi campioni.

### Formule attuali di corner e cartellini (da NON correggere di nuovo: il motore a eventi si riscala su queste medie)
- Corner modello (fasi C2/M): λ_casa = exp(a_casa + w_for·log corner_fatti_casa + w_against·log corner_concessi_ospite), simile per
  l'ospite; totale ridotto verso `corner_shrink_reference` con esponente `corner_shrink_weight` (ripartizione casa/ospite invariata);
  × fattori tattici (avversari simili, fase F). Poi ancoraggio alle linee Over/Under quotate (fase N, finale = mercato^0.8 ·
  modello^0.2) e fattore Claude. Distribuzione: binomiale negativa con `corner_dispersion`.
- Gialli modello (fasi C2/H3/M): exp(c + w_squadre·log(gialli_casa + gialli_ospite) + w_arb_gialli·log media_gialli_arbitro +
  w_arb_falli·log media_falli_arbitro + card_balance(|ΔElo|)) × fattore tattico; poi ancoraggio (0.8) e Claude. Rossi =
  `card_red_ratio` × gialli attesi; punti con la regola Eurobet (`regola_cartellini`). Divisione tra le squadre (fase T,
  `card_points_joint`): ritmo + provocati, sfavorita = P(2) − P(1), bilanciamento.
- Ricalibrazione finale accesa solo per «Over 3.5 cartellini» (Platt, a −0.034, b 1.191; `ricalibrazione` in `goal_model.json`).

## Stadi
1b. FATTO: `config/dizionario_tattico.json` (11 termini: possesso, verticalizzazione, altezza_linea, pressing, marcatura,
   transizione, fasce_cross, gestione_blocco_basso, adattabilita, reazione_svantaggio/vantaggio; valori ammessi, punteggio
   −1…+1, tassi spostati con segno; beta/intervallo/n/fonte = null finché lo stadio 2 non li stima), `tactical_dictionary.py`
   (`apply_profile`: moltiplicatore = exp(Σ beta·punteggio), termini/valori sconosciuti SEMPRE segnalati), `formation.py`
   (modulo → ruoli per linea e corsia, accoppiamenti fascia contro fascia speculare, `lane_shares` = dove nascono le azioni),
   campi `possesso` e `verticalizzazione` nella scheda tattica, avviso per termini non riconosciuti in `parse_profiles`.
   Test `test_event_dictionary.py` (un test per termine con beta di prova: si muove solo il tasso dichiarato, nel verso giusto).
   Download dettaglio StatsBomb: `python -m tools.minute_data --statsbomb-dettaglio` (in sequenza, pausa 1 s, ripresa dai file
   `.parziale`, log in `data/cache/minuto/dettaglio.log`; fonte da citare «Data: StatsBomb Open Data», StatsBomb Open Data User
   Agreement). COMPLETATO il 30/10: 1.551 partite (Premier 380, Liga 380, Serie A 380, Bundesliga 34, Ligue 1 377), ~0,8 MB in 5 file `statsbomb_dettaglio_*.json.gz`.
2. FATTO (30/10): `tools/stima_motore.py` → `config/motore_eventi.json` + beta in `config/dizionario_tattico.json` + report
   `docs/backtest/AK_stima.md`; arbitri in `referee_stats.py`; test `test_stima_motore.py`. Rigenerare con
   `python -m tools.stima_motore [--bootstrap 200] [--no-dizionario]` (~45 s, solo cache su disco). Risultati principali:
   - Tipi di tiro (ordine rigore > palla inattiva > transizione > fuori area > testa da cross > azione; palla inattiva = punizione
     diretta o possesso da corner, «From Free Kick» resta azione perché copre tutto il possesso): per squadra-partita 0,13 rigori
     (gol/tiro 0,75), 2,58 palla inattiva (0,080), 0,56 transizione (0,155), 3,92 fuori area (0,030), 0,75 testa da cross (0,117),
     4,53 azione (0,149). Per campionato e «comune»; Bundesliga = comune.
   - Corner per squadra-partita: da tiro parato/respinto 1,53, da cross 1,00, altro 2,57; 0,25 corner per tiro parato o respinto;
     15,0 falli per squadra-partita, 0,151 gialli per fallo; quote dei falli per zona.
   - Stato di partita (effetto fisso squadra-partita, bootstrap 200 per partita): rispetto al pareggio tiri ×1,35/×1,19 (−2/−1),
     ×0,67/×0,50 (+1/+2); xG ×1,59/×1,30, ×0,65/×0,41; corner ×1,21/×1,24, ×0,65/×0,54; falli ×0,85/×0,90, ×1,07/×1,05; gialli
     ×0,72/×0,95, ×1,25/×1,01. Più i moltiplicatori per fascia di minuti.
   - Dizionario (Poisson con controlli forza delle due squadre e casa, offset = concessioni dell'avversario senza la partita,
     errore robusto per partita; beta nel dizionario solo se l'IC 95% esclude lo zero, altrimenti 0 con la stima in «motivo»):
     stimati possesso→quota_possesso +0,115, possesso→tiri_fuori_area +0,085, pressing→falli_fatti +0,034, fasce_cross→cross
     +0,137, →tiri_da_cross +0,131, →corner_fasce +0,168; verticalizzazione→azioni_pericolose −0,033 (SEGNO OPPOSTO all'atteso:
     tenuto e segnalato, da rivedere col banco). A zero: possesso/verticalizzazione/transizione→tiri_transizione,
     altezza_linea→transizione concessa e corner concessi, gestione_blocco_basso. Null con motivo: recuperi_alti, marcatura,
     adattabilità (restano i valori fissi della fase Q), reazioni (solo effetto medio dello stato di partita). Verticalizzazione e
     transizione usano lo stesso indicatore: non sommarle. Le 20 righe stili con 0 passaggi (Ligue 1) sono escluse.
   - Incroci (solo stima, `attiva: false`): verticali contro linea alta −0,049 [−0,131, +0,032], possesso contro pressing (falli)
     +0,018 [+0,001, +0,034], cross contro blocco basso −0,028 [−0,089, +0,032]. L'accensione si decide allo stadio 14.
   - Arbitri: Premier (football-data 2019-26, 33 arbitri) varianza dovuta all'arbitro 4,6% sui falli (k 20,8, fuori campione
     −2,4% MSE) e 1,2% sui gialli (k 80,7, −0,1%); Scozia 5,1% (k 18,8) e 2,2% (k 44); StatsBomb 2015/16 (una stagione) Liga,
     Serie A, Ligue 1 con quote 2-18%. L'app usa k = 10 fisso: troppo poco shrinkage sui gialli; il cambio si decide col banco.
3. FATTO (30/10): stato della partita in `event_engine.MatchState` (punteggio per simulazione, passo, minuto, fascia,
   stato di ciascuna squadra = differenza reti dal suo punto di vista limitata a −2…+2 come nelle stime). Passo di 5 minuti di
   default (`step_minutes` deve dividere 15: 1, 3, 5, 15, così i passi non scavalcano fasce e intervallo). Parametri per
   campionato da `config/motore_eventi.json` con `event_engine.load(league)` (codici football-data E0/SP1/I1/F1/D1 o nomi;
   Bundesliga e campionati non stimati = «comune», dichiarato nella nota).
4. FATTO (30/10): azioni a passi = tiri per tipo. Tabelle `build_tables` (tipo × stato × passo): tasso base StatsBomb × forza
   × dizionario × moltiplicatori di stato e fascia «tiri», normalizzati sulla distribuzione osservata degli stati
   (`minuti_per_stato`) e sulla lunghezza delle fasce, così le medie per partita restano quelle stimate (verificato nel test).
   Dizionario tattico (`type_multipliers`): azioni_pericolose → azione, tiri_transizione → transizione, tiri_fuori_area →
   fuori area, tiri_da_cross → testa da cross; tiri_transizione_concessi sposta i tiri dell'AVVERSARIO;
   tiri_contro_blocco_basso solo se l'avversario ha la linea bassa; spinta_in_svantaggio/vantaggio moltiplicano lo stato
   (oggi null → 1). quota_possesso dà solo `possession_home` (informativo). Termini sconosciuti → `warnings`.
   Forma (moduli, `formation.lane_shares`) non ancora usata: serve a cross e corner (stadio 6). Rigori: tasso costante.
5. FATTO (30/10): tiri → gol con la conversione del tipo × qualità per stato e fascia (rapporto xG/tiri stimato,
   normalizzato sui tiri; rigori costanti). Due modi in `event_engine.simulate`:
   - «punteggi» (`scores` = punteggi Dixon-Coles del motore, default previsto per l'aggancio): gol e tiri sbagliati sono
     processi indipendenti (assottigliamento di Poisson), i gol dati si collocano nei passi con rischio ∝ intensità di gol del
     passo e stato attuale mantenuto per il futuro (come `timeline`), tipo del gol ∝ tasso × conversione; totali ESATTI.
   - «libero» (`scores` = None): gol dai tiri, forza riscalata su 3 passate pilota sui gol attesi λ, μ (scarto < 0,04).
   `first_share` (quota tarata `primo_tempo`) riscala i passi del primo/secondo tempo: esatta a stato neutro, nel modo
   punteggi resta entro 0,02 (test); nel modo libero gli stati la spostano (0,467 contro 0,45 con λ 1,6): da sistemare con
   il vincolo di coerenza (stadio 9).
   Uscite per simulazione: `goals_*`, `first_*`, `shots_*`/`goals_by_type_*`/`saved_*` (n × 6 tipi; parati o respinti tra i
   tiri non in gol, per i corner da tiro dello stadio 6), `xg_*`, `first_goal_minute`/`first_goal_team`, `state_steps_home`
   (passi in ciascuno stato), `ledger` (parametri, modo, forza, moltiplicatori per tipo), `dictionary_rows`, `warnings`;
   `summary` per le medie. Esempio Premier, λ 1,6 / μ 1,1, modo punteggi: tiri 15,4 / 11,5, xG 1,50 / 1,14, minuto medio del
   primo gol 30, 6,8% senza gol. Tempo: 100.000 simulazioni in ~1,8 s (punteggi) e ~3,3 s (libero, con il pilota): l'arresto
   adattivo è dello stadio 10. NON agganciato a `engine.simulate_match`: l'app non cambia finché lo stadio 9-11 non lo collega
   e il banco (14) non lo verifica. Test: `test_event_engine.py` (15).
6-8. FATTO (30/10), dentro lo stesso ciclo a passi di `event_engine._run` (`_count_step`):
   - Stime nuove in `tools/stima_motore.py` (le stime precedenti restano identiche, differenza massima 6·10⁻¹⁵): stato e fascia dei
     corner NON da tiro (`corner_gioco`: ×1,22/×1,29 sotto, ×0,67/×0,54 avanti), sezione `stato_partita.espulsioni` (uomo in meno /
     in più a parità di stato e fascia, 5.273 minuti con superiorità numerica: tiri ×0,58/×1,43, xG ×0,56/×1,42, corner di gioco
     ×0,54/×1,33, falli ×0,64/×1,00, gialli ×0,39/×0,93), rossi diretti per fallo 0,0043 (200) e seconda gialla per giallo preso
     da una squadra già ammonita 0,052 (220), per campionato e comune (il motore usa il comune: eventi rari).
   - Stadio 6, corner per origine: da tiro = binomiale sui tiri parati o respinti del passo × corner per tiro parato; da cross e
     «altro» = Poisson col tasso per squadra-partita × stato/fascia dei corner di gioco × uomini; dizionario `corner_fasce` (cross)
     e `corner_concessi` dell'avversario (oggi beta 0). Corsie dei moduli (`TeamInput.module`, `formation.lane_shares`, rapporto
     della quota sulle fasce contro 4-4-2/4-4-2) SOLO con `lanes=True`: pesi dichiarati e non verificati, spente di default
     (decide il banco). Uscite `corners_by_origin_*` (n × tiro/cross/altro), `corners_*`, `corners_first_*`.
   - Stadio 7, falli: Poisson col tasso del campionato × stato/fascia dei falli × uomini × `falli_fatti` (pressing) × arbitro.
     Arbitro con `RefereeInput(matches, fouls, yellows, league_fouls, league_yellows)`: fattore 1 + n/(n+k)·(media/media di
     campionato − 1) con k stimato (`referee_k`: football-data del campionato, poi StatsBomb 2015/16, poi mediana; Premier k 20,8
     falli / 80,7 gialli). Le medie di campionato vanno date dalla STESSA fonte dell'arbitro: se mancano, effetto 1 e avviso.
   - Stadio 8, cartellini: gialli = binomiale sui falli con gialli per fallo × (stato e fascia dei gialli / quelli dei falli,
     normalizzato) × uomini (gialli/falli) × arbitro (gialli/falli); rossi diretti = binomiale sui falli senza giallo; seconda
     gialla tra i gialli di una squadra già ammonita (mai più degli ammoniti in campo). Conteggi come `engine.CardRule`
     (`yellows_*` con il primo giallo dell'espulso, `reds_*` = diretti + doppie, `double_yellows_*`), `card_points(sample, rule)`.
     Un rosso cambia dal passo successivo tiri, xG, corner di gioco, falli e gialli di entrambe; nel modo «punteggi» non sposta i
     gol già decisi (rischio del passo e futuro scalano insieme). Uscite anche `fouls_*`, `*_first_*`, `first_red_minute_*`.
   - Scale `TeamInput.corner_scale/foul_scale/card_scale` (default 1) = aggancio per il vincolo di coerenza dello stadio 9
     (`foul_scale` non cambia i gialli attesi: li fissa `card_scale`).
   - Verifica contro StatsBomb 2015/16 (40.000 simulazioni, gol medi del campionato, forza uguale): corner 10,93/10,81 (Premier),
     10,14/10,11 (Liga), 10,42/10,37 (Serie A), 9,59/9,52 (Ligue 1); falli 24,8/25,0, 31,4/31,9, 32,8/33,3, 29,4/29,7; gialli
     3,16/3,23, 5,45/5,68, 5,09/5,28, 3,88/3,99 (un po' sotto: l'uomo in meno toglie gialli senza rinormalizzare); rossi
     0,17/0,16, 0,29/0,29, 0,29/0,34, 0,22/0,31. Varianza dei corner totali 11,1 contro 13,0 osservata (Premier): manca
     l'eterogeneità tra squadre, da recuperare nello stadio 9 con le medie per squadra e la dispersione attuale.
   - Tempo: 100.000 simulazioni modo punteggi ~2,9 s (era ~1,8 s senza conteggi). Test: `test_event_engine.py` (25).
9. FATTO (30/10): vincolo di coerenza in `event_engine.coherence(rng, casa, ospite, params, Targets(...), scores=..., pilot=10_000,
   passes=2)`. `Targets` = medie del motore attuale DOPO ancoraggio, divisione dei cartellini (fase T) e Claude: corner per squadra,
   gialli per squadra, rossi totali (`card_red_ratio` × gialli), quota dei rossi da doppia ammonizione (solo se la regola la
   dichiara, altrimenti resta quella stimata qui), varianza dei corner e dei gialli totali (`count_variance`: Poisson-gamma con la
   dispersione attuale e l'eventuale σ della fase P), quota tarata dei gol nel primo tempo. Su 2 passate pilota (10.000 partite)
   riscala `corner_scale` (SOLO i corner di gioco: quelli da tiro restano generati dai tiri parati/respinti), `card_scale`, i nuovi
   `red_scale` e `second_yellow_scale` (rossi diretti e seconde gialle), e `first_share` in ingresso (risolve lo scarto della quota
   del primo tempo: ora entro il rumore del pilota, ~0,01). Poi una passata di verifica stima la dispersione mancante: moltiplicatori
   gamma per simulazione con media 1 (`simulate(mix={"corner": v, "cards": v})`, sui corner di gioco e sulla probabilità di giallo,
   condivisi tra le due squadre) con v = (varianza obiettivo − varianza ottenuta) / media²; voce `dispersione` nel ledger.
   Esempio Serie A (λ 1,7 / μ 0,9, obiettivi corner 6,1/3,9, gialli 1,9/2,6, rossi 0,25, varianza corner 18,3 e gialli 7,0):
   ottenuti corner 6,13/3,91, gialli 1,88/2,58, varianza 18,3 e 6,8 (prima del mix 10,7 e 4,5: era l'eterogeneità mancante dello
   stadio 8), quota 1T 0,443/0,441. Costo ~0,9 s (3 simulazioni da 10.000). Test: `test_event_engine.py` (29).
10. FATTO (30/10): `event_engine.simulate_adaptive(rng, casa, ospite, params, maximum=100_000, batch=10_000, minimum=20_000,
   tolerance_pp=0.25, scores=..., rule=...)`: lotti vettoriali (ogni lotto è una `simulate` su tutti i passi), dopo `minimum`
   partite si ferma appena l'errore standard Monte Carlo di TUTTI gli eventi di `stop_events` (linee di corner e cartellini
   totali, per squadra e nel primo tempo, gol del primo tempo, 1X2 corner; punti con la regola del bookmaker) è ≤ 0,25 punti
   percentuali (IC 95% ±0,5), al più 100.000. Con i punteggi Dixon-Coles usa i PRIMI n (campione casuale anch'esso), così gli
   stessi n punteggi servono tutti i mercati. `sample["adaptive"]` = simulazioni, lotti, errore raggiunto, evento peggiore, motivo.
   Il collo di bottiglia restano le estrazioni casuali (già vettoriali su tutte le simulazioni): 100.000 partite ~2,9 s;
   con l'arresto (Premier λ 1,6/μ 1,1) 40.000 partite in ~1,2 s (tolleranza 0,25), 70.000 in 2,3 s (0,20); l'evento più
   lento è sempre la linea dei corner vicina al 50% (Over 10.5). Test in `test_event_engine.py` (32).
11. FATTO (30/10): aggancio a `engine.simulate_match`. Sezione `motore_eventi` di `config/goal_model.json` (`attivo: false`,
   `passo_minuti` 5, `pilota` 10.000, `passate` 2, `lotto` 10.000, `minimo` 20.000, `tolleranza_pp` 0,25, `corsie` false) letta
   in `engine.EventEngineParams` → `MatchConfig.event_engine` (default spento); ingressi facoltativi `MatchConfig.event_inputs`
   = {"home"/"away": {"profile": termini del dizionario, "module": «4-3-3»}} (None = solo medie e stato della partita; il
   collegamento con le schede tattiche dell'app è dello stadio 15). Parametri del campionato da `MatchConfig.league`
   (`engine._event_params`, in cache). Con `attivo`:
   - punteggi Dixon-Coles invariati (modo «punteggi»); `engine.event_engine_sample` costruisce i `Targets` dalle medie FINALI
     (corner per squadra di `corner_signals`, gialli di `card_total_mean` divisi con la quota di casa della fase T, rossi =
     `card_red_ratio` × gialli, doppie ammonizioni solo se la regola le pesa, varianze con dispersione e σ attuali, quota del
     primo tempo tarata × fattore tattico = `_first_half_targets`), applica `coherence` e `simulate_adaptive` (semi [seed, 4] e
     [seed, 5]);
   - primo tempo (gol), corner totali/per squadra/1T e punti cartellino totali/per squadra/1T vengono dal motore a eventi;
   - con l'arresto adattivo il campione è accorciato ai primi n punteggi e `config.simulations` = n per TUTTO (mercati, componenti
     modello/mercato, esatti, `event_samples` del combo builder, `simulation_count`): tutti i mercati restano dallo stesso campione;
   - `result["event_engine"]` = parametri, simulazioni, arresto, righe della coerenza, dispersione, scale, ledger, avvisi, medie;
     spento = {"active": False}. Fase O e fase AK accese insieme → errore esplicito.
   - Falli: media del campionato senza arbitro (i gialli seguono già la media attuale che contiene l'arbitro); niente mercati falli.
   Esempio (blocco completo dei test, Serie A, 100.000 simulazioni): spento 2,1 s; acceso 3,0 s con arresto a 40.000; 1X2
   36,5/26,8/36,7 → 36,6/27,1/36,3; corner medi 4,47 → 4,49; punti cartellino 3,75 → 3,68 (Over 3.5 49,5 → 48,3).
   Test in `test_event_engine.py` (36): spento di default e senza effetti, aggancio, campioni del combo builder, esclusione con la fase O.
12. FATTO (30/10): realismo. `python -m tools.event_sense [--output docs/backtest/AK_buon_senso.md]`: 5 partite tipo di Serie A
   (favorita netta, equilibrata, chiusa, arbitro severo, arbitro permissivo) con `simulate_match` spento/acceso e misure sui
   percorsi. Confronto con i dati reali (football-data 2020-23 + 2026/27, 4.481 partite, residui a parità di quote, medie e
   campionato): diff. gol/diff. corner −0,16, gol totali/corner −0,06, |diff. gol|/gialli −0,18, gialli in più nelle partite con
   un rosso +1,07. Difetti trovati e corretti:
   - effetti di stato troppo forti: StatsBomb dice che chi segna di più sbaglia MENO tiri (pendenza −0,60 ± 0,14 sui residui di una
     Poisson con attacco, difesa e casa), il motore dava −1,10/−1,30 (distorsione delle stime dentro la partita: i minuti prima di
     un gol sono minuti di pressione). Nuova stima in `tools/stima_motore.attenuation_section` → `stato_partita.attenuazione` di
     `config/motore_eventi.json`: esponente dei moltiplicatori di stato per inferenza indiretta = **0,53** (IC 95% 0,41-0,65),
     applicato a tiri, xG, corner di gioco, falli e gialli (`EventParams.with_state_power`, `load(attenuate=False)` per i
     grezzi); ipotesi dichiarata, uomo in meno/in più e fasce invariati. Le altre stime restano identiche. Correlazione dentro
     la partita diff. gol/diff. corner −0,36 → −0,22.
   - partita «calda»: il moltiplicatore gamma dei cartellini ora vale anche per rossi diretti e seconde gialle (gialli con/senza
     rosso 0,96 → 1,03). Resta sotto il reale (+24% circa): pesa l'effetto stimato «gialli ×0,39 per chi resta in 10»; limite
     dichiarato, lo misura il banco.
   Esempio (favorita netta): corner casa nel 2T 4,30 se sotto all'intervallo, 3,76 se pari, 3,04 se avanti; rosso presto (prima
   del 30') = tiri ×0,72 e corner avversari ×1,29; quota gol/gialli/corner nel 1T 0,45/0,38/0,49; 19-21% di partite con un rosso.
   `simulate_match` con `keep_samples` e motore acceso restituisce anche `result["event_engine_sample"]` (percorsi grezzi).
13. FATTO (30/10): `test_event_sense.py` (7): attenuazione stimata e applicata, punteggi ed esatti identici con medie attuali,
   chi è sotto spinge/chi è avanti gestisce, espulsione presto, arbitro severo contro permissivo, ritmo (primo gol, quote 1T),
   partita calda.
14. Banco fuori campione (3 stagioni, 5 campionati) → `docs/backtest/AK_motore_eventi.md`: DA FARE
15. «Vedi come andrà»: DA FARE
16. Test, merge, push: DA FARE

## Note
- Verifica Bundesliga (30/10): l'elenco partite StatsBomb per 1. Bundesliga 2015/2016 (competizione 9, stagione 27) contiene
  esattamente 34 partite, tutte del Bayer Leverkusen (34 su 34). Il download è COMPLETO: è StatsBomb che pubblica solo quelle.
  DECISIONE: nessun effetto proprio per la Bundesliga; le 34 partite entrano solo nelle stime comuni (non per campionato) e per la
  Bundesliga si usano i valori stimati sugli altri campionati, dichiarato in `config/motore_eventi.json`.
- Prossimo: stadi 12-13 (realismo e test di buon senso del motore acceso su partite tipo: favorita netta, partita chiusa,
  espulsione presto, arbitro severo), poi il banco dello stadio 14 che decide `motore_eventi.attivo`. Il modo «libero» resta
  solo nello strumento (non collegato all'app: cambierebbe i punteggi Dixon-Coles).
- 30/10: stadi 9-11 fatti in una nuova sessione e uniti a `main`; il motore a eventi è collegato ma SPENTO
  (`config/goal_model.json` → `motore_eventi.attivo: false`): l'app non cambia finché lo stadio 14 non lo accende.
- 30/10: stadi 6-8 fatti in una nuova sessione sul ramo `fase-ak-motore-eventi` e uniti a `main` (motore ancora non collegato).
- 30/10: stadi 3-5 fatti in una nuova sessione e ramo unito a `main` (il motore a eventi non è collegato all'app).
