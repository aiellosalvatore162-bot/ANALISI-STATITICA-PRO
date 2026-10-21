# Analisi avversari simili: validazione

Generato il 21/10/2026 con `python -m tools.tactical`. Serie A, Premier League, Liga e Bundesliga (Understat + football-data.co.uk). Per ogni partita: le 10 partite di ciascuna squadra negli ultimi 2 anni contro gli avversari più simili all'avversario di oggi (profilo al momento della partita su 10 metriche + Elo; emivita 1 anno), rendimento rispetto alla media delle 20 gare precedenti, shrinkage verso 1 con forza τ, limiti 0.85-1.15 (gol, primo tempo) e 0.80-1.20 (corner, cartellini).

Partite valutate: 3105; con partite simili: 3056 (in media 9.74 per squadra).

## τ scelto sulle stagioni di taratura e decisione

| Correzione | τ | Fattori (5°/50°/95° percentile) | Attiva |
|---|---|---|---|
| Gol (λ, μ) | 500 | lambda 0.994/1.000/1.004; mu 0.995/1.000/1.004 | no |
| Gol, solo rapporto di forza | 500 | lambda_supremacy 0.994/1.000/1.004; mu_supremacy 0.995/1.000/1.004 | no |
| Quota primo tempo | 200 | first_half 0.984/0.999/1.012 | no |
| Corner | 500 | corners_home 0.995/1.000/1.004; corners_away 0.995/1.000/1.004 | no |
| Cartellini | 50 | cards 0.951/0.996/1.036 | **sì** |

Regola: attiva solo se riduce il log-loss su tutti i mercati del gruppo, sia nelle stagioni di taratura sia in quella in corso, sia con il solo modello sia con l'ancoraggio al mercato.

Lettura: un τ pari al massimo della griglia (500) rende i fattori quasi uguali a 1 (5°-95° percentile tra 0.99 e
1.01): sulle stagioni di taratura i dati preferiscono nessuna correzione, cioè le partite contro avversari simili
non aggiungono informazione stabile a quella già contenuta nelle medie della squadra. L'unica correzione con un
effetto stabile è quella dei cartellini.

## taratura 2024-25/2025-26 · solo modello

| Mercato | Senza correzione | Gol | Gol, solo rapporto di forza | Primo tempo | Corner | Cartellini |
|---|---|---|---|---|---|---|
| 1X2 | 0.98556 | 0.98545 ✓ | 0.98546 ✓ | 0.98556 | 0.98556 | 0.98556 |
| Over/Under 2.5 | 0.68056 | 0.68063 | 0.68063 | 0.68056 | 0.68056 | 0.68056 |
| Multigol | 0.62777 | 0.62780 | 0.62780 | 0.62777 | 0.62777 | 0.62777 |
| Primo tempo | 0.68845 | 0.68843 ✓ | 0.68846 | 0.68842 ✓ | 0.68845 | 0.68845 |
| Corner | 3.29574 | 3.29574 | 3.29574 | 3.29574 | 3.29580 | 3.29574 |
| Cartellini | 2.76212 | 2.76212 | 2.76212 | 2.76212 | 2.76212 | 2.75763 ✓ |

Log-loss medio (corner e cartellini: log-verosimiglianza negativa del totale + log-loss medio delle linee Over/Under). ✓ = migliore che senza correzione.

## taratura 2024-25/2025-26 · ancorato al mercato

| Mercato | Senza correzione | Gol | Gol, solo rapporto di forza | Primo tempo | Corner | Cartellini |
|---|---|---|---|---|---|---|
| 1X2 | 0.96917 | 0.96916 ✓ | 0.96916 ✓ | 0.96917 | 0.96917 | 0.96917 |
| Over/Under 2.5 | 0.67023 | 0.67023 | 0.67023 | 0.67023 | 0.67023 | 0.67023 |
| Multigol | 0.62414 | 0.62414 | 0.62414 | 0.62414 | 0.62414 | 0.62414 |
| Primo tempo | 0.68081 | 0.68081 ✓ | 0.68081 | 0.68083 | 0.68081 | 0.68081 |
| Corner | 3.29574 | 3.29574 | 3.29574 | 3.29574 | 3.29580 | 3.29574 |
| Cartellini | 2.76212 | 2.76212 | 2.76212 | 2.76212 | 2.76212 | 2.75763 ✓ |

Log-loss medio (corner e cartellini: log-verosimiglianza negativa del totale + log-loss medio delle linee Over/Under). ✓ = migliore che senza correzione.

## fuori campione 2026-27 · solo modello

| Mercato | Senza correzione | Gol | Gol, solo rapporto di forza | Primo tempo | Corner | Cartellini |
|---|---|---|---|---|---|---|
| 1X2 | 0.94332 | 0.94305 ✓ | 0.94314 ✓ | 0.94332 | 0.94332 | 0.94332 |
| Over/Under 2.5 | 0.65769 | 0.65769 ✓ | 0.65766 ✓ | 0.65769 | 0.65769 | 0.65769 |
| Multigol | 0.64268 | 0.64266 ✓ | 0.64265 ✓ | 0.64268 | 0.64268 | 0.64268 |
| Primo tempo | 0.69067 | 0.69066 ✓ | 0.69061 ✓ | 0.69037 ✓ | 0.69067 | 0.69067 |
| Corner | 3.34572 | 3.34572 | 3.34572 | 3.34572 | 3.34490 ✓ | 3.34572 |
| Cartellini | 2.71202 | 2.71202 | 2.71202 | 2.71202 | 2.71202 | 2.70667 ✓ |

Log-loss medio (corner e cartellini: log-verosimiglianza negativa del totale + log-loss medio delle linee Over/Under). ✓ = migliore che senza correzione.

## fuori campione 2026-27 · ancorato al mercato

| Mercato | Senza correzione | Gol | Gol, solo rapporto di forza | Primo tempo | Corner | Cartellini |
|---|---|---|---|---|---|---|
| 1X2 | 0.93410 | 0.93408 ✓ | 0.93409 ✓ | 0.93410 | 0.93410 | 0.93410 |
| Over/Under 2.5 | 0.63896 | 0.63897 | 0.63896 ✓ | 0.63896 | 0.63896 | 0.63896 |
| Multigol | 0.63164 | 0.63164 ✓ | 0.63164 ✓ | 0.63164 | 0.63164 | 0.63164 |
| Primo tempo | 0.68308 | 0.68309 | 0.68308 ✓ | 0.68285 ✓ | 0.68308 | 0.68308 |
| Corner | 3.34572 | 3.34572 | 3.34572 | 3.34572 | 3.34490 ✓ | 3.34572 |
| Cartellini | 2.71202 | 2.71202 | 2.71202 | 2.71202 | 2.71202 | 2.70667 ✓ |

Log-loss medio (corner e cartellini: log-verosimiglianza negativa del totale + log-loss medio delle linee Over/Under). ✓ = migliore che senza correzione.

