# Formazioni e giocatori (fase AL): verifica sullo storico

Generato il 30/10/2026 con `python -m tools.lineup_check`. Campionati I1, E0, D1, SP1, stagioni 2526, 2627, 1606 partite con rosa Understat. Storico giocatori disponibile dal 2025-08-15 (cache `tools.player_data`: 2025/26 e 2026/27): le prime giornate del 2025/26 hanno poco passato e usano i tassi di ruolo.

**Cosa si confronta.** Gol attesi del modello senza fattori (= XI tipo) contro gli stessi moltiplicati per il fattore della FORMAZIONE EFFETTIVA (come sarebbe nota poco prima del fischio d'inizio; minuti attesi e tassi solo dal passato). Non è una previsione a più giorni: vale solo se la formazione è nota al momento della giocata. Previsioni del solo modello (non ancorato); differenza = dopo − prima (negativa = migliora).

Intervallo storico del fattore attacco (1°-99° percentile, periodo di taratura): 0.778-1.326.
Esponente del fattore attacco (elasticità dei gol attesi alla produzione npxG+xA, stimato nel periodo di taratura): γ = -0.097 ± 0.209 (usato: 0.000; l'1 vorrebbe dire che i gol seguono la produzione 1 a 1, ma npxG+xA conta due volte ogni occasione).

## Solo fattore attacco (con l'esponente stimato)

| Ambito | Mercato | N | Log-loss prima → dopo | ECE prima → dopo | Differenza ± e.s. |
|---|---|---|---|---|---|
| taratura (fino al 31/12/2025) | 1X2 | 591 | 0.9733 → 0.9733 | 0.0256 → 0.0256 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Over 1.5 gol | 591 | 0.5232 → 0.5232 | 0.0447 → 0.0447 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Over 2.5 gol | 591 | 0.6781 → 0.6781 | 0.0179 → 0.0179 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Over 3.5 gol | 591 | 0.5931 → 0.5931 | 0.0204 → 0.0204 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | GG | 591 | 0.6886 → 0.6886 | 0.0047 → 0.0047 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Casa Over 0.5 gol | 591 | 0.5054 → 0.5054 | 0.0254 → 0.0254 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Ospite Over 0.5 gol | 591 | 0.5763 → 0.5763 | 0.0496 → 0.0496 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Casa Over 1.5 gol | 591 | 0.6369 → 0.6369 | 0.0405 → 0.0405 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Ospite Over 1.5 gol | 591 | 0.5933 → 0.5933 | 0.0330 → 0.0330 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | 1X2 | 1015 | 0.9916 → 0.9916 | 0.0149 → 0.0149 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Over 1.5 gol | 1015 | 0.5075 → 0.5075 | 0.0115 → 0.0115 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Over 2.5 gol | 1015 | 0.6761 → 0.6761 | 0.0141 → 0.0141 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Over 3.5 gol | 1015 | 0.6120 → 0.6120 | 0.0211 → 0.0211 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | GG | 1015 | 0.6767 → 0.6767 | 0.0323 → 0.0323 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Casa Over 0.5 gol | 1015 | 0.4769 → 0.4769 | 0.0375 → 0.0375 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Ospite Over 0.5 gol | 1015 | 0.5637 → 0.5637 | 0.0248 → 0.0248 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Casa Over 1.5 gol | 1015 | 0.6524 → 0.6524 | 0.0322 → 0.0322 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Ospite Over 1.5 gol | 1015 | 0.6436 → 0.6436 | 0.0284 → 0.0284 | +0.00000 ± 0.00000 |
| tutte | 1X2 | 1606 | 0.9848 → 0.9848 | 0.0098 → 0.0098 | +0.00000 ± 0.00000 |
| tutte | Over 1.5 gol | 1606 | 0.5133 → 0.5133 | 0.0100 → 0.0100 | +0.00000 ± 0.00000 |
| tutte | Over 2.5 gol | 1606 | 0.6769 → 0.6769 | 0.0084 → 0.0084 | +0.00000 ± 0.00000 |
| tutte | Over 3.5 gol | 1606 | 0.6050 → 0.6050 | 0.0164 → 0.0164 | +0.00000 ± 0.00000 |
| tutte | GG | 1606 | 0.6811 → 0.6811 | 0.0212 → 0.0212 | +0.00000 ± 0.00000 |
| tutte | Casa Over 0.5 gol | 1606 | 0.4874 → 0.4874 | 0.0306 → 0.0306 | +0.00000 ± 0.00000 |
| tutte | Ospite Over 0.5 gol | 1606 | 0.5684 → 0.5684 | 0.0176 → 0.0176 | +0.00000 ± 0.00000 |
| tutte | Casa Over 1.5 gol | 1606 | 0.6467 → 0.6467 | 0.0191 → 0.0191 | +0.00000 ± 0.00000 |
| tutte | Ospite Over 1.5 gol | 1606 | 0.6251 → 0.6251 | 0.0198 → 0.0198 | +0.00000 ± 0.00000 |

## Per confronto: fattore PIENO (γ = 1), non usato

Se i gol seguissero la produzione 1 a 1 (come nelle assenze della Fase P), questo sarebbe l'effetto sul modello senza ancoraggio:

| Ambito | Mercato | N | Log-loss prima → dopo | ECE prima → dopo | Differenza ± e.s. |
|---|---|---|---|---|---|
| tutte | 1X2 | 1606 | 0.9848 → 0.9855 | 0.0098 → 0.0103 | +0.00065 ± 0.00225 |
| tutte | Over 1.5 gol | 1606 | 0.5133 → 0.5175 | 0.0100 → 0.0129 | +0.00422 ± 0.00177 |
| tutte | Over 2.5 gol | 1606 | 0.6769 → 0.6841 | 0.0084 → 0.0183 | +0.00725 ± 0.00216 |
| tutte | Over 3.5 gol | 1606 | 0.6050 → 0.6102 | 0.0164 → 0.0107 | +0.00514 ± 0.00213 |
| tutte | GG | 1606 | 0.6811 → 0.6852 | 0.0212 → 0.0200 | +0.00410 ± 0.00153 |
| tutte | Casa Over 0.5 gol | 1606 | 0.4874 → 0.4874 | 0.0306 → 0.0235 | +0.00001 ± 0.00156 |
| tutte | Ospite Over 0.5 gol | 1606 | 0.5684 → 0.5721 | 0.0176 → 0.0119 | +0.00379 ± 0.00170 |
| tutte | Casa Over 1.5 gol | 1606 | 0.6467 → 0.6509 | 0.0191 → 0.0198 | +0.00422 ± 0.00218 |
| tutte | Ospite Over 1.5 gol | 1606 | 0.6251 → 0.6309 | 0.0198 → 0.0211 | +0.00583 ± 0.00202 |

## Attacco + difesa per ruolo

| Ambito | Mercato | N | Log-loss prima → dopo | ECE prima → dopo | Differenza ± e.s. |
|---|---|---|---|---|---|
| taratura (fino al 31/12/2025) | 1X2 | 591 | 0.9733 → 0.9733 | 0.0256 → 0.0256 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Over 1.5 gol | 591 | 0.5232 → 0.5232 | 0.0447 → 0.0447 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Over 2.5 gol | 591 | 0.6781 → 0.6781 | 0.0179 → 0.0179 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Over 3.5 gol | 591 | 0.5931 → 0.5931 | 0.0204 → 0.0204 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | GG | 591 | 0.6886 → 0.6886 | 0.0047 → 0.0047 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Casa Over 0.5 gol | 591 | 0.5054 → 0.5054 | 0.0254 → 0.0254 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Ospite Over 0.5 gol | 591 | 0.5763 → 0.5763 | 0.0496 → 0.0496 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Casa Over 1.5 gol | 591 | 0.6369 → 0.6369 | 0.0405 → 0.0405 | +0.00000 ± 0.00000 |
| taratura (fino al 31/12/2025) | Ospite Over 1.5 gol | 591 | 0.5933 → 0.5933 | 0.0330 → 0.0330 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | 1X2 | 1015 | 0.9916 → 0.9916 | 0.0149 → 0.0149 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Over 1.5 gol | 1015 | 0.5075 → 0.5075 | 0.0115 → 0.0115 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Over 2.5 gol | 1015 | 0.6761 → 0.6761 | 0.0141 → 0.0141 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Over 3.5 gol | 1015 | 0.6120 → 0.6120 | 0.0211 → 0.0211 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | GG | 1015 | 0.6767 → 0.6767 | 0.0323 → 0.0323 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Casa Over 0.5 gol | 1015 | 0.4769 → 0.4769 | 0.0375 → 0.0375 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Ospite Over 0.5 gol | 1015 | 0.5637 → 0.5637 | 0.0248 → 0.0248 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Casa Over 1.5 gol | 1015 | 0.6524 → 0.6524 | 0.0322 → 0.0322 | +0.00000 ± 0.00000 |
| verifica (dal 01/01/2026) | Ospite Over 1.5 gol | 1015 | 0.6436 → 0.6436 | 0.0284 → 0.0284 | +0.00000 ± 0.00000 |
| tutte | 1X2 | 1606 | 0.9848 → 0.9848 | 0.0098 → 0.0098 | +0.00000 ± 0.00000 |
| tutte | Over 1.5 gol | 1606 | 0.5133 → 0.5133 | 0.0100 → 0.0100 | +0.00000 ± 0.00000 |
| tutte | Over 2.5 gol | 1606 | 0.6769 → 0.6769 | 0.0084 → 0.0084 | +0.00000 ± 0.00000 |
| tutte | Over 3.5 gol | 1606 | 0.6050 → 0.6050 | 0.0164 → 0.0164 | +0.00000 ± 0.00000 |
| tutte | GG | 1606 | 0.6811 → 0.6811 | 0.0212 → 0.0212 | +0.00000 ± 0.00000 |
| tutte | Casa Over 0.5 gol | 1606 | 0.4874 → 0.4874 | 0.0306 → 0.0306 | +0.00000 ± 0.00000 |
| tutte | Ospite Over 0.5 gol | 1606 | 0.5684 → 0.5684 | 0.0176 → 0.0176 | +0.00000 ± 0.00000 |
| tutte | Casa Over 1.5 gol | 1606 | 0.6467 → 0.6467 | 0.0191 → 0.0191 | +0.00000 ± 0.00000 |
| tutte | Ospite Over 1.5 gol | 1606 | 0.6251 → 0.6251 | 0.0198 → 0.0198 | +0.00000 ± 0.00000 |

## Pesi della difesa per ruolo (stimati nel periodo di taratura)

| Ruolo | β | e.s. | z | Peso applicato |
|---|---|---|---|---|
| POR | +0.0849 | 0.0925 | +0.92 | 0.0000 |
| DIF | +0.0161 | 0.0960 | +0.17 | 0.0000 |
| CEN | -0.1082 | 0.0908 | -1.19 | 0.0000 |

Regola: peso applicato solo se β > 0 e z ≥ 2; altrimenti la difesa è SOLO ETICHETTA (dichiarato in scheda).

## «Sta performando»: shrinkage di gol−npxG

| Unità | N | β (2ª metà su 1ª) | npxG medio 1ª metà | k stimato |
|---|---|---|---|---|
| giocatore | 928 | 0.1204 | 1.95 | 14.23 |
| squadra | 78 | 0.4553 | 31.25 | 37.38 |

β piccolo = la fortuna in finalizzazione quasi non si ripete: lo shrinkage è forte (k grande).
