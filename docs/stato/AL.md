# Stato Fase AL (formazioni e giocatori)

Ramo: `fase-al-formazioni-giocatori`. `docs/FONTI.md` non esiste (Fase AC non fatta): solo Understat (cache), CSV e report dell'Analista.

## Stadio 0 – riuso
- Dati partita-per-partita dei giocatori (rosa, minuti, posizione, xG, xA, tiri, rigori): `tools/player_data.py` → `data/cache/fase_p/giocatori_<lega>_<anno>.json.gz` (2025 = 2025/26, 2026 = 2026/27, aggiornati al 27/10).
- `absences.py` (Fase P: `role_of`, `absence_factor`, assenze da Claude/Analista, spento in config) → AL lo SOSTITUISCE (stessa grandezza npxG+xA, niente doppia conta).
- `scorers.py` (rigorista, quota xG), `claude_bridge.py` (righe assenti_casa/assenti_ospite), `style_profile.py` (AD: forma reale = xG−xGA; la finalizzazione gol−xG NON c'è: è la parte che AL aggiunge), `tools/backtest_wf.py` (banco AD).

## Stadi
1. `players.py` + `config/giocatori.json`: FATTO
2. `lineup.py` (XI atteso, minuti, fattori, rigorista, performando, `get_lineup_params`): FATTO
3. Backtest/stime `tools/lineup_check.py` → `docs/backtest/AL_giocatori.md`: FATTO (1606 partite, 4 campionati, 2025/26-2026/27). Esponente attacco γ = -0.097 ± 0.209 → usato 0; pesi difesa non stimabili (z < 2) → solo etichetta; k performando 14.2 (giocatore), 37.4 (squadra)
4. Motore (`MatchConfig.lineup`, ledger `formazione`), `today._attach_lineup`, righe `formazione_casa/ospite` in claude_bridge, `ui_lineup.py`, guardia in `absences.is_active`: FATTO
5. `test_lineup.py`, suite, merge, push: vedi git log

## Decisioni
- Il fattore attacco agisce sul modello PRIMA dell'ancoraggio al mercato (le quote già contengono le formazioni).
- «Sta performando» (gol−xG) non entra in λ (l'attacco è già solo xG): va ai probabili marcatori/conversione e all'etichetta.
