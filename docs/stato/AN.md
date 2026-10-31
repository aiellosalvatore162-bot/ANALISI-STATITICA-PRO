# Stato Fase AN (Simulatore reale e dati importati)

Ramo `fase-an-simulatore-reale`.

## Parte A – selettore del motore (FATTO)
- `engine_choice.py`: tre posizioni («Calcolo attuale», «Simulatore reale – completo», «Simulatore reale – solo corner»), avvisi per
  mercato (numeri da `docs/backtest/AK_motore_eventi_nuovo.md` e `docs/backtest/AN_libero.md`), predefinito in `data/impostazioni.json`.
- `engine.EventEngineParams.free`: modo «libero» (gol dai tiri, riscalati su λ/μ dal vincolo di coerenza) + `engine.dixon_coles_resample`
  (ripesatura Dixon-Coles dei punteggi 0-0, 1-0, 0-1, 1-1 ricampionando partite INTERE: un solo campione per tutti i mercati).
- Taratura AM: i mercati prodotti dal motore a eventi restano grezzi (`Taratura.excluding`), l'etichetta dice «poco verificata (nessuna taratura
  per questo motore)». `result["motore"]` (chiave, nome, modo, etichetta) → scheda (`dashboard.engine_badge`), registro (nota «motore: …»),
  memoria partita (`motore`), «Vedi come andrà» (`match_story.engine_label`). Fase O accesa: il selettore la spegne per la partita.
- UI: `ui_taratura.render_engine_choice` nella card «Parametri simulazione».
- `tools/libero_check.py`: prova rapida (1 stagione, 3 campionati) → `docs/backtest/AN_libero.md`.

## Parte B – dati importati (FATTO)
- `data_import.py` (logica), `tools/importa_dati.py` (comando), `tools/confronto_dati.py` (controllo proposto, non lanciato da solo),
  `ui_imported.py` (tab «Dati aggiunti»), modelli in `data/import/modelli/`, registro `data/import/registro.json`, cache `data/cache/importati/`.
- Priorità: `style_profile.forma_reale` usa xG/xGA importati (con `data_dati` PRIMA della partita) al posto del proxy dai tiri o dei soli gol;
  `get_style_params` riempie `tiri_transizione`, `quota_xg_palle_inattive`, `cross` quando mancano. Fonte e data dichiarate.
- Limite: giocatori, formazioni, arbitri e quote sono importati e consultabili ma non ancora letti dal motore; le colonne di stile
  possesso/ppda/pressioni… sono solo consultabili.
- Test: `test_import.py`.

## Esito (31/10/2026)
- Prova modo libero su 72 partite (un terzo stratificato; campione intero troppo lento, 40 min): nessuna differenza misurabile sui gol, cartellini
  nel complesso non migliori. Resta selezionabile con avviso. Avanzamento: `python -m tools.libero_avanzamento`.
- 549 test passati, 2 xfail noti; avvio app con AppTest senza eccezioni.
