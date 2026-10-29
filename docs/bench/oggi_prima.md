# «Analizza tutte»: tempi PRIMA della fase V (29/10/2026)

Misure con `python -m tools.bench_oggi` sul Codespace, giornata fissa di 13 partite (Serie A, Premier League,
La Liga, Bundesliga, 24-26/10/2026), 30.000 simulazioni per partita, nessuna quota The Odds API.

**Stato delle fonti al 29/10/2026:** `clubelo.com` risponde **403** con la verifica Cloudflare («Just a moment…»)
a ogni pagina, anche a robots.txt; `api.clubelo.com/AAAA-MM-GG` risponde **502**. Nessun aggiramento tentato.
Con ClubElo non disponibile il codice attuale ripete per ogni ricerca le 55 pagine del catalogo (6 principali +
49 di altri paesi), ognuna con la pausa di 3 s, e i rifiuti non vanno in cache: 110 richieste a partita anche a
cache calda. L'Elo finisce poi nel ripiego «calcolato dai risultati» (6 stagioni di CSV).

## Riepilogo

| Misura | Cache vuota | Cache calda |
|---|---|---|
| 1 partita, ClubElo come oggi (misurato) | 336,7 s | 328,1 s |
| 13 partite, ClubElo come oggi (stima: 13 × misura) | ≈ 73 min | ≈ 71 min |
| 13 partite, ClubElo escluso senza richieste (misurato) | 47,4 s | 18,8 s |
| Richieste ClubElo per 13 partite | 1.430 | 1.430 |

Il resto del percorso (CSV, Understat, forza Dixon-Coles, ripiego Elo, simulazione) vale circa 47 s a cache vuota
e 19 s a cache calda: quasi tutto il tempo attuale è nelle richieste ClubElo rifiutate.

## Misura 1: una partita con ClubElo come oggi

### Cache vuota: 336.7 s per 1 partite

| Fase | Secondi | Richieste HTTP | Hit di cache |
|---|---|---|---|
| ricerca del campionato | 0.23 |  |  |
| statistiche squadre (CSV e Understat) | 4.53 |  |  |
| forza Dixon-Coles | 0.09 |  |  |
| Elo ClubElo | 330.59 |  |  |
| arbitro | 0.00 |  |  |
| quote dal calendario | 0.66 |  |  |
| dati automatici (totale) | 336.11 |  |  |
| simulazione | 0.56 |  |  |
| fonte: clubelo | 326.85 | 110 | 0 |
| fonte: football-data.co.uk | 4.99 | 7 | 6 |
| fonte: understat | 3.44 | 2 | 6 |

| Partita | Secondi | Esito |
|---|---|---|
| Napoli - Roma | 336.68 | simulata |

### Cache calda: 328.1 s per 1 partite

| Fase | Secondi | Richieste HTTP | Hit di cache |
|---|---|---|---|
| ricerca del campionato | 0.04 |  |  |
| statistiche squadre (CSV e Understat) | 0.29 |  |  |
| forza Dixon-Coles | 0.16 |  |  |
| Elo ClubElo | 327.22 |  |  |
| arbitro | 0.00 |  |  |
| quote dal calendario | 0.01 |  |  |
| dati automatici (totale) | 327.72 |  |  |
| simulazione | 0.41 |  |  |
| fonte: clubelo | 326.88 | 110 | 0 |
| fonte: football-data.co.uk | 0.00 | 0 | 13 |
| fonte: understat | 0.00 | 0 | 8 |

| Partita | Secondi | Esito |
|---|---|---|
| Napoli - Roma | 328.13 | simulata |


## Misura 2: 13 partite con ClubElo escluso (nessuna richiesta a clubelo.com)

### Cache vuota: 47.4 s per 13 partite

| Fase | Secondi | Richieste HTTP | Hit di cache |
|---|---|---|---|
| ricerca del campionato | 2.01 |  |  |
| statistiche squadre (CSV e Understat) | 20.67 |  |  |
| forza Dixon-Coles | 1.69 |  |  |
| Elo ClubElo | 15.50 |  |  |
| arbitro | 0.05 |  |  |
| quote dal calendario | 1.30 |  |  |
| dati automatici (totale) | 41.23 |  |  |
| simulazione | 6.09 |  |  |
| fonte: clubelo | 0.01 | 1430 | 0 |
| fonte: football-data.co.uk | 18.23 | 25 | 180 |
| fonte: understat | 13.78 | 8 | 96 |

| Partita | Secondi | Esito |
|---|---|---|
| Napoli - Roma | 10.00 | simulata |
| Lazio - Parma | 1.02 | simulata |
| Inter - Fiorentina | 0.89 | simulata |
| Genoa - Venezia | 1.17 | simulata |
| Arsenal - Everton | 8.90 | simulata |
| Chelsea - Tottenham | 1.11 | simulata |
| Liverpool - Brighton | 1.01 | simulata |
| Barcelona - Real Madrid | 9.09 | simulata |
| Valencia - Villarreal | 1.07 | simulata |
| Celta - Betis | 1.00 | simulata |
| Dortmund - Ein Frankfurt | 9.12 | simulata |
| Freiburg - Bayern Munich | 1.55 | simulata |
| Hoffenheim - Leverkusen | 1.44 | simulata |

### Cache calda: 18.8 s per 13 partite

| Fase | Secondi | Richieste HTTP | Hit di cache |
|---|---|---|---|
| ricerca del campionato | 1.70 |  |  |
| statistiche squadre (CSV e Understat) | 3.49 |  |  |
| forza Dixon-Coles | 2.17 |  |  |
| Elo ClubElo | 3.60 |  |  |
| arbitro | 0.07 |  |  |
| quote dal calendario | 0.23 |  |  |
| dati automatici (totale) | 11.26 |  |  |
| simulazione | 7.49 |  |  |
| fonte: clubelo | 0.01 | 1430 | 0 |
| fonte: football-data.co.uk | 0.00 | 0 | 205 |
| fonte: understat | 0.00 | 0 | 104 |

| Partita | Secondi | Esito |
|---|---|---|
| Napoli - Roma | 1.47 | simulata |
| Lazio - Parma | 1.34 | simulata |
| Inter - Fiorentina | 1.21 | simulata |
| Genoa - Venezia | 1.27 | simulata |
| Arsenal - Everton | 1.38 | simulata |
| Chelsea - Tottenham | 1.47 | simulata |
| Liverpool - Brighton | 1.64 | simulata |
| Barcelona - Real Madrid | 1.37 | simulata |
| Valencia - Villarreal | 1.56 | simulata |
| Celta - Betis | 1.38 | simulata |
| Dortmund - Ein Frankfurt | 1.46 | simulata |
| Freiburg - Bayern Munich | 1.64 | simulata |
| Hoffenheim - Leverkusen | 1.64 | simulata |

