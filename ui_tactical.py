"""Interfaccia delle schede tattiche (fase Q): richiesta a Claude, conferma, schede salvate, scheda della partita.

Le schede stanno in ``st.session_state["tactical_sheets"]`` (dizionari di ``TacticalSheet``), finiscono nel foglio
«Schede tattiche» dell'Excel della giornata e tornano con «Riprendi da file».
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from tactical_sheets import (
    CHOICES, MatchEffects, PROFILE_FORMAT, TacticalSheet, contrasts, data_hints, load_rules, match_effects,
    matchup_text, parse_profiles, profile_prompt, sheet_lines, upsert,
)

STATE_KEY = "tactical_sheets"
# Colonne modificabili nella tabella di conferma: nome nella tabella -> campo della scheda.
EDITABLE = {"Squadra": "team", "Allenatore": "allenatore", "Dal": "dal", "Modulo": "modulo", "Alternativo": "alternativo",
            "Transizione": "transizione", "Gestione blocco basso": "gestione_blocco_basso", "Non possesso": "non_possesso",
            "Blocco": "blocco", "Pressing": "pressing", "Fasce/cross": "fasce_cross", "Adattabilità": "adattabilita",
            "Contro forti": "contro_forti", "Contro deboli": "contro_deboli", "Se in svantaggio": "se_in_svantaggio",
            "Se in vantaggio": "se_in_vantaggio", "Confidenza": "confidenza", "Note": "note", "Fonti": "fonti"}


def saved_sheets() -> list[dict]:
    return [item for item in st.session_state.get(STATE_KEY, []) if isinstance(item, dict) and item.get("team")]


def current_effects(home: str | None, away: str | None) -> MatchEffects:
    """Schede salvate della partita ed effetti (incroci accesi, reazioni, cambio allenatore)."""
    if not home or not away:
        return MatchEffects(None, None, {}, [], (1.0, 1.0, 1.0, 1.0))
    return match_effects(saved_sheets(), home, away)


def style_hints(team: str) -> dict[str, str]:
    """Indizi dai profili di stile già in cache (nessun download): pressing, blocco, transizione."""
    try:
        from datasources.sources import COMPETITIONS
        from datasources.style import ProfileStore, find_profile, radar_percentiles
        from ui_data import source_cache

        store = ProfileStore(source_cache())
        for league in COMPETITIONS:
            profiles = store.load(league, timedelta(days=30))
            profile = find_profile(profiles, team) if profiles else None
            if profile is not None:
                return data_hints(radar_percentiles(profile))
    except Exception:  # gli indizi sono facoltativi: senza cache o con errori si va avanti senza
        return {}
    return {}


def _table(sheets: list[TacticalSheet]) -> pd.DataFrame:
    rows = []
    for sheet in sheets:
        values = sheet.to_dict()
        row = {label: values[name] for label, name in EDITABLE.items()}
        row["Fonti"] = " ".join(sheet.fonti)
        row["Dal"] = sheet.dal or ""
        rows.append(row)
    return pd.DataFrame(rows, columns=list(EDITABLE))


def _from_table(frame: pd.DataFrame, origin: str) -> tuple[list[TacticalSheet], list[str]]:
    sheets, warnings = [], []
    for row in frame.to_dict("records"):
        team = str(row.get("Squadra") or "").strip()
        if not team:
            continue
        values = {}
        for label, name in EDITABLE.items():
            value = row.get(label)
            value = None if value is None or (isinstance(value, float) and pd.isna(value)) else value
            if name == "fonti":
                values[name] = str(value or "").split()
            elif name == "transizione":
                values[name] = int(value) if value not in (None, "") and 1 <= int(value) <= 5 else None
            elif name == "dal":
                text = str(value or "").strip()
                try:
                    values[name] = date.fromisoformat(text).isoformat() if text else None
                except ValueError:
                    warnings.append(f"{team}: data «{text}» non valida (aaaa-mm-gg), ignorata.")
                    values[name] = None
            elif name in CHOICES:
                values[name] = value if value in CHOICES[name] else None
            else:
                values[name] = str(value or "")
        sheets.append(TacticalSheet(**values, origine=origin, aggiornata=date.today().isoformat()))
    return sheets, warnings


def _column_config() -> dict:
    config = {label: st.column_config.SelectboxColumn(label, options=list(CHOICES[name]))
              for label, name in EDITABLE.items() if name in CHOICES}
    config["Transizione"] = st.column_config.NumberColumn("Transizione", min_value=1, max_value=5, step=1,
                                                          help="1 = orizzontale e paziente, 5 = verticale")
    config["Dal"] = st.column_config.TextColumn("Dal", help="Data di arrivo dell'allenatore, aaaa-mm-gg")
    return config


def render_manager(teams: list[str]) -> None:
    """Sezione della pagina Oggi: profili per Claude, conferma, schede salvate modificabili."""
    st.subheader("Schede tattiche")
    st.caption("Profilo tattico per squadra: Claude prepara una bozza con le fonti, tu la confermi o la correggi. "
               "Le regole di incrocio cambiano i calcoli solo se verificate fuori campione (oggi: "
               f"{sum(rule.get('attiva', False) for rule in load_rules()['regole'])} accese su "
               f"{len(load_rules()['regole'])}); l'allenatore nuovo cambia i pesi delle statistiche.")
    known = sorted({sheet["team"] for sheet in saved_sheets()})
    chosen = st.multiselect("Squadre", sorted(set(teams) | set(known)), key="tactical_teams",
                            placeholder="Scegli le squadre per cui preparare la scheda")
    extra = st.text_input("Altre squadre (separate da virgola)", key="tactical_extra")
    chosen = list(dict.fromkeys([*chosen, *[name.strip() for name in extra.split(",") if name.strip()]]))
    if st.button("Prepara richiesta profili per Claude", disabled=not chosen, key="tactical_prompt_button"):
        st.session_state["tactical_prompt"] = profile_prompt(chosen, {team: style_hints(team) for team in chosen})
    if st.session_state.get("tactical_prompt"):
        st.code(st.session_state["tactical_prompt"], language="text")
    with st.expander("Formato del profilo (anche a mano)"):
        st.code(PROFILE_FORMAT, language="text")
    answer = st.text_area("Incolla la risposta di Claude (blocchi PROFILO_TATTICO)", key="tactical_answer", height=160)
    if answer.strip():
        sheets, warnings = parse_profiles(answer)
        for warning in warnings:
            st.warning(warning)
        for sheet in sheets:
            for warning in contrasts(sheet, style_hints(sheet.team)):
                st.warning(f"Contrasto con i dati: {warning}")
        if sheets:
            st.caption("Controlla e correggi prima di salvare: nulla cambia finché non premi «Conferma e salva».")
            edited = st.data_editor(_table(sheets), hide_index=True, width="stretch", key=f"tactical_confirm_{hash(answer)}",
                                    column_config=_column_config())
            if st.button("Conferma e salva le schede", type="primary", key="tactical_save"):
                confirmed, problems = _from_table(edited, "Claude, confermata")
                for problem in problems:
                    st.warning(problem)
                st.session_state[STATE_KEY] = upsert(saved_sheets(), confirmed)
                st.success(f"{len(confirmed)} schede salvate.")
    render_saved()


def render_saved() -> None:
    sheets = [TacticalSheet.from_dict(item) for item in saved_sheets()]
    with st.expander(f"Schede salvate ({len(sheets)})", expanded=False):
        st.caption("Modificabili: aggiungi una riga per una scheda a mano, svuota «Squadra» per toglierla.")
        edited = st.data_editor(_table(sheets), hide_index=True, width="stretch", num_rows="dynamic",
                                key="tactical_saved_editor", column_config=_column_config())
        if st.button("Salva le modifiche", key="tactical_saved_save"):
            previous = {sheet.team: sheet for sheet in sheets}
            updated, problems = _from_table(edited, "manuale")
            for problem in problems:
                st.warning(problem)
            # Le schede non toccate tengono origine e data.
            kept = [previous[sheet.team] if sheet.team in previous and _same(sheet, previous[sheet.team]) else sheet
                    for sheet in updated]
            st.session_state[STATE_KEY] = [sheet.to_dict() for sheet in kept]
            st.rerun()


def _same(first: TacticalSheet, second: TacticalSheet) -> bool:
    ignore = {"origine", "aggiornata"}
    return {k: v for k, v in first.to_dict().items() if k not in ignore} == {k: v for k, v in second.to_dict().items()
                                                                              if k not in ignore}


def render_match(effects: MatchEffects, elo: tuple[float, float] | None = None) -> None:
    """Riquadro nella pagina Partita: schede delle due squadre, comportamento contro questo avversario, incroci."""
    if not effects.any_sheet:
        return
    for note in effects.analyst_notes:
        st.warning(f"Regola dell'Analista applicata, effetto piccolo (0,95-1,05): {note}. Si misura sullo storico "
                   "proprio nella pagina Prestazioni (sezione «Regole dell'Analista»).")
    with st.expander("Schede tattiche", expanded=False):
        for sheet, own, other in ((effects.home, 0, 1), (effects.away, 1, 0)):
            if sheet is None:
                continue
            st.markdown("\n".join(f"- {line.strip()}" for line in sheet_lines(sheet)))
            if elo is not None:
                text = matchup_text(sheet, elo[own], elo[other])
                if text:
                    st.caption(f"{sheet.team} {text}")
            for warning in contrasts(sheet, style_hints(sheet.team)):
                st.warning(f"Contrasto con i dati: {warning}")
            st.caption(f"Origine: {sheet.origine}" + (f" · aggiornata il {sheet.aggiornata}" if sheet.aggiornata else "")
                       + (f" · fonti: {' '.join(sheet.fonti)}" if sheet.fonti else ""))
        if effects.notes:
            st.info("Incroci applicati: " + "; ".join(effects.notes))
        else:
            st.caption("Nessun incrocio di stile acceso per questa partita (le regole cambiano i calcoli solo se "
                       "verificate fuori campione).")
        if effects.reactions != (1.0, 1.0, 1.0, 1.0):
            st.caption("Reazioni allo stato del punteggio lette dalle schede: contano solo con il motore minuto per "
                       "minuto acceso.")
