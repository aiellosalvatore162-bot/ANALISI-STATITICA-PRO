# Motore a eventi: verifica fuori campione (fase AK, stadio 14)

Generato il 30/10/2026 con `python -m tools.event_check`. 1454 partite di football-data.co.uk (D1 2021: 100. D1 2122: 100. D1 2223: 100. D1 2627: 49. E0 2021: 100. E0 2122: 100. E0 2223: 100. E0 2627: 61. I1 2021: 100. I1 2122: 100. I1 2223: 100. I1 2627: 70. SP1 2021: 100. SP1 2122: 100. SP1 2223: 100. SP1 2627: 74). Stessa `MatchConfig` dell'app (quote di chiusura 1X2 e Over/Under 2.5). `engine.simulate_match` con 20.000 simulazioni al massimo. motore attuale contro motore a eventi (stesso seme: stessi punteggi Dixon-Coles; arresto adattivo acceso nel motore a eventi; esponente di attenuazione degli stati 0.53). Corner e cartellini del primo tempo non sono nei dati: non verificabili.

## Decisione

- Log-loss media su tutti i mercati: 0.62234 → 0.62204 (differenza appaiata -0.00031 ± 0.00036, 2 e.s.).
- ECE media: 0.02223 → 0.02123 (tolleranza 0.0005).
- Gruppi peggiori di oltre 2 e.s.: cartellini.
- **Esito: motore a eventi SPENTO** (regola: log-loss giù di oltre 2 e.s. appaiati, ECE non peggiore, nessun gruppo peggiore).

## Per gruppo

| Gruppo | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE prima | ECE dopo |
|---|---|---|---|---|---|
| tempi | 0.69351 | 0.69375 | +0.00024 ± 0.00025 | 0.02228 | 0.02164 |
| corner | 0.69841 | 0.69717 | -0.00123 ± 0.00056 | 0.02582 | 0.02182 |
| cartellini | 0.68212 | 0.68342 | +0.00130 ± 0.00080 | 0.01814 | 0.02129 |
| combo | 0.49897 | 0.49792 | -0.00105 ± 0.00068 | 0.02247 | 0.02059 |
| tutti | 0.62234 | 0.62204 | -0.00031 ± 0.00036 | 0.02223 | 0.02123 |

## Per mercato

| Mercato | Gruppo | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE prima | ECE dopo |
|---|---|---|---|---|---|---|
| 1X2 1T | tempi | 1.0189 | 1.0193 | +0.00042 ± 0.00075 | 0.0105 | 0.0103 |
| 1X2 2T | tempi | 1.0521 | 1.0524 | +0.00035 ± 0.00070 | 0.0124 | 0.0155 |
| Over 0.5 gol 1T | tempi | 0.5731 | 0.5736 | +0.00046 ± 0.00052 | 0.0261 | 0.0224 |
| Over 1.5 gol 1T | tempi | 0.6515 | 0.6516 | +0.00010 ± 0.00056 | 0.0209 | 0.0195 |
| Over 0.5 gol 2T | tempi | 0.4878 | 0.4877 | -0.00007 ± 0.00043 | 0.0211 | 0.0225 |
| Over 1.5 gol 2T | tempi | 0.6763 | 0.6764 | +0.00008 ± 0.00050 | 0.0352 | 0.0310 |
| Goal 1T | tempi | 0.5262 | 0.5266 | +0.00041 ± 0.00056 | 0.0345 | 0.0339 |
| Multigol 1T 1-2 | tempi | 0.6782 | 0.6787 | +0.00044 ± 0.00048 | 0.0129 | 0.0124 |
| Multigol 2T 1-3 | tempi | 0.5775 | 0.5775 | -0.00003 ± 0.00041 | 0.0271 | 0.0274 |
| 1X2 corner | corner | 0.9183 | 0.9126 | -0.00574 ± 0.00215 | 0.0370 | 0.0315 |
| Over 8.5 corner | corner | 0.6596 | 0.6596 | +0.00001 ± 0.00068 | 0.0242 | 0.0205 |
| Over 9.5 corner | corner | 0.6878 | 0.6877 | -0.00009 ± 0.00069 | 0.0123 | 0.0139 |
| Over 10.5 corner | corner | 0.6618 | 0.6616 | -0.00020 ± 0.00068 | 0.0094 | 0.0084 |
| Casa Over 4.5 corner | corner | 0.6743 | 0.6717 | -0.00266 ± 0.00124 | 0.0482 | 0.0334 |
| Casa Over 5.5 corner | corner | 0.6508 | 0.6500 | -0.00080 ± 0.00083 | 0.0171 | 0.0174 |
| Ospite Over 3.5 corner | corner | 0.6619 | 0.6611 | -0.00084 ± 0.00104 | 0.0287 | 0.0216 |
| Ospite Over 4.5 corner | corner | 0.6726 | 0.6731 | +0.00046 ± 0.00076 | 0.0297 | 0.0279 |
| 1X2 cartellini | cartellini | 1.0527 | 1.0550 | +0.00233 ± 0.00286 | 0.0072 | 0.0194 |
| Over 3.5 cartellini | cartellini | 0.6391 | 0.6392 | +0.00010 ± 0.00084 | 0.0221 | 0.0245 |
| Over 4.5 cartellini | cartellini | 0.6572 | 0.6576 | +0.00037 ± 0.00082 | 0.0180 | 0.0149 |
| Over 5.5 cartellini | cartellini | 0.5700 | 0.5708 | +0.00089 ± 0.00080 | 0.0225 | 0.0220 |
| Casa Over 1.5 cartellini | cartellini | 0.6417 | 0.6428 | +0.00108 ± 0.00223 | 0.0130 | 0.0208 |
| Casa Over 2.5 cartellini | cartellini | 0.6142 | 0.6143 | +0.00006 ± 0.00143 | 0.0332 | 0.0278 |
| Ospite Over 1.5 cartellini | cartellini | 0.6250 | 0.6287 | +0.00368 ± 0.00175 | 0.0199 | 0.0193 |
| Ospite Over 2.5 cartellini | cartellini | 0.6570 | 0.6589 | +0.00190 ± 0.00140 | 0.0092 | 0.0216 |
| Over 2.5 gol & Over 9.5 corner | combo | 0.5716 | 0.5718 | +0.00024 ± 0.00090 | 0.0240 | 0.0234 |
| Over 2.5 gol & Over 4.5 cartellini | combo | 0.5229 | 0.5227 | -0.00016 ± 0.00075 | 0.0093 | 0.0079 |
| Goal & Over 9.5 corner | combo | 0.5919 | 0.5918 | -0.00014 ± 0.00059 | 0.0256 | 0.0246 |
| 1 & Casa Over 4.5 corner | combo | 0.4773 | 0.4729 | -0.00433 ± 0.00365 | 0.0392 | 0.0206 |
| 2 & Ospite Over 3.5 corner | combo | 0.4462 | 0.4475 | +0.00131 ± 0.00346 | 0.0085 | 0.0182 |
| 1 & Over 4.5 cartellini | combo | 0.4400 | 0.4395 | -0.00055 ± 0.00074 | 0.0162 | 0.0133 |
| X & Over 4.5 cartellini | combo | 0.3760 | 0.3761 | +0.00014 ± 0.00062 | 0.0165 | 0.0149 |
| Over 9.5 corner & Over 4.5 cartellini | combo | 0.5025 | 0.5027 | +0.00021 ± 0.00074 | 0.0064 | 0.0116 |
| Over 0.5 gol 1T & Over 9.5 corner | combo | 0.6455 | 0.6460 | +0.00051 ± 0.00104 | 0.0175 | 0.0246 |
| Over 1.5 gol 2T & Over 4.5 cartellini | combo | 0.4926 | 0.4927 | +0.00014 ± 0.00069 | 0.0196 | 0.0140 |
| X 1T & Over 4.5 cartellini | combo | 0.4846 | 0.4849 | +0.00029 ± 0.00070 | 0.0215 | 0.0186 |
| Under 2.5 gol & Under 9.5 corner | combo | 0.5133 | 0.5121 | -0.00118 ± 0.00078 | 0.0252 | 0.0343 |
| 1 & 2 corner | combo | 0.4750 | 0.4616 | -0.01340 ± 0.00650 | 0.0513 | 0.0294 |
| 2 & 1 corner | combo | 0.4462 | 0.4485 | +0.00225 ± 0.00426 | 0.0337 | 0.0329 |

## Medie, tempi e correlazioni

- Corner medi previsti 9.63 (attuale) / 9.63 (eventi), reali 9.67; punti cartellino 4.41 / 4.39, reali 4.40.
- Tempo medio per partita: 0.69 s (20.000 simulazioni) contro 3.13 s (20.000 simulazioni con l'arresto adattivo).

| Correlazione dei residui | Reale | Motore a eventi |
|---|---|---|
| diff. gol / diff. corner | -0.139 | -0.215 |
| gol totali / corner totali | -0.030 | -0.005 |
| |diff. gol| / gialli | -0.184 | -0.066 |
| gialli in più con un rosso (residuo) | +0.959 | +0.107 |

Nel motore attuale le prime tre sono circa 0 per costruzione (corner e cartellini indipendenti dai gol).
Residui = scarti da una regressione lineare su quote 1X2 e Over 2.5, medie di corner e cartellini, arbitro e campionato; per il motore a eventi una partita simulata per riga, stessi regressori.
