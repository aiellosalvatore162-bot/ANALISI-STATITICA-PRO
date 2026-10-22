# Simulatore-IA: motore on-demand

Applicazione Streamlit per analizzare una singola partita a partire da un
blocco di testo dichiarato dall'utente. Non usa calendari, database, seed
automatici, quote sintetiche o report narrativi preconfezionati.

## Avvio

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Modello storico gratuito

Il **Backtest storico gratuito** è facoltativo e non cambia il motore manuale né
l'input predefinito. Non richiede API key né servizi a pagamento. Puoi caricare
CSV locali; la previsione remota invece parte automaticamente quando incolli o
modifichi un blocco valido. Associa i nomi alla lega pubblica, scarica i CSV di
[Football-Data.co.uk](https://www.football-data.co.uk/data.php) e li cachea per
24 ore nell'app. Non richiede selezione manuale di lega, squadre o pulsante di
avvio; le righe storiche grezze non vengono aggiunte al risultato.

Il loader accetta colonne standard `Date`, `HomeTeam`, `AwayTeam`, `FTHG`,
`FTAG`, `Div`, `Season`, le quote `B365H/B365D/B365A` (o `PSH/PSD/PSA`) e,
facoltativamente, corner `HC/AC` e gialli `HY/AY`. `Season` può essere una
colonna; se manca, il nome del file deve contenere la stagione, ad esempio
`E0_2020-21.csv`. Occorrono almeno tre stagioni per lega.

Il backtest allena Dixon-Coles sulle stagioni precedenti, calibra la temperatura
sulla stagione validation e valuta la successiva, ripetendo il processo in
ordine cronologico. Riporta log-loss, Brier, RPS, ECE, quote senza margine e un
intervallo bootstrap appaiato per giornata. Corner e gialli mostrano un semplice
baseline di media storica, non una validazione completa del modello manuale.

**Prova previsione storica candidata** allena solo su risultati precedenti alla
data corrente e restituisce probabilità 1X2 e scoreline calibrati. Il lookup
usa automaticamente i nomi CASA/OSPITE del parser. La previsione ibrida miscela
la matrice storica con quella costruita dai dati manuali, mantenendo 1X2 e
mercati score-dependent coerenti. I dati manuali hanno sempre la maggioranza:
`75%` nella UI e almeno `51%` nell'API. Il peso **non è calibrato su input
storici equivalenti**: il confronto tra storico, manuale e miscela non dimostra
un miglioramento predittivo.

Se il download fallisce, mancano stagioni sufficienti o una squadra non compare
nella lega scelta, il candidato remoto ricade automaticamente al `100%` manuale
con un avviso. Non assegna alla squadra sconosciuta una forza media di lega e
non blocca la simulazione manuale.

La temperatura di calibrazione usa solo l'ultima stagione conclusa con almeno
60 partite; una stagione in corso viene esclusa. Se lo storico non offre un
campione sufficiente, viene usata temperatura neutra e l'interfaccia lo indica.
Il pannello mostra separatamente le componenti storiche, manuali e miscelate di
corner e gialli.

Per corner e gialli la stima candidata miscela medie per squadra delle ultime
10 gare con i valori manuali e applica una distribuzione Poisson. Non modella
ancora la dipendenza dal punteggio, gli infortuni o l'effetto partita sulle
statistiche disciplinari; i relativi baseline del backtest sono diagnostici.

## Dati automatici

La modalità **Dati automatici** compila il blocco di input da fonti gratuite,
nel formato attuale del parser; sotto ogni riga squadra un commento `# Fonti:`
(ignorato dal parser) riporta fonte, data di aggiornamento e ultima partita
inclusa di ogni valore, e una tabella li mostra con gli avvisi. Il blocco resta
modificabile a mano.

| Fonte | Stato (21/10/2026) | Cosa fornisce |
|---|---|---|
| ClubElo | API `api.clubelo.com` in errore 502; pagine `clubelo.com/<Squadra>` funzionanti | Elo pre-partita dallo storico datato (tutte le squadre europee) |
| Understat | funzionante (`getLeagueData`) | xG, xGA, PPDA, deep completions dei 5 campionati top |
| football-data.co.uk | funzionante | risultati, quote, corner, cartellini, falli, primo tempo, calendario con quote; arbitri solo Premier League |
| football-data.org | richiede `FOOTBALL_DATA_KEY` in `st.secrets` (saltata se manca) | calendario e Champions League |
| FBref | 403, accesso bloccato (soccerdata richiede Chrome; libreria non installata) | non usata |

- Statistiche per squadra separate casa/trasferta sulle ultime N gare (default
  10) pesate per recenza (emivita configurabile); i valori nel blocco sono
  riportati alla media generale della lega per non contare due volte il
  vantaggio casa. Per le squadre di coppa si usano i dati del campionato
  nazionale e l'Elo ClubElo come confronto tra campionati.
- Arbitro: gialli e falli medi di campionato avvicinati alla media della
  competizione con peso 10 partite; sotto 10 partite il dato è segnalato come
  poco affidabile. Coppe europee: nessuna fonte gratuita con gli arbitri.
- Cache SQLite in `data/cache/sources.sqlite` con pausa minima tra richieste;
  se una fonte non risponde si usa l'ultimo dato in cache con un avviso.
- I dati più vecchi della soglia (24 ore, configurabile) vengono riscaricati
  quando si seleziona o si crea una partita; **Aggiorna dati** forza il
  download. L'aggiornamento avviene solo all'apertura o alla selezione (su
  Streamlit Cloud l'app si addormenta). Un avviso segnala se ClubElo conosce
  una partita più recente dell'ultima inclusa nelle statistiche.

La modalità **Crea partita** compila i campi disponibili per due squadre
qualsiasi, lascia vuoti ed evidenziati quelli mancanti, accetta un blocco
incollato, controlla la plausibilità (es. xG 25 invece di 2.5, Elo fuori range,
quote sotto 1.01) e salva la partita nel database come «inserita manualmente».

## Profili di stile

La scheda **Stile** dei risultati mostra il radar delle due squadre
(percentile nel proprio campionato), l'archetipo e una breve descrizione.

| Metrica | Fonte |
|---|---|
| Intensità del pressing | Understat (PPDA) |
| Altezza del blocco (derivato: pressing e ingressi concessi vicino all'area) | Understat |
| Manovra vs gioco diretto (derivato dal PPDA concesso) | Understat |
| Pericolosità in transizione (quota di xG da azioni veloci) | Understat, endpoint squadra |
| Pericolosità sui piazzati (quota di xG da corner e punizioni) | Understat, endpoint squadra |
| xG fatti/subiti, tiri, corner prodotti/concessi, falli, cartellini, quota di gol nel primo tempo | football-data.co.uk (xG anche da Understat) |

Esclusi perché nessuna fonte gratuita funzionante li fornisce: **possesso** e
**uso delle fasce/cross**. Le metriche sono medie delle ultime 20 gare di
campionato, normalizzate con z-score per campionato. Le squadre di Portogallo,
Olanda, Belgio, Turchia, Grecia e Scozia hanno un **profilo parziale** (solo
football-data.co.uk); gli stessi CSV compilano anche il loro blocco di input.

Gli archetipi (`config/style_archetypes.json`, rigenerati con
`python -m tools.style`) vengono da k-means sulle 7 metriche di comportamento
(pressing, blocco, manovra, transizioni, piazzati, falli, cartellini) delle 96
squadre dei 5 campionati top; il numero di gruppi è quello con la silhouette
più alta tra 2 e 8 (k = 4, silhouette 0.187: struttura debole, gli stili
sfumano l'uno nell'altro).

| Archetipo | Squadre | Esempi |
|---|---|---|
| Forza sui piazzati e blocco basso | 16 | Angers, Betis, Bologna, Brest |
| Difesa alta e possesso manovrato | 24 | Arsenal, Ath Bilbao, Ath Madrid, Barcelona |
| Gioco fisico e molti cartellini | 30 | Alaves, Bournemouth, Brentford, Dortmund |
| Attesa senza pressing e transizioni veloci | 26 | Aston Villa, Atalanta, Augsburg, Auxerre |

I profili sono salvati nella cache SQLite e scadono con la stessa soglia dei
dati; «Aggiorna dati» li invalida.

## Scenario tattico (avversari simili)

Il riquadro **Scenario tattico** cerca, per ciascuna squadra, le 10 partite
degli ultimi 2 anni contro gli avversari più simili a quello di oggi: distanza
sul profilo di stile continuo al momento di ogni partita (pressing, blocco,
manovra, xG fatti/subiti, corner pro/contro, falli, cartellini, tiri; z-score
nel proprio campionato) più l'Elo, con più peso alle partite recenti. Non usa
l'etichetta dell'archetipo. Per ogni partita trovata calcola il rendimento
rispetto alla media della squadra (xG, gol, gol nel primo tempo, corner,
cartellini, falli) e ne ricava fattori con shrinkage bayesiano verso 1
(limiti 0.85-1.15 per i gol, 0.80-1.20 per corner e cartellini); con un
profilo parziale lo shrinkage è più forte. Mostra partite, fattori, numero di
partite e di metriche usate e una frase riassuntiva.

Le correzioni (gol prima della combinazione con il mercato, solo rapporto di
forza, quota del primo tempo, corner, cartellini) si attivano una per una;
di default sono accese solo quelle validate da `python -m tools.tactical`
su stagioni intere (risultati in [`docs/STILI.md`](./docs/STILI.md), interruttori
nella sezione `scenario_tattico` di `config/goal_model.json`).

## Analisi con Claude (copia e incolla, senza API)

Dopo la simulazione, **Prepara analisi per Claude** genera un testo da copiare
(pulsante di copia del riquadro) con: istruzioni per verificare sul web
formazioni, assenze, squalifiche, turnover, arbitro designato e sue medie,
motivazioni, meteo e incoerenze con gli input; il blocco di input con fonti e
date; le probabilità principali e i gol attesi solo-mercato, solo-modello e
finali; il formato di risposta:

```
CORREZIONI_CLAUDE:
gol_casa: 0.95 | motivo: ... | fonte: https://...
gol_ospite: 1.05 | motivo: ... | fonte: https://...
corner: 1.00 | motivo: ... | fonte: https://...
cartellini: 1.10 | motivo: ... | fonte: https://...
arbitro_gialli_medi: 4.6 | partite: 23 | fonte: https://...
confidenza: media
commento: ...
```

La risposta incollata viene letta da `claude_bridge.py`: limiti gol e corner
0.90-1.10, cartellini 0.85-1.15; ogni correzione diversa da 1 senza un link come
fonte viene ignorata; la media gialli dell'arbitro (con fonte e numero di
partite) sostituisce quella del blocco con lo stesso shrinkage della fase D. Le
correzioni sui gol si applicano dopo l'ancoraggio al mercato. Un interruttore
le applica e mostra il confronto prima/dopo; la probabilità con le correzioni
finisce nella colonna `Prob_Claude` del registro delle previsioni.

In **Crea partita**, **Prepara estrazione dati per Claude** genera le istruzioni
per trasformare il testo copiato da un sito nel blocco del parser; il blocco
restituito si incolla nel campo apposito e passa dal controllo di plausibilità.

## Registro delle previsioni e pagina Prestazioni

Dopo una simulazione, la sezione **Registro delle previsioni** salva una riga per
selezione con le colonne A–S del file `Registro_Previsioni.xlsx` (modello in
`tests/fixtures/`): `ID, Data, Ora, Competizione, Partita, Mercato, Selezione,
Prob_finale, Prob_mercato, Prob_modello, Prob_stile, Prob_Claude, Quota_presa,
Puntata, Tipo, Versione_modello, Quota_chiusura, Esito, Note`.

- Probabilità in decimali (0,62 = 62%). `Prob_mercato` è la simulazione con le
  sole quote, `Prob_modello` il solo modello, `Prob_stile` la simulazione con lo
  scenario tattico attivo, `Prob_Claude` quella con le correzioni di Claude;
  `Prob_finale` è l'ultima disponibile.
- `Mercato` usa sempre i 19 nomi della tabella «per mercato» del Riepilogo:
  1X2, Doppia chance, DNB, Over 1.5, Under 1.5, Over 2.5, Under 2.5, Over 3.5,
  Under 3.5, Goal/NoGoal, Multigol (totale), Multigol casa, Multigol ospite,
  Primo tempo (1X2 del primo tempo), Over 0.5 1T, Over 1.5 1T, Corner,
  Cartellini, Combo. Le linee senza nome (es. Over 4.5, Goal 1T) non sono
  registrabili. Per il DNB la probabilità è condizionata al non rimborso; con il
  pareggio la riga resta senza Esito (annotata «rimborsata») ed è esclusa dalle
  misure.
- Cartellini: il modello e gli esiti automatici contano i soli gialli; le righe
  Cartellini lo ricordano in `Note`. Il regolamento Eurobet (rossi contati o no,
  con quale peso) non è stato verificato: controllalo prima di giocare.
- `ID` = data + partita + mercato + selezione: salvare di nuovo la stessa
  selezione aggiorna la riga. **Scarica registro Excel** dà le righe della
  sessione, pronte da incollare nel foglio Registro.

La pagina **Prestazioni** (barra laterale) legge il tuo file (solo colonne A–S,
le colonne grigie si ricalcolano) e mostra: giudizio per mercato (vantaggio
dimostrato con almeno 100 selezioni con esito e CLV medio positivo),
calibrazione per fasce, Brier e log-loss nel tempo, CLV medio per mercato, ROI e
saldo separati per Reale e A carta, confronto delle componenti (mercato,
modello, stile, Claude) sulle stesse selezioni. **Cerca esiti e quote di
chiusura** compila solo le celle vuote da football-data.co.uk (esiti di tutti i
mercati registrabili, primo tempo dal risultato al 45'; quote medie di chiusura per 1X2 e Over/Under 2.5), annota
fonte e data in `Note` e permette di scaricare il file aggiornato con formule e
fogli intatti. Coppe (Champions League) e campionati non coperti restano da
compilare a mano.

## Input

```text
CASA: Inter | Quota 1: 1.85
Attacco: 1.34 | Difesa: 1.25 | Elo: 1835 | Forma: W-W-D-W-W | xG Fatti: 2.15 | xG Subiti: 0.85 | Corner pro/sub: 5.8/4.2 | Cartellini pro: 1.60

OSPITE: Milan | Quota X: 3.40 | Quota 2: 4.20
Attacco: 1.22 | Difesa: 1.10 | Elo: 1765 | Forma: W-W-L-D-W | xG Fatti: 1.85 | xG Subiti: 1.10 | Corner pro/sub: 5.1/4.8 | Cartellini pro: 1.85

ARBITRO: Gialli medi 4.5 | Falli medi 24
```

Per ottenere input utili, usa la stessa competizione, stagione e fonte per
entrambe le squadre e aggiorna i valori alla data della partita. Quando
disponibili, inserisci per la squadra di casa i dati delle sue gare casalinghe
e per l'ospite quelli delle trasferte; privilegia medie di stagione con almeno
8-10 gare, senza mescolare totali stagionali e medie per partita.

- `Attacco`: coefficiente relativo, gol fatti medi della squadra diviso la
   media della competizione. `1.0` è neutro, sopra `1.0` indica attacco sopra
   media; intervallo accettato `0.2-3.0`.
- `Difesa`: media della competizione dei gol subiti divisa per i gol subiti
   medi della squadra. Quindi un valore sopra `1.0` indica una difesa più
   solida; intervallo `0.2-3.0`.
- `Elo`: rating assoluto nella stessa scala e fonte per entrambe le squadre;
   intervallo accettato `800-2400`.
- `Forma`: da uno a cinque risultati, dal più vecchio al più recente, usando
   `W` (vittoria), `D` (pareggio), `L` (sconfitta).
- `xG Fatti/Subiti`: expected goals medi per squadra e partita, calcolati con
   la stessa fonte per entrambi; intervallo `0-10`.
- `Corner pro/sub`: corner conquistati/concessi medi per singola squadra e
   partita, non coefficienti, percentuali o totali del match; intervallo
   `0-15`. Il motore stima Casa come `(corner pro Casa + corner sub Ospite) / 2`
   e Ospite come `(corner pro Ospite + corner sub Casa) / 2`, poi li somma.
   Il totale atteso per il match deve essere al massimo `20`. Nell'esempio è
   circa `9.95`, non `44`. Medie totali sotto `4` generano un avviso di
   plausibilità: l'importazione prosegue, ma va verificato che i dati siano
   conteggi per partita e non coefficienti normalizzati.
- `Cartellini pro`: gialli medi ricevuti dalla squadra per partita; non
   includere i rossi; intervallo `0-10` per squadra. `Gialli medi` e `Falli medi` dell'arbitro sono totali
   medi per partita, rispettivamente nei limiti `0-15` e `0-60`. Il motore
   scala la media dei gialli di squadra usando il profilo dell'arbitro e il
   volume di falli; anche la media totale risultante deve essere al massimo
   `20` per partita.

La modalità standard richiede tutti i campi di entrambe le squadre e
dell'arbitro, inclusi corner pro/sub e cartellini. Se manca un campo o una quota
è duplicata, non valida o non riconosciuta, il parser interrompe l'importazione
con un messaggio esplicito invece di scartare o inventare valori. La modalità
permissiva con fallback è disponibile solo a livello API (`strict=False`) e non
viene usata dalla schermata di copia-incolla.

Le quote sono opzionali e possono essere aggiunte alle righe `CASA` e
`OSPITE`, o separate nelle sezioni `QUOTE_MERCATI_PRINCIPALI`,
`QUOTE_MULTIGOL_TOTALI`, `QUOTE_MULTIGOL_CASA`, `QUOTE_MULTIGOL_OSPITE`,
`QUOTE_SOMMA_GOL`, `QUOTE_CORNER_E_CARTELLINI` e `QUOTE_COMBO`. Sono accettati
alias come `Quota 1T 1`, `Quota DNB Casa` e combo a due gambe come
`Quota X2 + Over 1.5`. Tutte le 72 quote del blocco test Como-Roma sono coperte
da test; quel blocco è solo un fixture di test e non un input predefinito.
Le quote valide vengono normalizzate e passate al motore per l'analisi Value
Bet. Sono supportate tutte le fasce multigol totali, Casa e Ospite da `1-2` a
`3-6`, incluse `1-5`, `2-6`, `3-4` e `3-5`.

Il catalogo dichiarativo condiviso è in [`market_catalog.py`](./market_catalog.py):
le sue definizioni vengono usate per normalizzare le quote, validare i mercati,
materializzare il gruppo `markets["catalog"]` e generare le card del tab
Catalogo. Per i mercati DNB il risultato distingue vittoria, perdita e
rimborso (`push`); il Kelly e l'EV usano il settlement a tre esiti invece di
trattare il pareggio come una perdita.

## Modello

Il motore:

1. costruisce `lambda` e `mu` con un modello log-lineare tarato (vedi
   *Taratura del modello gol*): forza d'attacco e debolezza difensiva
   dell'avversario, scarto Elo, vantaggio casa applicato una sola volta;
2. applica la correzione Dixon-Coles ai punteggi `0-0`, `0-1`, `1-0`, `1-1` e
   campiona il punteggio finale da questa distribuzione corretta;
3. ripartisce i gol finali tra primo e secondo tempo, così i risultati parziali
   sono coerenti con il punteggio finale;
4. usa il seed scelto per il campionamento (default 100.000 simulazioni);
5. deriva tutti i mercati score-dependent dagli stessi campioni, inclusi
   1X2, doppia chance, DNB, Goal/No Goal, Over/Under, somme e multigol totali
   e di squadra;
6. calcola un unico totale Poisson per corner e cartellini, poi ripartisce
   ciascun totale tra Casa e Ospite senza alterare le soglie del match;
7. mostra score modale, intervalli Wilson e il ledger dei contributi;
8. espone per ogni mercato l'intervallo Wilson 95% e l'affidabilità campionaria;
9. calcola EV e Kelly frazionato (Quarter-Kelly, 25% del Kelly pieno) per le
   Value Bet e per la Schedina Mista.

La vista Scenario condizionato filtra i campioni per segno finale (`1`, `X` o
`2`) e mostra le probabilità dei mercati all'interno dello scenario. Non modifica
le probabilità incondizionate né l'analisi finanziaria.

Il risultato fisso è scelto come score esatto più frequente tra le simulazioni
che hanno prodotto il segno 1X2 più probabile. Perciò un segno Casa favorito
non può avere come risultato fisso un pareggio. La vista dei mercati coerenti
mostra le conseguenze determinate da quello score: per `2-1`, ad esempio,
vittoria Casa, Goal, Over 2.5, somma 3 e multigol che includono 3 risultano
vincenti nello scenario esatto. Lo score più frequente senza vincolo viene
mostrato separatamente; le probabilità aggregate non vengono alterate.

Il catalogo `result["markets"]` espone inoltre tutti i mercati richiesti,
raggruppati in esiti finali e parziali, goal e multigol, somme e combo,
corner e cartellini. Ogni voce di mercato contiene conteggio, percentuale,
intervallo Wilson 95% e indice di affidabilità; le quote fornite dall'utente
vengono analizzate con EV e Quarter-Kelly.
La sezione Value Bet mostra in primo piano solo i mercati con EV positivo,
ordinati per valore atteso; per i mercati binari la quota equa è
`1 / P_simulata`, mentre per il DNB considera anche la probabilità di perdita
e il rimborso sul pareggio. La puntata indicativa è il Quarter-Kelly. Le quote con EV nullo o negativo
restano disponibili nell'audit completo, ma non vengono consigliate per il
profitto.

Il testo prodotto è una sintesi numerica nell'interfaccia, non viene chiamato
“IA” e non contiene frasi narrative generate da template.

### Taratura del modello gol

```
log λ = log(base) + h/2 + β_att·[(1-α)·log Attacco + α·log(xG fatti/base)]
        + β_def·[(1-α_d)·log(1/Difesa avv.) + α_d·log(xG subiti avv./base)]
        + (k/2)·ΔElo/400 + φ·(forma - forma avv.)/2
```

`μ` è simmetrica con i segni di vantaggio casa, Elo e forma invertiti. I
parametri non sono scelti a mano: sono in
[`config/goal_model.json`](./config/goal_model.json), prodotti da
`python -m tools.calibrate` minimizzando log-loss 1X2 + Over/Under 2.5 su
Serie A, Premier League, Liga e Bundesliga (football-data.co.uk, stagioni
2024-25 e 2025-26; input costruiti solo con partite precedenti a ciascuna gara).
Il file indica anche quale formula è attiva: il modello tarato viene attivato
solo se batte la formula originale sulla stagione fuori campione, e una
componente opzionale (oggi la forma) resta accesa solo se migliora il
fuori campione di almeno 0.001 di log-loss. La formula originale resta
disponibile con `MatchConfig(goal_model="legacy")`; senza file di taratura il
motore usa quella.

### Ancoraggio alle quote di mercato

Se il blocco contiene le quote 1X2 (e, facoltativamente, Over e Under 2.5), il
motore toglie il margine (metodo proporzionale o di Shin) e trova `λ_mercato` e
`μ_mercato` che con Poisson + Dixon-Coles riproducono al meglio quelle
probabilità. I gol attesi finali sono
`mercato^w · modello^(1-w)` in scala logaritmica, con la correzione del modello
rispetto al mercato limitata a `[0.80, 1.20]`. Senza quote 1X2 si usa solo il
modello. Peso `w` e metodo sono tarati con
`python -m tools.baseline --tara-ancoraggio` (pesi 0.5-0.9) e salvati nella
sezione `ancoraggio_mercato` di `config/goal_model.json`, dove
`"active": false` disattiva l'ancoraggio.

Ogni card mostra probabilità solo-mercato, solo-modello e finale. Un `VALORE`
in cui modello e mercato divergono di oltre 10 punti è evidenziato in giallo
con la scritta "valore sospetto: verifica i dati".

Il pareggio (`X`) non viene mai segnalato come `VALORE` (`no_value_markets` in
`config/goal_model.json`): sulle quote di chiusura storiche quei segnali hanno
reso in perdita perché Poisson + Dixon-Coles non riproduce esattamente la X
quotata. L'EV resta visibile nell'audit. Il confronto per esito tra Shin e
metodo proporzionale si rigenera con `python -m tools.baseline --analisi-pareggio`.

### Primo tempo e mercati secondari

Ogni gol del punteggio finale simulato cade nel primo tempo con una quota
tarata separatamente per casa e ospite e crescente con i gol attesi totali
(sezione `primo_tempo` di `config/goal_model.json`, generata da
`python -m tools.calibrate --primo-tempo` sui gol del primo tempo dei CSV
football-data). Tutti i mercati gol (finale, primo tempo, multigol, somma gol,
risultati esatti) derivano dallo stesso campione di punteggi dei gol attesi
finali. `python -m tools.baseline --mercati-secondari` misura multigol, somma
gol e mercati del primo tempo prima/dopo.

`python -m tools.baseline --label ... --output docs/BASELINE.md` misura Brier,
log-loss e calibrazione di 1X2, Over 2.5 e GG e l'errore sulle medie di corner
e cartellini, confrontandoli con le quote di chiusura senza margine. I
risultati prima/dopo sono in [`docs/BASELINE.md`](./docs/BASELINE.md). Per i
test: `pip install -r requirements-dev.txt` e `python -m pytest -q`.

## Gestione del rischio

L'indice di affidabilità è una misura della stabilità del campione Monte Carlo:
`100 - ampiezza dell'intervallo Wilson 95%`, limitata a `0-100`. Non misura la
qualità dei dati inseriti né la correttezza del modello. Il Kelly pieno usa
`f* = (b·p - q) / b` con `b = quota - 1`; la dashboard mostra esclusivamente
Quarter-Kelly (il 25% del valore pieno) come stake massimo indicativo del
bankroll, mai come garanzia di profitto.

La dashboard usa card per ogni mercato: probabilità simulata, quota bookmaker
(se presente), quota equa, Wilson 95%, EV e Quarter-Kelly. Le card dei
multigol di Casa e Ospite sono sezioni separate e includono tutte le fasce
standard e quelle richieste dalle quote in input.

Gli intervalli Wilson e l'indice mostrato come stabilità sono riferiti alla
variabilità del campione Monte Carlo. Non sono una stima dell'incertezza dei
parametri del modello: questa richiede una distribuzione sui parametri e una
validazione out-of-sample, non ancora inclusa nell'applicazione.
