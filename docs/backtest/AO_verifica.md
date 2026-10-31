# Fase AO – verifica del Simulatore reale con tutti i dati

Generato con `python -m tools.ao_check`. 563 partite su 563 del terzo stratificato (D1 2526: 101, D1 2627: 17, E0 2526: 125, E0 2627: 21, I1 2526: 125, I1 2627: 24, SP1 2526: 125, SP1 2627: 25); 10,000 simulazioni, stesso seme. Formazione nel motore in 538 partite, corsie dai titolari in 552. Calcolo attuale contro «Simulatore reale – completo» (modo libero + ripesatura Dixon-Coles) con formazione, assenti, corsie e stile. Differenza di log-loss appaiata (reale − attuale; negativa = meglio) ± 2 errori standard. Arbitro nei falli non verificabile qui (manca il nome nel dataset storico). Partite 2025/26 nel periodo di taratura dei parametri base (2024-26): i gruppi gol e corner/cartellini partono dalle stesse medie in entrambe le varianti.

| Gruppo | Mercati | Differenza log-loss (± 2 e.s.) | ECE attuale | ECE reale |
|---|---|---|---|---|
| gol | 5 | +0.00103 ± 0.00279 | 0.0168 | 0.0191 |
| tempi | 9 | +0.00056 ± 0.00111 | 0.0225 | 0.0259 |
| corner | 8 | -0.00101 ± 0.00112 | 0.0232 | 0.0247 |
| cartellini | 8 | +0.00148 ± 0.00287 | 0.0229 | 0.0265 |
| combo | 14 | -0.00083 ± 0.00119 | 0.0283 | 0.0242 |

| Mercato | Log-loss attuale | Log-loss reale | Differenza (± 2 e.s.) | ECE attuale | ECE reale |
|---|---|---|---|---|---|
| 1X2 1T | 1.0478 | 1.0530 | +0.00517 ± 0.00429 | 0.0159 | 0.0259 |
| 1X2 2T | 1.0301 | 1.0299 | -0.00020 ± 0.00346 | 0.0198 | 0.0209 |
| Over 0.5 gol 1T | 0.5862 | 0.5852 | -0.00106 ± 0.00224 | 0.0293 | 0.0257 |
| Over 1.5 gol 1T | 0.6348 | 0.6347 | -0.00009 ± 0.00172 | 0.0268 | 0.0316 |
| Over 0.5 gol 2T | 0.4744 | 0.4743 | -0.00005 ± 0.00180 | 0.0292 | 0.0245 |
| Over 1.5 gol 2T | 0.6767 | 0.6788 | +0.00210 ± 0.00169 | 0.0187 | 0.0388 |
| Goal 1T | 0.4977 | 0.4992 | +0.00148 ± 0.00477 | 0.0147 | 0.0260 |
| Multigol 1T 1-2 | 0.6798 | 0.6783 | -0.00151 ± 0.00252 | 0.0149 | 0.0122 |
| Multigol 2T 1-3 | 0.5746 | 0.5738 | -0.00080 ± 0.00183 | 0.0329 | 0.0271 |
| 1X2 corner | 0.9145 | 0.9096 | -0.00488 ± 0.00338 | 0.0280 | 0.0241 |
| Over 8.5 corner | 0.6749 | 0.6749 | -0.00007 ± 0.00177 | 0.0210 | 0.0334 |
| Over 9.5 corner | 0.6902 | 0.6906 | +0.00035 ± 0.00176 | 0.0145 | 0.0218 |
| Over 10.5 corner | 0.6563 | 0.6566 | +0.00027 ± 0.00170 | 0.0151 | 0.0043 |
| Casa Over 4.5 corner | 0.6722 | 0.6719 | -0.00033 ± 0.00214 | 0.0286 | 0.0288 |
| Casa Over 5.5 corner | 0.6743 | 0.6740 | -0.00032 ± 0.00185 | 0.0195 | 0.0202 |
| Ospite Over 3.5 corner | 0.6680 | 0.6650 | -0.00293 ± 0.00204 | 0.0372 | 0.0308 |
| Ospite Over 4.5 corner | 0.6446 | 0.6445 | -0.00018 ± 0.00171 | 0.0219 | 0.0343 |
| 1X2 cartellini | 1.0630 | 1.0728 | +0.00982 ± 0.00810 | 0.0154 | 0.0396 |
| Over 3.5 cartellini | 0.6668 | 0.6689 | +0.00210 ± 0.00392 | 0.0121 | 0.0079 |
| Over 4.5 cartellini | 0.6615 | 0.6602 | -0.00125 ± 0.00312 | 0.0135 | 0.0192 |
| Over 5.5 cartellini | 0.5559 | 0.5556 | -0.00033 ± 0.00219 | 0.0258 | 0.0200 |
| Casa Over 1.5 cartellini | 0.6686 | 0.6682 | -0.00042 ± 0.00798 | 0.0364 | 0.0344 |
| Casa Over 2.5 cartellini | 0.6003 | 0.5971 | -0.00317 ± 0.00360 | 0.0390 | 0.0383 |
| Ospite Over 1.5 cartellini | 0.6458 | 0.6505 | +0.00471 ± 0.00797 | 0.0239 | 0.0318 |
| Ospite Over 2.5 cartellini | 0.6554 | 0.6558 | +0.00038 ± 0.00339 | 0.0174 | 0.0212 |
| Over 2.5 gol & Over 9.5 corner | 0.5598 | 0.5594 | -0.00046 ± 0.00175 | 0.0238 | 0.0140 |
| Over 2.5 gol & Over 4.5 cartellini | 0.5349 | 0.5341 | -0.00071 ± 0.00277 | 0.0409 | 0.0195 |
| Goal & Over 9.5 corner | 0.5719 | 0.5719 | +0.00006 ± 0.00492 | 0.0063 | 0.0231 |
| 1 & Casa Over 4.5 corner | 0.4998 | 0.4984 | -0.00140 ± 0.00626 | 0.0316 | 0.0293 |
| 2 & Ospite Over 3.5 corner | 0.4147 | 0.4120 | -0.00271 ± 0.00742 | 0.0277 | 0.0279 |
| 1 & Over 4.5 cartellini | 0.4253 | 0.4249 | -0.00044 ± 0.00355 | 0.0306 | 0.0178 |
| X & Over 4.5 cartellini | 0.3827 | 0.3793 | -0.00343 ± 0.00373 | 0.0186 | 0.0100 |
| Over 9.5 corner & Over 4.5 cartellini | 0.4696 | 0.4688 | -0.00082 ± 0.00213 | 0.0271 | 0.0202 |
| Over 0.5 gol 1T & Over 9.5 corner | 0.6251 | 0.6247 | -0.00042 ± 0.00176 | 0.0208 | 0.0156 |
| Over 1.5 gol 2T & Over 4.5 cartellini | 0.4899 | 0.4913 | +0.00147 ± 0.00248 | 0.0067 | 0.0137 |
| X 1T & Over 4.5 cartellini | 0.4095 | 0.4098 | +0.00034 ± 0.00274 | 0.0368 | 0.0256 |
| Under 2.5 gol & Under 9.5 corner | 0.5120 | 0.5123 | +0.00030 ± 0.00212 | 0.0218 | 0.0144 |
| 1 & 2 corner | 0.4718 | 0.4641 | -0.00776 ± 0.00728 | 0.0483 | 0.0466 |
| 2 & 1 corner | 0.4408 | 0.4452 | +0.00438 ± 0.00481 | 0.0557 | 0.0614 |
| 1X2 | 1.0020 | 1.0081 | +0.00606 ± 0.00899 | 0.0185 | 0.0209 |
| Over 2.5 gol | 0.6658 | 0.6667 | +0.00085 ± 0.00180 | 0.0239 | 0.0159 |
| Over 1.5 gol | 0.5141 | 0.5153 | +0.00122 ± 0.00299 | 0.0217 | 0.0269 |
| Over 3.5 gol | 0.5932 | 0.5940 | +0.00082 ± 0.00174 | 0.0115 | 0.0068 |
| Goal | 0.6767 | 0.6729 | -0.00380 ± 0.00813 | 0.0082 | 0.0248 |

Tempo medio per partita (Simulatore reale con dati): 10.2 s.
