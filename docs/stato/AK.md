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
3-5. Stato della partita, azioni a passi, tiri e gol (`event_engine.py`): DA FARE
6-8. Corner, falli e cartellini, effetti dello stato: DA FARE
9-11. Vincolo di coerenza (riscalatura sulle medie attuali), simulazione vettoriale con arresto adattivo, mercati dagli stessi campioni: DA FARE
12-13. Realismo e test di buon senso: DA FARE
14. Banco fuori campione (3 stagioni, 5 campionati) → `docs/backtest/AK_motore_eventi.md`: DA FARE
15. «Vedi come andrà»: DA FARE
16. Test, merge, push: DA FARE

## Note
- Verifica Bundesliga (30/10): l'elenco partite StatsBomb per 1. Bundesliga 2015/2016 (competizione 9, stagione 27) contiene
  esattamente 34 partite, tutte del Bayer Leverkusen (34 su 34). Il download è COMPLETO: è StatsBomb che pubblica solo quelle.
  DECISIONE: nessun effetto proprio per la Bundesliga; le 34 partite entrano solo nelle stime comuni (non per campionato) e per la
  Bundesliga si usano i valori stimati sugli altri campionati, dichiarato in `config/motore_eventi.json`.
- Prossimo: stadi 3-5 (`event_engine.py`: stato della partita, azioni a passi, tiri e gol) leggendo `config/motore_eventi.json`.
- La conversazione che ha fatto la ricognizione era già molto lunga: il lavoro riparte da qui in una nuova sessione.
