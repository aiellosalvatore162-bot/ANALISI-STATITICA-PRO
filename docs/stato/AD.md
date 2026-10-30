# Stato Fase AD (profilo di stile, forma reale, banco walk-forward)

Ramo: `fase-ad-stile-forma-wf`.

## Stadio 0 – cosa si riusa (fatto)
- `tools/dataset.py` (CSV football-data in `data/cache`, `build_features` solo sul passato, `ShotXgModel`/`fit_shot_xg`).
- `tools/baseline.py` (`summarize`, `binary`, `calibration_table`, `secondary_markets`, `secondary_outcomes`, `config_for_row`).
- `tools/calibrate.py` (`count_logpmf`, `count_sf`, `CORNER_LINES`, `CARD_LINES`, `score_matrices`).
- `tools/v2common.py` (regola severa `strict`: log-loss appaiata giù di 2 e.s. ED ECE non peggiore).
- `datasources/sources.py` (`Understat.league`, `FootballDataCoUk.season`), `datasources/names.py` (`match_team`).
- `datasources/style.py` esistente (z-score per campionato, archetipi): NON toccato; il nuovo profilo è in `style_profile.py`.
- `timeline.py`/cache StatsBomb (fasi O/Q): non servono qui.

## Stadi
1. Proxy xG (R² 0.545 fuori campione, usabile) + `config/stile.json` + `style_profile.py`: FATTO; foglio «Stile» nell'Excel (day_workbook + ui_memory): DA FARE; collegamento in today.prepare: DA FARE
2. Opzione `forma_reale` nel motore (`StyleModelParams`, `MatchConfig.style`, voce `forma_reale` nel formula_ledger): FATTO. NB: il modello calibrato ha `form_weight=0` e `attack_xg_share=1`, quindi la forma reale AGGIUNGE un termine dove prima non c'era forma; `k_xg` agisce solo sulla difesa (0.84).
3. Banco `tools/backtest_wf.py` (walk-forward, 25 mercati, CSV/MD, `run(...)`): FATTO, prova 1 stagione/3 campionati ok (26 s)
4. Backtest `forma_reale` (Serie A, Premier, Bundesliga, SC0, D2): DA FARE
5. Test, merge, push, riepilogo: DA FARE

## Decisioni
- Un solo backtest alla volta; risultati in cache `data/cache/ad/`.
