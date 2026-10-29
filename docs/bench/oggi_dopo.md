# «Analizza tutte»: tempi DOPO la fase V (29/10/2026)

Confronto con `oggi_prima.md`. Giornata fissa di 13 partite, 30.000 simulazioni per partita, nessun credito The Odds API.

## Prima / dopo

Numeri **su rete reale**, misurati il 29/10/2026 con `python -m tools.bench_oggi` (Serie A, Premier League, La Liga,
Bundesliga, 24-26/10/2026): non rifatti in questa consegna.

| 13 partite, 4 campionati | Prima | Dopo | Come |
|---|---|---|---|
| Cache vuota | ≈ 73 min (stima: 13 × 336,7 s) | **38,4 s** | ClubElo bloccato + letture una volta per campionato |
| Cache calda | ≈ 71 min (stima: 13 × 328,1 s) | **6,5 s** | idem; 5 s sono la simulazione |
| Richieste a ClubElo | 1.430 | **1** (0 a cache calda) | il blocco si segna per la giornata |
| football-data.co.uk, cache vuota: richieste / hit | 25 / 180 | 25 / 0 | un CSV per campionato e stagione |
| football-data.co.uk, cache calda: richieste / hit | 0 / 205 | 0 / 25 | idem |
| Understat, cache vuota: richieste / hit | 8 / 96 | 8 / 0 | una lettura per campionato |
| Understat, cache calda: richieste / hit | 0 / 104 | 0 / 8 | idem |

Con ClubElo escluso dal «prima» (misura 13 partite in `oggi_prima.md`) il tempo era 47,4 s a cache vuota e 18,8 s a
cache calda: anche senza il problema ClubElo, le letture ripetute pesavano (a cache calda 18,8 s → 6,5 s).

## Come si legge il risultato
- **ClubElo bloccato:** `clubelo.com` risponde 403 con Cloudflare e `api.clubelo.com` 502. Non si aggira. Il blocco
  si segna «non disponibile» per la giornata nella cache: niente altre richieste fino al giorno dopo.
- **Elo da risultati:** per le partite di campionato l'Elo si calcola da 6 stagioni di CSV e la scheda dichiara
  «Elo da risultati (ClubElo non disponibile)». Per le coppe tra campionati diversi resta MANCANTE (riga nella tabella
  «Partite non analizzate»: inseriscilo a mano nel blocco CASA/OSPITE).
- **Niente parallelismo:** scelta voluta. Le pause `MIN_INTERVAL` restano per fonte e a cache calda non servono.

## Misura offline con le risposte salvate (`--offline`, riproducibile senza rete)

`python -m tools.bench_oggi --offline`: 13 partite di Serie A e Primeira Liga più una coppa tra campionati diversi
(Napoli - Porto, Elo mancante), ClubElo bloccato (403), risposte da `tests/fixtures/sources`. Le pause
`MIN_INTERVAL` sono vere (1 s per richiesta a football-data.co.uk, 3 s per Understat): a cache vuota il tempo è
soprattutto attesa. **Non è rete reale:** i numeri in alto restano quelli di riferimento.

| Passata | Totale | Richieste HTTP | Hit di cache |
|---|---|---|---|
| Analizza tutte · cache vuota | 21.7 s | 20 | 0 |
| Analizza tutte · cache calda | 4.9 s | 0 | 19 |
| Prepara la giornata · cache vuota | 18.2 s | 20 | 0 |
| Analizza tutte · dopo Prepara | 5.0 s | 0 | 19 |

Dettaglio per fase, fonte e partita:

### Analizza tutte · cache vuota: 21.7 s per 13 partite

| Fase | Secondi | Richieste HTTP | Hit di cache |
|---|---|---|---|
| ricerca del campionato | 4.05 |  |  |
| statistiche squadre (CSV e Understat) | 5.27 |  |  |
| forza Dixon-Coles | 0.03 |  |  |
| Elo ClubElo | 7.04 |  |  |
| arbitro | 0.03 |  |  |
| quote dal calendario | 0.99 |  |  |
| dati automatici (totale) | 17.42 |  |  |
| blocco e configurazione | 0.04 |  |  |
| simulazione | 4.23 |  |  |
| fonte: clubelo | 0.00 | 1 | 0 |
| fonte: football-data.co.uk | 13.67 | 17 | 0 |
| fonte: understat | 3.00 | 2 | 0 |

| Fonte | Richieste HTTP | Hit di cache | Errori |
|---|---|---|---|
| clubelo | 1 | 0 | 1 |
| football-data.co.uk | 17 | 0 | 0 |
| understat | 2 | 0 | 0 |

| Partita | Secondi | Esito |
|---|---|---|
| Napoli - Roma | 8.48 | simulata |
| Lazio - Parma | 0.31 | simulata |
| Inter - Fiorentina | 0.28 | simulata |
| Genoa - Venezia | 0.45 | simulata |
| Milan - Udinese | 0.32 | simulata |
| Juventus - Lecce | 0.40 | simulata |
| Atalanta - Frosinone | 0.40 | simulata |
| Bologna - Cagliari | 0.43 | simulata |
| Como - Sassuolo | 0.38 | simulata |
| Torino - Monza | 0.41 | simulata |
| Porto - Benfica | 9.43 | simulata |
| Sp Braga - Estoril | 0.38 | simulata |
| Napoli - Porto | 0.03 | non analizzata: Elo da risultati · Elo MANCANTE: inseriscilo a mano nel blocco CASA/OSPITE |

### Analizza tutte · cache calda: 4.9 s per 13 partite

| Fase | Secondi | Richieste HTTP | Hit di cache |
|---|---|---|---|
| ricerca del campionato | 0.10 |  |  |
| statistiche squadre (CSV e Understat) | 0.32 |  |  |
| forza Dixon-Coles | 0.03 |  |  |
| Elo ClubElo | 0.18 |  |  |
| arbitro | 0.03 |  |  |
| quote dal calendario | 0.02 |  |  |
| dati automatici (totale) | 0.68 |  |  |
| blocco e configurazione | 0.04 |  |  |
| simulazione | 4.23 |  |  |
| fonte: football-data.co.uk | 0.00 | 0 | 17 |
| fonte: understat | 0.00 | 0 | 2 |

| Fonte | Richieste HTTP | Hit di cache | Errori |
|---|---|---|---|
| football-data.co.uk | 0 | 17 | 0 |
| understat | 0 | 2 | 0 |

| Partita | Secondi | Esito |
|---|---|---|
| Napoli - Roma | 0.55 | simulata |
| Lazio - Parma | 0.30 | simulata |
| Inter - Fiorentina | 0.26 | simulata |
| Genoa - Venezia | 0.46 | simulata |
| Milan - Udinese | 0.32 | simulata |
| Juventus - Lecce | 0.40 | simulata |
| Atalanta - Frosinone | 0.40 | simulata |
| Bologna - Cagliari | 0.44 | simulata |
| Como - Sassuolo | 0.38 | simulata |
| Torino - Monza | 0.45 | simulata |
| Porto - Benfica | 0.61 | simulata |
| Sp Braga - Estoril | 0.38 | simulata |
| Napoli - Porto | 0.03 | non analizzata: Elo da risultati · Elo MANCANTE: inseriscilo a mano nel blocco CASA/OSPITE |

### Prepara la giornata · cache vuota: 18.2 s per 13 partite

| Fase | Secondi | Richieste HTTP | Hit di cache |
|---|---|---|---|
| ricerca del campionato | 4.79 |  |  |
| statistiche squadre (CSV e Understat) | 5.26 |  |  |
| forza Dixon-Coles | 0.03 |  |  |
| Elo ClubElo | 7.05 |  |  |
| arbitro | 0.02 |  |  |
| quote dal calendario | 0.99 |  |  |
| dati automatici (totale) | 18.14 |  |  |
| blocco e configurazione | 0.03 |  |  |
| fonte: clubelo | 0.00 | 1 | 0 |
| fonte: football-data.co.uk | 14.46 | 17 | 0 |
| fonte: understat | 3.00 | 2 | 0 |

| Fonte | Richieste HTTP | Hit di cache | Errori |
|---|---|---|---|
| clubelo | 1 | 0 | 1 |
| football-data.co.uk | 17 | 0 | 0 |
| understat | 2 | 0 | 0 |

| Partita | Secondi | Esito |
|---|---|---|
| Napoli - Roma | 8.09 | preparata |
| Lazio - Parma | 0.03 | preparata |
| Inter - Fiorentina | 0.03 | preparata |
| Genoa - Venezia | 0.03 | preparata |
| Milan - Udinese | 0.03 | preparata |
| Juventus - Lecce | 0.03 | preparata |
| Atalanta - Frosinone | 0.03 | preparata |
| Bologna - Cagliari | 0.03 | preparata |
| Como - Sassuolo | 0.03 | preparata |
| Torino - Monza | 0.03 | preparata |
| Porto - Benfica | 9.79 | preparata |
| Sp Braga - Estoril | 0.03 | preparata |
| Napoli - Porto | 0.02 | non analizzata: Elo da risultati · Elo MANCANTE: inseriscilo a mano nel blocco CASA/OSPITE |

### Analizza tutte · dopo Prepara: 5.0 s per 13 partite

| Fase | Secondi | Richieste HTTP | Hit di cache |
|---|---|---|---|
| ricerca del campionato | 0.09 |  |  |
| statistiche squadre (CSV e Understat) | 0.32 |  |  |
| forza Dixon-Coles | 0.03 |  |  |
| Elo ClubElo | 0.17 |  |  |
| arbitro | 0.03 |  |  |
| quote dal calendario | 0.02 |  |  |
| dati automatici (totale) | 0.67 |  |  |
| blocco e configurazione | 0.04 |  |  |
| simulazione | 4.28 |  |  |
| fonte: football-data.co.uk | 0.00 | 0 | 17 |
| fonte: understat | 0.00 | 0 | 2 |

| Fonte | Richieste HTTP | Hit di cache | Errori |
|---|---|---|---|
| football-data.co.uk | 0 | 17 | 0 |
| understat | 0 | 2 | 0 |

| Partita | Secondi | Esito |
|---|---|---|
| Napoli - Roma | 0.55 | simulata |
| Lazio - Parma | 0.29 | simulata |
| Inter - Fiorentina | 0.28 | simulata |
| Genoa - Venezia | 0.40 | simulata |
| Milan - Udinese | 0.29 | simulata |
| Juventus - Lecce | 0.40 | simulata |
| Atalanta - Frosinone | 0.51 | simulata |
| Bologna - Cagliari | 0.45 | simulata |
| Como - Sassuolo | 0.39 | simulata |
| Torino - Monza | 0.44 | simulata |
| Porto - Benfica | 0.57 | simulata |
| Sp Braga - Estoril | 0.38 | simulata |
| Napoli - Porto | 0.03 | non analizzata: Elo da risultati · Elo MANCANTE: inseriscilo a mano nel blocco CASA/OSPITE |

