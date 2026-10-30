# Fase AK, stadio 2: stima del motore a eventi (2026-10-30)

Data: StatsBomb Open Data 2015/16; arbitri da football-data.co.uk. Partite: Premier League 380, La Liga 380, Serie A 380, Bundesliga 34, Ligue 1 377. Bundesliga solo nelle stime comuni.

## Tiri per tipo (comune)

| tipo | tiri/squadra-partita | quota | xG medio | gol/tiro | parati o respinti | n |
|---|---|---|---|---|---|---|
| rigore | 0.13 | 1.1% | 0.784 | 0.751 | 18.8% | 410 |
| palla_inattiva | 2.58 | 20.7% | 0.078 | 0.080 | 44.8% | 8001 |
| transizione | 0.56 | 4.5% | 0.142 | 0.155 | 51.4% | 1750 |
| fuori_area | 3.92 | 31.4% | 0.033 | 0.030 | 53.8% | 12171 |
| testa_da_cross | 0.75 | 6.0% | 0.113 | 0.117 | 29.2% | 2339 |
| azione | 4.53 | 36.3% | 0.140 | 0.149 | 50.8% | 14057 |

## Corner e falli (comune)

Corner per squadra-partita: tiro 1.53, cross 1.00, altro 2.57; corner per tiro parato o respinto 0.25; falli per squadra-partita 15.0; gialli per fallo 0.151.

## Stato di partita (moltiplicatore rispetto al pareggio, ± 2 e.s.)

| quantità | −2 | −1 | +1 | +2 |
|---|---|---|---|---|
| tiri | 1.35 ± 0.08 | 1.19 ± 0.05 | 0.67 ± 0.03 | 0.50 ± 0.03 |
| xg | 1.59 ± 0.19 | 1.30 ± 0.09 | 0.65 ± 0.05 | 0.41 ± 0.04 |
| corner | 1.21 ± 0.12 | 1.24 ± 0.08 | 0.65 ± 0.04 | 0.54 ± 0.05 |
| corner_gioco | 1.22 ± 0.14 | 1.29 ± 0.09 | 0.67 ± 0.05 | 0.54 ± 0.06 |
| falli | 0.85 ± 0.04 | 0.90 ± 0.03 | 1.07 ± 0.03 | 1.05 ± 0.05 |
| gialli | 0.72 ± 0.10 | 0.95 ± 0.10 | 1.25 ± 0.11 | 1.01 ± 0.15 |

## Espulsioni (moltiplicatore rispetto alla parità numerica, ± 2 e.s.)

Minuti con un uomo in meno o in più: 5273 su 146136. Rossi diretti per fallo 0.0043 (200), seconda gialla per giallo preso da una squadra già ammonita 0.0518 (220).

| quantità | uomo in meno | uomo in più |
|---|---|---|
| tiri | 0.58 ± 0.06 | 1.43 ± 0.10 |
| xg | 0.56 ± 0.11 | 1.42 ± 0.18 |
| corner | 0.53 ± 0.08 | 1.31 ± 0.14 |
| corner_gioco | 0.54 ± 0.09 | 1.33 ± 0.17 |
| falli | 0.78 ± 0.05 | 1.01 ± 0.05 |
| gialli | 0.87 ± 0.10 | 1.00 ± 0.12 |

## Attenuazione degli effetti di stato (stadio 12)

Esponente 0.496 (IC 95% 0.373-0.62): pendenza tiri sbagliati ~ gol osservata -0.602 ± 0.137 su 1517 partite; motore con esponente 1: -1.076. lo stesso esponente si applica a tiri, xG, corner di gioco, falli e gialli (ipotesi dichiarata: la stessa distorsione delle stime dentro la partita); effetti dell'uomo in meno/in più e fasce di minuti invariati.

## Dizionario tattico

| termine → tasso | beta | IC 95% | n | nel dizionario |
|---|---|---|---|---|
| possesso → quota_possesso | +0.115 | [+0.103, +0.128] | 2994 | sì |
| possesso → tiri_transizione | -0.019 | [-0.099, +0.061] | 2994 | 0 (non distinguibile da zero) |
| possesso → tiri_fuori_area | +0.085 | [+0.054, +0.115] | 2994 | sì |
| verticalizzazione → tiri_transizione | -0.006 | [-0.080, +0.068] | 2994 | 0 (non distinguibile da zero) |
| verticalizzazione → azioni_pericolose | -0.028 | [-0.046, -0.011] | 2994 | sì, segno opposto all'atteso |
| altezza_linea → tiri_transizione_concessi | -0.035 | [-0.121, +0.050] | 2994 | 0 (non distinguibile da zero) |
| altezza_linea → corner_concessi | -0.014 | [-0.043, +0.014] | 2994 | 0 (non distinguibile da zero) |
| altezza_linea → recuperi_alti | — | — | — | null: recuperi del pallone con la posizione non salvati nel riassunto StatsBomb |
| pressing → recuperi_alti | — | — | — | null: recuperi del pallone con la posizione non salvati nel riassunto StatsBomb |
| pressing → falli_fatti | +0.034 | [+0.018, +0.049] | 2994 | sì |
| marcatura → falli_fatti | — | — | — | null: uomo/zona non si ricava dagli eventi aperti |
| transizione → tiri_transizione | -0.006 | [-0.095, +0.083] | 2994 | 0 (non distinguibile da zero) |
| fasce_cross → cross | +0.137 | [+0.117, +0.156] | 2994 | sì |
| fasce_cross → tiri_da_cross | +0.131 | [+0.093, +0.170] | 2994 | sì |
| fasce_cross → corner_fasce | +0.168 | [+0.117, +0.219] | 2994 | sì |
| gestione_blocco_basso → tiri_contro_blocco_basso | +0.003 | [-0.040, +0.045] | 1002 | 0 (non distinguibile da zero) |
| adattabilita → attenuazione_incroci | — | — | — | null: l'adattabilità non ha un indicatore nei dati: restano i valori fissi della fase Q |
| reazione_svantaggio → spinta_in_svantaggio | — | — | — | null: nessun indicatore per squadra; effetto medio nello stato di partita (sezione stato_partita) |
| reazione_vantaggio → spinta_in_vantaggio | — | — | — | null: nessun indicatore per squadra; effetto medio nello stato di partita (sezione stato_partita) |

## Incroci (solo stima, spenti)

| incrocio | beta | IC 95% | n |
|---|---|---|---|
| verticali_contro_linea_alta | -0.049 | [-0.131, +0.032] | 2994 |
| possesso_contro_pressing | +0.018 | [+0.001, +0.034] | 2994 |
| cross_contro_blocco_basso | -0.028 | [-0.089, +0.032] | 2994 |

## Arbitri

| fonte | campionato | quantità | arbitri | partite | quota varianza | k | fuori campione |
|---|---|---|---|---|---|---|---|
| football_data | Premier League | falli | 33 | 2644 | 4.6% | 20.8 | +2.4% MSE |
| football_data | Premier League | gialli | 33 | 2644 | 1.2% | 80.7 | +0.1% MSE |
| football_data | Scozia | falli | 29 | 1539 | 5.1% | 18.8 | +1.5% MSE |
| football_data | Scozia | gialli | 29 | 1539 | 2.2% | 44.0 | +0.7% MSE |
| statsbomb_2015_16 | La Liga | falli | 20 | 361 | 8.4% | 10.9 | — |
| statsbomb_2015_16 | La Liga | gialli | 20 | 361 | 5.2% | 18.4 | — |
| statsbomb_2015_16 | Ligue 1 | falli | 22 | 347 | 18.0% | 4.5 | — |
| statsbomb_2015_16 | Ligue 1 | gialli | 22 | 347 | 2.1% | 47.3 | — |
| statsbomb_2015_16 | Premier League | falli | 14 | 365 | 0.7% | 142.8 | — |
| statsbomb_2015_16 | Premier League | gialli | 14 | 365 | 0.0% | ∞ | — |
| statsbomb_2015_16 | Serie A | falli | 22 | 358 | 7.2% | 13.0 | — |
| statsbomb_2015_16 | Serie A | gialli | 22 | 358 | 6.6% | 14.2 | — |
