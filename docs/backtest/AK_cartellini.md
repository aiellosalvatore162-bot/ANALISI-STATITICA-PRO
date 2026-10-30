# Motore a eventi: legame tra rossi, gialli e stato della partita (fase AK)

Generato il 30/10/2026 con `python -m tools.event_cards`. Momenti reali su 2851 partite football-data 2024/25-2025/26 (stagioni di taratura. nessuna partita dei banchi di verifica); motore su 400 partite delle stesse stagioni × 10 percorsi (`simulate_match` acceso. 4.000 simulazioni). Residui a parità di quote. medie. arbitro e campionato.

## Stima

- Esponente di stato dei gialli: **3.36** (± 1.49, 2 e.s.; era l'esponente comune 0.496).
- Esponente della partita calda sui rossi: **4** (± 2.52) — FUORI dalla griglia: valore al bordo.

| Momento | Reale (± 2 e.s.) | Motore prima | Motore dopo |
|---|---|---|---|
| pendenza gialli / |diff. reti| | -0.302 ± 0.065 | -0.054 | -0.316 |
| correlazione |diff. reti| / gialli | -0.164 ± 0.034 | -0.031 | -0.181 |
| gialli in più con un rosso | +1.067 ± 0.231 | +0.517 | +0.737 |

«Motore prima» = uomo in meno già stimato tra partite (gialli ×0,87), esponente comune, partita calda con esponente 1. Con l'uomo in meno stimato con l'effetto fisso (×0,39) il banco dava +0,11 gialli con un rosso.

## Curve

| a (g = 1) | pendenza | correlazione | gialli con rosso |
|---|---|---|---|
| 1 | -0.114 | -0.063 | +0.671 |
| 2 | -0.203 | -0.113 | +0.457 |
| 3 | -0.292 | -0.162 | +0.531 |

| g (a = 3) | pendenza | correlazione | gialli con rosso |
|---|---|---|---|
| 1 | -0.292 | -0.162 | +0.531 |
| 2 | -0.279 | -0.159 | +0.535 |
| 3 | -0.299 | -0.170 | +0.664 |
| 4 | -0.276 | -0.153 | +0.794 |

| a (g = 4) | pendenza | correlazione | gialli con rosso |
|---|---|---|---|
| 2.5 | -0.269 | -0.149 | +0.977 |
| 3 | -0.276 | -0.153 | +0.794 |
| 3.5 | -0.312 | -0.177 | +0.854 |
