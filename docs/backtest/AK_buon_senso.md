## Motore a eventi: realismo e buon senso (fase AK, stadi 12-13)

Generato il 30/10/2026 con `python -m tools.event_sense`. Serie A, partite tipo con quote di chiusura inventate ma plausibili; stessi punteggi Dixon-Coles e stesse medie finali nei due motori (vincolo di coerenza). Le misure sui percorsi esistono solo col motore a eventi: nel motore attuale corner e cartellini sono indipendenti dal punteggio (correlazioni 0 per costruzione).

### Mercati (%): motore attuale → motore a eventi

| Mercato | favorita netta | equilibrata | chiusa | arbitro severo | arbitro permissivo |
|---|---|---|---|---|---|
| 1 | 73.1 → 73.1 | 38.2 → 38.2 | 36.1 → 36.1 | 38.2 → 38.2 | 38.2 → 38.2 |
| X | 18.3 → 18.3 | 28.9 → 28.9 | 31.8 → 31.8 | 28.9 → 28.9 | 28.9 → 28.9 |
| 2 | 8.7 → 8.7 | 32.9 → 32.9 | 32.1 → 32.1 | 32.9 → 32.9 | 32.9 → 32.9 |
| Over 2.5 gol | 58.3 → 58.3 | 49.5 → 49.5 | 37.8 → 37.8 | 49.5 → 49.5 | 49.5 → 49.5 |
| X 1T | 34.3 → 34.4 | 43.3 → 43.5 | 49.1 → 49.1 | 43.3 → 43.2 | 43.3 → 43.3 |
| Over 0.5 gol 1T | 74.6 → 74.5 | 68.3 → 68.1 | 59.9 → 59.7 | 68.3 → 68.5 | 68.3 → 68.4 |
| Over 1.5 gol 2T | 50.1 → 50.1 | 44.8 → 44.7 | 37.1 → 37.4 | 44.8 → 44.0 | 44.8 → 44.4 |
| Over 9.5 corner | 55.4 → 54.2 | 52.5 → 51.7 | 48.5 → 48.3 | 52.5 → 51.5 | 52.5 → 51.9 |
| 1 corner | 82.9 → 81.4 | 60.6 → 59.4 | 58.7 → 57.8 | 60.6 → 59.7 | 60.6 → 59.4 |
| Casa Over 4.5 corner | 79.8 → 78.2 | 65.3 → 63.5 | 61.7 → 60.4 | 65.3 → 63.5 | 65.3 → 63.7 |
| Over 4.5 cartellini | 53.0 → 52.4 | 54.6 → 53.9 | 57.4 → 56.5 | 60.6 → 60.7 | 47.9 → 47.4 |
| Over 1.5 cartellini 1T | 54.8 → 53.3 | 56.2 → 53.8 | 57.9 → 55.0 | 59.8 → 58.3 | 51.4 → 49.4 |
| Ospite Over 1.5 cartellini | 77.5 → 78.4 | 71.4 → 68.9 | 73.2 → 70.8 | 75.2 → 73.4 | 66.6 → 64.7 |
| Over 2.5 gol + Over 9.5 corner | 32.4 → 30.4 | 25.9 → 25.2 | 18.2 → 17.8 | 25.9 → 25.1 | 25.9 → 25.3 |
| 1 + Over 4.5 cartellini | 38.6 → 37.7 | 20.7 → 20.2 | 20.6 → 20.4 | 23.0 → 23.1 | 18.2 → 17.9 |
| media corner | 10.18 → 10.09 | 9.96 → 9.89 | 9.61 → 9.61 | 9.96 → 9.88 | 9.96 → 9.88 |
| media punti cartellino | 4.97 → 4.93 | 5.10 → 5.04 | 5.30 → 5.22 | 5.53 → 5.50 | 4.66 → 4.61 |
| simulazioni | 40.000 → 40.000 | 40.000 → 40.000 | 40.000 → 40.000 | 40.000 → 40.000 | 40.000 → 40.000 |

### Percorsi del motore a eventi

| Misura | favorita netta | equilibrata | chiusa | arbitro severo | arbitro permissivo |
|---|---|---|---|---|---|
| corner da tiro (quota) | 0.343 | 0.324 | 0.278 | 0.325 | 0.325 |
| corner casa 2T se sotto all'intervallo | 4.295 | 3.354 | 3.231 | 3.340 | 3.326 |
| corner casa 2T se pari all'intervallo | 3.761 | 2.993 | 2.894 | 2.994 | 3.002 |
| corner casa 2T se avanti all'intervallo | 3.041 | 2.448 | 2.367 | 2.445 | 2.446 |
| correlazione diff. gol / diff. corner | -0.213 | -0.232 | -0.213 | -0.231 | -0.227 |
| correlazione gol totali / corner totali | -0.074 | -0.018 | -0.027 | -0.024 | -0.021 |
| correlazione |diff. gol| / gialli | -0.046 | -0.033 | -0.018 | -0.032 | -0.023 |
| quota gialli nel 1T | 0.379 | 0.376 | 0.376 | 0.377 | 0.374 |
| quota corner nel 1T | 0.487 | 0.475 | 0.471 | 0.476 | 0.475 |
| quota gol nel 1T | 0.451 | 0.434 | 0.417 | 0.440 | 0.437 |
| minuto medio del primo gol | 27.742 | 30.483 | 33.922 | 30.201 | 30.297 |
| partite con un rosso (%) | 18.990 | 19.293 | 20.480 | 21.152 | 18.215 |
| gialli medi con un rosso / senza | 1.007 | 1.028 | 1.039 | 1.028 | 1.026 |
| falli medi | 32.788 | 32.871 | 32.953 | 32.832 | 32.889 |
| tiri casa con rosso prima del 30' / media | 0.716 | 0.712 | 0.712 | 0.710 | 0.713 |
| corner ospite con rosso casa prima del 30' / media | 1.292 | 1.296 | 1.297 | 1.281 | 1.290 |
