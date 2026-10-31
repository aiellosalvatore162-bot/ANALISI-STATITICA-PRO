# Fase AO – moduli e corsie nel motore a eventi

Data: StatsBomb Open Data 2015/16, 3058 squadre-partita (1529 partite). Giocatori larghi in attacco (media 1.88; distribuzione {0.0: 243, 1.0: 1, 2.0: 2753, 4.0: 61}), scontro = larghi propri − larghi difensivi dell'avversario (media -0.69). Quasi-Poisson con offset (media del campionato × concessi dall'avversario senza la partita), errori robusti per partita.

## cross (media 12.49 per squadra-partita)

| termine | stima | e.s. | IC 95% |
|---|---|---|---|
| intercetta | -0.1456 | 0.0116 | -0.1683 … -0.1229 |
| casa | +0.2728 | 0.0169 | +0.2397 … +0.3060 |
| fasce | +0.0387 | 0.0148 | +0.0097 … +0.0677 |
| scontro | -0.0095 | 0.0086 | -0.0263 … +0.0074 |

## corner_da_cross (media 1.00 per squadra-partita)

| termine | stima | e.s. | IC 95% |
|---|---|---|---|
| intercetta | -0.1949 | 0.0310 | -0.2556 … -0.1342 |
| casa | +0.3502 | 0.0416 | +0.2688 … +0.4316 |
| fasce | +0.0737 | 0.0407 | -0.0061 … +0.1535 |
| scontro | -0.0415 | 0.0224 | -0.0854 … +0.0024 |

## testa_da_cross (media 0.88 per squadra-partita)

| termine | stima | e.s. | IC 95% |
|---|---|---|---|
| intercetta | -0.2192 | 0.0333 | -0.2845 … -0.1540 |
| casa | +0.3919 | 0.0446 | +0.3044 … +0.4794 |
| fasce | +0.0750 | 0.0418 | -0.0069 … +0.1569 |
| scontro | -0.0180 | 0.0228 | -0.0627 … +0.0266 |

«fasce» = effetto sul logaritmo per ogni giocatore largo in più; «scontro» = per ogni larghi in più rispetto a chi copre la fascia avversaria. Nel motore: cross, corner da cross e tiri di testa da cross × exp(fasce·ΔL + scontro·ΔS); il totale dei corner resta quello del motore attuale (vincolo di coerenza), le corsie spostano la parte da cross.
