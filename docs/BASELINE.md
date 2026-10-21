# Baseline del motore

Misure prodotte da `tools/baseline.py` su partite reali (input calcolati solo con dati precedenti alla gara, vedi `tools/dataset.py`). Il mercato è la quota media di chiusura senza margine. Log-loss, Brier ed ECE: più bassi è meglio.

## PRIMA (formula originale)

Generato il 21/10/2026 con `python -m tools.baseline`. Campionati: Serie A, Premier League, Liga, Bundesliga (football-data.co.uk).

### taratura 2024-25/2025-26 (2852 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 1.0225 | 0.9698 | 0.6130 | 0.5769 | 0.0166 | 0.0097 |
| Over 2.5 | 0.6879 | 0.6701 | 0.4948 | 0.4775 | 0.0108 | 0.0140 |
| GG | 0.6879 | — | 0.4948 | — | 0.0053 | — |

- Favorite nette (mercato ≥ 70%, 314 partite): probabilità media mercato 76.4%, modello 58.7%.
- Errore medio assoluto sulla media corner: 2.72; cartellini gialli: 1.80.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 17 | 0.087 | 0.059 |
| 10%-20% | 550 | 0.167 | 0.113 |
| 20%-30% | 3804 | 0.263 | 0.252 |
| 30%-40% | 2056 | 0.340 | 0.343 |
| 40%-50% | 1247 | 0.447 | 0.464 |
| 50%-60% | 670 | 0.542 | 0.584 |
| 60%-70% | 190 | 0.639 | 0.716 |
| 70%-80% | 22 | 0.727 | 0.864 |

### fuori campione 2026-27 (254 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 1.0024 | 0.9373 | 0.5987 | 0.5543 | 0.0331 | 0.0282 |
| Over 2.5 | 0.6782 | 0.6394 | 0.4853 | 0.4486 | 0.0121 | 0.0668 |
| GG | 0.6877 | — | 0.4947 | — | 0.0255 | — |

- Favorite nette (mercato ≥ 70%, 31 partite): probabilità media mercato 78.1%, modello 56.3%.
- Errore medio assoluto sulla media corner: 2.87; cartellini gialli: 1.82.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 2 | 0.092 | 0.000 |
| 10%-20% | 41 | 0.171 | 0.049 |
| 20%-30% | 357 | 0.263 | 0.269 |
| 30%-40% | 161 | 0.340 | 0.323 |
| 40%-50% | 131 | 0.448 | 0.412 |
| 50%-60% | 55 | 0.543 | 0.636 |
| 60%-70% | 13 | 0.634 | 1.000 |
| 70%-80% | 2 | 0.722 | 1.000 |

