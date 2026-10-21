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

