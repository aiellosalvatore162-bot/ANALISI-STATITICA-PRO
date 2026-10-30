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
1. Proxy xG + `config/stile.json` + `style_profile.py` + foglio «Stile»: DA FARE
2. Opzione `forma_reale` nel motore (`engine.py`, formula_ledger): DA FARE
3. Banco `tools/backtest_wf.py` (walk-forward, mercati, CSV/MD): DA FARE
4. Backtest `forma_reale` (Serie A, Premier, Bundesliga, SC0, D2): DA FARE
5. Test, merge, push, riepilogo: DA FARE

## Decisioni
- Un solo backtest alla volta; risultati in cache `data/cache/ad/`.
