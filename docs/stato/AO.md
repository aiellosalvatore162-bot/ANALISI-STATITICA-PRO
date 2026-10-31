# Stato Fase AO (tutti i dati nel motore a eventi)

Ramo `fase-ao-dati-motore-eventi` (da `main` dopo la fase AN).

## Stadio 1 – Inventario (FATTO)

Punto d'ingresso unico del motore a eventi: `engine.event_engine_sample` → `event_engine.TeamInput` (gol attesi, `profile`
del dizionario tattico, `module`, scale del vincolo di coerenza) + `RefereeInput` (facoltativo). Prima della fase AO
`MatchConfig.event_inputs` NON veniva riempito da nessuna parte dell'app: il motore vedeva solo λ/μ, medie e stato della partita.

| Dato | Dove vive | Motore a eventi prima di AO | Dove va collegato |
|---|---|---|---|
| Giocatori (tassi npxG/xA/tiri per 90, ruolo) | `players.py` (Understat `data/cache/fase_p`), importati `data_import` «giocatori» | non letto (solo λ/μ tramite `MatchConfig.lineup`, esponente ≈ 0) | tassi e qualità dei tiri per squadra (`TeamInput.shot_scale`/`quality_scale`) |
| Formazione attesa / XI tipo | `lineup.team_lineup` | non letto | idem (rapporto XI atteso / XI tipo su tiri e npxG/tiro) |
| Assenti pesati | `lineup` (assenti + `ASSENTI_PESATI`), `absences.py` | non letto | tolgono la loro quota di tiri, ridistribuita a chi entra (già nel calcolo dei minuti attesi) |
| Difesa / portiere | `lineup` quota minuti mancanti POR/DIF/CEN | non letto (pesi = 0 nella AL) | tiri e qualità concessi all'avversario |
| Riposo / turnover | `MatchConfig.rest_days` (v2 spento), turnover in `lineup` | non letto | turnover passa dalla formazione; riposo resta su λ/μ (spento: non verificato nella P) |
| Moduli e ruoli per corsia | `formation.py`, campo modulo della scheda tattica | letto solo con `lanes=True` (spento, pesi dichiarati) | corner da cross e tiri di testa, scontro esterno-terzino |
| Arbitro | `MatchConfig.referee_*_avg` (blocco), `referee_stats.py`, `motore_eventi.arbitri` (k), importati «arbitri» | `RefereeInput` previsto ma mai passato; gialli già dentro il bersaglio del vincolo | falli del motore (gialli restano riportati al bersaglio, che contiene già l'arbitro) |
| Stile: possesso, verticalità, PPDA, altezza blocco, pressioni, passaggi | `style_profile.py` (quota_tiri, deep, ppda, deep_concessi…), importati «stile» | non letto (solo `forma_reale` su λ/μ) | termini del dizionario (`possesso`, `pressing`, `verticalizzazione`, `altezza_linea`) con beta stimati |
| Difesa a uomo/zona, recuperi alti, reazioni | `config/dizionario_tattico.json` (beta null) | null → neutro | neutri finché manca il dato («dato mancante, importalo in data/import/») |
| Palle inattive, transizioni, cross | `style_profile` (stagionali Understat o importati) | non letto | `palla_inattiva`, `transizione`, `testa_da_cross` per tipo di tiro |
| Profilo qualitativo (scheda tattica) | `tactical_sheets`, `tactical_dictionary.from_sheet` | non letto (event_inputs vuoto) | `TeamInput.profile` |
| Quote di chiusura | ancoraggio (`final_goal_rates`, `CountAnchorParams`) | entrano tramite λ/μ e i bersagli del vincolo | invariato |

## Stadio 2 – Giocatori e formazione nel motore (FATTO)
- `lineup.team_lineup` restituisce `eventi`: rapporto XI atteso / XI tipo dei tiri (assenti esterni e turnover tolgono tiri) e
  dell'npxG per tiro, quote di minuti mancanti POR/DIF/CEN. Gli assenti tolgono la loro quota e i minuti vanno a chi entra
  (già nei minuti attesi della AL).
- Stima `python -m tools.ao_giocatori --salva` (parziali in `data/cache/ao/`, ~15 min) → `config/giocatori.json` →
  `motore_eventi`, report `docs/backtest/AO_giocatori.md`. Understat 2025-26, 3.677 squadre-partita (1.839 partite, 5
  campionati), quasi-Poisson con offset (XI tipo × concessioni dell'avversario), errori robusti per partita:
  - tiri: esponente attacco **+0,577** (IC 95% +0,424…+0,729); difesa (per quota mancante nell'avversario, centrata sulla media
    0,09/0,25/0,27) POR +0,032 (−0,008…+0,073), DIF +0,044 (−0,014…+0,101), CEN +0,060 (+0,002…+0,119);
  - npxG per tiro: attacco **+0,420** (+0,164…+0,676); POR +0,038 (−0,011…+0,088), DIF −0,014 (−0,083…+0,055), CEN +0,022
    (−0,051…+0,095). Valori usati come stimati (anche quelli vicini a zero), intervallo nella scheda.
- `event_engine.TeamInput.shot_scale`/`quality_scale` (tiri non su rigore e conversione), `type_scale`, `corner_cross_scale`;
  `event_inputs.py` costruisce `MatchConfig.event_inputs` da tutti i dati (`today.match_event_inputs`, chiamato in
  `today.simulate`). Sui gol, col motore a eventi acceso, `event_inputs["formazione"]` (tiri × qualità dell'XI, difesa dei
  reparti) SOSTITUISCE il fattore della AL prima dell'ancoraggio (λ resta il vincolo del motore a eventi; i tiri seguono).
- Prova: XI senza i due attaccanti (tiri ×0,75, qualità ×0,85) → tiri 15,2 → 12,6, xG 1,48 → 1,17, xG/tiro in calo.
