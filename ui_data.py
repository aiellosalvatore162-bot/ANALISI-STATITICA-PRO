"""Sezioni Streamlit del livello dati: compilazione automatica e «Crea partita».

L'aggiornamento avviene solo all'apertura della sezione o alla selezione della
partita (su Streamlit Cloud l'app si addormenta e non può aggiornarsi da sola):
i dati più vecchi della soglia scelta vengono riscaricati prima di compilare
il blocco; «Aggiorna dati» forza il download.
"""

from __future__ import annotations

from datetime import date, timedelta

import math

import altair as alt
import pandas as pd
import streamlit as st

from datasources.builder import (
    ODDS_FIELDS, DataProvider, MatchSheet, apply_edits, empty_sheet, missing_fields, plausibility_warnings,
    provenance_rows, render_block,
)
from datasources.cache import SourceCache
from datasources.sources import COMPETITIONS, CUP_COMPETITIONS, football_data_org_key
from datasources.style import (
    EXCLUDED_METRICS, METRIC_BY_KEY, ProfileStore, StyleProfile, assign_archetype, describe, find_profile, load_archetypes,
    radar_percentiles,
)


@st.cache_resource(show_spinner=False)
def source_cache() -> SourceCache:
    return SourceCache()


def _settings(prefix: str) -> dict:
    with st.expander("Impostazioni dati", expanded=False):
        columns = st.columns(3)
        hours = columns[0].number_input("Aggiorna se più vecchi di (ore)", 1, 168, 24, key=f"{prefix}_hours",
                                        help="Soglia di età dei dati in cache per squadre e arbitri.")
        matches = columns[1].number_input("Ultime N partite", 3, 38, 10, key=f"{prefix}_matches")
        half_life = columns[2].number_input("Emivita recenza (partite)", 1.0, 38.0, 5.0, 0.5, key=f"{prefix}_half_life",
                                            help="La partita giocata N gare prima pesa la metà dell'ultima.")
    return {"max_age": timedelta(hours=int(hours)), "matches": int(matches), "half_life": float(half_life)}


def _provider(settings: dict, force: bool) -> DataProvider:
    provider = DataProvider(source_cache(), max_age=settings["max_age"], matches=settings["matches"],
                            half_life=settings["half_life"], football_data_key=football_data_org_key())
    if force:
        provider.refresh()
    return provider


def _highlight(row: pd.Series) -> list[str]:
    colors = {"MANCANTE": "background-color: rgba(255,110,104,.35)", "da verificare": "background-color: rgba(244,201,93,.30)"}
    return [colors.get(row.get("Stato"), "")] * len(row)


def show_provenance(rows: list[dict], warnings: list[str]) -> None:
    """Valori con fonte, data di aggiornamento e ultima partita inclusa; mancanti evidenziati."""
    if warnings:
        st.warning("\n".join(f"- {warning}" for warning in warnings))
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(frame.style.apply(_highlight, axis=1), hide_index=True, width="stretch")


def use_in_simulator(block: str) -> None:
    """Porta il blocco nel copia-incolla; la modalità cambia al giro successivo, prima del selettore."""
    st.session_state["input_text"] = block
    st.session_state["input_touched"] = True
    st.session_state["pending_input_mode"] = "Copia-incolla"
    st.rerun()


def _use_block(sheet: MatchSheet) -> None:
    st.session_state["auto_sheet_rows"] = provenance_rows(sheet)
    st.session_state["auto_sheet_warnings"] = sheet.warnings
    use_in_simulator(render_block(sheet))


def render_automatic() -> None:
    """Scelta di competizione e partita (o due squadre) e compilazione del blocco."""
    settings = _settings("auto")
    competitions = list(COMPETITIONS) + (list(CUP_COMPETITIONS) if football_data_org_key() else [])
    if not football_data_org_key():
        st.caption("Champions League dal calendario non disponibile: chiave FOOTBALL_DATA_KEY non configurata "
                   "in st.secrets. Puoi comunque scrivere le due squadre.")
    refresh = st.button("Aggiorna dati", key="auto_refresh", help="Riscarica ora i dati delle fonti, ignorando la cache.")
    source_choice = st.radio("Partita", ["Dal calendario", "Scrivo le due squadre"], horizontal=True, key="auto_source")
    home = away = competition = referee = None
    match_date = date.today()
    if source_choice == "Dal calendario":
        competition = st.selectbox("Competizione", competitions, key="auto_competition")
        with st.spinner("Carico il calendario…"):
            provider = _provider(settings, refresh)
            fixtures = provider.fixtures()
        if provider.warnings:
            st.caption(" · ".join(dict.fromkeys(provider.warnings)))
        options = fixtures[fixtures["competition"] == competition] if not fixtures.empty else fixtures
        if options.empty:
            st.info("Nessuna partita in calendario per questa competizione nei prossimi giorni: scrivi le due squadre.")
        else:
            labels = [f"{row.date:%d/%m} · {row.home_team} - {row.away_team}" for row in options.itertuples()]
            chosen = st.selectbox("Partita", range(len(labels)), format_func=labels.__getitem__, key="auto_fixture")
            row = options.iloc[chosen]
            home, away, match_date = row["home_team"], row["away_team"], row["date"].date()
            referee = row.get("referee") if pd.notna(row.get("referee")) else None
    else:
        columns = st.columns(3)
        home = columns[0].text_input("Squadra casa", key="auto_home")
        away = columns[1].text_input("Squadra ospite", key="auto_away")
        match_date = columns[2].date_input("Data", value=date.today(), key="auto_date")
        referee = st.text_input("Arbitro (facoltativo)", key="auto_referee") or None
    if st.button("Compila il blocco", type="primary", disabled=not (home and away), key="auto_build") or (refresh and home and away):
        with st.spinner("Scarico e calcolo i dati…"):
            sheet = _provider(settings, refresh).build(home, away, match_date=match_date, competition=competition, referee=referee)
        _use_block(sheet)


def render_create() -> None:
    """Partita personalizzata: compilazione parziale, completamento a mano, salvataggio."""
    settings = _settings("create")
    columns = st.columns(4)
    home = columns[0].text_input("Squadra casa", key="create_home")
    away = columns[1].text_input("Squadra ospite", key="create_away")
    match_date = columns[2].date_input("Data", value=date.today(), key="create_date")
    competition = columns[3].text_input("Competizione (facoltativa)", key="create_competition") or None
    buttons = st.columns(2)
    search = buttons[0].button("Cerca i dati disponibili", disabled=not (home and away), key="create_search")
    refresh = buttons[1].button("Aggiorna dati", disabled=not (home and away), key="create_refresh")
    if search or refresh:
        with st.spinner("Cerco i dati delle due squadre…"):
            sheet = _provider(settings, refresh).build(home, away, match_date=match_date, competition=competition)
        st.session_state["create_sheet"] = sheet
    sheet: MatchSheet | None = st.session_state.get("create_sheet")
    if sheet is None and home and away:
        sheet = empty_sheet(home, away, match_date, competition)
    if sheet is not None:
        rows = provenance_rows(sheet)
        present = {(row["Soggetto"], row["Campo"]) for row in rows}
        rows += [{"Soggetto": "Quote", "Campo": label, "Valore": "", "Fonte": "facoltativa", "Aggiornato": "—",
                  "Ultima partita inclusa": "—", "Nota": "quota bookmaker (facoltativa)", "Stato": "facoltativa"}
                 for _, label in ODDS_FIELDS if ("Quote", label) not in present]
        rows = [row for row in rows if not str(row["Campo"]).startswith("(info)")]
        for row in rows:
            if row["Stato"] == "MANCANTE":
                row["Stato"] = "⚠️ MANCANTE"
        st.markdown("**Valori della partita** · completa i campi ⚠️ MANCANTE nella colonna Valore")
        if sheet.warnings:
            st.warning("\n".join(f"- {warning}" for warning in sheet.warnings))
        edited = st.data_editor(
            pd.DataFrame(rows), hide_index=True, width="stretch", key="create_editor",
            disabled=["Soggetto", "Campo", "Fonte", "Aggiornato", "Ultima partita inclusa", "Nota", "Stato"],
        )
        updated_sheet, errors = apply_edits(sheet, edited.to_dict("records"))
        updated_sheet.origin = "inserimento manuale"
        block = render_block(updated_sheet)
        for error in errors:
            st.error(error)
        still_missing = missing_fields(updated_sheet)
        if still_missing:
            st.warning("Campi ancora mancanti: " + ", ".join(still_missing))
    else:
        block = ""
    pasted = st.text_area("Oppure incolla un blocco nel formato del parser", key="create_paste", height=160)
    if pasted.strip():
        block = pasted
    if block:
        warnings = plausibility_warnings(block)
        if warnings:
            st.warning("Controllo di plausibilità:\n" + "\n".join(f"- {warning}" for warning in warnings))
        else:
            st.success("Controllo di plausibilità superato.")
        st.code(block, language="text")
        actions = st.columns(2)
        if actions[0].button("Usa nel simulatore", key="create_use", width="stretch"):
            st.session_state.pop("auto_sheet_rows", None)
            use_in_simulator(block)
        if actions[1].button("Salva partita (inserita manualmente)", key="create_save", width="stretch",
                             disabled=not (home and away)):
            match_id = source_cache().save_custom_match(home, away, block, competition=competition,
                                                        match_date=match_date.isoformat())
            st.success(f"Partita salvata con id {match_id} · inserita manualmente.")
    saved = source_cache().custom_matches()
    if saved:
        st.markdown("**Partite salvate**")
        labels = {match["id"]: f"#{match['id']} · {match['home']} - {match['away']} · {match['match_date'] or '—'} · {match['origin']}"
                  for match in saved}
        chosen = st.selectbox("Riapri una partita salvata", list(labels), format_func=labels.__getitem__, key="create_saved")
        if st.button("Carica nel simulatore", key="create_load"):
            st.session_state.pop("auto_sheet_rows", None)
            use_in_simulator(next(match["block"] for match in saved if match["id"] == chosen))


# --- Stile ---------------------------------------------------------------------------------

def style_radar(profiles: list[StyleProfile]) -> alt.Chart:
    """Radar in coordinate polari (percentile nel proprio campionato, 50 = media)."""
    keys = [metric for metric in METRIC_BY_KEY if any(metric in profile.z for profile in profiles)]
    angles = {key: 2 * math.pi * index / len(keys) for index, key in enumerate(keys)}
    points = []
    for profile in profiles:
        percentiles = radar_percentiles(profile)
        available = [key for key in keys if key in percentiles]
        for order, key in enumerate(available + available[:1]):
            radius = percentiles[key] / 100.0
            points.append({"Squadra": profile.team, "ordine": order, "x": radius * math.sin(angles[key]),
                           "y": radius * math.cos(angles[key]), "Metrica": METRIC_BY_KEY[key].label,
                           "Percentile": round(percentiles[key]), "z-score": round(profile.z[key], 2)})
    grid = [{"anello": level, "ordine": index, "x": level * math.sin(2 * math.pi * index / 60),
             "y": level * math.cos(2 * math.pi * index / 60)} for level in (0.25, 0.5, 0.75, 1.0) for index in range(61)]
    labels = [{"x": 1.18 * math.sin(angle), "y": 1.18 * math.cos(angle), "Metrica": METRIC_BY_KEY[key].label}
              for key, angle in angles.items()]
    scale = alt.Scale(domain=[-1.35, 1.35])
    axes = {"x": alt.X("x:Q", scale=scale, axis=None), "y": alt.Y("y:Q", scale=scale, axis=None)}
    rings = alt.Chart(pd.DataFrame(grid)).mark_line(color="#294258", strokeWidth=1).encode(
        **axes, detail="anello:N", order="ordine:Q")
    text = alt.Chart(pd.DataFrame(labels)).mark_text(color="#9eb1c2", fontSize=10).encode(**axes, text="Metrica:N")
    teams = alt.Chart(pd.DataFrame(points)).encode(
        **axes, color=alt.Color("Squadra:N", scale=alt.Scale(range=["#3bd18b", "#f4c95d"]), legend=alt.Legend(orient="bottom")),
        order="ordine:Q", tooltip=["Squadra", "Metrica", "Percentile", "z-score"],
    )
    return (rings + teams.mark_line(strokeWidth=2) + teams.mark_point(filled=True, size=40) + text).properties(height=460)


def render_style(home: str, away: str) -> None:
    """Scheda Stile: radar, archetipo e descrizione delle due squadre."""
    archetypes = load_archetypes()
    settings = {"max_age": timedelta(hours=int(st.session_state.get("auto_hours", 24))), "matches": 10, "half_life": 5.0}
    provider = _provider(settings, force=False)
    leagues = {team: provider.competition_of(team) for team in (home, away)}
    store = ProfileStore(source_cache())
    cached = {league: store.load(league, settings["max_age"]) for league in set(leagues.values()) if league}
    missing = [league for league, profiles in cached.items() if profiles is None]
    if missing:
        st.info(f"Profili di stile da calcolare per: {', '.join(missing)} (la prima volta circa un minuto per campionato; "
                "poi restano in cache e si aggiornano con la stessa soglia dei dati).")
        if st.button("Calcola profili di stile", key="style_compute"):
            with st.spinner("Calcolo i profili di stile…"):
                for league in missing:
                    cached[league] = provider.style_profiles(league)
            st.rerun()
    profiles = []
    for team, league in leagues.items():
        if league is None:
            st.warning(f"{team}: campionato non coperto dalle fonti, nessun profilo di stile.")
            continue
        league_profiles = cached.get(league)
        profile = find_profile(league_profiles, team) if league_profiles else None
        if profile is not None:
            profiles.append(assign_archetype(profile, archetypes))
    if not profiles:
        return
    st.altair_chart(style_radar(profiles), width="stretch")
    st.caption("Percentile nel proprio campionato (50 = media del campionato), da z-score per campionato.")
    for column, profile in zip(st.columns(len(profiles)), profiles):
        with column:
            label = "Profilo parziale · " if profile.partial else ""
            st.markdown(f"**{profile.team}** · {profile.league}")
            archetype = profile.archetype or ("non assegnabile: mancano le metriche Understat di pressing, blocco, "
                                              "manovra, transizioni e piazzati" if profile.partial else "non assegnato")
            st.markdown(f"{label}Archetipo: **{archetype}**")
            st.write(describe(profile))
            st.caption(f"Ultime {profile.matches} partite di campionato · calcolato il "
                       f"{profile.computed_at[:10]}")
    with st.expander("Metriche escluse e metodo"):
        st.write("\n".join(f"- {name}: {reason}" for name, reason in EXCLUDED_METRICS.items()))
        if archetypes:
            st.write(f"Archetipi: {archetypes['metodo']}; {archetypes['k']} gruppi su {archetypes['squadre']} squadre "
                     f"(silhouette {archetypes['silhouette'][str(archetypes['k'])]:.3f}).")
