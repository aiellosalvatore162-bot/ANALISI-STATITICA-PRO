# Stato Fase AP (Simulatore unico per mercato) – FATTA

Ramo `fase-ap-simulatore-unico`. Ripresa: «Riprendi AP dallo stadio N».

## Stadio 1 – incroci di stile (FATTO, 31/10)
- Collegati al motore a eventi (`event_engine.apply_crossings`, `EventEngineParams.crossings`), spenti in `config/motore_eventi.json`.
- `python -m tools.ap_check` → `docs/backtest/AP_incroci.md`: 282 partite (un sesto del campione AO, ~23 min). Corner −0,00051 ± 0,00101,
  cartellini +0,00010 ± 0,00103 (2 e.s.): dentro l'errore → **nessun incrocio tenuto**. Limite: «cross contro blocco basso» non
  si attiva mai (le partite storiche hanno solo possesso e pressing).

## Stadio 2 – sorgente per famiglia (FATTO)
- `python -m tools.ap_scegli --salva` → `config/simulatore_unico.json` (campioni AK 1.454, AK nuovo 2.672, AO 563, pesi 1/e.s.²).
  Corner → motore a eventi (−0,00092 ± 0,00032, ECE 0,0204 → 0,0183), combo con corner seguono i corner (stesso campione);
  gol, tempi, cartellini, combo senza corner → calcolo attuale tarato AM.
- Limite: AK usa il modo «punteggi», AO il modo «libero» con dati: unione indicativa; corner significativo anche con i soli AK.

## Stadio 3-4 – selettore e test (FATTO)
- «Simulatore unico» in `engine_choice` (`UNIQUE`, `unified_table`), tabella in `ui_taratura.render_engine_choice`; predefinito invariato.
- Test: `test_simulatore_unico.py`.
