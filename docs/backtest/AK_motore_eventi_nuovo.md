# Motore a eventi: seconda verifica su un campione nuovo (fase AK)

Generato il 30/10/2026 con `python -m tools.event_check --campione nuovo`. 2672 partite di football-data.co.uk (D1 1920: 261. D1 2324: 296. E0 1920: 330. E0 2324: 375. I1 1920: 330. I1 2324: 375. SP1 1920: 330. SP1 2324: 375). Campione mai usato per scegliere o correggere: nessuna partita del primo banco (`data/cache/event_check/`). fuori dalla taratura (2024-26) e dalla stima (StatsBomb 2015/16. legame cartellini sul 2024-26). Stessa `MatchConfig` dell'app (quote di chiusura 1X2 e Over/Under 2.5). `engine.simulate_match` con 20.000 simulazioni al massimo. motore attuale contro motore a eventi (stesso seme: stessi punteggi Dixon-Coles; arresto adattivo acceso nel motore a eventi; esponente di attenuazione degli stati 0.496; esponente di stato dei gialli 3.36. partita calda sui rossi 4). «Eventi solo corner» = motore a eventi solo per i corner. tempi e cartellini dal motore attuale. Corner e cartellini del primo tempo non sono nei dati: non verificabili.

## Decisione

- Motore completo, log-loss media su tutti i mercati: 0.62194 → 0.62255 (differenza appaiata +0.00062 ± 0.00041, 2 e.s.); ECE 0.01874 → 0.02080 (tolleranza 0.0005); gruppi peggiori di oltre 2 e.s.: cartellini.
- Corner e combo del motore completo migliorano entrambi (stessa regola per gruppo): no. «Eventi solo corner»: gruppi peggiori nessuno, ECE media non peggiore.
- **Esito: motore a eventi SPENTO; mercati dal motore a eventi: nessuno** (regola: log-loss giù di oltre 2 e.s. appaiati, ECE non peggiore, nessun gruppo peggiore; per il solo corner: corner e combo migliorano e la variante solo corner non peggiora nulla).

## Per gruppo: motore a eventi completo

| Gruppo | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE prima | ECE dopo | Regola |
|---|---|---|---|---|---|---|
| tempi | 0.68447 | 0.68450 | +0.00003 ± 0.00018 | 0.01967 | 0.01926 | pari |
| corner | 0.68474 | 0.68400 | -0.00075 ± 0.00039 | 0.01679 | 0.01510 | meglio |
| cartellini | 0.68737 | 0.69158 | +0.00421 ± 0.00136 | 0.02006 | 0.03188 | peggio |
| combo | 0.50846 | 0.50818 | -0.00029 ± 0.00058 | 0.01851 | 0.01871 | pari |
| tutti | 0.62194 | 0.62255 | +0.00062 ± 0.00041 | 0.01874 | 0.02080 | peggio |

## Per gruppo: eventi solo corner

| Gruppo | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE prima | ECE dopo | Regola |
|---|---|---|---|---|---|---|
| tempi | 0.68447 | 0.68447 | +0.00000 ± 0.00000 | 0.01967 | 0.01967 | pari |
| corner | 0.68474 | 0.68400 | -0.00075 ± 0.00039 | 0.01679 | 0.01510 | meglio |
| cartellini | 0.68737 | 0.68737 | +0.00000 ± 0.00000 | 0.02006 | 0.02006 | pari |
| combo | 0.50846 | 0.50794 | -0.00053 ± 0.00045 | 0.01851 | 0.01655 | meglio |
| tutti | 0.62194 | 0.62160 | -0.00034 ± 0.00021 | 0.01874 | 0.01769 | meglio |

## Per mercato

| Mercato | Gruppo | Log-loss attuale | Completo: differenza (± 2 e.s.) | Solo corner: differenza (± 2 e.s.) | ECE attuale | ECE completo | ECE solo corner |
|---|---|---|---|---|---|---|---|
| 1X2 1T | tempi | 1.0300 | +0.00020 ± 0.00055 | +0.00000 ± 0.00000 | 0.0102 | 0.0077 | 0.0102 |
| 1X2 2T | tempi | 1.0281 | +0.00001 ± 0.00050 | +0.00000 ± 0.00000 | 0.0120 | 0.0113 | 0.0120 |
| Over 0.5 gol 1T | tempi | 0.5759 | +0.00015 ± 0.00038 | +0.00000 ± 0.00000 | 0.0134 | 0.0137 | 0.0134 |
| Over 1.5 gol 1T | tempi | 0.6453 | -0.00003 ± 0.00042 | +0.00000 ± 0.00000 | 0.0058 | 0.0045 | 0.0058 |
| Over 0.5 gol 2T | tempi | 0.4666 | -0.00001 ± 0.00032 | +0.00000 ± 0.00000 | 0.0287 | 0.0288 | 0.0287 |
| Over 1.5 gol 2T | tempi | 0.6794 | -0.00011 ± 0.00037 | +0.00000 ± 0.00000 | 0.0222 | 0.0211 | 0.0222 |
| Goal 1T | tempi | 0.4961 | -0.00013 ± 0.00039 | +0.00000 ± 0.00000 | 0.0165 | 0.0174 | 0.0165 |
| Multigol 1T 1-2 | tempi | 0.6744 | +0.00007 ± 0.00036 | +0.00000 ± 0.00000 | 0.0275 | 0.0280 | 0.0275 |
| Multigol 2T 1-3 | tempi | 0.5645 | +0.00012 ± 0.00031 | +0.00000 ± 0.00000 | 0.0407 | 0.0408 | 0.0407 |
| 1X2 corner | corner | 0.8675 | -0.00481 ± 0.00148 | -0.00481 ± 0.00148 | 0.0223 | 0.0195 | 0.0195 |
| Over 8.5 corner | corner | 0.6397 | +0.00029 ± 0.00050 | +0.00029 ± 0.00050 | 0.0286 | 0.0244 | 0.0244 |
| Over 9.5 corner | corner | 0.6829 | +0.00074 ± 0.00049 | +0.00074 ± 0.00049 | 0.0058 | 0.0037 | 0.0037 |
| Over 10.5 corner | corner | 0.6713 | +0.00001 ± 0.00048 | +0.00001 ± 0.00048 | 0.0160 | 0.0175 | 0.0175 |
| Casa Over 4.5 corner | corner | 0.6424 | -0.00039 ± 0.00086 | -0.00039 ± 0.00086 | 0.0140 | 0.0154 | 0.0154 |
| Casa Over 5.5 corner | corner | 0.6606 | +0.00042 ± 0.00061 | +0.00042 ± 0.00061 | 0.0132 | 0.0089 | 0.0089 |
| Ospite Over 3.5 corner | corner | 0.6513 | -0.00142 ± 0.00078 | -0.00142 ± 0.00078 | 0.0213 | 0.0191 | 0.0191 |
| Ospite Over 4.5 corner | corner | 0.6623 | -0.00079 ± 0.00057 | -0.00079 ± 0.00057 | 0.0131 | 0.0122 | 0.0122 |
| 1X2 cartellini | cartellini | 1.0542 | +0.00578 ± 0.00425 | +0.00000 ± 0.00000 | 0.0135 | 0.0326 | 0.0135 |
| Over 3.5 cartellini | cartellini | 0.6138 | +0.00313 ± 0.00144 | +0.00000 ± 0.00000 | 0.0324 | 0.0458 | 0.0324 |
| Over 4.5 cartellini | cartellini | 0.6663 | +0.00226 ± 0.00118 | +0.00000 ± 0.00000 | 0.0195 | 0.0147 | 0.0195 |
| Over 5.5 cartellini | cartellini | 0.6196 | +0.00134 ± 0.00084 | +0.00000 ± 0.00000 | 0.0167 | 0.0150 | 0.0167 |
| Casa Over 1.5 cartellini | cartellini | 0.6352 | +0.00451 ± 0.00392 | +0.00000 ± 0.00000 | 0.0052 | 0.0421 | 0.0052 |
| Casa Over 2.5 cartellini | cartellini | 0.6398 | +0.00121 ± 0.00204 | +0.00000 ± 0.00000 | 0.0231 | 0.0126 | 0.0231 |
| Ospite Over 1.5 cartellini | cartellini | 0.5960 | +0.01276 ± 0.00388 | +0.00000 ± 0.00000 | 0.0320 | 0.0650 | 0.0320 |
| Ospite Over 2.5 cartellini | cartellini | 0.6742 | +0.00269 ± 0.00192 | +0.00000 ± 0.00000 | 0.0180 | 0.0273 | 0.0180 |
| Over 2.5 gol & Over 9.5 corner | combo | 0.5734 | +0.00016 ± 0.00063 | +0.00016 ± 0.00063 | 0.0180 | 0.0147 | 0.0147 |
| Over 2.5 gol & Over 4.5 cartellini | combo | 0.5693 | +0.00053 ± 0.00171 | +0.00000 ± 0.00000 | 0.0095 | 0.0239 | 0.0095 |
| Goal & Over 9.5 corner | combo | 0.5918 | +0.00003 ± 0.00042 | +0.00003 ± 0.00042 | 0.0195 | 0.0188 | 0.0188 |
| 1 & Casa Over 4.5 corner | combo | 0.4914 | -0.00243 ± 0.00259 | -0.00243 ± 0.00259 | 0.0362 | 0.0253 | 0.0253 |
| 2 & Ospite Over 3.5 corner | combo | 0.4216 | +0.00081 ± 0.00233 | +0.00081 ± 0.00233 | 0.0161 | 0.0179 | 0.0179 |
| 1 & Over 4.5 cartellini | combo | 0.4809 | -0.00039 ± 0.00227 | +0.00000 ± 0.00000 | 0.0127 | 0.0145 | 0.0127 |
| X & Over 4.5 cartellini | combo | 0.3924 | +0.00061 ± 0.00127 | +0.00000 ± 0.00000 | 0.0148 | 0.0135 | 0.0148 |
| Over 9.5 corner & Over 4.5 cartellini | combo | 0.5636 | +0.00062 ± 0.00076 | +0.00035 ± 0.00036 | 0.0101 | 0.0138 | 0.0129 |
| Over 0.5 gol 1T & Over 9.5 corner | combo | 0.6438 | +0.00059 ± 0.00072 | +0.00043 ± 0.00051 | 0.0177 | 0.0158 | 0.0151 |
| Over 1.5 gol 2T & Over 4.5 cartellini | combo | 0.5422 | +0.00079 ± 0.00118 | +0.00000 ± 0.00000 | 0.0151 | 0.0246 | 0.0151 |
| X 1T & Over 4.5 cartellini | combo | 0.4975 | +0.00139 ± 0.00144 | +0.00000 ± 0.00000 | 0.0124 | 0.0166 | 0.0124 |
| Under 2.5 gol & Under 9.5 corner | combo | 0.4788 | -0.00091 ± 0.00063 | -0.00091 ± 0.00063 | 0.0306 | 0.0262 | 0.0262 |
| 1 & 2 corner | combo | 0.4300 | -0.00562 ± 0.00439 | -0.00562 ± 0.00439 | 0.0291 | 0.0168 | 0.0168 |
| 2 & 1 corner | combo | 0.4417 | -0.00018 ± 0.00314 | -0.00018 ± 0.00314 | 0.0174 | 0.0196 | 0.0196 |

## Medie, tempi e correlazioni

- Corner medi previsti 9.86 (attuale) / 9.86 (eventi), reali 10.01; punti cartellino 4.72 / 4.71, reali 4.78.
- Tempo medio per partita: 0.65 s (20.000 simulazioni) contro 3.65 s (20.000 simulazioni con l'arresto adattivo).

| Correlazione dei residui | Reale | Motore a eventi |
|---|---|---|
| diff. gol / diff. corner | -0.176 | -0.236 |
| gol totali / corner totali | -0.100 | -0.039 |
| |diff. gol| / gialli | -0.154 | -0.183 |
| gialli in più con un rosso (residuo) | +1.162 | +0.761 |

Nel motore attuale le prime tre sono circa 0 per costruzione (corner e cartellini indipendenti dai gol).
Residui = scarti da una regressione lineare su quote 1X2 e Over 2.5, medie di corner e cartellini, arbitro e campionato; per il motore a eventi una partita simulata per riga, stessi regressori; gialli nella convenzione dei dati (Inghilterra senza il primo giallo dell'espulso).
