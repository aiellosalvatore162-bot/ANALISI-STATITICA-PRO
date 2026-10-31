# Guida del simulatore

Stato al 31/10/2026, dopo la fase AO. Tutto quello che c'è scritto qui è stato ricavato dal repository (config, codice, `docs/stato/`, `docs/BASELINE.md`, `docs/backtest/`). Quando un dato è «solo consultabile» significa che il motore **non lo legge**: è scritto chiaro, scheda per scheda.

---

## 1. Cosa fa il simulatore e cosa NON fa

**Cosa fa.** Per una partita simula decine di migliaia di punteggi (Monte Carlo, modello Dixon-Coles) e da quel solo campione ricava tutti i mercati: 1X2, gol, multigol, risultati esatti, primo tempo, corner, cartellini, combo. Poi confronta le percentuali con le quote e segnala dove c'è differenza.

**L'obiettivo vero: percentuali vere, non battere le quote.** Se il simulatore dice 80%, quell'evento deve uscire circa 8 volte su 10. Questo si misura con la *calibrazione* (scarto tra «dichiarato» e «uscito», chiamato ECE) e con la log-loss, mai con «quante schedine vinco».

**Cosa NON fa.**
- Non garantisce vincite e non «batte il mercato»: sui gol il modello ancorato alle quote fa circa quanto la quota di chiusura (1X2 fuori campione 2026-27: log-loss 0,9341 contro 0,9373 del mercato, su 254 partite: pari, non migliore).
- Non inventa dati: se manca un campo obbligatorio il blocco di input fallisce con messaggio chiaro. I dati recuperati da soli restano visibili e modificabili, con fonte e data.
- Non legge notizie, infortuni o umori da solo: assenti, formazioni e correzioni arrivano dal report dell'Analista / di Claude incollato a mano (nessuna API di Claude, solo copia e incolla).
- Non usa dati dal futuro: ogni misura usa solo partite precedenti a quella simulata.
- Non è tarato dappertutto: i mercati con pochi casi (molte combo, risultati esatti rari) hanno l'etichetta «poco verificata». Per un giudizio affidabile sul registro servono almeno 100 selezioni con esito per mercato.
- Ogni miglioramento è stato tenuto acceso **solo** se la verifica fuori campione lo ha confermato (regola severa: log-loss appaiata giù di oltre 2 errori standard **e** ECE non peggiore). Per questo molte funzioni sotto risultano spente.

---

## 2. Dai dati alla percentuale

```
 DATI (automatici / importati / a mano)
   risultati, tiri, corner, falli, cartellini, arbitri  ← football-data.co.uk / .org
   xG, rose, giocatori                                 ← Understat
   Elo                                                 ← ClubElo (se bloccato: Elo dai risultati)
        │
        ▼
 1. MODELLO GOL (expected_goals)         Elo + attacco/difesa (xG) [+ forma reale AD]
        │                                 → gol attesi λ (casa) e μ (ospite)
        ▼
 2. ANCORAGGIO ALLE QUOTE                 quote 1X2 e Over/Under 2.5, senza margine
        │                                 (peso 0,9) → "gol finali" (final_goal_rates)
        ▼
 3. CORREZIONI SUI GOL                    Claude / Analista / segnalazioni (limitate), dopo l'ancoraggio
        │
        ▼
 4. SIMULAZIONE Dixon-Coles              un solo campione di punteggi per TUTTI i mercati
        │   + corner e cartellini: medie da storico, arbitro, stile, avversari simili,
        │     ancorati alle linee Over/Under quotate (peso 0,8) quando ci sono
        ▼
 5. TARATURA PER MERCATO (fase AM)       mappe walk-forward dove migliorano, altrimenti nessuna
        │
        ▼
 6. PERCENTUALE + ETICHETTA              "verificata / poco verificata", semaforo, EV, registro
```

Con il selettore «Simulatore reale» (sezione 3) il punto 4 cambia: la partita viene giocata a eventi (tiri, corner, falli), ma i totali restano riportati alle stesse medie del punto 2-3.

---

## 3. Motori e funzioni: stato reale

Fonte dello stato: sezioni `attiva`/`attivo` in `config/*.json` e `engine_choice.py`.

### 3.1 Selettore «Simulatore reale» (card «Parametri simulazione»)

Il predefinito è **Calcolo attuale** (`data/impostazioni.json` non esiste: vale il predefinito del codice). Tre posizioni, scelte dall'utente:

| Posizione | Cosa fa | Stato / avviso onesto |
|---|---|---|
| **Calcolo attuale** | Punteggi Dixon-Coles ancorati alle quote; corner e cartellini dalle medie | **Il verificato e tarato.** Scarto medio dichiarato/uscito intorno all'1% |
| **Simulatore reale – completo** | I gol nascono dai tiri; stile, formazione, corsie e arbitro agiscono sulla partita (tempi, corner, cartellini) | **Opzionale, non migliore.** Su 563 partite (AO): gol +0,0010 ± 0,0028, tempi +0,0006 ± 0,0011, corner −0,0010 ± 0,0011, cartellini +0,0015 ± 0,0029, combo −0,0008 ± 0,0012 (differenze di log-loss, negativo = meglio): nessuna differenza misurabile. Nessuna taratura AM per questo motore («poco verificata»). Cartellini peggiori nel campione AK da 2.672 partite |
| **Simulatore reale – solo corner** | Come l'attuale, ma i corner vengono dal motore a eventi | **Candidato**, meglio sul campione AK (−0,00075 ± 0,00039), non riverificato su un terzo campione |

Se è accesa la fase O (minuto per minuto) il selettore la spegne per quella partita (sono incompatibili).

### 3.2 Tabella delle funzioni

| Funzione | Stato | Perché |
|---|---|---|
| Modello gol log-lineare (Elo + xG attacco/difesa) | **Acceso** | Tarato sul 2024-26; sostituisce la formula originale (`goal_model="legacy"` resta disponibile) |
| Ancoraggio alle quote 1X2 / O-U 2.5 (peso 0,9, margine tolto con Shin) | **Acceso** | Porta le favorite da 58,7% a 74,5% (mercato 76,4%) |
| Ancoraggio corner e cartellini alle linee quotate (peso 0,8) | **Acceso se ci sono le linee** | Peso dichiarato, **non tarato** (manca storico di quote corner) |
| Quota di gol del primo tempo | **Acceso** | Tarata (`primo_tempo`) |
| Forma W-D-L (`componenti.forma`) | **Spenta** | Miglioramento fuori campione troppo piccolo |
| Forma reale xG−xGA (AD, `phi` 0,038) | **Accesa** | 4.715 partite: 1X2 −0,00071 ± 0,00032, gli altri mercati pari. Aggiunge un termine (la forma W-D-L è a peso 0) |
| Tarature corner/cartellini, punti Eurobet, divisione cartellini per squadra (T) | **Accese** | Verificate fuori campione |
| Avversari simili (`scenario_tattico`) | **Corner e cartellini accesi; gol, supremazia, primo tempo spenti** | Verificato solo dove migliora |
| Taratura per mercato (AM, `config/taratura.json`) | **Accesa dove migliora** | Es. Goal, Multigol 1-3, X + Over 1.5/2.5, Esatti 1-0/2-0/2-1; gli altri mercati non vengono toccati |
| Ricalibrazione fase P | **Accesa solo su «Over 3.5 cartellini»**; il resto è sostituito dalla AM | |
| Marcatori v2 | **Acceso** | Verificato (NON verificato fuori campione per la parte base di `scorers.py`) |
| Regole dell'Analista (`regole_analista`) | **Accese**, limiti 0,95–1,05, stato «da verificare» finché non ci sono ≥150 partite | Servono settimane di report |
| Forza per il calendario (`forza_calendario`) | **Spenta** | Non supera la regola severa |
| Assenze pesate fase P (`assenze`) | **Spenta** | Non tiene (ECE peggiora) |
| Incertezza dei parametri, peso mercato per campionato, riposo (`contesto_riposo`), soglie EV (`soglie_valore`), goleade | **Spenti** | Non verificati o non migliorano |
| Formazioni e giocatori (AL, `lineup`) | **Neutri sui gol** | Esponente attacco ≈ 0 (−0,10 ± 0,21), pesi difesa non stimabili → fattori 1,0. Servono per etichette, marcatori e (con motore a eventi) per i tiri |
| Motore minuto per minuto (fase O, `minuto_per_minuto`) | **Spento** (tutte le componenti) | Nessuna componente supera la verifica |
| Incroci di stile (`config/tattica.json` regole) | **Tutti spenti** | Non verificati o non verificabili (campi `non_possesso`, `fasce_cross` assenti dai dati) |
| Motore a eventi (AK/AN/AO, `motore_eventi.attivo`) | **Spento per default; opzionale dal selettore** | Verificato due volte + AO: pari sul calcolo attuale, cartellini a volte peggio |
| Corsie dei moduli (AO) | **Stimate e attive solo dentro il motore a eventi** | Effetti piccoli (cross +0,039, IC +0,010…+0,068) |
| Doppio pronostico, schedine, costruttore di multiple, ricerca rapida, «Vedi come andrà» | **Accesi** | Funzioni di uso, non cambiano le probabilità |

Importante: l'unico elemento dello **stile** che cambia i gol attesi nel calcolo attuale è la **forma reale (xG−xGA)**. Possesso, verticalità, fasce, pressing, aggressività, palle inattive sono calcolati e mostrati nel riquadro «Stile» (`config/stile.json` li ha tutti `true`), ma il motore attuale non li legge. Li legge soltanto il **motore a eventi** (`event_inputs.style_terms`), quando lo scegli.

---

## 4. I DATI: cosa serve e come inserirlo

Legenda di ogni scheda:
- **a)** a cosa serve · **b)** obbligatorio / consigliato / facoltativo · **c)** da dove arriva (automatico, `data/import/` con quale modello CSV, a mano nell'app) · **d)** cosa legge davvero il motore · **e)** se manca.

Regola generale: precedenza **manuale > automatico > stima**. I dati a mano (pannello «Modifica o completa i dati» in Oggi) non vengono mai toccati da un nuovo «Prepara/Analizza»; «Ripristina dati automatici» li toglie.

### 4.0 Come si importa un file (`data/import/`)

```
python -m tools.importa_dati data/import/modelli/stile_squadra.csv --fonte "Opta"
```

- Modelli pronti in `data/import/modelli/`: `stile_squadra.csv`, `giocatori.csv`, `formazioni_assenti.csv`, `arbitri.csv`, `quote.csv`. Il tipo è riconosciuto dalle intestazioni (nomi italiani e inglesi accettati).
- I nomi squadra non riconosciuti vengono elencati e si sceglie l'abbinamento (`--scegli "Nome nel file=Nome app"`, oppure `--non-interattivo` per scartare). Nessun abbinamento dubbio è fatto da solo.
- Regola fondamentale: `data_dati` = data a cui i dati sono aggiornati; il motore usa solo righe con `data_dati` **precedente** alla partita (stesso giorno = non ancora noto).
- Il registro delle importazioni (`data/import/registro.json`) tiene fonte, data, righe importate e scartate. Sono consultabili nella tab «Dati aggiunti». I dati stanno in `data/cache/importati/` (cache non versionata).
- Controllo consigliato dopo l'importazione (non parte da solo): `python -m tools.confronto_dati --tipo <tipo>`.

**Quali colonne il motore legge davvero dai file importati** (da `data_import.KINDS[...].used_by_engine`):

| Modello CSV | Letto dal motore | Solo consultabile |
|---|---|---|
| `stile_squadra.csv` | `xg`, `xga`, `partite` (forma reale al posto del proxy dai tiri); `tiri_transizione`, `quota_xg_palle_inattive`, `cross` (riempiono i campi «non disponibile»). Col motore a eventi anche `possesso`, `ppda`, `cross` per le etichette di stile | `passaggi`, `pressioni`, `tiri_area`, `tiri_fuori_area`, `corner`, `falli` |
| `giocatori.csv` | **niente** | tutto |
| `formazioni_assenti.csv` | **niente** | tutto |
| `arbitri.csv` | **niente** | tutto |
| `quote.csv` | **niente** | tutto |

Quindi per giocatori, formazioni, assenti, arbitri e quote il canale che **agisce** non è l'importazione CSV ma: Understat/football-data (automatici), il report dell'Analista incollato, il blocco di input e le quote incollate.

---

### 4.1 Risultati delle partite
- **a)** Base di tutto: forza di attacco/difesa, Elo da risultati, frequenze storiche, tarature.
- **b)** Obbligatorio (senza non si calcola nulla).
- **c)** Automatico: football-data.co.uk (CSV per stagione, cache SQLite). football-data.org come fonte aggiuntiva (serve la chiave in `st.secrets`). Non si importa a mano.
- **d)** Letto: sì.
- **e)** Fonte non raggiungibile → avviso e si ricade sul manuale; la simulazione manuale non si blocca mai.
- **Calibrazione:** non è un valore di cui calibrare: alimenta Elo (K=20, vantaggio casa 65, stagioni di riscaldamento in `goal_model.json`) e le tarature. Taratura finale per mercato: solo dove `config/taratura.json` dice «tarato» (soglie: ≥ 400 casi, ≥ 30 positivi, isotonica da 3.000 casi altrimenti Platt con shrinkage 200, correzione max 15 punti). Etichetta attesa: «verificata» sui mercati gol principali.
- **Come preparare il valore:** non si prepara a mano. Se serve, punteggi interi (`2-1`), data `AAAA-MM-GG` (accettati anche `gg/mm/aaaa`), squadre col nome dell'app, casa a sinistra.

### 4.2 Tiri (totali, in porta)
- **a)** Proxy xG quando manca l'xG (`config/proxy_xg.json`, usato solo se R² ≥ 0,5; R² fuori campione 0,545), profilo di stile.
- **b)** Consigliato.
- **c)** Automatico da football-data (colonne tiri). Dai CSV del modello stile: `tiri_area`, `tiri_fuori_area` (solo consultabili).
- **d)** Letto solo come proxy xG. Le colonne importate di tiri in/fuori area **non** sono lette.
- **e)** Si usa l'xG Understat; se manca anche quello, i gol.
- **Calibrazione:** entra solo come proxy xG (`config/proxy_xg.json`, usato se R² ≥ 0,5; misurato 0,545) dentro la forma reale: shrinkage n/(n+6) verso il campionato, ultime 8 gare con emivita 4, winsorizzazione ai percentili 2-98 (minimo 30 valori nel campionato). Nessuna taratura propria; l'etichetta è quella dei gol.
- **Come preparare il valore:** totale o media per partita, non per 90 minuti. Casa e ospite separati. Pochi dati: nessun intervento, lo shrinkage riporta alla media del campionato (con 4 gare pesa 4/(4+6) = 40%).
  - Esempio: «Inter 21 tiri su 3 gare in casa» → `7.0` tiri per gara (solo se compili `tiri_area`/`tiri_fuori_area`, comunque non letti).

### 4.3 Corner
- **a)** Mercati corner (medie casa/ospite, totale ridotto verso la media di riferimento, 1X2 corner).
- **b)** Consigliato (medie nel blocco); le quote corner sono facoltative ma permettono l'ancoraggio.
- **c)** Automatico dallo storico football-data; a mano nel blocco (`Corner fatti/subiti`); quote da The Odds API o incollate.
- **d)** Letto. La colonna `corner` di `stile_squadra.csv` è solo consultabile.
- **e)** Senza quote corner: solo modello, con avviso sull'EV (`CORNER_EV_WARNING`).
- **Calibrazione:** totale corner ridotto verso `corner_shrink_reference` (fase M), poi ancoraggio alle linee Over/Under quotate con peso 0,8 (non tarato), poi eventuale fattore Claude. Nessuna taratura finale AM (Over 8.5/9.5/10.5 corner: «non tarato»). Etichetta attesa: «poco verificata».
- **Come preparare il valore:** nel blocco `Corner pro/sub: 5.8/4.2` = corner fatti/subiti **per partita** della squadra, punto decimale (la virgola è accettata e convertita), casa e ospite non invertiti. Quote corner: decimali europee con due decimali.
  - Esempio: «27 corner fatti, 18 subiti in 5 gare» → `5.4/3.6`.

### 4.4 Falli
- **a)** Contribuiscono ai gialli (via arbitro) e, nel motore a eventi, al ritmo dei falli.
- **b)** Facoltativo.
- **c)** Automatico da football-data; `ARBITRO: ... Falli medi` nel blocco; colonna `falli` di `arbitri.csv`/`stile_squadra.csv` (non letta).
- **d)** Letto dal blocco/arbitro automatico.
- **e)** Nel blocco manuale, se manca «Falli medi» dell'arbitro: errore in modalità strict.
- **Calibrazione:** falli dell'arbitro entrano nei gialli attesi; nel motore a eventi con shrinkage k = 20,8. Nessuna taratura finale propria.
- **Come preparare il valore:** `Falli medi` = falli totali **per partita** dell'arbitro (0-60), punto decimale. Con poche partite dell'arbitro: lascia la media del campionato (meglio del dato grezzo).
  - Esempio: «Orsato, 720 falli in 30 gare» → `Falli medi 24.0`.

### 4.5 Cartellini
- **a)** Mercati cartellini (in punti del bookmaker: giallo 1, rosso 2, doppia ammonizione = giallo + rosso), divisione tra casa e ospite.
- **b)** Consigliato.
- **c)** Automatico da football-data (gialli e rossi); nel blocco a mano `Cartellini fatti`, facoltativo `Cartellini provocati`. Nei dati inglesi/scozzesi la doppia ammonizione vale 2 invece di 3.
- **d)** Letto.
- **e)** Dato mancante → campo vuoto da completare in «Modifica o completa i dati».
- **Calibrazione:** gialli come prima (arbitro + Claude), rossi = `card_red_ratio` × gialli; gialli × exp(`card_balance_intercept` + `card_balance_weight`·|ΔElo|/100); ancoraggio alle linee quotate peso 0,8 (non tarato); divisione casa/ospite fase T. Taratura finale: «Over 3.5 cartellini» e «Over 4.5 cartellini» tarati, «Over 5.5» no; ricalibrazione fase P attiva su Over 3.5. Etichetta: «verificata» sul totale, più cauta sui cartellini per squadra (esclusi da liste e multiple se l'ECE supera `ece_massimo`).
- **Come preparare il valore:** `Cartellini pro` = cartellini **per partita** della squadra, in **punti** della regola del bookmaker (giallo 1, rosso 2, doppia ammonizione = giallo + rosso), punto decimale. Campo facoltativo `Cartellini provocati` con lo stesso criterio.
  - Esempio: «14 gialli e 1 rosso in 8 gare» → (14 + 2)/8 = `2.00`.

### 4.6 Arbitri
- **a)** Gialli e falli attesi della partita.
- **b)** **Obbligatorio** nel blocco testuale manuale (`ARBITRO: Nome | Gialli medi | Falli medi`, entrambi con valori tra 0-15 e 0-60). In automatico è consigliato.
- **c)** Automatico: profilo arbitro dallo storico (`referee_profile`). A mano: riga `ARBITRO:` del blocco. `arbitri.csv` (colonne `arbitro, stagione, partite, falli, gialli, rossi, data_dati`) si importa ma **non è letto**.
- **d)** Letto: medie dal blocco/profilo; nel motore a eventi come `RefereeInput` con shrinkage (falli k = 20,8, gialli k = 80,7). I gialli restano comunque riportati alla media attuale (nessuna doppia conta). Il nome dell'arbitro nei dati storici manca: la verifica sull'arbitro dei falli non è stata possibile.
- **e)** Arbitro sconosciuto → medie del campionato con avviso.
- **Calibrazione:** gialli medi dell'arbitro entrano nei cartellini attesi; nel motore a eventi shrinkage k = 80,7 (gialli) e 20,8 (falli), poi riportati alla media attuale (nessuna doppia conta). Etichetta: quella dei cartellini.
- **Come preparare il valore:** `ARBITRO: Gialli medi 4.5 | Falli medi 24` = medie **per partita**. Nel CSV `arbitri.csv`: totali stagionali (`partite`, `falli`, `gialli`, `rossi`) con `data_dati` `AAAA-MM-GG` e `stagione` `2025/26`. Pochi dati: sotto circa 10 partite lascia la media del campionato.
  - Esempio: «118 gialli in 30 gare» → `Gialli medi 3.93` nel blocco; nel CSV `partite=30, gialli=118`.

### 4.7 Quote 1X2, gol (Over/Under), Goal/NoGoal
- **a)** Ancoraggio del modello (la parte che più avvicina le percentuali alla realtà) ed EV.
- **b)** **Consigliato fortemente.** Senza quote 1X2 e O/U 2.5 il simulatore usa solo il modello (meno preciso sulle favorite).
- **c)** In ordine: a mano nel blocco (`QUOTE_MERCATI_PRINCIPALI`); incollate da qualunque bookmaker (Eurobet con parser dedicato; formato generico); The Odds API (chiave `ODDS_API_KEY` solo in `st.secrets`, budget mensile e conferme); CSV di chiusura. `quote.csv` importato è solo consultabile.
- **d)** Letto: l'ancoraggio usa le quote *sharp* (se arrivano dall'API) altrimenti Eurobet; le quote dell'EV restano separate da quelle dell'ancoraggio. Un conflitto tra fonti viene mostrato e confermato, non deciso in silenzio.
- **e)** Quote «sospese» = vuote, mai zero.
- **Calibrazione:** margine tolto con il metodo **Shin**; modello ancorato con peso mercato **0,9** (tarato su football-data 2024-26); correzione limitata a 0,8-1,2; scarto sospetto tra modello e mercato oltre 10 punti segnalato; «X» escluso dai segnali di valore. Taratura finale: Goal e combo con Goal tarati, Over 1.5/2.5/3.5 «non tarato» (già ben calibrati). Etichetta attesa: «verificata», ECE intorno all'1%.
- **Come preparare il valore:** quote **decimali europee** (es. `1.85`), punto decimale, **due decimali** per le quote incollate (il parser Eurobet non fa slittare i valori), linee con un decimale (`Over 2.5`). Casa = 1, ospite = 2, non invertiti. Sospesa = lascia vuoto, mai `0`. In `quote.csv` la data è `AAAA-MM-GG`, `tipo` = `apertura|chiusura` (consultabile).
  - Esempio: americana `-120` o frazionaria `5/6` → decimale `1.83`; «1.85» scritto `1,85` è accettato ma preferisci il punto.

### 4.8 Quote corner e cartellini
- **a)** Ancorare le medie corner/cartellini alle linee Over/Under quotate (peso 0,8, dichiarato, **non tarato**) e calcolare l'EV.
- **b)** Facoltativo, ma senza di esse l'EV corner porta un avviso.
- **c)** The Odds API (profilo «risparmio»: 2 crediti a partita), Eurobet incollata (`QUOTE_CORNER_E_CARTELLINI`), a mano nel blocco.
- **d)** Letto.
- **e)** Solo modello.
- **Calibrazione:** media del mercato dalle linee x.5 senza margine (metodo proporzionale), stessa distribuzione della simulazione, finale = mercato^0,8 · modello^0,2; il peso 0,8 è **dichiarato, non tarato**. Cartellini per squadra: ancoraggio a 1X2 cartellini e linee per squadra, peso 0,8. Scarto > 10 punti tra mercato e modello = avviso e niente verde. Etichetta attesa: «poco verificata».
- **Come preparare il valore:** quote decimali con due decimali; linea con un decimale (`Over 9.5`); una sola coppia Over/Under per linea; i cartellini sono in **punti** (non gialli). Mercati diversi dai punti Eurobet non vanno mescolati.
  - Esempio: «Over 9.5 corner @ 1.90 / Under @ 1.90» → margine 5,3%, tolto dal modello; inserisci le due quote così come sono.

### 4.9 Multigol, somma gol, combo
- **a)** Verifica di coerenza, EV e «I miei mercati». Le probabilità congiunte dei Combo Builder vengono dallo stesso campione (`joint_pairs`).
- **b)** Facoltativo.
- **c)** Incollate Eurobet (`QUOTE_MULTIGOL_*`, `QUOTE_SOMMA_GOL`, `QUOTE_COMBO`) o a mano. Il flag «Combo Builder» per mercato è letto dalla pagina incollata.
- **d)** Le quote multigol/combo servono all'EV e alla quota di chiusura; non cambiano i gol attesi.
- **e)** Quota CB stimata (prodotto × sconto) con nota «quota CB stimata».
- **Calibrazione:** nessun ancoraggio dei gol: servono all'EV e alla quota di chiusura. Multigol 1-3 e 1-2: tarati/non tarati come da `taratura.json` (1-3 tarato isotonica, 2-4, 2-5, 1-2 «non tarato»). Combo da campione congiunto stesso (`joint_pairs`). Quota CB stimata = prodotto × `sconto_cb`; osservata in `performance.observed_cb_discount`.
- **Come preparare il valore:** quote decimali con due decimali, sezione corretta (`QUOTE_MULTIGOL_TOTALI`, `..._CASA`, `..._OSPITE`, `QUOTE_SOMMA_GOL`, `QUOTE_COMBO`). Casa e ospite non invertiti.
  - Esempio: «Multigol 2-4 @ 1,52» → `Quota Multigol 2-4: 1.52`.

### 4.10 Elo
- **a)** Differenza di forza tra le squadre (gol attesi, equilibrio dei cartellini).
- **b)** **Obbligatorio** (campo `Elo` di CASA/OSPITE nel blocco manuale).
- **c)** Automatico da ClubElo. Se ClubElo è bloccato (403/502/503 o Cloudflare) l'app lo segna «non disponibile» per la giornata, non lo aggira e calcola l'Elo dai risultati di 6 stagioni, dichiarandolo. Per le coppe fra campionati diversi l'Elo resta MANCANTE e va inserito a mano.
- **d)** Letto.
- **e)** Mancante → blocco non valido (strict), mai un default nascosto.
- **Calibrazione:** Elo → differenza di forza nei gol attesi (`elo_k` 0,98) e nell'equilibrio dei cartellini; poi ancoraggio alle quote. Elo da risultati (ClubElo non disponibile) è dichiarato in scheda. Nessuna taratura propria; l'etichetta resta quella dei gol.
- **Come preparare il valore:** punti Elo **ClubElo** come numero intero o con un decimale, per **squadra** (non per partita). Elo non-ClubElo (altre scale) non vanno mescolati. Per coppe tra campionati diversi inserisci a mano.
  - Esempio: «Inter 1835,4» → `Elo: 1835`.

### 4.11 xG e tiri per zona
- **a)** Attacco e difesa (il modello usa solo xG per l'attacco), forma reale, profilo di stile (tiri in area/fuori area, transizioni, palle inattive).
- **b)** Consigliato (xG); la scomposizione per zona è facoltativa.
- **c)** Automatico da Understat (5 grandi campionati). Fuori da Understat: proxy dai tiri, altrimenti gol. `stile_squadra.csv`: `xg`, `xga`, `partite` (letti, sostituiscono il proxy), `tiri_transizione`, `quota_xg_palle_inattive`, `cross` (letti solo dove mancano).
- **d)** Letto. I tiri per zona del CSV (`tiri_area`, `tiri_fuori_area`) sono solo consultabili.
- **e)** Fonte e campione dichiarati nella scheda («proxy dai tiri», «gol»).
- **Calibrazione:** attacco e difesa (solo xG, `attack_xg_share = 1`); forma reale = (xG − xGA) per gara centrata sul campionato × `phi` 0,038 (stimato su 10.705 partite), shrinkage n/(n+6); `k_xg` alza il peso dell'xG con poche gare (α_eff = α + (1−α)·k/(n+k)). Stile importato `xg`/`xga` sostituisce proxy e gol solo se la stima attuale non viene da Understat. Etichetta attesa: «verificata» (1X2 −0,00071 ± 0,00032 sul banco AD).
- **Come preparare il valore:** `xG Fatti`/`xG Subiti` nel blocco = **per partita**. Nel CSV `xg`/`xga` = **totale stagionale** con `partite`, così la media per gara = totale / partite. `data_dati` `AAAA-MM-GG` **precedente** alla partita. Meno di circa 8 partite: il dato è riportato verso zero con n/(n+6) (con 4 gare pesa 40%).
  - Esempio: «xG 68,5 e xGA 35,2 in 38 gare» → `xg=68.5, xga=35.2, partite=38` (nel blocco: `xG Fatti: 1.80 | xG Subiti: 0.93`).

### 4.12 Giocatori e minuti
- **a)** Marcatori, formazione attesa, assenti pesati, tiri dell'XI per il motore a eventi.
- **b)** Facoltativo.
- **c)** Automatico da Understat (rose, minuti, npxG/xA/tiri per 90, decadimento 240 giorni su 2 stagioni, shrinkage verso la media del ruolo POR/DIF/CEN/ATT); storico locale con `python -m tools.player_data 2025 2026`. `giocatori.csv` (`giocatore, squadra, stagione, ruolo, minuti, xg, xa, tiri, data_dati`) si importa ma **non è letto**.
- **d)** Letto da `players.py`/`lineup.py`. Sui gol attesi l'effetto della formazione è **neutro** (esponente ≈ 0); col motore a eventi pesa sui tiri (esponente +0,577) e sulla qualità per tiro (+0,420).
- **e)** Squadra senza dati Understat (coppe, campionati minori) → nessun fattore; i marcatori usano la quota con shrinkage.
- **Calibrazione:** tassi per 90 con decadimento 240 giorni su 2 stagioni; shrinkage n/(n+k) verso la media del ruolo con k minuti = 900 per POR/DIF/CEN/ATT; winsorizzazione ai percentili del ruolo (minimo 450 minuti); «sta performando» (gol − npxG) con k = 14,2 (giocatore) e 37,4 (squadra); rigori k_conversione 20, k_frequenza 30 partite. Sui gol effetto neutro. Marcatori: shrinkage verso `PRIOR_SHARE`, non verificati fuori campione (etichetta «poco verificata»).
- **Come preparare il valore:** nel CSV: `minuti` = **totale stagionale** (0-6000), `xg`/`xa`/`tiri` = **totali stagionali** (non per 90; il motore divide), `ruolo` ∈ POR/DIF/CEN/ATT, `stagione` `2025/26`, `data_dati` `AAAA-MM-GG`, squadra col nome dell'app. Giocatore con meno di 450 minuti: i tassi sono molto riportati verso il ruolo.
  - Esempio: «Lautaro, 2.650 minuti, xG 19,4» → `minuti=2650, xg=19.4` (= 0,66 xG per 90, calcolato dal motore).

### 4.13 Formazioni
- **a)** XI atteso rispetto all'XI tipo (ultimi 5 undici), rigorista, minuti attesi.
- **b)** Facoltativo.
- **c)** Dal report dell'Analista: righe `formazione_casa:` / `formazione_ospite:` con 11 nomi `| fonte: url`. `formazioni_assenti.csv` (`data, squadra, formazione, assenti`, nomi separati da `;`) si importa ma **non è letto**. Senza report: XI tipo.
- **d)** Letto da `lineup.py`, ma neutro sui gol; attivo sui tiri solo col motore a eventi.
- **e)** Si usa l'XI tipo, senza avviso di errore.
- **Calibrazione:** rapporto XI atteso / XI tipo → fattore attacco con esponente ≈ 0 (neutro sui gol); col motore a eventi tiri +0,577, npxG/tiro +0,420. Nessuna taratura finale; etichetta delle partite con formazione: quella dei gol (nessun miglioramento dichiarato).
- **Come preparare il valore:** nel report `formazione_casa: 11 nomi separati da virgola | fonte: https://...`; nel CSV `formazione` con nomi separati da `;` (11 nomi), `data` `AAAA-MM-GG`, `squadra` come nell'app. Casa e ospite su righe separate, non invertiti. Meno di 11 nomi: l'XI tipo resta.
  - Esempio: «Sommer, Pavard, Acerbi, …» → `Sommer;Pavard;Acerbi;Bastoni;Dumfries;Barella;Calhanoglu;Mkhitaryan;Dimarco;Thuram;Lautaro Martinez`.

### 4.14 Assenti
- **a)** Tolgono la loro quota di produzione, ridistribuita a chi entra (assenti PESATI).
- **b)** Facoltativo.
- **c)** Report: righe `assenti_casa:` / `assenti_ospite:`. Per i giocatori che Understat non conosce: `ASSENTI_PESATI:` (ruolo POR/DIF/CEN/ATT, peso 0-1, tetto 0,35, fonte obbligatoria). Un assente noto a Understat conta una volta sola.
- **d)** Il vecchio calcolo delle assenze (fase P) è **spento**. Gli assenti agiscono nella formazione (AL), neutra sui gol, e nei tiri del motore a eventi.
- **e)** Nessuna correzione.
- **Calibrazione:** quota di produzione tolta e ridistribuita (limiti 0,85-1,05 nel vecchio calcolo, spento); peso massimo 0,35 per `ASSENTI_PESATI`; neutro sui gol, attivo sui tiri nel motore a eventi. Etichetta: nessun miglioramento dichiarato.
- **Come preparare il valore:** `assenti_casa: Nome1; Nome2 | fonte: https://...`; `peso` tra 0 e 1 (0,12 = 12% della produzione offensiva), ruolo POR/DIF/CEN/ATT. Nel CSV `assenti` separati da `;`.
  - Esempio: «Zielinski e Bisseck fuori» → `Zielinski;Bisseck`; «attaccante che segna il 12% della produzione» → `peso: 0.12`.

### 4.15 Riposo e turnover
- **a)** Stanchezza e rotazioni.
- **b)** Facoltativo.
- **c)** Riposo: dal calendario (automatico); il `RIPOSO:` del report vale solo se manca il calendario. `TURNOVER: probabile|no` nel report, con fonte.
- **d)** Il riposo sui gol attesi è **spento** (`contesto_riposo`, non verificato). Il turnover riduce la forza dell'XI atteso (formazione), con effetto dichiarato in scheda.
- **e)** Nessun effetto.
- **Calibrazione:** riposo sui gol spento (`contesto_riposo` non verificato); turnover = 3 titolari sostituiti con i migliori di panchina (`n_rotazioni` 3) poi ^esponente come il resto della formazione. Etichetta: nessuna.
- **Come preparare il valore:** `RIPOSO: casa: 3 | ospite: 7 | fonte: https://...` = **giorni interi** dall'ultima partita; `TURNOVER: probabile` oppure `no`. Casa e ospite non invertiti.
  - Esempio: «ha giocato giovedì, oggi domenica» → `casa: 3`.

### 4.16 Stile di squadra

Dati di stile disponibili: da Understat (e dal proxy dai tiri) si calcolano le ultime 8 gare con media esponenziale, casa e trasferta separate, shrinkage verso il campionato, winsorizzazione ai percentili 2-98 (`config/stile.json`). Si importano in `stile_squadra.csv`.

| Dato | Serve a | Obbligatorio? | Origine | Lo legge il motore? |
|---|---|---|---|---|
| **Possesso** | etichetta «palla a terra / misto / diretto»; nel motore a eventi quota possesso | facoltativo | Understat (proxy: quota di tiri, terzili del campionato); `stile_squadra.csv` `possesso` (soglie StatsBomb 44,4%/52,2%) | **Calcolo attuale: no.** Motore a eventi: sì (importato > misurato > scheda) |
| **Passaggi** | solo descrizione | facoltativo | `stile_squadra.csv` `passaggi` | **No** |
| **Verticalità / transizione** | tiri da transizione | facoltativo | Understat; `tiri_transizione` importato | Il dato importato **sì** (riempie «non disponibile»); la verticalità come termine di stile solo nel motore a eventi |
| **Pressing / PPDA** | pressing alto/basso, falli | facoltativo | Understat (terzili del campionato, PPDA basso = pressing alto); `ppda` importato. `pressioni` senza passaggi avversari: non convertibile | Calcolo attuale: no. Motore a eventi: sì (PPDA importato > Understat > scheda) |
| **Altezza del blocco** | contrasto con attacchi verticali | facoltativo | Dalla scheda tattica (`PROFILO_TATTICO`, qualitativa) | Solo etichetta e avviso di contrasto; l'incrocio di stile è **spento** |
| **Difesa a uomo / zona** | incroci tattici (fasce contro difesa a uomo) | facoltativo | Solo scheda tattica a mano: **nessun dato aperto** la contiene (`non_possesso`) | **No**: neutro, la scheda dice «dato mancante, importalo in data/import/» |
| **Palle inattive** | quota di xG da palla inattiva, tipo di tiro | facoltativo | Understat stagionale; `quota_xg_palle_inattive` importato | Dato importato: letto dove manca; resto solo nel motore a eventi |
| **Cross** | corner e tiri di testa da cross | facoltativo | `stile_squadra.csv` `cross` (soglie 10,8/12,8) | Motore a eventi: sì. Calcolo attuale: solo se riempie il campo |
| **Moduli** | corsie: larghi in attacco e in difesa, scontro esterno-terzino | facoltativo | Campo modulo della scheda tattica; titolari Understat; StatsBomb per la stima (2015/16) | Solo motore a eventi, effetti piccoli (cross +0,039; scontro −0,010 con IC che tocca lo zero) |
| **Recuperi alti, reazioni per squadra** | stato di partita | facoltativo | Non misurabili nei dati aperti | **No**: neutri e dichiarati |

Come inserire lo stile a mano: blocchi `PROFILO_TATTICO:` nel report dell'Analista (un profilo senza link viene scartato; conferma in tabella prima del salvataggio). Per i numeri: `stile_squadra.csv` con `data_dati`. Un profilo qualitativo funge da *prior* dei numeri solo quando ci sono almeno 5 squadre con profilo e dati (`config/stile_prior.json`: oggi `null`).
- **Calibrazione:** finestra 8 gare con emivita 4, casa e trasferta separate; shrinkage n/(n+k) con k forma_reale 6, possesso 8, verticalità 8, fasce 10, pressing 8, aggressività 10, palle inattive 12; winsorizzazione 2-98 (minimo 30 valori). Nessuna taratura finale per mercato. Etichette di stile (alto/medio/basso) dai terzili del campionato o dalle soglie StatsBomb (`soglie_stile`: possesso 0,444/0,522, cross 10,8/12,8). Stile come input del motore a eventi: etichetta «poco verificata».
- **Come preparare il valore (CSV `stile_squadra.csv`, una riga per squadra e stagione):**
  - `possesso` in **percentuale 0-100** (non 0-1), media per partita; `quota_xg_palle_inattive` invece è **0-1**.
  - `ppda` = passaggi avversari / azioni difensive nella zona di pressing, 0-60; **più basso = pressing più alto**.
  - `pressioni` e `passaggi`, `tiri_area`, `tiri_fuori_area`, `corner`, `falli` = **medie per partita** (non totali). `xg`/`xga`/`partite` = **totali stagionali**.
  - Se la fonte dà valori per 90 minuti usali così; se dà totali dividi per `partite`.
  - Pochi dati (sotto 5-8 partite): inserisci comunque, ma lo shrinkage li riporta alla media del campionato; sotto 8 gare il dato pesa meno di metà.
  - Esempi «valore grezzo → valore da inserire»:
    - PPDA: «9,8» → `9.8` (punto decimale).
    - Possesso: «0,552» → `55.2`; «55,2%» → `55.2`.
    - Pressioni: «6.080 in 38 gare» → `160` (= 6080 / 38).
    - xG: «68,5 in 38 gare» → `xg=68.5, partite=38`.
    - Cross: «646 in 38 gare» → `17.0`.

### 4.17 Campionati e stagioni
- **a)** Dimensione del campione per Elo, forme, taratura e medie.
- **b)** Obbligatorio per partita: la competizione, scelta tra quelle di `COMPETITIONS` in `datasources/sources.py`.
- **c)** Automatico. Competizioni davvero coperte (codice football-data / Understat):

| Competizione | football-data.co.uk | Understat (xG, rose) |
|---|---|---|
| Serie A | I1 | sì |
| Premier League | E0 | sì |
| La Liga | SP1 | sì |
| Bundesliga | D1 | sì |
| Ligue 1 | F1 | sì |
| Primeira Liga | P1 | no |
| Eredivisie | N1 | no |
| Jupiler Pro League | B1 | no |
| Süper Lig | T1 | no |
| Super League Grecia | G1 | no |
| Premiership scozzese | SC0 | no |
| Champions League (coppa, `CUP_COMPETITIONS` = «CL») | via football-data.org (chiave in `st.secrets`) | no |

  Stagioni: la stagione parte il 1° luglio (`season_start`), codice football-data tipo `2526`. Si leggono la stagione corrente e le precedenti: 2 stagioni per i dati recenti (`recent`), 3 per l'archivio di stile (`load_store`) e per Understat nel builder, 6 per l'Elo calcolato dai risultati. Understat 2025-26 e 2026-27 sono in cache locale (`tools.player_data`).
  Le tarature (modello gol, ancoraggio, AM) sono state fatte su Serie A, Premier League, Liga, Bundesliga (2024-25 e 2025-26, fuori campione 2026-27; per i corner 2019-24 e 2026-27). Il banco AD ha usato anche SC0 e D2 (Bundesliga 2, **non** in `COMPETITIONS`: non selezionabile nell'app). Ligue 1 e i campionati senza Understat girano ma **senza taratura propria**: l'etichetta è più cauta.
- **d)** Letto.
- **e)** Competizione non in elenco o coppa tra campionati diversi → Elo e altri campi «MANCANTE», da compilare a mano; la simulazione manuale non si blocca.

---

## 5. Cosa fare a mano, in breve

1. **Sempre**: un blocco `CASA:` / `OSPITE:` / `ARBITRO:` valido, con Elo (o lasciarlo compilare in automatico).
2. **Molto utile**: incollare le quote (almeno 1X2 e Over/Under 2.5).
3. **Se vuoi più realismo con il Simulatore reale**: importare `stile_squadra.csv` con `xg`, `xga`, `ppda`, `possesso`, `cross`.
4. **Report dell'Analista** (facoltativo): correzioni, formazioni, assenti, riposo/turnover, schede tattiche, esiti con fonte.
5. **Dopo la partita**: gli esiti (anche corner, cartellini, primo tempo) alimentano il registro e la pagina Prestazioni. Solo con molte partite i giudizi diventano significativi.

---

## 5b. Limiti noti

- **Pagina «Partita singola»:** non carica formazione e stile per il motore a eventi. Solo la pagina **Oggi** costruisce `event_inputs` (formazione, corsie, stile, arbitro), perciò il «Simulatore reale» dà il meglio solo da lì.
- Giocatori, formazioni, assenti, arbitri e quote importati da CSV sono consultabili ma non letti dal motore (sezione 4.0).
- Peso 0,8 dell'ancoraggio di corner e cartellini dichiarato, non tarato; corner senza taratura finale.
- Marcatori non verificati fuori campione per la parte base; regole dell'Analista «da verificare» finché non ci sono ≥150 partite.
- Difesa a uomo/zona, recuperi alti, reazioni per squadra: nessun dato aperto, neutri.
- Prior dei profili qualitativi `null` finché mancano ≥5 squadre con profilo e dati.

---

## 6. Riferimenti

| Argomento | File |
|---|---|
| Misure prima/dopo del modello e tabella di calibrazione | `docs/BASELINE.md` |
| Importazione dati | `data/import/README.md`, `tools/importa_dati.py` |
| Report dell'Analista | `docs/formato_analista.md` |
| Selettore «Simulatore reale» | `engine_choice.py`, `docs/backtest/AK_motore_eventi_nuovo.md`, `AN_libero.md`, `AO_verifica.md` |
| Stile e forma reale | `docs/backtest/forma_reale.md`, `docs/stato/AD.md`, `AH.md` |
| Formazioni e giocatori | `docs/backtest/AL_giocatori.md`, `AO_giocatori.md`, `docs/stato/AL.md`, `AO.md` |
| Corsie | `docs/backtest/AO_corsie.md` |
| Taratura per mercato | `config/taratura.json`, `docs/stato/AM.md` |
