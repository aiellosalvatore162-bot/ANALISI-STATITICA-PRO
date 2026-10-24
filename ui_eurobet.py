"""Sezione Streamlit «Incolla quote Eurobet»: tabella delle voci lette, margini e applicazione ai campi quota.

Le pagine incollate restano in ``st.session_state["eurobet_pastes"]`` per partita (nomi delle squadre):
la scheda partita, la pagina «Quote del giorno» e i risultati esatti leggono la stessa incollata. Le quote
«sharp» dell'API salvate alla compilazione del blocco stanno in ``st.session_state["odds_sharp"]``.
"""

from __future__ import annotations

from typing import Callable, Mapping

import pandas as pd
import streamlit as st

from datasources.names import match_team
from eurobet import (
    DUPLICATE, NOT_SIMULATED, OK, SOURCE, EurobetPaste, apply_plan, format_margin, parse_eurobet, table_rows,
)


def _find(store_name: str, home: str, away: str) -> dict | None:
    """Voce salvata per la stessa partita (nomi riconosciuti anche con grafie diverse)."""
    for entry in reversed(st.session_state.get(store_name, [])):
        if match_team(home, [entry["home"]]) and match_team(away, [entry["away"]]):
            return entry
    return None


def _store(store_name: str, home: str, away: str, **values) -> None:
    entries = [entry for entry in st.session_state.get(store_name, [])
               if not (match_team(home, [entry["home"]]) and match_team(away, [entry["away"]]))]
    st.session_state[store_name] = entries + [{"home": home, "away": away, **values}]


def find_paste(home: str | None, away: str | None) -> EurobetPaste | None:
    entry = _find("eurobet_pastes", home, away) if home and away else None
    return entry["paste"] if entry else None


def sharp_for(home: str | None, away: str | None) -> dict[str, float] | None:
    entry = _find("odds_sharp", home, away) if home and away else None
    return entry["quotes"] if entry else None


def save_sharp(home: str, away: str, quotes: Mapping[str, float], label: str) -> None:
    _store("odds_sharp", home, away, quotes=dict(quotes), label=label)


def render_paste(home: str, away: str, key: str) -> EurobetPaste | None:
    """Campo di incolla (una o più pagine, qualsiasi ordine), tabella, margini e voci non simulate."""
    entry = _find("eurobet_pastes", home, away)
    text = st.text_area(
        "Incolla quote Eurobet", value=entry["text"] if entry else "", height=160, key=f"{key}_text",
        help="Copia dal sito Eurobet una o più pagine quote della partita (principali, multigol, corner, "
             "cartellini) e incollale qui una dopo l'altra, in qualsiasi ordine.",
    )
    if not text.strip():
        if entry:
            st.session_state["eurobet_pastes"] = [item for item in st.session_state["eurobet_pastes"] if item is not entry]
            st.rerun()
        return None
    paste = parse_eurobet(text)
    changed = entry is None or entry["text"] != text
    _store("eurobet_pastes", home, away, text=text, paste=paste)
    if changed:
        st.rerun()  # le sezioni sopra (costo dei mercati API, ancoraggio) devono vedere la nuova incollata
    if paste.empty:
        st.warning("Nessuna voce Eurobet riconosciuta nel testo incollato.")
        return paste
    rows = pd.DataFrame(table_rows(paste))
    counts = rows["Stato"].value_counts()
    st.caption(f"{home} - {away}: " + " · ".join(f"{state} {counts[state]}" for state in counts.index)
               + ". «Non simulato» = nessun campo nel simulatore: non entra in EV, ancoraggio o registro.")
    shown = rows[rows["Stato"] != NOT_SIMULATED]
    st.dataframe(shown, hide_index=True, width="stretch",
                 column_config={"Quota": st.column_config.NumberColumn(format="%.2f")})
    margins = paste.margins()
    used = {quote.section for quote in paste.quotes if quote.status in (OK, DUPLICATE)}
    if margins:
        st.caption("Margine Eurobet: " + " · ".join(f"{section.lower()} {format_margin(value)}"
                                                       for section, value in margins.items() if section in used))
    with st.expander(f"Voci non simulate ({int(counts.get(NOT_SIMULATED, 0))}) e sezioni sconosciute", expanded=False):
        st.dataframe(rows[rows["Stato"] == NOT_SIMULATED], hide_index=True, width="stretch",
                     column_config={"Quota": st.column_config.NumberColumn(format="%.2f")})
        other = {section: value for section, value in margins.items() if section not in used}
        if other:
            st.caption("Margine delle altre sezioni: " + " · ".join(f"{s.lower()} {format_margin(v)}" for s, v in other.items()))
        if paste.unknown_sections:
            st.caption("Sezioni sconosciute, ignorate: " + ", ".join(paste.unknown_sections))
    combo = [section for section, flag in paste.combo_sections.items() if flag]
    if combo:
        st.caption("Combinabili nel Combo Builder: " + ", ".join(section.lower() for section in combo)
                   + ". Le multiple combinate si costruiscono solo con questi mercati.")
    st.session_state["eurobet_combo_markets"] = sorted(paste.combinable())
    return paste


def render_apply(paste: EurobetPaste, current: Mapping[str, float], set_field: Callable[[str, float], None],
                 key: str) -> None:
    """Pulsante che copia le quote nei campi: i campi già valorizzati cambiano solo dopo conferma."""
    plan = apply_plan(paste, current)
    if not plan["fill"] and not plan["conflicts"]:
        st.caption("Nessuna quota Eurobet per i campi del simulatore.")
        return
    replace = False
    if plan["conflicts"]:
        detail = ", ".join(f"{market} {float(current[market]):.2f} → {price:.2f}" for market, price in list(plan["conflicts"].items())[:8])
        replace = st.checkbox(f"Sostituisci anche le {len(plan['conflicts'])} quote già presenti con quelle Eurobet "
                              f"({detail}{'…' if len(plan['conflicts']) > 8 else ''})", key=f"{key}_replace")
    if st.button(f"Applica le quote Eurobet ai campi ({len(plan['fill'])} campi"
                 + (f" + {len(plan['conflicts'])} da sostituire" if plan["conflicts"] else "") + ")", key=f"{key}_apply"):
        chosen = {**plan["fill"], **(plan["conflicts"] if replace else {})}
        for market, price in chosen.items():
            set_field(market, price)
        skipped = 0 if replace else len(plan["conflicts"])
        st.success(f"{len(chosen)} quote Eurobet applicate ({SOURCE})."
                   + (f" {skipped} campi già valorizzati lasciati com'erano." if skipped else ""))
