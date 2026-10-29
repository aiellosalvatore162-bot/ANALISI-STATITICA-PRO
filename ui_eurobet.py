"""Sezione Streamlit «Incolla quote Eurobet»: tabella delle voci lette, margini e applicazione ai campi quota.

Fase Z: le pagine incollate e le quote «sharp» dell'API stanno nell'archivio unico della giornata (``day_archive``,
``ui_quotes.archive()``): la scheda partita, la pagina Oggi, «Quote del giorno», i risultati esatti e il registro
leggono le stesse voci. Nessuna copia parallela in sessione.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Mapping

import pandas as pd
import streamlit as st

import day_archive
from eurobet import (
    DUPLICATE, NOT_SIMULATED, OK, SOURCE, EurobetPaste, apply_plan, format_margin, parse_eurobet, table_rows,
)


def _entry(home: str | None, away: str | None, *, create: bool = False) -> dict | None:
    from ui_quotes import archive

    if not home or not away:
        return None
    meta = st.session_state.get("match_meta") or {}
    day = meta.get("date") if isinstance(meta.get("date"), date) else None
    key = day_archive.find(archive(), home, away, day)
    if key is None and create:
        key = day_archive.ensure(archive(), home, away, day, meta.get("competition") or "")
    return archive()[key] if key else None


def pasted_text(home: str | None, away: str | None) -> str:
    entry = _entry(home, away)
    return day_archive.eurobet_text(entry) if entry else ""


def find_paste(home: str | None, away: str | None) -> EurobetPaste | None:
    entry = _entry(home, away)
    return day_archive.eurobet_paste(entry) if entry else None


def sharp_for(home: str | None, away: str | None) -> dict[str, float] | None:
    entry = _entry(home, away)
    return day_archive.sharp_odds(entry) if entry else None


def save_paste(home: str, away: str, text: str) -> None:
    from ui_quotes import archive

    entry = _entry(home, away, create=True)
    day_archive.set_eurobet_text(archive(), entry["key"], text)


def save_sharp(home: str, away: str, quotes: Mapping[str, float], label: str) -> None:
    """Quote di riferimento dell'API (Pinnacle o mediana) nell'archivio, come bookmaker «label»."""
    from quotes.model import QuoteMercato, now_iso
    from ui_quotes import archive

    entry = _entry(home, away, create=True)
    book = "pinnacle" if label.lower().startswith("pinnacle") else (label or "riferimento API")
    fresh = [QuoteMercato(f"{home} - {away}", key, None, key, float(price), book, "The Odds API", now_iso())
             for key, price in quotes.items() if price and float(price) > 1.0]
    day_archive.add_quotes(archive(), entry["key"], fresh, confirm=True)


def render_paste(home: str, away: str, key: str) -> EurobetPaste | None:
    """Campo di incolla (una o più pagine, qualsiasi ordine), tabella, margini e voci non simulate."""
    stored = pasted_text(home, away)
    text = st.text_area(
        "Incolla quote Eurobet", value=stored, height=160, key=f"{key}_text",
        help="Copia dal sito Eurobet una o più pagine quote della partita (principali, multigol, corner, "
             "cartellini) e incollale qui una dopo l'altra, in qualsiasi ordine.",
    )
    if not text.strip():
        if stored:
            save_paste(home, away, "")
            st.rerun()
        return None
    paste = parse_eurobet(text)
    changed = stored != text
    if changed:
        save_paste(home, away, text)
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


def sharp_notes(home: str, away: str) -> dict[str, str]:
    """Fase Y (0b): note «eurobet_vs_sharp» per le selezioni con quota Eurobet incollata e riferimento sharp."""
    from sharp_value import notes_for

    paste = find_paste(home, away)
    return notes_for(paste.odds(), sharp_for(home, away)) if paste is not None else {}


def render_sharp_value(home: str, away: str) -> None:
    """Eurobet contro il prezzo equo sharp, per selezione, e le quote sopra la soglia."""
    from sharp_value import above, compare, describe, threshold_pct

    paste, sharp = find_paste(home, away), sharp_for(home, away)
    if paste is None or not sharp:
        if paste is not None:
            st.caption("Confronto con lo sharp: manca la quota di riferimento dell'API per questa partita.")
        return
    rows = compare(paste.odds(), sharp)
    if not rows:
        return
    limit = threshold_pct()
    st.markdown("**Eurobet contro il prezzo equo sharp**")
    st.dataframe(pd.DataFrame([{**row, "Lettura": describe(row)} for row in rows]), hide_index=True, width="stretch")
    best = above(rows, limit)
    st.caption((f"Quote Eurobet sopra il prezzo equo sharp (≥ +{limit:g}%): "
                + ", ".join(f"{row['Selezione']} {row['Scarto %']:+.1f}%" for row in best)) if best else
               f"Nessuna quota Eurobet sopra il prezzo equo sharp di almeno {limit:g}%.")
