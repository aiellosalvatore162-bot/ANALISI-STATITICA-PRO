# Stato Fase AM (calibrazione per mercato)

Ramo `fase-am-taratura`. Obiettivo: percentuale dichiarata = frequenza uscita, non battere le quote.

## Stadio 1 – inventario (FATTO)
- Ancoraggio alle quote 1X2/O-U: `engine.final_goal_rates` / `anchor_goal_rates_split` (sezioni `ancoraggio_mercato`, `peso_mercato_campionato`).
- Ancoraggio conteggi corner/cartellini: `engine.CountAnchorParams` (`ancoraggio_conteggi`, peso 0.8 non tarato), cartellini per squadra `CardSplitParams`.
- Ricalibrazione fase P: `engine.apply_recalibration`/`recalibrate` (sezione `ricalibrazione`, oggi solo «Over 3.5 cartellini»), stimata da `tools/recalibration_check.py`.
- Quota 1T `primo_tempo`, shrink corner `taratura_estremi`.

## Stadi 2-8 (FATTO)
- `tools/taratura_check.py` (cache `data/cache/fase_p/`): tabelle di affidabilità, walk-forward per stagione (stagione S corretta con le sole precedenti), isotonica se casi ≥ `soglia_isotonica_casi`, altrimenti Platt con shrinkage; terne 1X2 trattate come unità e normalizzate; una sola mappa per mercato (la fase P resta solo se migliore).
- `config/taratura.json` (versionato, parametri e soglie delle etichette), `taratura.py` (applicazione, coerenza, etichette), `engine.apply_recalibration` usa solo la taratura se accesa; `_market` mostra le percentuali tarate (`result["taratura"]`).
- UI: `ui_taratura.py` (tab Prestazioni, expander «Calibrazione»), etichetta nelle giocate solide.
- Test: `test_taratura.py`.
- Limite dichiarato: i parametri del modello gol sono tarati sul 2024-26, quindi le stagioni 2024-26 non sono pienamente fuori campione per il modello base (la mappa di taratura invece è walk-forward). Corner/cartellini dello storico senza quote corner (nessun ancoraggio).
- Etichette accanto alle percentuali: barre di Gol, Gol per squadra, Multigol, 1X2 e giocate solide (`dashboard._tag`).
- Risultato del backtest completo (8.753 casi walk-forward): tabella in `docs/BASELINE.md` (sezione «Calibrazione per mercato»).
- Limite: `combo.evaluate` usa i campioni grezzi per la congiunta, mentre le percentuali mostrate sono tarate (scarto piccolo).
- Test finali: 537 passati, 2 xfail noti; avvio app con AppTest senza eccezioni. STADIO FINALE: fatto.
