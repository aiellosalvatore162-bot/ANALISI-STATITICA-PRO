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

## DOPO (modello log-lineare tarato)

Generato il 21/10/2026 con `python -m tools.baseline --goal-model calibrato`. Campionati: Serie A, Premier League, Liga, Bundesliga (football-data.co.uk).

### taratura 2024-25/2025-26 (2852 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 0.9858 | 0.9698 | 0.5879 | 0.5769 | 0.0091 | 0.0097 |
| Over 2.5 | 0.6806 | 0.6701 | 0.4877 | 0.4775 | 0.0016 | 0.0140 |
| GG | 0.6855 | — | 0.4924 | — | 0.0039 | — |

- Favorite nette (mercato ≥ 70%, 314 partite): probabilità media mercato 76.4%, modello 74.5%.
- Errore medio assoluto sulla media corner: 2.72; cartellini gialli: 1.80.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 281 | 0.071 | 0.082 |
| 10%-20% | 1118 | 0.157 | 0.140 |
| 20%-30% | 3400 | 0.260 | 0.259 |
| 30%-40% | 1451 | 0.343 | 0.340 |
| 40%-50% | 944 | 0.449 | 0.480 |
| 50%-60% | 649 | 0.546 | 0.542 |
| 60%-70% | 411 | 0.645 | 0.618 |
| 70%-80% | 216 | 0.742 | 0.764 |
| 80%-90% | 79 | 0.834 | 0.861 |
| 90%-100% | 7 | 0.918 | 0.714 |

### fuori campione 2026-27 (254 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 0.9433 | 0.9373 | 0.5573 | 0.5543 | 0.0483 | 0.0282 |
| Over 2.5 | 0.6577 | 0.6394 | 0.4655 | 0.4486 | 0.0281 | 0.0668 |
| GG | 0.6785 | — | 0.4856 | — | 0.0195 | — |

- Favorite nette (mercato ≥ 70%, 31 partite): probabilità media mercato 78.1%, modello 73.6%.
- Errore medio assoluto sulla media corner: 2.87; cartellini gialli: 1.82.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 23 | 0.073 | 0.000 |
| 10%-20% | 93 | 0.160 | 0.097 |
| 20%-30% | 315 | 0.260 | 0.276 |
| 30%-40% | 118 | 0.342 | 0.314 |
| 40%-50% | 100 | 0.445 | 0.370 |
| 50%-60% | 54 | 0.550 | 0.630 |
| 60%-70% | 34 | 0.639 | 0.794 |
| 70%-80% | 18 | 0.740 | 0.944 |
| 80%-90% | 7 | 0.849 | 0.857 |

## Fase 2 · PRIMA (solo modello tarato, senza ancoraggio)

Generato il 21/10/2026 con `python -m tools.baseline`. Campionati: Serie A, Premier League, Liga, Bundesliga (football-data.co.uk).

### taratura 2024-25/2025-26 (2852 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 0.9858 | 0.9698 | 0.5879 | 0.5769 | 0.0091 | 0.0097 |
| Over 2.5 | 0.6806 | 0.6701 | 0.4877 | 0.4775 | 0.0016 | 0.0140 |
| GG | 0.6855 | — | 0.4924 | — | 0.0039 | — |

- Favorite nette (mercato ≥ 70%, 314 partite): probabilità media mercato 76.4%, modello 74.5%.
- Segnali VALORE 1X2 alle quote di chiusura: 1.06 per partita (1: 858, X: 962, 2: 1205); rendimento medio puntando 1 su ciascuno: -10.0%.
- Errore medio assoluto sulla media corner: 2.72; cartellini gialli: 1.80.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 281 | 0.071 | 0.082 |
| 10%-20% | 1118 | 0.157 | 0.140 |
| 20%-30% | 3400 | 0.260 | 0.259 |
| 30%-40% | 1451 | 0.343 | 0.340 |
| 40%-50% | 944 | 0.449 | 0.480 |
| 50%-60% | 649 | 0.546 | 0.542 |
| 60%-70% | 411 | 0.645 | 0.618 |
| 70%-80% | 216 | 0.742 | 0.764 |
| 80%-90% | 79 | 0.834 | 0.861 |
| 90%-100% | 7 | 0.918 | 0.714 |

### fuori campione 2026-27 (254 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 0.9433 | 0.9373 | 0.5573 | 0.5543 | 0.0483 | 0.0282 |
| Over 2.5 | 0.6577 | 0.6394 | 0.4655 | 0.4486 | 0.0281 | 0.0668 |
| GG | 0.6785 | — | 0.4856 | — | 0.0195 | — |

- Favorite nette (mercato ≥ 70%, 31 partite): probabilità media mercato 78.1%, modello 73.6%.
- Segnali VALORE 1X2 alle quote di chiusura: 1.13 per partita (1: 86, X: 108, 2: 94); rendimento medio puntando 1 su ciascuno: -9.3%.
- Errore medio assoluto sulla media corner: 2.87; cartellini gialli: 1.82.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 23 | 0.073 | 0.000 |
| 10%-20% | 93 | 0.160 | 0.097 |
| 20%-30% | 315 | 0.260 | 0.276 |
| 30%-40% | 118 | 0.342 | 0.314 |
| 40%-50% | 100 | 0.445 | 0.370 |
| 50%-60% | 54 | 0.550 | 0.630 |
| 60%-70% | 34 | 0.639 | 0.794 |
| 70%-80% | 18 | 0.740 | 0.944 |
| 80%-90% | 7 | 0.849 | 0.857 |

## Taratura dell'ancoraggio al mercato

Generato il 21/10/2026 con `python -m tools.baseline --tara-ancoraggio` (3106 partite con quote di chiusura). Log-loss 1X2 + Over/Under 2.5, più basso è meglio.

| Metodo margine | Peso mercato | Tipo | taratura 2024-25/2025-26 | fuori campione 2026-27 |
|---|---|---|---|---|
| — | 0.0 | solo modello | 1.6664 | 1.6010 |
| proporzionale | 0.5 | ancorato | 1.6475 | 1.5832 |
| proporzionale | 0.6 | ancorato | 1.6453 | 1.5811 |
| proporzionale | 0.7 | ancorato | 1.6433 | 1.5793 |
| proporzionale | 0.8 | ancorato | 1.6417 | 1.5780 |
| proporzionale | 0.9 | ancorato | 1.6405 | 1.5771 |
| proporzionale | 1.0 | solo mercato | 1.6398 | 1.5766 |
| shin | 0.5 | ancorato | 1.6466 | 1.5804 |
| shin | 0.6 | ancorato | 1.6444 | 1.5778 |
| shin | 0.7 | ancorato | 1.6424 | 1.5758 |
| shin | 0.8 | ancorato | 1.6408 | 1.5742 |
| shin | 0.9 | ancorato | 1.6397 | 1.5731 |
| shin | 1.0 | solo mercato | 1.6390 | 1.5725 |

Scelta: metodo **shin**, peso mercato **0.9**, correzione del modello limitata a [0.8, 1.2]; ancoraggio attivo.

## Fase 2 · DOPO (modello ancorato al mercato)

Generato il 21/10/2026 con `python -m tools.baseline --ancorato`. Campionati: Serie A, Premier League, Liga, Bundesliga (football-data.co.uk).

### taratura 2024-25/2025-26 (2852 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 0.9695 | 0.9698 | 0.5770 | 0.5769 | 0.0074 | 0.0097 |
| Over 2.5 | 0.6702 | 0.6701 | 0.4777 | 0.4775 | 0.0096 | 0.0140 |
| GG | 0.6812 | — | 0.4881 | — | 0.0043 | — |

- Favorite nette (mercato ≥ 70%, 314 partite): probabilità media mercato 76.4%, modello 77.3%.
- Segnali VALORE 1X2 alle quote di chiusura: 0.06 per partita (1: 6, X: 167, 2: 7); rendimento medio puntando 1 su ciascuno: -24.6%.
- Errore medio assoluto sulla media corner: 2.72; cartellini gialli: 1.80.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 333 | 0.073 | 0.060 |
| 10%-20% | 1186 | 0.157 | 0.153 |
| 20%-30% | 3063 | 0.256 | 0.251 |
| 30%-40% | 1640 | 0.338 | 0.337 |
| 40%-50% | 923 | 0.447 | 0.462 |
| 50%-60% | 663 | 0.547 | 0.552 |
| 60%-70% | 415 | 0.648 | 0.643 |
| 70%-80% | 247 | 0.745 | 0.789 |
| 80%-90% | 83 | 0.837 | 0.892 |
| 90%-100% | 3 | 0.913 | 0.667 |

### fuori campione 2026-27 (254 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 0.9341 | 0.9373 | 0.5527 | 0.5543 | 0.0333 | 0.0282 |
| Over 2.5 | 0.6390 | 0.6394 | 0.4484 | 0.4486 | 0.0449 | 0.0668 |
| GG | 0.6734 | — | 0.4803 | — | 0.0245 | — |

- Favorite nette (mercato ≥ 70%, 31 partite): probabilità media mercato 78.1%, modello 79.2%.
- Segnali VALORE 1X2 alle quote di chiusura: 0.00 per partita (1: 0, X: 1, 2: 0); rendimento medio puntando 1 su ciascuno: -100.0%.
- Errore medio assoluto sulla media corner: 2.87; cartellini gialli: 1.82.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 29 | 0.064 | 0.000 |
| 10%-20% | 109 | 0.157 | 0.128 |
| 20%-30% | 273 | 0.255 | 0.256 |
| 30%-40% | 138 | 0.338 | 0.297 |
| 40%-50% | 91 | 0.446 | 0.505 |
| 50%-60% | 54 | 0.551 | 0.519 |
| 60%-70% | 35 | 0.642 | 0.714 |
| 70%-80% | 21 | 0.752 | 0.952 |
| 80%-90% | 10 | 0.830 | 0.800 |
| 90%-100% | 2 | 0.929 | 1.000 |

## Analisi del pareggio (1, X, 2 separati)

Generato il 21/10/2026 con `python -m tools.baseline --analisi-pareggio`. Probabilità media prevista contro frequenza osservata; i VALORE sono calcolati alle quote di chiusura (con margine) puntando 1 su ciascun segnale.

### taratura 2024-25/2025-26 (2852 partite; osservato 1 42.3%, X 25.7%, 2 32.0%)

| Fonte | 1 prevista | X prevista | 2 prevista | Scarto X (punti) | Log-loss 1X2 |
|---|---|---|---|---|---|
| quote senza margine · proporzionale | 43.7% | 25.3% | 31.1% | -0.44 | 0.9698 |
| quote senza margine · shin | 44.1% | 24.9% | 31.0% | -0.76 | 0.9691 |
| Dixon-Coles adattato al mercato · proporzionale | 43.4% | 25.8% | 30.8% | +0.09 | 0.9697 |
| finale (peso 0.9) · proporzionale | 43.3% | 25.8% | 30.9% | +0.10 | 0.9702 |
| Dixon-Coles adattato al mercato · shin | 43.8% | 25.6% | 30.7% | -0.14 | 0.9689 |
| finale (peso 0.9) · shin | 43.7% | 25.6% | 30.8% | -0.11 | 0.9695 |

| Scenario VALORE | 1: n / rend. | X: n / rend. | 2: n / rend. | Totale: n / rend. |
|---|---|---|---|---|
| PRIMA: finale shin, VALORE su 1, X e 2 | 6 / -55.2% | 167 / -22.8% | 7 / -41.6% | 180 / -24.6% |
| alternativa: finale proporzionale | 10 / -73.1% | 532 / -8.3% | 21 / 63.4% | 563 / -6.8% |
| DOPO: finale shin, nessun VALORE sul pareggio | 6 / -55.2% | 0 / — | 7 / -41.6% | 13 / -47.8% |

### fuori campione 2026-27 (254 partite; osservato 1 44.9%, X 23.2%, 2 31.9%)

| Fonte | 1 prevista | X prevista | 2 prevista | Scarto X (punti) | Log-loss 1X2 |
|---|---|---|---|---|---|
| quote senza margine · proporzionale | 43.1% | 24.3% | 32.5% | +1.11 | 0.9373 |
| quote senza margine · shin | 43.6% | 23.9% | 32.5% | +0.69 | 0.9348 |
| Dixon-Coles adattato al mercato · proporzionale | 42.9% | 24.9% | 32.2% | +1.66 | 0.9373 |
| finale (peso 0.9) · proporzionale | 42.8% | 25.0% | 32.2% | +1.73 | 0.9366 |
| Dixon-Coles adattato al mercato · shin | 43.3% | 24.6% | 32.2% | +1.33 | 0.9347 |
| finale (peso 0.9) · shin | 43.2% | 24.7% | 32.1% | +1.44 | 0.9341 |

| Scenario VALORE | 1: n / rend. | X: n / rend. | 2: n / rend. | Totale: n / rend. |
|---|---|---|---|---|
| PRIMA: finale shin, VALORE su 1, X e 2 | 0 / — | 1 / -100.0% | 0 / — | 1 / -100.0% |
| alternativa: finale proporzionale | 1 / -100.0% | 41 / -20.3% | 0 / — | 42 / -22.2% |
| DOPO: finale shin, nessun VALORE sul pareggio | 0 / — | 0 / — | 0 / — | 0 / — |

## Mercati secondari (prima/dopo la taratura del primo tempo)

Generato il 21/10/2026 con `python -m tools.baseline --mercati-secondari`. Tutti i mercati escono dalla matrice dei punteggi dei gol attesi finali (ancorati alle quote di chiusura 1X2 e O/U 2.5). Prima: primo tempo al 50% dei gol; dopo: quote del primo tempo tarate (0.448 casa, 0.431 ospite, pendenza +0.150). football-data non pubblica quote per questi mercati: il riferimento «mercato» è derivato dalla matrice di λ e μ che riproducono le quote di chiusura 1X2 e O/U 2.5. «Solo modello» usa i gol attesi dei soli dati squadra, senza quote. ⚠️ = log-loss peggiore del mercato derivato di oltre 0.005 (finale / solo modello).

### taratura 2024-25/2025-26 (2851 partite)

| Mercato | Log-loss prima | Log-loss dopo | Log-loss mercato | Log-loss solo modello | Brier prima | Brier dopo | ECE prima | ECE dopo | Finale | Solo modello |
|---|---|---|---|---|---|---|---|---|---|---|
| Multigol 1-2 | 0.6651 | 0.6651 | 0.6651 | 0.6712 | 0.4727 | 0.4727 | 0.0168 | 0.0168 |  | ⚠️ +0.006 |
| Multigol 1-3 | 0.6435 | 0.6435 | 0.6433 | 0.6507 | 0.4516 | 0.4516 | 0.0273 | 0.0273 |  | ⚠️ +0.007 |
| Multigol 1-4 | 0.5052 | 0.5052 | 0.5055 | 0.5070 | 0.3244 | 0.3244 | 0.0359 | 0.0359 |  |  |
| Multigol 2-3 | 0.6893 | 0.6893 | 0.6893 | 0.6908 | 0.4962 | 0.4962 | 0.0065 | 0.0065 |  |  |
| Multigol 2-4 | 0.6595 | 0.6595 | 0.6595 | 0.6601 | 0.4667 | 0.4667 | 0.0127 | 0.0127 |  |  |
| Multigol 2-5 | 0.5954 | 0.5954 | 0.5954 | 0.5980 | 0.4058 | 0.4058 | 0.0129 | 0.0129 |  |  |
| Multigol 2-6 | 0.5507 | 0.5507 | 0.5506 | 0.5560 | 0.3659 | 0.3659 | 0.0096 | 0.0096 |  | ⚠️ +0.005 |
| Multigol 3-5 | 0.6844 | 0.6844 | 0.6844 | 0.6883 | 0.4913 | 0.4913 | 0.0121 | 0.0121 |  |  |
| Multigol Casa 1-2 | 0.6786 | 0.6786 | 0.6785 | 0.6810 | 0.4855 | 0.4855 | 0.0177 | 0.0177 |  |  |
| Multigol Ospite 1-2 | 0.6793 | 0.6793 | 0.6795 | 0.6804 | 0.4863 | 0.4863 | 0.0281 | 0.0281 |  |  |
| Multigol Casa 1-3 | 0.6032 | 0.6032 | 0.6034 | 0.6036 | 0.4131 | 0.4131 | 0.0294 | 0.0294 |  |  |
| Multigol Ospite 1-3 | 0.6186 | 0.6186 | 0.6186 | 0.6223 | 0.4278 | 0.4278 | 0.0349 | 0.0349 |  |  |
| Multigol Casa 2-3 | 0.6353 | 0.6353 | 0.6353 | 0.6400 | 0.4452 | 0.4452 | 0.0173 | 0.0173 |  |  |
| Multigol Ospite 2-3 | 0.6146 | 0.6146 | 0.6145 | 0.6210 | 0.4238 | 0.4238 | 0.0298 | 0.0298 |  | ⚠️ +0.006 |
| Multigol Casa 2-4 | 0.6369 | 0.6369 | 0.6368 | 0.6457 | 0.4466 | 0.4466 | 0.0181 | 0.0181 |  | ⚠️ +0.009 |
| Multigol Ospite 2-4 | 0.6211 | 0.6211 | 0.6208 | 0.6316 | 0.4301 | 0.4301 | 0.0236 | 0.0236 |  | ⚠️ +0.011 |
| Somma gol | 1.6911 | 1.6911 | 1.6909 | 1.7082 | 0.8039 | 0.8039 | 0.0041 | 0.0041 |  | ⚠️ +0.017 |
| 1X2 1T | 1.0278 | 1.0263 | 1.0257 | 1.0396 | 0.6219 | 0.6207 | 0.0137 | 0.0061 |  | ⚠️ +0.014 |
| Over 0.5 1T | 0.5883 | 0.5857 | 0.5857 | 0.5906 | 0.4000 | 0.3977 | 0.0320 | 0.0190 |  |  |
| Over 1.5 1T | 0.6363 | 0.6252 | 0.6250 | 0.6345 | 0.4447 | 0.4348 | 0.0606 | 0.0111 |  | ⚠️ +0.010 |
| GG 1T | 0.4904 | 0.4860 | 0.4862 | 0.4891 | 0.3117 | 0.3086 | 0.0383 | 0.0133 |  |  |

### fuori campione 2026-27 (254 partite)

| Mercato | Log-loss prima | Log-loss dopo | Log-loss mercato | Log-loss solo modello | Brier prima | Brier dopo | ECE prima | ECE dopo | Finale | Solo modello |
|---|---|---|---|---|---|---|---|---|---|---|
| Multigol 1-2 | 0.6068 | 0.6068 | 0.6057 | 0.6215 | 0.4184 | 0.4184 | 0.0399 | 0.0399 |  | ⚠️ +0.016 |
| Multigol 1-3 | 0.6486 | 0.6486 | 0.6466 | 0.6699 | 0.4572 | 0.4572 | 0.0798 | 0.0798 |  | ⚠️ +0.023 |
| Multigol 1-4 | 0.5824 | 0.5824 | 0.5808 | 0.5989 | 0.3957 | 0.3957 | 0.0414 | 0.0414 |  | ⚠️ +0.018 |
| Multigol 2-3 | 0.6643 | 0.6643 | 0.6632 | 0.6735 | 0.4719 | 0.4719 | 0.0457 | 0.0457 |  | ⚠️ +0.010 |
| Multigol 2-4 | 0.6842 | 0.6842 | 0.6834 | 0.6905 | 0.4910 | 0.4910 | 0.0436 | 0.0436 |  | ⚠️ +0.007 |
| Multigol 2-5 | 0.6014 | 0.6014 | 0.6008 | 0.6076 | 0.4115 | 0.4115 | 0.0166 | 0.0166 |  | ⚠️ +0.007 |
| Multigol 2-6 | 0.5788 | 0.5788 | 0.5783 | 0.5837 | 0.3894 | 0.3894 | 0.0368 | 0.0368 |  | ⚠️ +0.005 |
| Multigol 3-5 | 0.6866 | 0.6866 | 0.6858 | 0.6958 | 0.4935 | 0.4935 | 0.0125 | 0.0125 |  | ⚠️ +0.010 |
| Multigol Casa 1-2 | 0.6685 | 0.6685 | 0.6679 | 0.6754 | 0.4763 | 0.4763 | 0.0303 | 0.0303 |  | ⚠️ +0.007 |
| Multigol Ospite 1-2 | 0.6760 | 0.6760 | 0.6759 | 0.6787 | 0.4828 | 0.4828 | 0.0322 | 0.0322 |  |  |
| Multigol Casa 1-3 | 0.6269 | 0.6269 | 0.6264 | 0.6332 | 0.4355 | 0.4355 | 0.0284 | 0.0284 |  | ⚠️ +0.007 |
| Multigol Ospite 1-3 | 0.6105 | 0.6105 | 0.6105 | 0.6137 | 0.4203 | 0.4203 | 0.0313 | 0.0313 |  |  |
| Multigol Casa 2-3 | 0.6512 | 0.6512 | 0.6512 | 0.6553 | 0.4601 | 0.4601 | 0.0280 | 0.0280 |  |  |
| Multigol Ospite 2-3 | 0.6409 | 0.6409 | 0.6408 | 0.6463 | 0.4494 | 0.4494 | 0.0531 | 0.0531 |  | ⚠️ +0.005 |
| Multigol Casa 2-4 | 0.6561 | 0.6561 | 0.6560 | 0.6650 | 0.4651 | 0.4651 | 0.0346 | 0.0346 |  | ⚠️ +0.009 |
| Multigol Ospite 2-4 | 0.6455 | 0.6455 | 0.6456 | 0.6510 | 0.4543 | 0.4543 | 0.0691 | 0.0691 |  | ⚠️ +0.005 |
| Somma gol | 1.6749 | 1.6749 | 1.6725 | 1.7092 | 0.7925 | 0.7925 | 0.0063 | 0.0063 |  | ⚠️ +0.037 |
| 1X2 1T | 1.0107 | 1.0061 | 1.0066 | 1.0104 | 0.6138 | 0.6106 | 0.0443 | 0.0214 |  |  |
| Over 0.5 1T | 0.6144 | 0.6003 | 0.6000 | 0.6075 | 0.4252 | 0.4139 | 0.0834 | 0.0468 |  | ⚠️ +0.007 |
| Over 1.5 1T | 0.6476 | 0.6404 | 0.6398 | 0.6527 | 0.4558 | 0.4496 | 0.0531 | 0.0262 |  | ⚠️ +0.013 |
| GG 1T | 0.4948 | 0.4856 | 0.4853 | 0.4920 | 0.3156 | 0.3096 | 0.0591 | 0.0344 |  | ⚠️ +0.007 |

## Corner e cartellini (prima/dopo la taratura sui dati reali)

Generato il 21/10/2026 con `python -m tools.baseline --corner-cartellini`. Medie calcolate dalle funzioni del motore (`corner_signals`, `card_total_mean`); distribuzione Poisson o binomiale negativa come nella simulazione. Dopo: dispersione corner 51.3032, gialli 0 (0 = Poisson), peso gialli arbitro 0.248, peso falli arbitro 0.048. football-data non ha quote su corner e cartellini: nessun confronto con il mercato.

### taratura 2024-25/2025-26 (2851 partite)

| Mercato | Misura | Prima | Dopo |
|---|---|---|---|
| Corner totali | errore medio assoluto | 2.723 | 2.700 |
| Corner totali | log-verosimiglianza negativa | 2.6408 | 2.6230 |
| Corner totali Over 8.5 | log-loss / Brier / ECE | 0.6735 / 0.4795 / 0.0378 | 0.6666 / 0.4737 / 0.0171 |
| Corner totali Over 9.5 | log-loss / Brier / ECE | 0.6984 / 0.5042 / 0.0468 | 0.6905 / 0.4971 / 0.0275 |
| Corner totali Over 10.5 | log-loss / Brier / ECE | 0.6682 / 0.4739 / 0.0314 | 0.6612 / 0.4683 / 0.0217 |
| Gialli totali | errore medio assoluto | 1.801 | 1.670 |
| Gialli totali | log-verosimiglianza negativa | 2.2694 | 2.1458 |
| Gialli totali Over 3.5 | log-loss / Brier / ECE | 0.7634 / 0.5547 / 0.1405 | 0.6788 / 0.4858 / 0.0055 |
| Gialli totali Over 4.5 | log-loss / Brier / ECE | 0.7373 / 0.5103 / 0.1348 | 0.6549 / 0.4623 / 0.0107 |
| Gialli totali Over 5.5 | log-loss / Brier / ECE | 0.5770 / 0.3582 / 0.0791 | 0.5153 / 0.3342 / 0.0030 |

### fuori campione 2026-27 (254 partite)

| Mercato | Misura | Prima | Dopo |
|---|---|---|---|
| Corner totali | errore medio assoluto | 2.871 | 2.873 |
| Corner totali | log-verosimiglianza negativa | 2.6989 | 2.6780 |
| Corner totali Over 8.5 | log-loss / Brier / ECE | 0.6812 / 0.4874 / 0.0779 | 0.6748 / 0.4823 / 0.0517 |
| Corner totali Over 9.5 | log-loss / Brier / ECE | 0.6788 / 0.4862 / 0.0437 | 0.6740 / 0.4815 / 0.0404 |
| Corner totali Over 10.5 | log-loss / Brier / ECE | 0.6578 / 0.4655 / 0.0212 | 0.6544 / 0.4625 / 0.0387 |
| Gialli totali | errore medio assoluto | 1.821 | 1.633 |
| Gialli totali | log-verosimiglianza negativa | 2.2858 | 2.1026 |
| Gialli totali Over 3.5 | log-loss / Brier / ECE | 0.8089 / 0.5938 / 0.2094 | 0.6775 / 0.4846 / 0.0125 |
| Gialli totali Over 4.5 | log-loss / Brier / ECE | 0.7352 / 0.4941 / 0.1606 | 0.6351 / 0.4440 / 0.0103 |
| Gialli totali Over 5.5 | log-loss / Brier / ECE | 0.6117 / 0.3637 / 0.1457 | 0.5158 / 0.3361 / 0.0275 |

## Punti cartellini (regola del bookmaker, prima/dopo)

Generato il 22/10/2026 con `python -m tools.baseline --cartellini-punti`. Regola: giallo 1, rosso 2, doppia ammonizione giallo e rosso. Prima = modello dei soli gialli usato come previsione dei punti; dopo = gialli più rossi (0.0455 rossi per giallo atteso), dispersione gialli 0 → 12.3537. Punti reali da gialli e rossi di football-data.co.uk: esatti nelle leghe europee; in Premier League la doppia ammonizione vale 2 invece di 3 (il primo giallo non è nei dati).

### taratura 2024-25/2025-26 (2851 partite, di cui 2101 con conteggio esatto)

| Misura | Prima | Dopo |
|---|---|---|
| Punti medi reali / previsti | 4.353 / 3.990 | 4.353 / 4.353 |
| Errore medio assoluto | 1.893 | 1.912 |
| Log-verosimiglianza negativa | 2.3082 | 2.2634 |
| Log-verosimiglianza negativa (solo leghe esatte) | 2.3437 | 2.2868 |
| Over 3.5 punti: log-loss / Brier / ECE | 0.6693 / 0.4766 / 0.0210 | 0.6665 / 0.4739 / 0.0086 |
| Over 4.5 punti: log-loss / Brier / ECE | 0.6799 / 0.4865 / 0.0469 | 0.6745 / 0.4816 / 0.0135 |
| Over 5.5 punti: log-loss / Brier / ECE | 0.5880 / 0.3977 / 0.0587 | 0.5792 / 0.3913 / 0.0183 |
| Over 6.5 punti: log-loss / Brier / ECE | 0.4756 / 0.2940 / 0.0641 | 0.4579 / 0.2856 / 0.0079 |

### fuori campione 2026-27 (254 partite, di cui 193 con conteggio esatto)

| Misura | Prima | Dopo |
|---|---|---|
| Punti medi reali / previsti | 4.169 / 3.848 | 4.169 / 4.198 |
| Errore medio assoluto | 1.810 | 1.792 |
| Log-verosimiglianza negativa | 2.2203 | 2.1994 |
| Log-verosimiglianza negativa (solo leghe esatte) | 2.2102 | 2.1946 |
| Over 3.5 punti: log-loss / Brier / ECE | 0.6720 / 0.4792 / 0.0197 | 0.6689 / 0.4761 / 0.0501 |
| Over 4.5 punti: log-loss / Brier / ECE | 0.6577 / 0.4659 / 0.0536 | 0.6521 / 0.4600 / 0.0520 |
| Over 5.5 punti: log-loss / Brier / ECE | 0.5985 / 0.4073 / 0.0905 | 0.5777 / 0.3914 / 0.0265 |
| Over 6.5 punti: log-loss / Brier / ECE | 0.4383 / 0.2659 / 0.0610 | 0.4226 / 0.2580 / 0.0358 |

## Risultati esatti (calibrazione storica)

Generato il 22/10/2026 con `python -m tools.baseline --risultati-esatti`. Matrici Dixon-Coles con i gol attesi finali (modello ancorato alle quote medie di chiusura 1X2 e O/U 2.5) e, per confronto, del solo modello. Riferimento ingenuo: frequenze dei risultati nelle stagioni di taratura (nel fuori campione è un riferimento onesto, nella taratura è in-sample).

### taratura 2024-25/2025-26 (2852 partite)

| Misura | Valore |
|---|---|
| Log-loss risultato esatto: ancorato / solo modello / frequenze storiche | 2.8540 / 2.8878 / 3.0013 |
| Risultato più probabile: probabilità media prevista / frequenza reale | 12.9% / 13.3% |

Gruppo minimo (i risultati più probabili fino alla copertura scelta):

| Copertura scelta | Copertura prevista media | Frequenza reale | Risultati medi nel gruppo |
|---|---|---|---|
| 40% | 44.0% | 46.0% | 4.4 |
| 50% | 53.5% | 56.2% | 5.7 |
| 60% | 63.1% | 65.6% | 7.3 |
| 70% | 72.4% | 74.1% | 9.1 |
| 80% | 81.6% | 83.7% | 11.7 |
| 90% | 90.8% | 92.5% | 15.9 |

Calibrazione dei singoli risultati (tutte le celle della matrice):

| Probabilità prevista | Celle | Prevista media | Frequenza reale |
|---|---|---|---|
| 0%–2% | 304938 | 0.11% | 0.10% |
| 2%–4% | 12853 | 2.90% | 2.85% |
| 4%–6% | 8969 | 4.97% | 4.95% |
| 6%–8% | 6902 | 6.96% | 6.97% |
| 8%–10% | 6136 | 9.02% | 9.44% |
| 10%–12% | 2602 | 10.92% | 11.15% |
| 12%–15% | 2484 | 13.36% | 14.37% |
| 15%–20% | 207 | 15.66% | 14.01% |
| 20%–100% | 1 | 20.29% | 0.00% |

### fuori campione 2026-27 (254 partite)

| Misura | Valore |
|---|---|
| Log-loss risultato esatto: ancorato / solo modello / frequenze storiche | 3.0154 / 3.0553 / 3.2734 |
| Risultato più probabile: probabilità media prevista / frequenza reale | 12.2% / 12.2% |

Gruppo minimo (i risultati più probabili fino alla copertura scelta):

| Copertura scelta | Copertura prevista media | Frequenza reale | Risultati medi nel gruppo |
|---|---|---|---|
| 40% | 43.7% | 42.1% | 4.7 |
| 50% | 53.3% | 51.2% | 6.1 |
| 60% | 62.8% | 59.4% | 7.8 |
| 70% | 72.2% | 68.5% | 9.8 |
| 80% | 81.5% | 80.7% | 12.5 |
| 90% | 90.7% | 89.4% | 17.1 |

Calibrazione dei singoli risultati (tutte le celle della matrice):

| Probabilità prevista | Celle | Prevista media | Frequenza reale |
|---|---|---|---|
| 0%–2% | 27014 | 0.12% | 0.14% |
| 2%–4% | 1243 | 2.92% | 3.30% |
| 4%–6% | 897 | 4.96% | 4.24% |
| 6%–8% | 678 | 6.93% | 7.08% |
| 8%–10% | 528 | 9.00% | 7.95% |
| 10%–12% | 203 | 10.89% | 7.88% |
| 12%–15% | 163 | 13.30% | 16.56% |
| 15%–20% | 8 | 15.89% | 37.50% |

## Corner e cartellini: previsioni estreme ed equilibrio (fase M)

Generato il 23/10/2026 con `python -m tools.baseline --estremi`. Parametri stimati sul 2024-26 (`python -m tools.calibrate --estremi`); fuori campione = 2019-24 e 2026-27. Prima: corner = modello log-lineare, dispersione 51.3032; cartellini in punti (giallo 1, rosso 2, doppia ammonizione giallo e rosso), dispersione 12.3537. Dopo: totale corner = 9.63·(totale/9.63)^0.617, dispersione 53.9454; gialli × exp(0.099 -0.070·|ΔElo|/100), dispersione 13.4989. Nessuna quota corner/cartellini in football-data: nessun confronto con il mercato.

### 2019-24 (6899 partite)

Corner totali per fascia di previsione (prima, 8 fasce uguali):

| Fascia prevista | Partite | Previsti prima | Previsti dopo | Reali | Scarto prima | Scarto dopo |
|---|---|---|---|---|---|---|
| 7.02–8.81 | 863 | 8.43 | 8.87 | 8.86 | +0.43 | -0.01 |
| 8.81–9.20 | 862 | 9.02 | 9.25 | 9.20 | +0.18 | -0.05 |
| 9.20–9.49 | 862 | 9.36 | 9.46 | 9.65 | +0.29 | +0.19 |
| 9.49–9.75 | 863 | 9.63 | 9.63 | 9.83 | +0.20 | +0.20 |
| 9.75–10.02 | 862 | 9.89 | 9.79 | 9.77 | -0.12 | -0.02 |
| 10.02–10.33 | 862 | 10.17 | 9.96 | 10.05 | -0.12 | +0.09 |
| 10.33–10.75 | 862 | 10.52 | 10.17 | 10.26 | -0.26 | +0.09 |
| 10.75–13.29 | 863 | 11.20 | 10.57 | 10.67 | -0.53 | +0.10 |

Per equilibrio della partita (|ΔElo| in 5 fasce uguali):

| Scarto Elo (assoluto) | Partite | Corner previsti prima / dopo / reali | Gialli previsti prima / dopo / reali |
|---|---|---|---|
| 0–37 | 1380 | 9.82 / 9.74 / 9.80 | 4.16 / 4.54 / 4.54 |
| 37–78 | 1380 | 9.80 / 9.73 / 9.79 | 4.15 / 4.41 / 4.46 |
| 78–131 | 1379 | 9.78 / 9.71 / 9.60 | 4.12 / 4.23 / 4.34 |
| 131–208 | 1380 | 9.75 / 9.70 / 9.77 | 4.08 / 4.01 / 4.11 |
| 208–523 | 1380 | 9.72 / 9.68 / 9.96 | 4.06 / 3.68 / 3.72 |

Dispersione (rapporto varianza/media dei residui; 1 = Poisson):

| Conteggio | Media reale | Varianza reale | Varianza/media residui (dopo) |
|---|---|---|---|
| Corner totali | 9.78 | 11.66 | 1.170 |
| Gialli totali | 4.23 | 4.91 | 1.060 |

| Mercato | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|
| Corner Over 8.5 | 0.6554 | 0.6536 | 0.0099 | 0.0143 |
| Corner Over 9.5 | 0.6912 | 0.6876 | 0.0361 | 0.0103 |
| Corner Over 10.5 | 0.6663 | 0.6629 | 0.0188 | 0.0071 |
| Corner Over 11.5 | 0.5939 | 0.5915 | 0.0262 | 0.0052 |
| Corner: log-verosimiglianza negativa (binomiale negativa / Poisson) | 2.6215 / 2.6278 | 2.6182 / 2.6239 | | |
| Punti cartellini Over 3.5 | 0.6333 | 0.6249 | 0.0381 | 0.0306 |
| Punti cartellini Over 4.5 | 0.6633 | 0.6575 | 0.0269 | 0.0191 |
| Punti cartellini Over 5.5 | 0.5957 | 0.5921 | 0.0411 | 0.0222 |
| Punti cartellini: log-verosimiglianza negativa (binomiale negativa / Poisson) | 2.2704 / 2.2798 | 2.2617 / 2.2693 | | |

### 2026-27 (254 partite)

Corner totali per fascia di previsione (prima, 5 fasce uguali):

| Fascia prevista | Partite | Previsti prima | Previsti dopo | Reali | Scarto prima | Scarto dopo |
|---|---|---|---|---|---|---|
| 7.47–8.88 | 51 | 8.53 | 8.94 | 9.12 | +0.59 | +0.18 |
| 8.88–9.54 | 51 | 9.24 | 9.39 | 9.12 | -0.13 | -0.27 |
| 9.54–9.96 | 50 | 9.74 | 9.70 | 10.08 | +0.34 | +0.38 |
| 9.96–10.39 | 51 | 10.18 | 9.97 | 9.41 | -0.77 | -0.56 |
| 10.39–11.98 | 51 | 10.78 | 10.32 | 10.82 | +0.05 | +0.50 |

Per equilibrio della partita (|ΔElo| in 5 fasce uguali):

| Scarto Elo (assoluto) | Partite | Corner previsti prima / dopo / reali | Gialli previsti prima / dopo / reali |
|---|---|---|---|
| 1–40 | 51 | 9.66 / 9.64 / 8.57 | 3.96 / 4.31 / 4.18 |
| 40–85 | 51 | 9.65 / 9.64 / 9.84 | 3.88 / 4.10 / 4.53 |
| 85–150 | 50 | 9.73 / 9.69 / 9.48 | 3.84 / 3.92 / 3.60 |
| 150–224 | 51 | 9.71 / 9.67 / 10.75 | 3.78 / 3.68 / 3.43 |
| 224–512 | 51 | 9.72 / 9.67 / 9.90 | 3.78 / 3.35 / 3.45 |

Dispersione (rapporto varianza/media dei residui; 1 = Poisson):

| Conteggio | Media reale | Varianza reale | Varianza/media residui (dopo) |
|---|---|---|---|
| Corner totali | 9.71 | 12.90 | 1.290 |
| Gialli totali | 3.84 | 4.25 | 1.032 |

| Mercato | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|
| Corner Over 8.5 | 0.6748 | 0.6765 | 0.0517 | 0.0414 |
| Corner Over 9.5 | 0.6740 | 0.6769 | 0.0404 | 0.0231 |
| Corner Over 10.5 | 0.6544 | 0.6589 | 0.0387 | 0.0363 |
| Corner Over 11.5 | 0.6305 | 0.6297 | 0.0524 | 0.0485 |
| Corner: log-verosimiglianza negativa (binomiale negativa / Poisson) | 2.6780 / 2.6939 | 2.6777 / 2.6932 | | |
| Punti cartellini Over 3.5 | 0.6689 | 0.6654 | 0.0501 | 0.0119 |
| Punti cartellini Over 4.5 | 0.6521 | 0.6431 | 0.0520 | 0.0607 |
| Punti cartellini Over 5.5 | 0.5777 | 0.5704 | 0.0265 | 0.0224 |
| Punti cartellini: log-verosimiglianza negativa (binomiale negativa / Poisson) | 2.1994 / 2.2009 | 2.1880 / 2.1875 | | |

### fuori campione (unione) (7153 partite)

Corner totali per fascia di previsione (prima, 8 fasce uguali):

| Fascia prevista | Partite | Previsti prima | Previsti dopo | Reali | Scarto prima | Scarto dopo |
|---|---|---|---|---|---|---|
| 7.02–8.80 | 895 | 8.43 | 8.87 | 8.84 | +0.42 | -0.03 |
| 8.80–9.20 | 894 | 9.02 | 9.25 | 9.23 | +0.21 | -0.02 |
| 9.20–9.49 | 894 | 9.35 | 9.46 | 9.62 | +0.26 | +0.16 |
| 9.49–9.75 | 894 | 9.63 | 9.63 | 9.84 | +0.22 | +0.21 |
| 9.75–10.02 | 894 | 9.88 | 9.79 | 9.76 | -0.12 | -0.03 |
| 10.02–10.33 | 894 | 10.17 | 9.96 | 10.00 | -0.16 | +0.04 |
| 10.33–10.74 | 894 | 10.52 | 10.17 | 10.31 | -0.21 | +0.14 |
| 10.74–13.29 | 894 | 11.19 | 10.56 | 10.65 | -0.54 | +0.08 |

Per equilibrio della partita (|ΔElo| in 5 fasce uguali):

| Scarto Elo (assoluto) | Partite | Corner previsti prima / dopo / reali | Gialli previsti prima / dopo / reali |
|---|---|---|---|
| 0–37 | 1431 | 9.81 / 9.74 / 9.76 | 4.16 / 4.53 / 4.52 |
| 37–79 | 1430 | 9.80 / 9.73 / 9.80 | 4.15 / 4.40 / 4.46 |
| 79–131 | 1431 | 9.78 / 9.72 / 9.58 | 4.11 / 4.22 / 4.32 |
| 131–209 | 1430 | 9.75 / 9.70 / 9.80 | 4.07 / 4.00 / 4.09 |
| 209–523 | 1431 | 9.72 / 9.68 / 9.98 | 4.05 / 3.66 / 3.71 |

Dispersione (rapporto varianza/media dei residui; 1 = Poisson):

| Conteggio | Media reale | Varianza reale | Varianza/media residui (dopo) |
|---|---|---|---|
| Corner totali | 9.78 | 11.70 | 1.174 |
| Gialli totali | 4.22 | 4.89 | 1.059 |

| Mercato | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|
| Corner Over 8.5 | 0.6561 | 0.6544 | 0.0084 | 0.0127 |
| Corner Over 9.5 | 0.6906 | 0.6872 | 0.0357 | 0.0091 |
| Corner Over 10.5 | 0.6659 | 0.6627 | 0.0188 | 0.0076 |
| Corner Over 11.5 | 0.5952 | 0.5928 | 0.0262 | 0.0066 |
| Corner: log-verosimiglianza negativa (binomiale negativa / Poisson) | 2.6235 / 2.6301 | 2.6203 / 2.6264 | | |
| Punti cartellini Over 3.5 | 0.6346 | 0.6263 | 0.0352 | 0.0291 |
| Punti cartellini Over 4.5 | 0.6629 | 0.6569 | 0.0262 | 0.0203 |
| Punti cartellini Over 5.5 | 0.5951 | 0.5913 | 0.0399 | 0.0217 |
| Punti cartellini: log-verosimiglianza negativa (binomiale negativa / Poisson) | 2.2679 / 2.2770 | 2.2590 / 2.2664 | | |

## Cartellini per squadra: divisione tra casa e ospite (fase T)

Generato il 27/10/2026 con `python -m tools.card_split`. Totale gialli invariato (fase M); si modella solo la quota della squadra di casa. Punti Eurobet (giallo 1, rosso 2). Taratura sul 2024-26, fuori campione 2019-24 e 2026-27 (stesso schema della fase M). Una componente resta accesa solo se migliora sia la log-loss media sia l'ECE media fuori campione (unione dei due insiemi).

### Componenti provate, nell'ordine

| Passo | Log-loss media | ECE media | Brier media | Tenuta |
|---|---|---|---|---|
| prima (divisione attuale) | 0.62674 | 0.02963 | 0.41298 | sì |
| a) ritmo + provocati, con shrinkage | 0.61491 | 0.02901 | 0.40340 | sì |
| b) sfavorita (differenza Elo) | 0.61233 | 0.02915 | 0.40133 | no |
| b) sfavorita (1X2 di mercato senza margine) | 0.61069 | 0.02414 | 0.40005 | sì |
| c) casa/trasferta | 0.61002 | 0.02455 | 0.39951 | no |
| d) fattore comune: divisione più dispersa (beta-binomiale) | 0.61069 | 0.02413 | 0.40005 | no |
| d) fattore comune: bilanciamento (binomiale moltiplicativa) | 0.60908 | 0.01534 | 0.39916 | sì |
| e) arbitro sulla divisione | 0.60908 | 0.01552 | 0.39916 | no |

Parametri scelti: {"home": 0.0, "rate_weight": 0.13867465795530382, "provoked_weight": 0.40399673261415386, "underdog_weight": 0.7064553010509802, "referee_weight": 0.0, "concentration": 0.0, "balance": 0.15331340427512674, "shrink": true, "underdog": "mercato"}

### 2019-24 (6899 partite): prima / dopo

| Mercato | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|
| 1X2 cartellini | 1.0905 | 1.0492 | 0.0627 | 0.0113 |
| Casa Over 0.5 | 0.3778 | 0.3682 | 0.0126 | 0.0156 |
| Ospite Over 0.5 | 0.3265 | 0.3140 | 0.0434 | 0.0191 |
| Casa Over 1.5 | 0.6544 | 0.6369 | 0.0252 | 0.0094 |
| Ospite Over 1.5 | 0.6240 | 0.6073 | 0.0248 | 0.0281 |
| Casa Over 2.5 | 0.6423 | 0.6269 | 0.0112 | 0.0217 |
| Ospite Over 2.5 | 0.6683 | 0.6585 | 0.0318 | 0.0041 |
| media | 0.6263 | 0.6087 | 0.0303 | 0.0156 |

### 2026-27 (254 partite): prima / dopo

| Mercato | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|
| 1X2 cartellini | 1.0706 | 1.0300 | 0.0555 | 0.0182 |
| Casa Over 0.5 | 0.3975 | 0.3885 | 0.0282 | 0.0194 |
| Ospite Over 0.5 | 0.3928 | 0.3897 | 0.0333 | 0.0106 |
| Casa Over 1.5 | 0.6880 | 0.6556 | 0.0433 | 0.0402 |
| Ospite Over 1.5 | 0.6557 | 0.6284 | 0.0484 | 0.0321 |
| Casa Over 2.5 | 0.6138 | 0.5960 | 0.0437 | 0.0597 |
| Ospite Over 2.5 | 0.6564 | 0.6471 | 0.0883 | 0.0338 |
| media | 0.6392 | 0.6193 | 0.0487 | 0.0306 |

### Previsto / reale per fascia (fuori campione, 5 fasce uguali): prima → dopo

| Mercato | Fascia | Partite | Prevista prima | Prevista dopo | Reale |
|---|---|---|---|---|---|
| 1 cartellini | 1 | 1431 | 23.1% | 24.5% | 30.9% |
| 1 cartellini | 2 | 1430 | 33.4% | 31.0% | 30.2% |
| 1 cartellini | 3 | 1431 | 40.5% | 36.4% | 35.8% |
| 1 cartellini | 4 | 1430 | 47.8% | 42.0% | 35.5% |
| 1 cartellini | 5 | 1431 | 59.5% | 49.9% | 39.9% |
| X cartellini | 1 | 1431 | 16.0% | 19.3% | 19.6% |
| X cartellini | 2 | 1430 | 17.7% | 20.3% | 22.6% |
| X cartellini | 3 | 1431 | 18.6% | 21.0% | 22.6% |
| X cartellini | 4 | 1430 | 19.5% | 21.7% | 23.1% |
| X cartellini | 5 | 1431 | 21.1% | 23.1% | 22.3% |
| 2 cartellini | 1 | 1431 | 23.0% | 28.6% | 38.0% |
| 2 cartellini | 2 | 1430 | 33.1% | 36.7% | 40.1% |
| 2 cartellini | 3 | 1431 | 40.0% | 42.6% | 43.8% |
| 2 cartellini | 4 | 1430 | 47.5% | 48.1% | 47.6% |
| 2 cartellini | 5 | 1431 | 59.2% | 55.0% | 47.9% |
| Casa Over 0.5 | 1 | 1431 | 75.8% | 78.7% | 79.9% |
| Casa Over 0.5 | 2 | 1430 | 83.6% | 85.1% | 85.5% |
| Casa Over 0.5 | 3 | 1431 | 86.9% | 87.7% | 87.5% |
| Casa Over 0.5 | 4 | 1430 | 89.4% | 89.7% | 89.4% |
| Casa Over 0.5 | 5 | 1431 | 92.4% | 92.0% | 92.7% |
| Ospite Over 0.5 | 1 | 1431 | 75.7% | 80.6% | 84.9% |
| Ospite Over 0.5 | 2 | 1430 | 83.6% | 86.8% | 88.6% |
| Ospite Over 0.5 | 3 | 1431 | 86.7% | 89.3% | 89.9% |
| Ospite Over 0.5 | 4 | 1430 | 89.3% | 91.1% | 91.6% |
| Ospite Over 0.5 | 5 | 1431 | 92.4% | 93.2% | 94.7% |
| Casa Over 1.5 | 1 | 1431 | 45.2% | 48.0% | 51.6% |
| Casa Over 1.5 | 2 | 1430 | 57.2% | 58.3% | 60.3% |
| Casa Over 1.5 | 3 | 1431 | 63.4% | 63.5% | 61.0% |
| Casa Over 1.5 | 4 | 1430 | 68.5% | 67.7% | 64.6% |
| Casa Over 1.5 | 5 | 1431 | 75.5% | 73.1% | 72.5% |
| Ospite Over 1.5 | 1 | 1431 | 45.1% | 51.0% | 57.8% |
| Ospite Over 1.5 | 2 | 1430 | 57.0% | 61.6% | 63.6% |
| Ospite Over 1.5 | 3 | 1431 | 62.9% | 66.8% | 68.6% |
| Ospite Over 1.5 | 4 | 1430 | 68.3% | 70.9% | 72.3% |
| Ospite Over 1.5 | 5 | 1431 | 75.4% | 76.2% | 77.7% |
| Casa Over 2.5 | 1 | 1431 | 22.3% | 23.6% | 23.5% |
| Casa Over 2.5 | 2 | 1430 | 32.7% | 32.7% | 34.1% |
| Casa Over 2.5 | 3 | 1431 | 39.2% | 38.1% | 34.9% |
| Casa Over 2.5 | 4 | 1430 | 45.1% | 42.8% | 38.6% |
| Casa Over 2.5 | 5 | 1431 | 54.2% | 49.6% | 48.6% |
| Ospite Over 2.5 | 1 | 1431 | 22.3% | 26.2% | 29.7% |
| Ospite Over 2.5 | 2 | 1430 | 32.6% | 36.0% | 37.4% |
| Ospite Over 2.5 | 3 | 1431 | 38.7% | 41.7% | 40.4% |
| Ospite Over 2.5 | 4 | 1430 | 44.9% | 46.6% | 45.8% |
| Ospite Over 2.5 | 5 | 1431 | 54.1% | 53.7% | 54.4% |

## Motore minuto per minuto: regole stimate (fase O)

Generato il 27/10/2026 con `python -m tools.minute_model`. Understat: 3504 partite (EPL, Liga, Bundesliga, Serie A, Ligue 1, stagioni 2023/24 e 2024/25). StatsBomb: 1551 partite (StatsBomb Open Data 2015/16: Premier League, Liga, Serie A, Bundesliga, Ligue 1; Data: StatsBomb Open Data). Effetto fisso di squadra-partita, shrinkage verso 1 ({'stato': 15.0, 'espulsioni': 8.0, 'corner': 15.0, 'cartellini': 15.0}).

### Ritmo degli xG per stato del punteggio (squadra che…), per fascia di minuti: Understat / StatsBomb

| Stato | 0-30' | 30-60' | 60-75' | 75-90' |
|---|---|---|---|---|
| perde di 2+ | 1.12 / 1.18 | 1.46 / 1.52 | 1.52 / 1.61 | 1.49 / 1.48 |
| perde di 1 | 1.16 / 1.14 | 1.30 / 1.28 | 1.31 / 1.29 | 1.41 / 1.45 |
| pareggia (rif.) | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| vince di 1 | 0.57 / 0.59 | 0.61 / 0.71 | 0.64 / 0.66 | 0.66 / 0.70 |
| vince di 2+ | 0.45 / 0.51 | 0.41 / 0.44 | 0.42 / 0.44 | 0.43 / 0.44 |

Espulsioni (ritmo xG di chi è in 10 / della squadra in superiorità): Understat 0.63 / 1.78; StatsBomb 0.65 / 1.56.

Pesi dei blocchi di 5 minuti (gol, Understat): 0.66, 0.65, 0.66, 0.76, 0.80, 0.80, 0.80, 0.81, 2.18, 1.27, 1.00, 1.01, 0.94, 0.95, 0.94, 0.86, 0.89, 2.02

Corner ∝ pressione offensiva^γ: γ = 0.77 (log-verosimiglianza negativa 59133.5 contro 59364.4 con γ = 0; 16555 corner).

Cartellini: moltiplicatore se la partita è in parità, per fascia: 0-30' 0.88, 30-60' 1.00, 60-75' 1.01, 75-90' 1.23; pesi dei blocchi: 0.20, 0.30, 0.45, 0.59, 0.68, 0.83, 0.88, 1.01, 2.00, 0.70, 0.92, 1.13, 1.16, 1.11, 1.19, 1.05, 1.20, 2.59 (7325 cartellini).


## Motore minuto per minuto: verifica fuori campione (fase O)

Generato il 27/10/2026 con `python -m tools.minute_check`. 1754 partite di football-data.co.uk (1920: 354. 2021: 399. 2122: 346. 2223: 401. 2627: 254). escluse le stagioni usate per stimare le regole o tarare gli altri parametri (2324. 2425. 2526). Gol ancorati alle quote di chiusura come nell'app; 20.000 simulazioni per partita e variante. Una componente resta accesa solo se la log-loss media scende di più di due errori standard (confronto appaiato partita per partita) e l'ECE media non sale (tolleranza 0.0005).

### Componenti provate, nell'ordine

| Passo | Log-loss media | ECE media | Differenza appaiata (± 2 e.s.) | Tenuta |
|---|---|---|---|---|
| motore attuale | 0.61703 | 0.01792 | +0.00000 ± 0.00000 | sì |
| gol_stato | 0.61962 | 0.02192 | +0.00259 ± 0.00106 | no |
| espulsioni | 0.61749 | 0.01960 | +0.00046 ± 0.00044 | no |
| corner_pressione | 0.61699 | 0.01769 | -0.00004 ± 0.00012 | no |
| cartellini_tempo | 0.61707 | 0.01739 | +0.00003 ± 0.00011 | no |

### Per mercato: motore attuale → scelta finale (motore attuale)

| Mercato | Gruppo | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|---|
| 1X2 | gol | 0.9654 | 0.9654 | 0.0168 | 0.0168 |
| Over 1.5 | gol | 0.4951 | 0.4951 | 0.0124 | 0.0124 |
| Over 2.5 | gol | 0.6629 | 0.6629 | 0.0211 | 0.0211 |
| Over 3.5 | gol | 0.6135 | 0.6135 | 0.0183 | 0.0183 |
| Goal | gol | 0.6808 | 0.6808 | 0.0098 | 0.0098 |
| 1X2 1T | tempi | 1.0183 | 1.0183 | 0.0075 | 0.0075 |
| 1T Over 0.5 | tempi | 0.5907 | 0.5907 | 0.0087 | 0.0087 |
| 1T Over 1.5 | tempi | 0.6451 | 0.6451 | 0.0110 | 0.0110 |
| 2T Over 0.5 | tempi | 0.4751 | 0.4751 | 0.0290 | 0.0290 |
| 2T Over 1.5 | tempi | 0.6760 | 0.6760 | 0.0387 | 0.0387 |
| Corner Over 8.5 | corner | 0.6604 | 0.6604 | 0.0165 | 0.0165 |
| Corner Over 9.5 | corner | 0.6869 | 0.6869 | 0.0065 | 0.0065 |
| Corner Over 10.5 | corner | 0.6605 | 0.6605 | 0.0138 | 0.0138 |
| Cartellini Over 3.5 | cartellini | 0.6358 | 0.6358 | 0.0211 | 0.0211 |
| Cartellini Over 4.5 | cartellini | 0.6497 | 0.6497 | 0.0413 | 0.0413 |
| Cartellini Over 5.5 | cartellini | 0.5757 | 0.5757 | 0.0277 | 0.0277 |
| Over 2.5 & Corner Over 9.5 | combo | 0.5724 | 0.5724 | 0.0191 | 0.0191 |
| Over 2.5 & Cartellini Over 4.5 | combo | 0.5167 | 0.5167 | 0.0219 | 0.0219 |
| Goal & Corner Over 9.5 | combo | 0.5802 | 0.5802 | 0.0116 | 0.0116 |
| 1 & Over 2.5 | combo | 0.5500 | 0.5500 | 0.0164 | 0.0164 |
| X & Under 2.5 | combo | 0.4593 | 0.4593 | 0.0200 | 0.0200 |
| Corner Over 9.5 & Cartellini Over 4.5 | combo | 0.5194 | 0.5194 | 0.0129 | 0.0129 |
| X & Cartellini Over 4.5 | combo | 0.3679 | 0.3679 | 0.0089 | 0.0089 |
| 1T Over 0.5 & Over 2.5 | combo | 0.6678 | 0.6678 | 0.0053 | 0.0053 |
| Under 2.5 & Corner Under 9.5 | combo | 0.5002 | 0.5002 | 0.0316 | 0.0316 |

| Media per gruppo | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|
| media gol | 0.6836 | 0.6836 | 0.0157 | 0.0157 |
| media tempi | 0.6810 | 0.6810 | 0.0190 | 0.0190 |
| media corner | 0.6693 | 0.6693 | 0.0122 | 0.0122 |
| media cartellini | 0.6204 | 0.6204 | 0.0300 | 0.0300 |
| media combo | 0.5260 | 0.5260 | 0.0164 | 0.0164 |
| media | 0.6170 | 0.6170 | 0.0179 | 0.0179 |

### Tutte le varianti (log-loss / ECE medie per gruppo)

| Variante | gol | tempi | corner | cartellini | combo | media |
|---|---|---|---|---|---|---|
| motore attuale | 0.6836 / 0.0157 | 0.6810 / 0.0190 | 0.6693 / 0.0122 | 0.6204 / 0.0300 | 0.5260 / 0.0164 | 0.6170 / 0.0179 |
| gol_stato | 0.6896 / 0.0281 | 0.6861 / 0.0241 | 0.6692 / 0.0120 | 0.6205 / 0.0266 | 0.5270 / 0.0190 | 0.6196 / 0.0219 |
| espulsioni | 0.6848 / 0.0194 | 0.6811 / 0.0197 | 0.6692 / 0.0105 | 0.6208 / 0.0304 | 0.5264 / 0.0191 | 0.6175 / 0.0196 |
| corner_pressione | 0.6836 / 0.0157 | 0.6810 / 0.0182 | 0.6691 / 0.0136 | 0.6206 / 0.0295 | 0.5258 / 0.0159 | 0.6170 / 0.0177 |
| cartellini_tempo | 0.6836 / 0.0157 | 0.6810 / 0.0182 | 0.6692 / 0.0119 | 0.6208 / 0.0293 | 0.5260 / 0.0157 | 0.6171 / 0.0174 |


## Motore minuto per minuto: varianti ibride con punteggi Dixon-Coles fissi (fase Q, punto 0)

Generato il 27/10/2026 con `python -m tools.minute_check`. 1754 partite di football-data.co.uk (1920: 354. 2021: 399. 2122: 346. 2223: 401. 2627: 254). escluse le stagioni usate per stimare le regole o tarare gli altri parametri (2324. 2425. 2526). Gol ancorati alle quote di chiusura come nell'app; 20.000 simulazioni per partita e variante. Una componente resta accesa solo se la log-loss media scende di più di due errori standard (confronto appaiato partita per partita) e l'ECE media non sale (tolleranza 0.0005).

### Componenti provate, nell'ordine

| Passo | Log-loss media | ECE media | Differenza appaiata (± 2 e.s.) | Tenuta |
|---|---|---|---|---|
| motore attuale | 0.61530 | 0.01815 | +0.00000 ± 0.00000 | sì |
| tempi_stato | 0.61531 | 0.01774 | +0.00001 ± 0.00016 | no |
| espulsioni_tempi | 0.61531 | 0.01784 | +0.00002 ± 0.00013 | no |
| corner_pressione | 0.61528 | 0.01836 | -0.00002 ± 0.00015 | no |
| cartellini_tempo | 0.61533 | 0.01753 | +0.00004 ± 0.00013 | no |

### Per mercato: motore attuale → scelta finale (motore attuale)

| Mercato | Gruppo | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|---|
| 1X2 | gol | 0.9654 | 0.9654 | 0.0168 | 0.0168 |
| Over 1.5 | gol | 0.4951 | 0.4951 | 0.0124 | 0.0124 |
| Over 2.5 | gol | 0.6629 | 0.6629 | 0.0211 | 0.0211 |
| Over 3.5 | gol | 0.6135 | 0.6135 | 0.0183 | 0.0183 |
| Goal | gol | 0.6808 | 0.6808 | 0.0098 | 0.0098 |
| 1X2 1T | tempi | 1.0183 | 1.0183 | 0.0075 | 0.0075 |
| 1X2 2T | tempi | 1.0438 | 1.0438 | 0.0070 | 0.0070 |
| 1T Over 0.5 | tempi | 0.5907 | 0.5907 | 0.0087 | 0.0087 |
| 1T Over 1.5 | tempi | 0.6451 | 0.6451 | 0.0110 | 0.0110 |
| 2T Over 0.5 | tempi | 0.4751 | 0.4751 | 0.0290 | 0.0290 |
| 2T Over 1.5 | tempi | 0.6760 | 0.6760 | 0.0387 | 0.0387 |
| Multigol 1T 0-1 | tempi | 0.6451 | 0.6451 | 0.0110 | 0.0110 |
| Multigol 1T 1-2 | tempi | 0.6787 | 0.6787 | 0.0125 | 0.0125 |
| Multigol 2T 0-1 | tempi | 0.6760 | 0.6760 | 0.0387 | 0.0387 |
| Multigol 2T 1-3 | tempi | 0.5874 | 0.5874 | 0.0186 | 0.0186 |
| Primo tempo con più gol | tempi | 0.5919 | 0.5919 | 0.0257 | 0.0257 |
| Corner Over 8.5 | corner | 0.6604 | 0.6604 | 0.0165 | 0.0165 |
| Corner Over 9.5 | corner | 0.6869 | 0.6869 | 0.0065 | 0.0065 |
| Corner Over 10.5 | corner | 0.6605 | 0.6605 | 0.0138 | 0.0138 |
| Cartellini Over 3.5 | cartellini | 0.6358 | 0.6358 | 0.0211 | 0.0211 |
| Cartellini Over 4.5 | cartellini | 0.6497 | 0.6497 | 0.0413 | 0.0413 |
| Cartellini Over 5.5 | cartellini | 0.5757 | 0.5757 | 0.0277 | 0.0277 |
| Over 2.5 & Corner Over 9.5 | combo | 0.5724 | 0.5724 | 0.0191 | 0.0191 |
| Over 2.5 & Cartellini Over 4.5 | combo | 0.5167 | 0.5167 | 0.0219 | 0.0219 |
| Goal & Corner Over 9.5 | combo | 0.5802 | 0.5802 | 0.0116 | 0.0116 |
| 1 & Over 2.5 | combo | 0.5500 | 0.5500 | 0.0164 | 0.0164 |
| X & Under 2.5 | combo | 0.4593 | 0.4593 | 0.0200 | 0.0200 |
| Corner Over 9.5 & Cartellini Over 4.5 | combo | 0.5194 | 0.5194 | 0.0129 | 0.0129 |
| X & Cartellini Over 4.5 | combo | 0.3679 | 0.3679 | 0.0089 | 0.0089 |
| 1T Over 0.5 & Over 2.5 | combo | 0.6678 | 0.6678 | 0.0053 | 0.0053 |
| Under 2.5 & Corner Under 9.5 | combo | 0.5002 | 0.5002 | 0.0316 | 0.0316 |
| 1T Over 0.5 & Corner Over 9.5 | combo | 0.6435 | 0.6435 | 0.0086 | 0.0086 |
| 2T Over 1.5 & Cartellini Over 4.5 | combo | 0.4938 | 0.4938 | 0.0187 | 0.0187 |
| 1X2 1T pari & Cartellini Over 4.5 | combo | 0.4754 | 0.4754 | 0.0161 | 0.0161 |

| Media per gruppo | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|
| media gol | 0.6836 | 0.6836 | 0.0157 | 0.0157 |
| media tempi | 0.6935 | 0.6935 | 0.0190 | 0.0190 |
| media corner | 0.6693 | 0.6693 | 0.0122 | 0.0122 |
| media cartellini | 0.6204 | 0.6204 | 0.0300 | 0.0300 |
| media combo | 0.5289 | 0.5289 | 0.0159 | 0.0159 |
| media | 0.6153 | 0.6153 | 0.0182 | 0.0182 |

### Tutte le varianti (log-loss / ECE medie per gruppo)

| Variante | gol | tempi | corner | cartellini | combo | media |
|---|---|---|---|---|---|---|
| motore attuale | 0.6836 / 0.0157 | 0.6935 / 0.0190 | 0.6693 / 0.0122 | 0.6204 / 0.0300 | 0.5289 / 0.0159 | 0.6153 / 0.0182 |
| tempi_stato | 0.6836 / 0.0157 | 0.6933 / 0.0185 | 0.6694 / 0.0119 | 0.6207 / 0.0287 | 0.5290 / 0.0158 | 0.6153 / 0.0177 |
| espulsioni_tempi | 0.6836 / 0.0157 | 0.6935 / 0.0179 | 0.6691 / 0.0125 | 0.6206 / 0.0297 | 0.5289 / 0.0162 | 0.6153 / 0.0178 |
| corner_pressione | 0.6836 / 0.0157 | 0.6934 / 0.0185 | 0.6691 / 0.0136 | 0.6207 / 0.0320 | 0.5289 / 0.0161 | 0.6153 / 0.0184 |
| cartellini_tempo | 0.6836 / 0.0157 | 0.6934 / 0.0185 | 0.6692 / 0.0119 | 0.6209 / 0.0295 | 0.5289 / 0.0151 | 0.6153 / 0.0175 |


## Goleade: calibrazione fuori campione e correzione della coda (fase Q, 6c)

Generato il 27/10/2026 con `python -m tools.goleade`. 7153 partite fuori campione (2019-24 e 2026-27), gol attesi ancorati alle quote di chiusura, punteggi Dixon-Coles. Correzione provata: marginali binomiali negative con dispersione k = 500.0 tarata sul 2024-26 (2852 partite, verosimiglianza dei punteggi esatti). Differenza appaiata della log-loss media dei tre mercati -0.00011 ± 0.00009 (2 e.s.): **spenta** (dispersione al limite superiore: i dati non chiedono una coda più pesante, il modello Poisson non sottostima le goleade).

| Mercato | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |
|---|---|---|---|---|
| Favorita 4+ gol | 0.3249 | 0.3248 | 0.0081 | 0.0085 |
| Favorita vince di 3+ | 0.3835 | 0.3832 | 0.0134 | 0.0123 |
| Totale 5+ gol | 0.4221 | 0.4221 | 0.0071 | 0.0072 |
| media goleade | 0.3768 | 0.3767 | 0.0095 | 0.0093 |
| 1X2 | 0.9651 | 0.9648 | 0.0095 | 0.0064 |
| Over 2.5 | 0.6666 | 0.6666 | 0.0159 | 0.0161 |

Per fascia di squilibrio (media prevista prima / dopo / frequenza reale):

| Fascia |λ − μ| | Partite | Favorita 4+ gol: prima / dopo / reale | Favorita vince di 3+: prima / dopo / reale | Totale 5+ gol: prima / dopo / reale |
|---|---|---|---|---|
| -0.00–0.23 | 1431 | 5.2% / 5.2% / 4.4% | 6.6% / 6.7% / 5.6% | 12.9% / 12.9% / 13.3% |
| 0.23–0.48 | 1430 | 6.8% / 6.8% / 6.9% | 9.0% / 9.0% / 9.3% | 13.4% / 13.4% / 13.0% |
| 0.48–0.83 | 1431 | 9.3% / 9.3% / 8.7% | 12.5% / 12.5% / 10.8% | 14.5% / 14.5% / 14.2% |
| 0.83–1.29 | 1430 | 13.8% / 13.7% / 13.6% | 18.4% / 18.2% / 17.3% | 16.9% / 16.8% / 16.0% |
| 1.29–3.82 | 1431 | 25.7% / 25.4% / 23.1% | 32.9% / 32.5% / 28.7% | 24.4% / 24.1% / 23.7% |


## Incroci di stile delle schede tattiche (fase Q, punti 5 e 7)

Generato il 27/10/2026 con `python -m tools.tactical_cross`. Stima su StatsBomb Open Data 2015/16 (Premier, Liga, Serie A, Ligue 1; schede dai valori di stagione senza la partita; cartellini misurati con i falli), verifica su football-data.co.uk + Understat 2019-27 (10004 partite, 8789 con le schede di entrambe le squadre). Fattori dopo l'ancoraggio alle quote di chiusura; regola severa: log-loss appaiata giù di oltre 2 errori standard ED ECE non peggiore.

| Regola | Casi StatsBomb | Effetto stimato (± e.s.) | Valore usato | Verifica | Esito |
|---|---|---|---|---|---|
| Verticale contro blocco alto a zona | 0 | non stimabile: campo non misurabile nei dati: non_possesso | gol 1.06 (prudente (campo non misurabile nei dati: non_possesso)) | non verificabile: manca nei dati Understat: non_possesso | **spenta** |
| Orizzontale contro blocco basso, gestione scarsa | 82 | gol 1.122 ± 0.063, corner 1.008 ± 0.069 | gol 1.12, corner 1.008 (stimato su StatsBomb Open Data 2015/16) | 204 partite; gol: 0.8170 → 0.8170 (+0.00000 ± 0.00018), ECE 0.0100 → 0.0101; corner: 2.6200 → 2.6200 (+0.00003 ± 0.00006), ECE 0.0062 → 0.0066 | **spenta** |
| Orizzontale contro blocco basso, gestione buona | 202 | gol 0.920 ± 0.034, corner 0.937 ± 0.036 | gol 0.92, corner 0.937 (stimato su StatsBomb Open Data 2015/16) | 1409 partite; gol: 0.8170 → 0.8173 (+0.00029 ± 0.00045), ECE 0.0100 → 0.0113; corner: 2.6200 → 2.6238 (+0.00382 ± 0.00144), ECE 0.0062 → 0.0191 | **spenta** |
| Pressing alto contro squadra che non gestisce palla | 331 | gol 1.022 ± 0.029, cartellini 0.993 ± 0.011 | gol 1.022, cartellini 0.993 (stimato su StatsBomb Open Data 2015/16) | 1905 partite; gol: 0.8170 → 0.8170 (+0.00005 ± 0.00013), ECE 0.0100 → 0.0096; cartellini: 2.1460 → 2.1461 (+0.00005 ± 0.00010), ECE 0.0129 → 0.0134 | **spenta** |
| Fasce e cross contro difesa a uomo | 0 | non stimabile: campo non misurabile nei dati: non_possesso | corner 1.08 (prudente (campo non misurabile nei dati: non_possesso)) | non verificabile: manca nei dati Understat: fasce_cross, non_possesso | **spenta** |


## Nuovi mercati: verifica fuori campione (fase Q, punto 7)

Generato il 27/10/2026 con `python -m tools.new_markets`. 7153 partite 2019-24 e 2026-27 (fuori dal periodo di taratura), gol ancorati alle quote di chiusura, primo tempo con le quote tarate, corner e gialli dal modello dei conteggi. Per ogni famiglia: media sui mercati della log-loss binaria e dell'ECE, scarto massimo tra probabilità media e frequenza osservata.

| Famiglia | Mercati | Log-loss media | ECE media | Scarto massimo (mercato: previsto / reale) |
|---|---|---|---|---|
| Multigol 1T | 10 | 0.5108 | 0.0077 | Multigol 1T 1-3: 66.4% / 67.7% |
| Multigol 2T | 11 | 0.5249 | 0.0153 | Multigol 2T 1-3: 70.9% / 73.5% |
| Over 4.5-6.5 gol | 3 | 0.2633 | 0.0051 | Over 4.5 gol: 16.4% / 16.0% |
| Goal/No Goal + U/O | 12 | 0.4846 | 0.0084 | Goal + Under 4.5: 38.6% / 40.4% |
| Segno + U/O | 40 | 0.4438 | 0.0100 | X + Under 1.5: 7.7% / 6.3% |
| Multigol casa+ospite | 100 | 0.5175 | 0.0121 | Multigol Casa 1-2 + Ospite 0-4: 53.3% / 56.6% |
| Fasce corner totali | 7 | 0.5113 | 0.0065 | Corner totali 0-8: 38.5% / 37.6% |
| Fasce corner per squadra | 8 | 0.5488 | 0.0337 | Corner casa 0-2: 11.6% / 16.8% |
| Fasce cartellini totali (gialli) | 10 | 0.2511 | 0.0133 | Cartellini totali 0-3: 43.8% / 39.8% |

Non verificabili con i dati storici disponibili: Corner per tempo (Over/Under 1T e 2T, 1X2 corner 1T); Cartellini per tempo (Over/Under 1T e 2T, 1X2 cartellini 1T); Fasce cartellini per squadra (divisione verificata nella fase T solo per le linee). Le quote dei tempi per corner (0,493) e cartellini (0,386) vengono dai pesi dei blocchi stimati su StatsBomb Open Data 2015/16 (fase O) e restano dichiarate come non verificate.


# Fase P – Motore statistico v2 (27/10/2026)

Ogni punto è un'opzione di config/goal_model.json, accesa solo con la regola severa fuori campione.

## Forza corretta per il calendario (fase P, punto 1)

Generato il 27/10/2026 con `python -m tools.strength_check`. Forze Dixon-Coles di tutte le squadre stimate insieme, solo con le partite precedenti (730 giorni, settimana per settimana), risposta = peso·gol + (1 − peso)·xG Understat (xG presenti nel 100% delle partite storiche). Griglia scelta sul 2024-26 con i gol ancorati al mercato: migliore ξ = 0.001/giorno, peso dei gol 0.0; modo scelto sul 2024-26: **ingressi** (taratura: attuale 1.6397, diretto 1.6403, ingressi 1.6395).

Fuori campione (2019-24 e 2026-27), log-loss 1X2 + Over/Under 2.5 per partita:

| Variante | Partite | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE | Esito |
|---|---|---|---|---|---|---|
| finale ancorato, diretto | 7152 | 1.6318 | 1.6324 | +0.00057 ± 0.00095 | 0.0127 → 0.0140 | **spenta** |
| finale ancorato, ingressi | 7152 | 1.6318 | 1.6316 | -0.00028 ± 0.00033 | 0.0127 → 0.0125 | **spenta** |
| solo modello, diretto (informativo) | 7152 | 1.6614 | 1.7020 | +0.04059 ± 0.00919 | 0.0093 → 0.0609 | *non migliora* |
| solo modello, ingressi (informativo) | 7152 | 1.6614 | 1.6528 | -0.00863 ± 0.00329 | 0.0093 → 0.0070 | *migliora* |

Griglia (taratura 2024-26, modo diretto):

| ξ/giorno | Peso gol | Log-loss | ECE |
|---|---|---|---|
| 0.0005 | 1.0 | 1.6405 | 0.0139 |
| 0.0005 | 0.5 | 1.6404 | 0.0141 |
| 0.0005 | 0.0 | 1.6403 | 0.0125 |
| 0.001 | 1.0 | 1.6406 | 0.0131 |
| 0.001 | 0.5 | 1.6404 | 0.0132 |
| 0.001 | 0.0 | 1.6403 | 0.0126 |
| 0.002 | 1.0 | 1.6407 | 0.0132 |
| 0.002 | 0.5 | 1.6404 | 0.0126 |
| 0.002 | 0.0 | 1.6403 | 0.0124 |
| 0.004 | 1.0 | 1.6410 | 0.0148 |
| 0.004 | 0.5 | 1.6406 | 0.0132 |
| 0.004 | 0.0 | 1.6403 | 0.0124 |

Esito: **spenta** (modo ingressi).


## Marcatori v2 e assenze pesate (fase P, punti 7b e 2)

Generato il 27/10/2026 con `python -m tools.player_check`. Storico partita per partita Understat 2025/26 e 2026/27 (5 campionati, statistiche fino alla partita precedente).

### Marcatori

Parametri v2 stimati fino al 31/12/2025 (14391 righe giocatore-partita): quota a priori difensore 0.032, centrocampista 0.095, attaccante 0.207; xG fittizi 10.79; quota dei gol su rigore 0.076. Verifica dal 01/01/2026 (26003 righe).

| Variante | Partite | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE | Esito |
|---|---|---|---|---|---|---|
| attuale → v2 | 26003 | 0.2751 | 0.2716 | -0.00347 ± 0.00135 | 0.0078 → 0.0021 | **accesa** |

Esito: v2 **adottata**; marcatori **verificati** (soglia ECE 0.015).

| Ruolo | Minuti medi | Righe | P media attuale | P media v2 | Frequenza reale |
|---|---|---|---|---|---|
| attaccante | < 30' | 656 | 8.3% | 7.5% | 11.4% |
| attaccante | 30-60' | 2787 | 13.7% | 13.5% | 14.9% |
| attaccante | 60'+ | 3091 | 22.6% | 22.5% | 22.8% |
| centrocampista | < 30' | 597 | 3.7% | 3.4% | 4.5% |
| centrocampista | 30-60' | 3650 | 6.3% | 6.3% | 6.6% |
| centrocampista | 60'+ | 6469 | 8.7% | 9.3% | 8.8% |
| difensore | < 30' | 155 | 2.2% | 1.3% | 2.6% |
| difensore | 30-60' | 1549 | 3.2% | 2.5% | 2.5% |
| difensore | 60'+ | 7049 | 5.0% | 4.3% | 4.0% |

### Assenze pesate

Produzione per 90 minuti (npxG + xA) per ruolo nei dati: difensore 0.107, centrocampista 0.239, attaccante 0.456.
1335 partite con quote; almeno un'assenza pesata nel 98%; fattore medio 0.994, minimo 0.850. Nessun parametro stimato: tutte le partite sono fuori campione per il fattore.

| Variante | Partite | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE | Esito |
|---|---|---|---|---|---|---|
| finale ancorato × fattore assenze | 1335 | 1.6465 | 1.6497 | +0.00322 ± 0.00366 | 0.0122 → 0.0153 | **spenta** |
| solo modello × fattore assenze (informativo) | 1335 | 1.6657 | 1.6678 | +0.00204 ± 0.00377 | 0.0101 → 0.0123 | *non migliora* |


## Incertezza dei parametri (fase P, punto 3)

Generato il 27/10/2026 con `python -m tools.model_v2 --incertezza`. In ogni simulazione la media (gol di ciascuna squadra; corner totali; gialli e rossi) è moltiplicata per exp(σZ − σ²/2): stessa media, più dispersione. σ scelto sul 2024-26 (griglia 0, 0.05, 0.1, 0.15, 0.2, 0.25), verifica fuori campione con la regola severa (gol: 1X2 + Over/Under 2.5; corner: Over 8.5-10.5; cartellini in punti: Over 3.5-5.5).

| Variante | Partite | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE | Esito |
|---|---|---|---|---|---|---|
| gol, σ scelto = 0 | 7152 | 1.6318 | 1.6318 | +0.00000 ± 0.00000 | 0.0127 → 0.0127 | **spenta** |
| gol, σ = 0.1 imposto (confronto) | 7152 | 1.6318 | 1.6320 | +0.00012 ± 0.00013 | 0.0127 → 0.0136 | **spenta** |
| corner, σ scelto = 0 | 7152 | 0.6681 | 0.6681 | +0.00000 ± 0.00000 | 0.0098 → 0.0098 | **spenta** |
| corner, σ = 0.1 imposto (confronto) | 7152 | 0.6681 | 0.6683 | +0.00022 ± 0.00021 | 0.0098 → 0.0115 | **spenta** |
| cartellini, σ scelto = 0 | 7152 | 0.6249 | 0.6249 | +0.00000 ± 0.00000 | 0.0237 → 0.0237 | **spenta** |
| cartellini, σ = 0.1 imposto (confronto) | 7152 | 0.6249 | 0.6252 | +0.00037 ± 0.00011 | 0.0237 → 0.0246 | **spenta** |

Log-loss sul 2024-26 per σ:

| Mercati | σ = 0 | σ = 0.05 | σ = 0.1 | σ = 0.15 | σ = 0.2 | σ = 0.25 |
|---|---|---|---|---|---|---|
| gol | 1.6397 | 1.6397 | 1.6399 | 1.6401 | 1.6405 | 1.6410 |
| corner | 0.6705 | 0.6705 | 0.6706 | 0.6709 | 0.6716 | 0.6727 |
| cartellini | 0.6331 | 0.6331 | 0.6332 | 0.6333 | 0.6336 | 0.6340 |

## Peso del mercato per campionato e tipo (fase P, punto 5)

Generato il 27/10/2026 con `python -m tools.model_v2 --peso-mercato`. Ancoraggio separato del totale gol (media geometrica di λ e μ) e della supremazia (λ/μ); peso per campionato stimato sul 2024-26 (griglia 0,50-1,00) e riavvicinato a 0.9 con 1000 partite fittizie. Corner e cartellini: nessuna quota storica, peso non stimabile (resta 0,8 dichiarato).

| Campionato | Partite 2024-26 | Totale: stima → usato | Supremazia: stima → usato |
|---|---|---|---|
| D1 | 597 | 1.0 → 0.937 | 1.0 → 0.937 |
| E0 | 750 | 0.75 → 0.836 | 1.0 → 0.943 |
| I1 | 750 | 0.6 → 0.771 | 1.0 → 0.943 |
| SP1 | 755 | 1.0 → 0.943 | 1.0 → 0.943 |

| Variante | Partite | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE | Esito |
|---|---|---|---|---|---|---|
| pesi per campionato e tipo | 7152 | 1.6318 | 1.6315 | -0.00030 ± 0.00040 | 0.0127 → 0.0131 | **spenta** |

## Contesto: giorni di riposo (fase P, punto 6)

Generato il 27/10/2026 con `python -m tools.model_v2 --contesto`. Riposo dalla partita di campionato precedente (2-7 giorni), effetto dopo l'ancoraggio al mercato: gol attesi casa × exp(a·(riposo casa − riposo ospite)/7 + b·(corto ospite − corto casa)). Stima sul 2024-26: a = -0.158, b = -0.001; partite con almeno una squadra a riposo corto: 15.4%. Le partite di coppa nei 4 giorni precedenti non sono nei dati storici (football-data.co.uk ha solo il campionato): non verificabili, escluse.

| Variante | Partite | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE | Esito |
|---|---|---|---|---|---|---|
| riposo | 7152 | 1.6318 | 1.6321 | +0.00022 ± 0.00078 | 0.0127 → 0.0133 | **spenta** |


## Ricalibrazione finale per mercato (fase P, punti 4 e 0b)

Generato il 27/10/2026 con `python -m tools.recalibration_check`. Mappa (Platt o isotonica, scelta in validazione incrociata tra 2024-25 e 2025-26) stimata sul 2024-26, verificata sul 2019-24 e 2026-27 per mercato con la regola severa e, poiché i mercati sono tanti, con la correzione di Holm per i confronti multipli. Accese: 1 su 45 (Over 3.5 cartellini).

| Mercato | Metodo | Partite | Log-loss prima | dopo | Differenza (± 2 e.s.) | ECE prima → dopo | Prevista prima / dopo / reale | Esito |
|---|---|---|---|---|---|---|---|---|
| 1 | isotonica | 7152 | 0.6011 | 0.6016 | +0.00050 ± 0.00125 | 0.0143 → 0.0081 | 43.4% / 42.4% / 43.5% | **spenta** |
| X | platt | 7152 | 0.5554 | 0.5552 | -0.00013 ± 0.00042 | 0.0028 → 0.0053 | 25.3% / 25.4% / 25.2% | **spenta** |
| 2 | platt | 7152 | 0.5398 | 0.5398 | +0.00002 ± 0.00092 | 0.0137 → 0.0162 | 31.3% / 32.5% / 31.3% | **spenta** |
| 1X | platt | 7152 | 0.5398 | 0.5398 | +0.00002 ± 0.00092 | 0.0137 → 0.0162 | 68.7% / 67.5% / 68.7% | **spenta** |
| X2 | isotonica | 7152 | 0.6011 | 0.6016 | +0.00052 ± 0.00125 | 0.0143 → 0.0098 | 56.6% / 57.6% / 56.5% | **spenta** |
| 12 | platt | 7152 | 0.5554 | 0.5552 | -0.00013 ± 0.00042 | 0.0028 → 0.0053 | 74.7% / 74.6% / 74.8% | **spenta** |
| Over 1.5 gol | platt | 7152 | 0.5133 | 0.5133 | +0.00000 ± 0.00024 | 0.0052 → 0.0045 | 78.2% / 77.8% / 78.0% | **spenta** |
| Over 2.5 gol | platt | 7152 | 0.6667 | 0.6668 | +0.00010 ± 0.00021 | 0.0158 → 0.0153 | 53.5% / 53.9% / 53.7% | **spenta** |
| Over 3.5 gol | platt | 7152 | 0.5989 | 0.5987 | -0.00013 ± 0.00076 | 0.0139 → 0.0111 | 31.8% / 30.8% / 31.6% | **spenta** |
| Goal | isotonica | 7152 | 0.6782 | 0.6776 | -0.00069 ± 0.00107 | 0.0129 → 0.0087 | 52.9% / 54.6% / 54.6% | **spenta** |
| Multigol 1-3 | isotonica | 7152 | 0.6509 | 0.6504 | -0.00044 ± 0.00146 | 0.0169 → 0.0052 | 60.5% / 62.7% / 62.1% | **spenta** |
| Multigol 2-4 | isotonica | 7152 | 0.6632 | 0.6639 | +0.00068 ± 0.00071 | 0.0042 → 0.0081 | 61.8% / 62.7% / 61.9% | **spenta** |
| Multigol 2-5 | platt | 7152 | 0.6011 | 0.6013 | +0.00022 ± 0.00055 | 0.0046 → 0.0117 | 70.7% / 71.7% / 70.8% | **spenta** |
| Multigol 1-2 | platt | 7152 | 0.6588 | 0.6586 | -0.00018 ± 0.00076 | 0.0129 → 0.0089 | 38.8% / 40.3% / 40.0% | **spenta** |
| 1 + Over 1.5 | isotonica | 7152 | 0.5708 | 0.5717 | +0.00086 ± 0.00153 | 0.0077 → 0.0148 | 35.8% / 33.8% / 34.7% | **spenta** |
| 1 + Over 2.5 | isotonica | 7152 | 0.5347 | 0.5356 | +0.00091 ± 0.00119 | 0.0060 → 0.0088 | 28.3% / 27.2% / 27.6% | **spenta** |
| 1 + Over 3.5 | platt | 7152 | 0.3787 | 0.3790 | +0.00030 ± 0.00140 | 0.0098 → 0.0108 | 15.9% / 14.2% / 14.9% | **spenta** |
| X + Over 1.5 | platt | 7152 | 0.4801 | 0.4797 | -0.00042 ± 0.00125 | 0.0130 → 0.0077 | 17.6% / 19.6% / 18.9% | **spenta** |
| X + Over 2.5 | platt | 7152 | 0.2468 | 0.2462 | -0.00065 ± 0.00171 | 0.0104 → 0.0073 | 5.7% / 7.4% / 6.8% | **spenta** |
| X + Over 3.5 | platt | 7152 | 0.2468 | 0.2462 | -0.00065 ± 0.00171 | 0.0104 → 0.0073 | 5.7% / 7.4% / 6.8% | **spenta** |
| 2 + Over 1.5 | platt | 7152 | 0.4869 | 0.4873 | +0.00035 ± 0.00047 | 0.0124 → 0.0137 | 24.8% / 25.0% / 24.4% | **spenta** |
| 2 + Over 2.5 | platt | 7152 | 0.4344 | 0.4355 | +0.00108 ± 0.00073 | 0.0102 → 0.0162 | 19.5% / 19.6% / 19.3% | **spenta** |
| 2 + Over 3.5 | platt | 7152 | 0.2833 | 0.2837 | +0.00038 ± 0.00090 | 0.0088 → 0.0091 | 10.2% / 9.2% / 10.0% | **spenta** |
| Goal + Over 2.5 | isotonica | 7152 | 0.6679 | 0.6677 | -0.00020 ± 0.00106 | 0.0017 → 0.0086 | 41.1% / 42.4% / 42.5% | **spenta** |
| Goal + Over 3.5 | platt | 7152 | 0.5647 | 0.5645 | -0.00024 ± 0.00039 | 0.0111 → 0.0091 | 26.5% / 26.5% / 26.8% | **spenta** |
| Esatti 1-0/2-0/2-1 | platt | 7152 | 0.5353 | 0.5338 | -0.00152 ± 0.00143 | 0.0214 → 0.0102 | 23.1% / 24.0% / 24.6% | **spenta (Holm)** |
| Esatti 0-1/0-2/1-2 | platt | 7152 | 0.4601 | 0.4607 | +0.00060 ± 0.00158 | 0.0156 → 0.0200 | 18.4% / 20.5% / 19.0% | **spenta** |
| Esatti 0-0/1-1 | platt | 7152 | 0.4671 | 0.4665 | -0.00070 ± 0.00119 | 0.0115 → 0.0046 | 19.5% / 18.0% / 18.4% | **spenta** |
| Esatti 1-1/2-2 | platt | 7152 | 0.4620 | 0.4616 | -0.00039 ± 0.00113 | 0.0122 → 0.0100 | 16.5% / 18.3% / 17.7% | **spenta** |
| Esatti 2-1/3-1/3-2 | isotonica | 7152 | 0.4156 | 0.4157 | +0.00019 ± 0.00105 | 0.0047 → 0.0099 | 14.7% / 15.7% / 15.2% | **spenta** |
| Esatti 1-0/0-1/0-0 | platt | 7152 | 0.5133 | 0.5133 | +0.00000 ± 0.00024 | 0.0052 → 0.0045 | 21.8% / 22.2% / 22.0% | **spenta** |
| Favorita 4+ gol | platt | 7152 | 0.3247 | 0.3258 | +0.00108 ± 0.00192 | 0.0081 → 0.0158 | 12.2% / 9.8% / 11.3% | **spenta** |
| Favorita vince di 3+ | platt | 7152 | 0.3835 | 0.3829 | -0.00058 ± 0.00185 | 0.0133 → 0.0138 | 15.9% / 13.3% / 14.3% | **spenta** |
| Totale 5+ gol | platt | 7152 | 0.4220 | 0.4226 | +0.00055 ± 0.00110 | 0.0072 → 0.0122 | 16.4% / 14.8% / 16.0% | **spenta** |
| 1 1T | isotonica | 7152 | 0.6006 | 0.6008 | +0.00011 ± 0.00122 | 0.0074 → 0.0064 | 34.9% / 34.2% / 33.7% | **spenta** |
| X 1T | isotonica | 7152 | 0.6677 | 0.6687 | +0.00100 ± 0.00108 | 0.0034 → 0.0153 | 39.8% / 39.5% / 40.3% | **spenta** |
| 2 1T | isotonica | 7152 | 0.5362 | 0.5367 | +0.00053 ± 0.00108 | 0.0092 → 0.0108 | 25.3% / 26.1% / 26.0% | **spenta** |
| Over 0.5 gol 1T | platt | 7152 | 0.5871 | 0.5871 | -0.00004 ± 0.00060 | 0.0077 → 0.0063 | 70.9% / 72.0% / 71.6% | **spenta** |
| Over 1.5 gol 1T | platt | 7152 | 0.6438 | 0.6445 | +0.00072 ± 0.00056 | 0.0100 → 0.0185 | 35.8% / 34.7% / 36.5% | **spenta** |
| Over 8.5 corner | platt | 7152 | 0.6544 | 0.6543 | -0.00005 ± 0.00006 | 0.0127 → 0.0119 | 61.5% / 61.5% / 62.4% | **spenta** |
| Over 9.5 corner | platt | 7152 | 0.6872 | 0.6870 | -0.00023 ± 0.00063 | 0.0092 → 0.0035 | 49.7% / 51.0% / 50.7% | **spenta** |
| Over 10.5 corner | platt | 7152 | 0.6627 | 0.6627 | -0.00001 ± 0.00057 | 0.0075 → 0.0038 | 38.4% / 39.5% / 39.1% | **spenta** |
| Over 3.5 cartellini | platt | 7152 | 0.6263 | 0.6236 | -0.00274 ± 0.00097 | 0.0292 → 0.0143 | 61.7% / 62.9% / 63.0% | **accesa** |
| Over 4.5 cartellini | platt | 7152 | 0.6570 | 0.6583 | +0.00132 ± 0.00055 | 0.0202 → 0.0166 | 45.7% / 44.7% / 46.4% | **spenta** |
| Over 5.5 cartellini | platt | 7152 | 0.5913 | 0.5912 | -0.00010 ± 0.00077 | 0.0216 → 0.0212 | 31.6% / 30.2% / 31.6% | **spenta** |

Goleade nel quinto di partite più squilibrate (|λ − μ|), fuori campione (0b):

| Mercato | Partite | Prevista prima | Prevista dopo | Reale |
|---|---|---|---|---|
| Favorita 4+ gol | 1431 | 25.7% | 21.5% | 23.1% |
| Favorita vince di 3+ | 1431 | 32.9% | 27.5% | 28.7% |
| Totale 5+ gol | 1431 | 24.4% | 22.3% | 23.7% |


## Soglia di valore per mercato (fase P, punto 7)

Generato il 27/10/2026 con `python -m tools.value_thresholds`. Soglia = errore relativo tipico della probabilità finale fuori campione (2019-24 e 2026-27), in punti di EV.

| Mercato | Soglia attuale (oggi.json) | Errore tipico stimato |
|---|---|---|
| 1X2 | 3.0 | 6 |
| Doppia chance | 2.0 | 3.2 |
| DNB | 2.0 | 5.3 |
| Gol | 3.0 | 3.4 |
| Primo tempo | 4.0 | 4.3 |
| Corner | 5.0 | 3.1 |
| Cartellini | 5.0 | 7.6 |
| Combo | 4.0 | 4.8 |
| Risultati esatti | 8.0 | 9.8 |

Verifica sulle quote di chiusura (1 e 2, Over/Under 2.5; il pareggio resta escluso come sempre):

| Soglie | Giocate | Rendimento medio (± e.s.) |
|---|---|---|
| attuali | 7 | +28.86% ± 84.81% |
| stimate | 3 | +25.00% ± 125.00% |

Esito: **restano le soglie attuali** (meno di 100 giocate: le probabilità finali sono ancorate alle stesse quote di chiusura, quindi l'EV sulla chiusura supera di rado la soglia e il rendimento non è misurabile; le soglie stimate restano disponibili in configurazione).


## fase P: motore v2 (ricalibrazione Over 3.5 cartellini, marcatori v2)

Generato il 27/10/2026 con `python -m tools.baseline`. Campionati: Serie A, Premier League, Liga, Bundesliga (football-data.co.uk).

### taratura 2024-25/2025-26 (2852 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 0.9858 | 0.9698 | 0.5879 | 0.5769 | 0.0091 | 0.0097 |
| Over 2.5 | 0.6806 | 0.6701 | 0.4877 | 0.4775 | 0.0016 | 0.0140 |
| GG | 0.6855 | — | 0.4924 | — | 0.0039 | — |

- Favorite nette (mercato ≥ 70%, 314 partite): probabilità media mercato 76.4%, modello 74.5%.
- Segnali VALORE 1X2 alle quote di chiusura: 1.06 per partita (1: 858, X: 962, 2: 1205); rendimento medio puntando 1 su ciascuno: -10.0%.
- Errore medio assoluto sulla media corner: 2.70; cartellini gialli: 1.66.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 281 | 0.071 | 0.082 |
| 10%-20% | 1118 | 0.157 | 0.140 |
| 20%-30% | 3400 | 0.260 | 0.259 |
| 30%-40% | 1451 | 0.343 | 0.340 |
| 40%-50% | 944 | 0.449 | 0.480 |
| 50%-60% | 649 | 0.546 | 0.542 |
| 60%-70% | 411 | 0.645 | 0.618 |
| 70%-80% | 216 | 0.742 | 0.764 |
| 80%-90% | 79 | 0.834 | 0.861 |
| 90%-100% | 7 | 0.918 | 0.714 |

### fuori campione 2026-27 (254 partite)

| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |
|---|---|---|---|---|---|---|
| 1X2 | 0.9433 | 0.9373 | 0.5573 | 0.5543 | 0.0483 | 0.0282 |
| Over 2.5 | 0.6577 | 0.6394 | 0.4655 | 0.4486 | 0.0281 | 0.0668 |
| GG | 0.6785 | — | 0.4856 | — | 0.0195 | — |

- Favorite nette (mercato ≥ 70%, 31 partite): probabilità media mercato 78.1%, modello 73.6%.
- Segnali VALORE 1X2 alle quote di chiusura: 1.13 per partita (1: 86, X: 108, 2: 94); rendimento medio puntando 1 su ciascuno: -9.3%.
- Errore medio assoluto sulla media corner: 2.90; cartellini gialli: 1.61.

Calibrazione 1X2 del modello (tutte le classi):

| Fascia | n | Prevista | Osservata |
|---|---|---|---|
| 0%-10% | 23 | 0.073 | 0.000 |
| 10%-20% | 93 | 0.160 | 0.097 |
| 20%-30% | 315 | 0.260 | 0.276 |
| 30%-40% | 118 | 0.342 | 0.314 |
| 40%-50% | 100 | 0.445 | 0.370 |
| 50%-60% | 54 | 0.550 | 0.630 |
| 60%-70% | 34 | 0.639 | 0.794 |
| 70%-80% | 18 | 0.740 | 0.944 |
| 80%-90% | 7 | 0.849 | 0.857 |

## Calibrazione per mercato (fase AM)

Generato il 30/10/2026 con `python -m tools.taratura_check`. Walk-forward: ogni stagione è corretta solo con le precedenti. Scarto = ECE (media pesata |dichiarato − uscito|).

| Gruppo | Mercato | Casi | Scarto prima | Scarto dopo | Log-loss prima → dopo | Stato |
|---|---|---|---|---|---|---|
| 1X2 | 1X | — | — | — | — | derivato dalla base |
| 1X2 | X2 | — | — | — | — | derivato dalla base |
| 1X2 | 12 | — | — | — | — | derivato dalla base |
| over/under gol | Over 1.5 gol | 8753 | 0.0057 | 0.0065 | 0.51972 → 0.52073 | non tarato |
| over/under gol | Over 2.5 gol | 8753 | 0.0105 | 0.0007 | 0.66854 → 0.66930 | non tarato |
| over/under gol | Over 3.5 gol | 8753 | 0.0154 | 0.0097 | 0.59603 → 0.59625 | non tarato |
| GG/NG | Goal | 8753 | 0.0092 | 0.0051 | 0.67878 → 0.67801 | tarato (isotonica, nuova) |
| multigol | Multigol 1-3 | 8753 | 0.0173 | 0.0020 | 0.64930 → 0.64862 | tarato (isotonica, nuova) |
| multigol | Multigol 2-4 | 8753 | 0.0013 | 0.0108 | 0.66474 → 0.66541 | non tarato |
| multigol | Multigol 2-5 | 8753 | 0.0015 | 0.0072 | 0.60352 → 0.60445 | non tarato |
| multigol | Multigol 1-2 | 8753 | 0.0125 | 0.0084 | 0.66208 → 0.66219 | non tarato |
| combo e gruppi | 1 + Over 1.5 | 8753 | 0.0127 | 0.0103 | 0.56413 → 0.56458 | non tarato |
| combo e gruppi | 1 + Over 2.5 | 8753 | 0.0089 | 0.0049 | 0.52944 → 0.53002 | non tarato |
| combo e gruppi | 1 + Over 3.5 | 8753 | 0.0092 | 0.0060 | 0.37593 → 0.37622 | non tarato |
| combo e gruppi | X + Over 1.5 | 8753 | 0.0163 | 0.0071 | 0.48571 → 0.48538 | tarato (isotonica, nuova) |
| combo e gruppi | X + Over 2.5 | 8753 | 0.0124 | 0.0048 | 0.25171 → 0.25068 | tarato (isotonica, nuova) |
| combo e gruppi | X + Over 3.5 | — | — | — | — | derivato dalla base |
| combo e gruppi | 2 + Over 1.5 | 8753 | 0.0115 | 0.0061 | 0.48772 → 0.48857 | non tarato |
| combo e gruppi | 2 + Over 2.5 | 8753 | 0.0078 | 0.0023 | 0.43668 → 0.43788 | non tarato |
| combo e gruppi | 2 + Over 3.5 | 8753 | 0.0058 | 0.0030 | 0.27839 → 0.27931 | non tarato |
| combo e gruppi | Goal + Over 2.5 | 8753 | 0.0060 | 0.0042 | 0.66885 → 0.66851 | tarato (isotonica, nuova) |
| combo e gruppi | Goal + Over 3.5 | 8753 | 0.0105 | 0.0112 | 0.56454 → 0.56456 | non tarato |
| combo e gruppi | Esatti 1-0/2-0/2-1 | 8753 | 0.0201 | 0.0129 | 0.53126 → 0.53029 | tarato (isotonica, nuova) |
| combo e gruppi | Esatti 0-1/0-2/1-2 | 8753 | 0.0149 | 0.0094 | 0.46386 → 0.46323 | tarato (isotonica, nuova) |
| combo e gruppi | Esatti 0-0/1-1 | 8753 | 0.0115 | 0.0025 | 0.46987 → 0.46973 | tarato (isotonica, nuova) |
| combo e gruppi | Esatti 1-1/2-2 | 8753 | 0.0154 | 0.0072 | 0.46720 → 0.46704 | tarato (isotonica, nuova) |
| combo e gruppi | Esatti 2-1/3-1/3-2 | 8753 | 0.0073 | 0.0036 | 0.41824 → 0.41840 | non tarato |
| combo e gruppi | Esatti 1-0/0-1/0-0 | — | — | — | — | derivato dalla base |
| combo e gruppi | Favorita 4+ gol | 8753 | 0.0115 | 0.0021 | 0.31448 → 0.31422 | tarato (isotonica, nuova) |
| combo e gruppi | Favorita vince di 3+ | 8753 | 0.0167 | 0.0044 | 0.37453 → 0.37339 | tarato (isotonica, nuova) |
| combo e gruppi | Totale 5+ gol | — | — | — | — | derivato dalla base |
| primo tempo | Over 0.5 gol 1T | 8753 | 0.0093 | 0.0052 | 0.58725 → 0.58743 | non tarato |
| primo tempo | Over 1.5 gol 1T | 8753 | 0.0065 | 0.0055 | 0.63862 → 0.63931 | non tarato |
| corner | Over 8.5 corner | 8753 | 0.0088 | 0.0103 | 0.65978 → 0.66039 | non tarato |
| corner | Over 9.5 corner | 8753 | 0.0082 | 0.0059 | 0.68813 → 0.68845 | non tarato |
| corner | Over 10.5 corner | 8753 | 0.0075 | 0.0053 | 0.66017 → 0.66047 | non tarato |
| cartellini | Over 3.5 cartellini | 8753 | 0.0265 | 0.0119 | 0.64113 → 0.63924 | tarato (platt, precedente (fase P)) |
| cartellini | Over 4.5 cartellini | 8753 | 0.0148 | 0.0099 | 0.66192 → 0.66182 | tarato (isotonica, nuova) |
| cartellini | Over 5.5 cartellini | 8753 | 0.0133 | 0.0096 | 0.58343 → 0.58410 | non tarato |
| over/under gol | Over 4.5 gol | 8753 | 0.0087 | 0.0067 | 0.41706 → 0.41756 | non tarato |
| secondo tempo | Over 0.5 gol 2T | 8753 | 0.0145 | 0.0028 | 0.49001 → 0.48988 | tarato (isotonica, nuova) |
| secondo tempo | Over 1.5 gol 2T | 8753 | 0.0149 | 0.0115 | 0.67948 → 0.67983 | non tarato |
| per squadra | Casa Over 0.5 gol | 8753 | 0.0170 | 0.0072 | 0.49562 → 0.49548 | tarato (isotonica, nuova) |
| per squadra | Casa Over 1.5 gol | 8753 | 0.0046 | 0.0036 | 0.62854 → 0.62912 | non tarato |
| per squadra | Ospite Over 0.5 gol | 8753 | 0.0162 | 0.0101 | 0.56645 → 0.56536 | tarato (isotonica, nuova) |
| per squadra | Ospite Over 1.5 gol | 8753 | 0.0096 | 0.0045 | 0.60612 → 0.60575 | tarato (isotonica, nuova) |
| 1X2 | 1 | 8753 | 0.0151 | 0.0074 | 0.96634 → 0.96705 | non tarato |
| 1X2 | X | 8753 | 0.0025 | 0.0053 | 0.96634 → 0.96705 | non tarato |
| 1X2 | 2 | 8753 | 0.0120 | 0.0110 | 0.96634 → 0.96705 | non tarato |
| primo tempo | 1 1T | 8753 | 0.0076 | 0.0058 | 1.02584 → 1.02640 | non tarato |
| primo tempo | X 1T | 8753 | 0.0047 | 0.0041 | 1.02584 → 1.02640 | non tarato |
| primo tempo | 2 1T | 8753 | 0.0079 | 0.0061 | 1.02584 → 1.02640 | non tarato |
| secondo tempo | 1 secondo tempo | 8753 | 0.0132 | 0.0099 | 1.03845 → 1.03896 | non tarato |
| secondo tempo | X secondo tempo | 8753 | 0.0047 | 0.0015 | 1.03845 → 1.03896 | non tarato |
| secondo tempo | 2 secondo tempo | 8753 | 0.0059 | 0.0072 | 1.03845 → 1.03896 | non tarato |

### Dichiarato contro uscito (grezzo, fasce 50+)

| Mercato | Fascia | Dichiarato | Uscito | Casi |
|---|---|---|---|---|
| Over 1.5 gol | 50-55 | 53.6% | 66.7% | 6 |
| Over 1.5 gol | 55-60 | 58.1% | 59.7% | 57 |
| Over 1.5 gol | 60-70 | 66.8% | 66.5% | 1118 |
| Over 1.5 gol | 70-80 | 75.4% | 74.4% | 4034 |
| Over 1.5 gol | oltre 80 | 84.6% | 84.6% | 3538 |
| Over 2.5 gol | 50-55 | 52.5% | 52.8% | 1664 |
| Over 2.5 gol | 55-60 | 57.4% | 58.8% | 1519 |
| Over 2.5 gol | 60-70 | 64.0% | 65.6% | 1667 |
| Over 2.5 gol | 70-80 | 73.4% | 70.3% | 441 |
| Over 2.5 gol | oltre 80 | 82.6% | 81.6% | 38 |
| Over 3.5 gol | 50-55 | 52.1% | 48.7% | 226 |
| Over 3.5 gol | 55-60 | 57.3% | 57.3% | 82 |
| Over 3.5 gol | 60-70 | 63.0% | 65.5% | 55 |
| Over 3.5 gol | 70-80 | 73.3% | 100.0% | 3 |
| Goal | 50-55 | 52.5% | 54.0% | 2375 |
| Goal | 55-60 | 57.3% | 59.2% | 1948 |
| Goal | 60-70 | 63.2% | 67.1% | 1300 |
| Goal | 70-80 | 71.5% | 67.4% | 43 |
| Multigol 1-3 | 50-55 | 52.8% | 54.2% | 895 |
| Multigol 1-3 | 55-60 | 57.7% | 57.7% | 1848 |
| Multigol 1-3 | 60-70 | 64.9% | 67.5% | 5101 |
| Multigol 1-3 | 70-80 | 70.5% | 73.2% | 216 |
| Multigol 2-4 | 50-55 | 53.2% | 56.4% | 140 |
| Multigol 2-4 | 55-60 | 58.4% | 58.1% | 1127 |
| Multigol 2-4 | 60-70 | 62.5% | 62.4% | 7467 |
| Multigol 2-5 | 50-55 | 53.6% | 66.7% | 12 |
| Multigol 2-5 | 55-60 | 58.3% | 56.2% | 112 |
| Multigol 2-5 | 60-70 | 66.9% | 67.0% | 2815 |
| Multigol 2-5 | 70-80 | 72.6% | 72.5% | 5814 |
| Multigol 1-2 | 50-55 | 51.5% | 53.5% | 389 |
| Multigol 1-2 | 55-60 | 55.4% | 83.3% | 6 |
| 1 + Over 1.5 | 50-55 | 52.5% | 51.6% | 471 |
| 1 + Over 1.5 | 55-60 | 57.5% | 58.3% | 417 |
| 1 + Over 1.5 | 60-70 | 64.6% | 60.6% | 604 |
| 1 + Over 1.5 | 70-80 | 74.3% | 76.1% | 322 |
| 1 + Over 1.5 | oltre 80 | 83.4% | 81.0% | 105 |
| 1 + Over 2.5 | 50-55 | 52.4% | 54.1% | 318 |
| 1 + Over 2.5 | 55-60 | 57.4% | 59.7% | 238 |
| 1 + Over 2.5 | 60-70 | 64.4% | 60.7% | 247 |
| 1 + Over 2.5 | 70-80 | 73.4% | 70.1% | 77 |
| 1 + Over 2.5 | oltre 80 | 82.4% | 100.0% | 6 |
| 1 + Over 3.5 | 50-55 | 52.2% | 55.6% | 54 |
| 1 + Over 3.5 | 55-60 | 57.2% | 46.9% | 32 |
| 1 + Over 3.5 | 60-70 | 62.4% | 78.6% | 14 |
| 1 + Over 3.5 | 70-80 | 71.3% | 100.0% | 2 |
| 2 + Over 1.5 | 50-55 | 52.2% | 53.6% | 252 |
| 2 + Over 1.5 | 55-60 | 57.2% | 57.4% | 190 |
| 2 + Over 1.5 | 60-70 | 64.1% | 60.8% | 204 |
| 2 + Over 1.5 | 70-80 | 73.8% | 67.1% | 70 |
| 2 + Over 1.5 | oltre 80 | 81.4% | 83.3% | 6 |
| 2 + Over 2.5 | 50-55 | 52.2% | 43.8% | 112 |
| 2 + Over 2.5 | 55-60 | 57.4% | 53.7% | 67 |
| 2 + Over 2.5 | 60-70 | 64.0% | 56.4% | 55 |
| 2 + Over 2.5 | 70-80 | 72.9% | 60.0% | 5 |
| 2 + Over 3.5 | 50-55 | 51.6% | 54.5% | 11 |
| 2 + Over 3.5 | 55-60 | 56.2% | 100.0% | 2 |
| 2 + Over 3.5 | 60-70 | 61.1% | 0.0% | 1 |
| Goal + Over 2.5 | 50-55 | 52.2% | 57.1% | 704 |
| Goal + Over 2.5 | 55-60 | 57.0% | 59.0% | 249 |
| Goal + Over 2.5 | 60-70 | 62.0% | 63.6% | 66 |
| Goal + Over 3.5 | 50-55 | 51.5% | 63.6% | 11 |
| Goal + Over 3.5 | 55-60 | 56.3% | 100.0% | 1 |
| Favorita 4+ gol | 50-55 | 51.6% | 22.2% | 9 |
| Favorita 4+ gol | 55-60 | 55.4% | 66.7% | 3 |
| Favorita 4+ gol | 60-70 | 62.2% | 100.0% | 3 |
| Favorita vince di 3+ | 50-55 | 52.1% | 49.2% | 63 |
| Favorita vince di 3+ | 55-60 | 57.1% | 39.1% | 23 |
| Favorita vince di 3+ | 60-70 | 63.4% | 33.3% | 9 |
| Favorita vince di 3+ | 70-80 | 71.8% | 100.0% | 1 |
| Over 0.5 gol 1T | 50-55 | 53.4% | 50.0% | 56 |
| Over 0.5 gol 1T | 55-60 | 58.2% | 59.5% | 407 |
| Over 0.5 gol 1T | 60-70 | 65.9% | 66.7% | 3625 |
| Over 0.5 gol 1T | 70-80 | 74.2% | 75.5% | 3942 |
| Over 0.5 gol 1T | oltre 80 | 83.0% | 83.2% | 721 |
| Over 1.5 gol 1T | 50-55 | 52.2% | 48.8% | 340 |
| Over 1.5 gol 1T | 55-60 | 57.1% | 59.4% | 123 |
| Over 1.5 gol 1T | 60-70 | 63.4% | 63.1% | 65 |
| Over 1.5 gol 1T | 70-80 | 73.7% | 100.0% | 3 |
| Over 8.5 corner | 50-55 | 53.0% | 54.1% | 1052 |
| Over 8.5 corner | 55-60 | 57.8% | 58.9% | 2437 |
| Over 8.5 corner | 60-70 | 64.0% | 64.7% | 4689 |
| Over 8.5 corner | 70-80 | 71.9% | 71.5% | 330 |
| Over 8.5 corner | oltre 80 | 80.1% | 100.0% | 1 |
| Over 9.5 corner | 50-55 | 52.3% | 53.2% | 2528 |
| Over 9.5 corner | 55-60 | 57.0% | 56.7% | 1064 |
| Over 9.5 corner | 60-70 | 62.2% | 58.2% | 206 |
| Over 9.5 corner | 70-80 | 71.0% | 0.0% | 1 |
| Over 10.5 corner | 50-55 | 51.6% | 50.9% | 108 |
| Over 10.5 corner | 55-60 | 56.1% | 81.2% | 16 |
| Over 10.5 corner | 60-70 | 60.7% | 0.0% | 1 |
| Over 3.5 cartellini | 50-55 | 52.7% | 50.9% | 1205 |
| Over 3.5 cartellini | 55-60 | 57.7% | 59.7% | 1791 |
| Over 3.5 cartellini | 60-70 | 64.8% | 67.5% | 3631 |
| Over 3.5 cartellini | 70-80 | 72.9% | 77.6% | 1054 |
| Over 3.5 cartellini | oltre 80 | 81.5% | 60.0% | 5 |
| Over 4.5 cartellini | 50-55 | 52.3% | 53.5% | 1345 |
| Over 4.5 cartellini | 55-60 | 57.1% | 57.1% | 720 |
| Over 4.5 cartellini | 60-70 | 62.3% | 73.9% | 264 |
| Over 4.5 cartellini | 70-80 | 71.1% | 0.0% | 1 |
| Over 5.5 cartellini | 50-55 | 51.3% | 54.0% | 37 |
| Over 5.5 cartellini | 55-60 | 56.0% | 75.0% | 4 |
| Over 4.5 gol | 50-55 | 51.7% | 66.7% | 3 |
| Over 4.5 gol | 55-60 | 56.0% | 100.0% | 2 |
| Over 0.5 gol 2T | 60-70 | 68.4% | 70.3% | 145 |
| Over 0.5 gol 2T | 70-80 | 76.5% | 77.2% | 5059 |
| Over 0.5 gol 2T | oltre 80 | 82.7% | 85.1% | 3549 |
| Over 1.5 gol 2T | 50-55 | 52.2% | 55.7% | 1699 |
| Over 1.5 gol 2T | 55-60 | 57.1% | 58.2% | 649 |
| Over 1.5 gol 2T | 60-70 | 62.3% | 68.0% | 156 |
| Casa Over 0.5 gol | 50-55 | 52.8% | 53.9% | 191 |
| Casa Over 0.5 gol | 55-60 | 57.8% | 56.0% | 389 |
| Casa Over 0.5 gol | 60-70 | 65.7% | 65.1% | 1718 |
| Casa Over 0.5 gol | 70-80 | 75.1% | 77.5% | 3066 |
| Casa Over 0.5 gol | oltre 80 | 86.7% | 88.6% | 3306 |
| Casa Over 1.5 gol | 50-55 | 52.4% | 52.9% | 763 |
| Casa Over 1.5 gol | 55-60 | 57.4% | 59.1% | 608 |
| Casa Over 1.5 gol | 60-70 | 64.6% | 64.1% | 953 |
| Casa Over 1.5 gol | 70-80 | 74.4% | 73.7% | 566 |
| Casa Over 1.5 gol | oltre 80 | 84.1% | 82.0% | 222 |
| Ospite Over 0.5 gol | 50-55 | 52.7% | 54.8% | 590 |
| Ospite Over 0.5 gol | 55-60 | 57.6% | 58.8% | 935 |
| Ospite Over 0.5 gol | 60-70 | 65.2% | 66.3% | 2644 |
| Ospite Over 0.5 gol | 70-80 | 74.8% | 78.0% | 2390 |
| Ospite Over 0.5 gol | oltre 80 | 85.3% | 87.5% | 1672 |
| Ospite Over 1.5 gol | 50-55 | 52.3% | 51.3% | 460 |
| Ospite Over 1.5 gol | 55-60 | 57.4% | 59.4% | 389 |
| Ospite Over 1.5 gol | 60-70 | 64.5% | 68.4% | 449 |
| Ospite Over 1.5 gol | 70-80 | 74.2% | 68.9% | 167 |
| Ospite Over 1.5 gol | oltre 80 | 82.8% | 77.4% | 31 |
| 1 | 50-55 | 52.5% | 54.1% | 674 |
| 1 | 55-60 | 57.4% | 58.3% | 638 |
| 1 | 60-70 | 64.9% | 68.8% | 907 |
| 1 | 70-80 | 74.6% | 74.9% | 605 |
| 1 | oltre 80 | 84.2% | 83.8% | 259 |
| 2 | 50-55 | 52.4% | 53.2% | 374 |
| 2 | 55-60 | 57.4% | 60.0% | 350 |
| 2 | 60-70 | 64.5% | 67.2% | 408 |
| 2 | 70-80 | 74.1% | 78.6% | 168 |
| 2 | oltre 80 | 82.3% | 75.0% | 32 |
| 1 1T | 50-55 | 52.3% | 53.8% | 493 |
| 1 1T | 55-60 | 57.3% | 53.6% | 330 |
| 1 1T | 60-70 | 63.9% | 62.1% | 338 |
| 1 1T | 70-80 | 72.7% | 65.5% | 87 |
| 1 1T | oltre 80 | 82.2% | 100.0% | 3 |
| X 1T | 50-55 | 51.6% | 54.8% | 208 |
| X 1T | 55-60 | 55.8% | 80.0% | 5 |
| 2 1T | 50-55 | 52.2% | 49.0% | 151 |
| 2 1T | 55-60 | 57.1% | 62.0% | 79 |
| 2 1T | 60-70 | 63.1% | 60.8% | 51 |
| 2 1T | 70-80 | 71.8% | 100.0% | 1 |
| 1 secondo tempo | 50-55 | 52.4% | 54.6% | 590 |
| 1 secondo tempo | 55-60 | 57.4% | 59.5% | 464 |
| 1 secondo tempo | 60-70 | 64.1% | 62.0% | 490 |
| 1 secondo tempo | 70-80 | 72.5% | 70.1% | 107 |
| 1 secondo tempo | oltre 80 | 80.1% | 50.0% | 2 |
| 2 secondo tempo | 50-55 | 52.4% | 50.2% | 307 |
| 2 secondo tempo | 55-60 | 57.2% | 58.2% | 189 |
| 2 secondo tempo | 60-70 | 63.8% | 59.7% | 149 |
| 2 secondo tempo | 70-80 | 71.8% | 75.0% | 8 |

