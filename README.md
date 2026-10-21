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

1. costruisce `lambda` e `mu` con attacco, difesa avversaria, xG, forma ed Elo;
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
