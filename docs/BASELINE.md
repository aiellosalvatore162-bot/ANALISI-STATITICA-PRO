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

