"""«Modifica o completa i dati» nella pagina Oggi (fase R): integrazioni a mano partita per partita.

Fase Z: i manuali stanno nell'archivio unico della giornata (``day_archive``, campo ``manual`` di ogni voce, chiave
data|Casa - Ospite; ``manual_store`` ne è una vista): un nuovo
«Prepara» o «Analizza» li applica sopra i dati automatici (manuale > automatico > proxy/stima) e non li tocca;
«Ripristina dati automatici» li toglie. «Applica e ricalcola» rifà SOLO quella partita, con lo stesso seed e senza
rete (usa la scheda automatica già costruita), e aggiorna la sua riga.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import replace
import hashlib

import pandas as pd
import streamlit as st

import day_archive
import manual_data
from datasources.builder import empty_sheet, missing_fields
from manual_data import apply_manual, has_manual
from today import Analysis, prepare, problem_rows, simulate

EXAMPLE = "CASA: Napoli | Elo: 1650\nOSPITE: Roma | Elo: 1620 | Forma: W-D-L-W-W"


def match_key(match) -> str:
    from match_memory import match_id

    return match_id(match.commence_time.date(), match.home, match.away)


class ManualView(MutableMapping):
    """Vista dei dati inseriti a mano dentro l'archivio della giornata: nessuna copia separata."""

    def __init__(self, store: dict) -> None:
        self.store = store

    def __getitem__(self, key: str) -> dict:
        entry = self.store.get(key)
        if entry is None or not has_manual(entry.get("manual")):
            raise KeyError(key)
        return entry["manual"]

    def __setitem__(self, key: str, value: dict) -> None:
        if key not in self.store:
            day, _, teams = key.partition("|")
            home, _, away = teams.partition(" - ")
            self.store[key] = day_archive.new_entry(key, home=home, away=away, commence=f"{day}T00:00:00")
        self.store[key]["manual"] = value

    def __delitem__(self, key: str) -> None:
        if key not in self:
            raise KeyError(key)
        self.store[key]["manual"] = {}

    def __iter__(self):
        return (key for key, entry in self.store.items() if has_manual(entry.get("manual")))

    def __len__(self) -> int:
        return sum(1 for _ in self)


def manual_store() -> ManualView:
    from ui_quotes import archive

    return ManualView(archive())


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
    from eurobet import anchor_odds
    from ui_quotes import entry_for
    from ui_tactical import saved_sheets
    from ui_today import _analyses, _remember

    analyses = _analyses()
    old = analyses[index]
    simulations = old.config.simulations if old.config is not None else int(
        st.session_state.get("today_simulations") or settings["simulazioni"])
    entry = entry_for(old.match.home, old.match.away, old.match.commence_time.date())
    fresh = prepare(old.match, None, old.odds_fields, simulations=simulations, competition=old.match.competition, settings=settings,
                    sheets=saved_sheets(), manual=manual_for(old.match), auto_sheet=_auto_sheet(old),
                    keep_samples=bool(entry and entry.get("to_play")))
    if fresh.config is not None:
        fresh.flags, fresh.claude, fresh.claude_text = old.flags, old.claude, old.claude_text
        if old.config is not None and old.config.style:   # il ricalcolo è offline: si tiene il profilo di stile già letto
            fresh.config = replace(fresh.config, style=old.config.style)
            fresh.style_profiles = old.style_profiles
        if old.config is not None and old.config.lineup:
            fresh.config = replace(fresh.config, lineup=old.config.lineup)
            fresh.lineup = old.lineup
        extra = day_archive.engine_odds(entry) if entry else {}
        if extra:  # come «Analizza»: quote dell'archivio per EV e ancoraggio, in una sola simulazione
            anchor, _ = anchor_odds({**fresh.odds, **extra}, day_archive.sharp_odds(entry), day_archive.eurobet_paste(entry))
            fresh.config = replace(fresh.config, anchor_odds=anchor)
        extra = extra or None
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
