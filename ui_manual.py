"""«Modifica o completa i dati» nella pagina Oggi (fase R): integrazioni a mano partita per partita.

I manuali stanno in ``st.session_state["manual_fields"]`` (chiave data|Casa - Ospite, vedi ``manual_data``): un nuovo
«Prepara» o «Analizza» li applica sopra i dati automatici (manuale > automatico > proxy/stima) e non li tocca;
«Ripristina dati automatici» li toglie. «Applica e ricalcola» rifà SOLO quella partita, con lo stesso seed e senza
rete (usa la scheda automatica già costruita), e aggiorna la sua riga.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib

import pandas as pd
import streamlit as st

import manual_data
from datasources.builder import empty_sheet, missing_fields
from manual_data import apply_manual, has_manual
from today import Analysis, prepare, problem_rows, simulate

STORE_KEY = "manual_fields"
EXAMPLE = "CASA: Napoli | Elo: 1650\nOSPITE: Roma | Elo: 1620 | Forma: W-D-L-W-W"


def match_key(match) -> str:
    from match_memory import match_id

    return match_id(match.commence_time.date(), match.home, match.away)


def manual_store() -> dict:
    return st.session_state.setdefault(STORE_KEY, {})


def manual_for(match) -> dict | None:
    return manual_store().get(match_key(match))


def manual_items() -> list[dict]:
    """Voci per l'Excel della giornata (foglio tecnico): una per partita con almeno un manuale."""
    return [{"id": key, **entry} for key, entry in manual_store().items() if has_manual(entry)]


def restore_items(items: list[dict]) -> None:
    store = manual_store()
    for item in items:
        entry = {side: item.get(side, {}) for side in manual_data.SIDES}
        store[item["id"]] = {"partita": item.get("partita", ""), **entry}


# --- Ricalcolo di una sola partita -----------------------------------------------------------------------

def _widget_key(prefix: str, key: str) -> str:
    return f"{prefix}_{hashlib.md5(key.encode()).hexdigest()[:10]}"


def _auto_sheet(analysis: Analysis):
    return analysis.auto_sheet or empty_sheet(analysis.match.home, analysis.match.away, analysis.match.commence_time.date(),
                                              analysis.match.competition)


def recompute(index: int, settings: dict) -> Analysis:
    """Ricalcola la partita ``index`` di Oggi con i manuali correnti: una sola simulazione, stesso seed, nessuna rete."""
    from ui_eurobet import find_paste, sharp_for
    from ui_tactical import saved_sheets
    from ui_today import _analyses, _remember
    from eurobet import anchor_odds

    analyses = _analyses()
    old = analyses[index]
    simulations = old.config.simulations if old.config is not None else int(
        st.session_state.get("today_simulations") or settings["simulazioni"])
    fresh = prepare(old.match, None, old.odds_fields, simulations=simulations, competition=old.match.competition, settings=settings,
                    sheets=saved_sheets(), manual=manual_for(old.match), auto_sheet=_auto_sheet(old))
    if fresh.config is not None:
        fresh.flags, fresh.claude, fresh.claude_text = old.flags, old.claude, old.claude_text
        extra = None
        paste = find_paste(fresh.match.home, fresh.match.away)
        if paste is not None and not paste.empty:  # come «Analizza»: quote Eurobet per EV e ancoraggio, in una sola simulazione
            anchor, _ = anchor_odds({**fresh.odds, **paste.odds()}, sharp_for(fresh.match.home, fresh.match.away) or {}, paste)
            fresh.config = replace(fresh.config, anchor_odds=anchor)
            extra = paste.odds()
        try:
            simulate(fresh, flags=old.flags, claude=old.claude, extra_odds=extra, settings=settings)
            _remember(fresh)
        except Exception as exc:
            fresh.result = None
            from today import mark_failed

            mark_failed(fresh, "simulazione", "motore", f"simulazione non riuscita ({type(exc).__name__}: {str(exc)[:120]})")
    analyses[index] = fresh
    st.session_state["today_problems"] = problem_rows(analyses)
    st.session_state.pop("today_overrides", None)
    return fresh


def _notice(key: str, text: str) -> None:
    st.session_state.setdefault("manual_notice", {})[key] = text


def _apply(index: int, key: str, text_key: str, settings: dict) -> None:
    """Callback di «Applica e ricalcola»."""
    from ui_today import _analyses

    analysis = _analyses()[index]
    block = manual_data.parse_block(st.session_state.get(text_key, ""))
    problem = manual_data.check_teams(block, analysis.match.home, analysis.match.away)
    if problem or block.empty:
        _notice(key, problem or "Niente da applicare: nessun campo riconosciuto.")
        return
    entry = manual_store().get(key)
    new_values = manual_data.changes(block, _auto_sheet(analysis), entry)
    manual_store()[key] = manual_data.merge(entry, new_values, analysis.match.label)
    st.session_state[text_key] = ""
    fresh = recompute(index, settings)
    stored = sum(len(values) for values in new_values.values())
    _notice(key, f"Applicato: {stored} campi a mano. " + ("Partita analizzata." if fresh.ok else
                                                          f"Ancora non analizzata: {fresh.problem[2] if fresh.problem else 'in attesa'}"))


def _restore(index: int, key: str, settings: dict) -> None:
    """Callback di «Ripristina dati automatici»."""
    manual_store().pop(key, None)
    fresh = recompute(index, settings)
    _notice(key, "Dati automatici ripristinati. " + ("Partita ricalcolata." if fresh.ok else
                                                     f"Non analizzata: {fresh.problem[2] if fresh.problem else 'in attesa'}"))


# --- Interfaccia -----------------------------------------------------------------------------------------

def render_manual_section(analyses: list[Analysis], settings: dict) -> None:
    if not analyses:
        return
    st.subheader("Modifica o completa i dati")
    st.caption("Per ogni partita puoi incollare un blocco anche parziale (es. «CASA: Napoli | Elo: 1650»). I valori a mano "
               "restano finché non premi «Ripristina dati automatici»; precedenza: manuale > automatico > proxy/stima. "
               "Le partite con dati mancanti hanno l'expander aperto.")
    for index, analysis in enumerate(analyses):
        key = match_key(analysis.match)
        entry = manual_store().get(key)
        sheet = apply_manual(_auto_sheet(analysis), entry)
        lacking = missing_fields(sheet)
        incomplete = analysis.problem is not None and analysis.problem[0] in ("dati", "dati automatici")
        flags = ([f"MANCANTE: {', '.join(lacking[:3])}{'…' if len(lacking) > 3 else ''}"] if lacking else []) + \
                (["con dati a mano"] if has_manual(entry) else [])
        label = analysis.match.label + (" · " + " · ".join(flags) if flags else "")
        with st.expander(label, expanded=bool(incomplete or lacking)):
            notice = st.session_state.get("manual_notice", {}).pop(key, None)
            if notice:
                st.info(notice)
            if lacking:
                st.warning("Dati mancanti, mai inventati: " + "; ".join(lacking))
            if analysis.problem is not None and not lacking:
                st.warning(f"{analysis.problem[0]} · {analysis.problem[1]}: {analysis.problem[2]}")
            st.dataframe(pd.DataFrame(manual_data.field_table(sheet)), hide_index=True, width="stretch")
            text_key = _widget_key("manual_text", key)
            text = st.text_area("Blocco da incollare (anche parziale; le righe # sono ignorate)", key=text_key, height=110,
                                placeholder=EXAMPLE)
            ready = False
            if text.strip():
                block = manual_data.parse_block(text)
                problem = manual_data.check_teams(block, analysis.match.home, analysis.match.away)
                if problem:
                    st.warning(problem)
                elif block.empty and not (block.unrecognized or block.errors):
                    st.warning("Nessun campo riconosciuto nel blocco.")
                else:
                    st.markdown("**Anteprima**")
                    st.dataframe(pd.DataFrame(manual_data.preview(block, _auto_sheet(analysis), entry)), hide_index=True,
                                 width="stretch")
                    ready = not block.empty
            columns = st.columns(2)
            columns[0].button("Applica e ricalcola", key=_widget_key("manual_apply", key), type="primary", disabled=not ready,
                              on_click=_apply, args=(index, key, text_key, settings), width="stretch",
                              help="Ricalcola solo questa partita (stesso seed), senza rete.")
            columns[1].button("Ripristina dati automatici", key=_widget_key("manual_restore", key),
                              disabled=not has_manual(entry), on_click=_restore, args=(index, key, settings), width="stretch",
                              help="Toglie i valori a mano di questa partita e la ricalcola.")
