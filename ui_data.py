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


def use_in_simulator(block: str, *, match_date: date | None = None, competition: str | None = None) -> None:
    """Porta il blocco nel copia-incolla; la modalità cambia al giro successivo, prima del selettore.

    Data e competizione restano in sessione come valori proposti per il registro delle previsioni.
    """
    st.session_state["input_text"] = block
    st.session_state["match_meta"] = {"date": match_date, "competition": competition or ""}
    st.session_state["input_touched"] = True
    st.session_state["pending_input_mode"] = "Copia-incolla"
    st.rerun()


def _use_block(sheet: MatchSheet) -> None:
    st.session_state["auto_sheet_rows"] = provenance_rows(sheet)
    st.session_state["auto_sheet_warnings"] = sheet.warnings
    use_in_simulator(render_block(sheet), match_date=sheet.match_date, competition=sheet.competition)


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
    if st.button("Prepara estrazione dati per Claude", key="create_claude_extract",
                 help="Istruzioni per far trasformare a Claude il testo di un sito nel blocco del parser."):
        from claude_bridge import extraction_prompt

        st.session_state["create_extract_prompt"] = extraction_prompt(home or None, away or None)
    if st.session_state.get("create_extract_prompt"):
        st.caption(COPY_HINT)
        st.code(st.session_state["create_extract_prompt"], language="text")
        st.caption("Incolla in Claude queste istruzioni e, al posto della riga finale, il testo copiato dal sito; "
                   "poi incolla qui sotto il blocco che ti restituisce: passa dal controllo di plausibilità.")
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
            use_in_simulator(block, match_date=match_date, competition=competition)
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
            match = next(match for match in saved if match["id"] == chosen)
            use_in_simulator(match["block"], match_date=date.fromisoformat(match["match_date"]) if match["match_date"] else None,
                             competition=match.get("competition"))


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


# --- Scenario tattico ------------------------------------------------------------------------

TACTICAL_OPTIONS = (
    ("goals", "Gol attesi (λ, μ)"),
    ("goals_supremacy", "Gol: solo rapporto di forza"),
    ("first_half", "Quota di gol nel primo tempo"),
    ("corners", "Corner"),
    ("cards", "Cartellini"),
)


def _matches_table(result) -> pd.DataFrame:
    rows = []
    for row in result.matches.sort_values("date", ascending=False).itertuples():
        rows.append({
            "Data": f"{row.date:%d/%m/%Y}", "Avversario": row.opponent, "Campo": "casa" if row.venue == "home" else "trasferta",
            "Risultato": f"{int(row.goals_for)}-{int(row.goals_against)}",
            "xG": f"{row.xg_for:.2f}-{row.xg_against:.2f}" if pd.notna(row.xg_for) else "—",
            "Corner": f"{row.corners_for:.0f}-{row.corners_against:.0f}" if pd.notna(row.corners_for) else "—",
            "Cartellini": f"{row.cards:.0f}" if pd.notna(row.cards) else "—",
            "Distanza": round(float(row.distance), 2), "Peso": round(float(row.weight), 3),
        })
    return pd.DataFrame(rows)


def render_tactical(home: str | None, away: str | None):
    """Riquadro «Scenario tattico»: partite simili, fattori e scelta delle correzioni da applicare."""
    from engine import DEFAULT_TACTICAL_SWITCHES, TacticalFactors, TacticalSwitches
    from datasources.similar import FEATURES, STAT_LABELS, summary_sentence

    with st.expander("Scenario tattico · avversari simili", expanded=False):
        if not (home and away):
            st.caption("Inserisci un blocco valido per analizzare le partite contro avversari simili.")
            return None, DEFAULT_TACTICAL_SWITCHES
        key = (home, away)
        scenario = st.session_state.get("tactical_scenario")
        if scenario is not None and scenario.get("key") != key:
            scenario = None
        if st.button("Analizza avversari simili", key="tactical_run",
                     help="Scarica lo storico dei campionati delle due squadre (la prima volta qualche decina di secondi)."):
            with st.spinner("Cerco le partite contro avversari simili…"):
                scenario = {"key": key, **_provider({"max_age": timedelta(hours=int(st.session_state.get("auto_hours", 24))),
                                                     "matches": 10, "half_life": 5.0}, False).tactical_scenario(home, away)}
            st.session_state["tactical_scenario"] = scenario
        if scenario is None:
            st.caption("Per ogni squadra: le 10 partite degli ultimi 2 anni contro gli avversari più simili a quello di oggi "
                       "(profilo di stile continuo + Elo, non l'archetipo), con rendimento rispetto alla sua media.")
            return None, DEFAULT_TACTICAL_SWITCHES
        for note in scenario["notes"]:
            st.info(note)
        if scenario["cross_league"]:
            st.caption("Campionati diversi: Elo degli avversari da ClubElo, stile come z-score nel proprio campionato.")
        for side in ("home", "away"):
            result = scenario["results"].get(side)
            if result is None:
                continue
            st.markdown(f"**{result.team}** contro avversari simili a **{result.opponent}**")
            st.write(summary_sentence(result, result.opponent))
            st.caption(f"Confronto su {len(result.features_used)} metriche di stile su {len(FEATURES)} + Elo · "
                       f"{len(result.matches)} partite ({result.effective_matches:.1f} effettive dopo i pesi)"
                       + (" · profilo parziale: shrinkage più forte" if len(result.features_used) < len(FEATURES) else ""))
            if not result.matches.empty:
                st.dataframe(_matches_table(result), hide_index=True, width="stretch")
                st.dataframe(pd.DataFrame([
                    {"Statistica": STAT_LABELS[stat], "Rapporto grezzo": round(result.raw[stat], 3),
                     "Fattore dopo lo shrinkage": round(result.factors[stat], 3)} for stat in result.factors
                ]), hide_index=True, width="stretch")
        factors = scenario.get("factors")
        if factors is None:
            return None, DEFAULT_TACTICAL_SWITCHES
        st.markdown("**Fattori della partita** (limiti 0.85-1.15 per i gol, 0.80-1.20 per corner e cartellini)")
        st.dataframe(pd.DataFrame([{"Fattore": name, "Valore": round(value, 3)} for name, value in (
            ("λ casa", factors["lambda"]), ("μ ospite", factors["mu"]), ("quota primo tempo", factors["first_half"]),
            ("corner casa", factors["corners_home"]), ("corner ospite", factors["corners_away"]), ("cartellini", factors["cards"]),
        )]), hide_index=True, width="stretch")
        st.caption("Le correzioni attive di default sono solo quelle validate su stagioni intere (docs/STILI.md). "
                   "I gol sono corretti prima della combinazione con il mercato: con peso mercato 0.9 l'effetto finale è piccolo.")
        switches = {}
        columns = st.columns(len(TACTICAL_OPTIONS))
        for column, (family, label) in zip(columns, TACTICAL_OPTIONS):
            validated = getattr(DEFAULT_TACTICAL_SWITCHES, family)
            switches[family] = column.checkbox(label + (" ✓ validata" if validated else ""), value=validated,
                                               key=f"tactical_{family}")
        return TacticalFactors(lambda_=factors["lambda"], mu=factors["mu"], first_half=factors["first_half"],
                               corners_home=factors["corners_home"], corners_away=factors["corners_away"],
                               cards=factors["cards"]), TacticalSwitches(**switches)


# --- Claude (copia e incolla) --------------------------------------------------------------------

COPY_HINT = "Per copiare usa il pulsante «Copia» in alto a destra del riquadro (compare passando sopra al testo)."


def render_claude(result: dict, config, block: str) -> tuple[dict | None, str]:
    """Prepara il testo per Claude, legge la risposta incollata e confronta prima/dopo le correzioni.

    Restituisce la simulazione con le correzioni applicate (o ``None``) e una nota per il registro.
    """
    from dataclasses import replace

    from claude_bridge import ResponseError, analysis_prompt, changes_table, parse_response
    from engine import simulate_match
    from prediction_log import DEFAULT_SELECTIONS

    st.subheader("Analisi con Claude (copia e incolla)")
    st.caption("Nessuna API: copi il testo in Claude (con la ricerca web attiva), poi incolli qui la risposta.")
    if st.button("Prepara analisi per Claude", key="claude_prepare"):
        st.session_state["claude_prompt"] = analysis_prompt(
            block, result, sources=st.session_state.get("auto_sheet_rows"), match_date=date.today().strftime("%d/%m/%Y"))
    prompt = st.session_state.get("claude_prompt")
    if prompt:
        st.caption(COPY_HINT)
        st.code(prompt, language="text")
    answer = st.text_area("Incolla risposta di Claude", key="claude_answer", height=180)
    if not answer.strip():
        return None, ""
    try:
        response = parse_response(answer)
    except ResponseError as exc:
        st.error(str(exc))
        return None, ""
    if response.preamble:
        st.markdown(f"**Commento di Claude:** {response.preamble}")
    if response.comment or response.confidence:
        st.caption(f"Confidenza: {response.confidence or '—'} · {response.comment}")
    st.dataframe(pd.DataFrame(changes_table(response)), hide_index=True, width="stretch")
    for warning in response.warnings:
        st.warning(warning)
    from today import combined_adjustment

    adjustment = response.adjustment()
    referee = response.referee_yellow(config.referee_yellow_avg)
    flags = st.session_state.get("result_flags") or []
    if flags:
        st.caption(f"Le correzioni si sommano alle segnalazioni da osservatore: {', '.join(flags)}.")
    if adjustment is None and referee is None:
        st.info("Nessuna correzione applicabile (mancano fonti o valori validi).")
        return None, ""
    if referee is not None:
        st.caption(f"Gialli medi dell'arbitro: {config.referee_yellow_avg:.2f} → {referee:.2f} "
                   "(media di Claude avvicinata alla media corrente con peso 10 partite).")
    apply = st.toggle("Applica le correzioni di Claude", key="claude_apply")
    after = None
    if apply:
        signature = (answer, id(result))
        if st.session_state.get("claude_signature") != signature:
            adjusted = replace(config, claude=combined_adjustment(flags, response),
                               referee_yellow_avg=referee if referee is not None else config.referee_yellow_avg)
            st.session_state["claude_result"] = simulate_match(adjusted)
            st.session_state["claude_signature"] = signature
        after = st.session_state["claude_result"]
        before_final, after_final = result["components"]["finale"], after["components"]["finale"]
        st.dataframe(pd.DataFrame([
            {"Mercato": market, "Simulatore %": before_final.get(market), "Con Claude %": after_final.get(market),
             "Differenza (punti)": round(after_final.get(market, 0) - before_final.get(market, 0), 2)}
            for market in DEFAULT_SELECTIONS if market in before_final
        ]), hide_index=True, width="stretch")
        st.caption(f"Gol attesi finali: λ {result['model']['lambda']:.3f} → {after['model']['lambda']:.3f}, "
                   f"μ {result['model']['mu']:.3f} → {after['model']['mu']:.3f} (correzioni dopo l'ancoraggio al mercato).")
    note = f"confidenza Claude {response.confidence}" if response.confidence else ""
    return after, note


# --- Registro delle previsioni -------------------------------------------------------------------

def _base_result(result: dict, config) -> dict:
    """Simulazione senza scenario tattico, per separare la colonna Prob_stile da Prob_modello."""
    from dataclasses import replace

    from engine import TacticalSwitches, simulate_match

    signature = (id(result), config.tactical, config.tactical_switches)
    if st.session_state.get("registry_base_signature") != signature:
        st.session_state["registry_base"] = simulate_match(replace(config, tactical_switches=TacticalSwitches()))
        st.session_state["registry_base_signature"] = signature
    return st.session_state["registry_base"]


def render_registry(result: dict, config, claude: dict | None = None, claude_note: str = "") -> None:
    """Salva le selezioni scelte nel registro di sessione e scarica il file Excel (colonne A–S)."""
    import uuid
    from dataclasses import asdict
    from datetime import datetime

    from prediction_log import (
        DEFAULT_SELECTIONS, PROBABILITY_COLUMNS, TYPES, PredictionLog, SaveInfo, market_of, model_version, prediction_rows,
    )

    st.subheader("Registro delle previsioni")
    st.caption("Una riga per selezione, con le colonne A–S del tuo file Registro_Previsioni.xlsx. "
               "Quota_chiusura ed Esito restano vuote: le compili a mano o dalla pagina «Prestazioni».")
    styled = result if config.tactical is not None and any(asdict(config.tactical_switches).values()) else None
    base = _base_result(result, config) if styled is not None else result
    available = [key for key in result["components"]["finale"] if market_of(key) is not None]
    played = [key for key in (config.odds or {}) if key in available]
    odds = dict(config.odds or {})
    group = st.session_state.get("exact_group")  # dalla sezione «Risultati esatti»
    if group:
        available.append(group["selection"])
        played.append(group["selection"])
        if group["odds"]:
            odds[group["selection"]] = group["odds"]
    meta = st.session_state.get("match_meta") or {}
    now = datetime.now()
    columns = st.columns(4)
    day = columns[0].date_input("Data partita", value=meta.get("date") or now.date(), key="registry_date")
    time = columns[1].text_input("Ora", value=now.strftime("%H:%M"), key="registry_time")
    competition = columns[2].text_input("Competizione", value=meta.get("competition") or "", key="registry_competition",
                                        help="Con il nome del campionato (es. Serie A) la pagina Prestazioni trova più in fretta gli esiti.")
    kind = columns[3].radio("Tipo", TYPES, index=1, horizontal=True, key="registry_kind")
    selections = st.multiselect(
        "Selezioni da registrare", available, placeholder="Scegli le selezioni", default=played or [key for key in DEFAULT_SELECTIONS if key in available],
        format_func=lambda key: f"{market_of(key)} · {key}", key=f"registry_selections_{id(result)}_{(group or {}).get('selection', '')}",
        help="Solo i mercati della tabella del Riepilogo (1X2, Doppia chance, DNB, Over/Under 1.5-2.5-3.5, "
             "Goal/NoGoal, Multigol totale/casa/ospite, 1X2 primo tempo, Over 0.5/1.5 1T, Corner, Cartellini, Combo, "
             "Risultati esatti dal gruppo scelto nella sezione omonima).")
    if not selections:
        return
    info = SaveInfo(day, time.strip(), competition.strip(), kind, model_version(config, claude=claude is not None), claude_note)
    rows = prediction_rows(base, selections, info, styled=styled, claude=claude, odds=odds)
    edited = st.data_editor(
        pd.DataFrame(rows), hide_index=True, width="stretch", key=f"registry_editor_{id(result)}",
        disabled=[column for column in rows[0] if column not in ("Quota_presa", "Puntata", "Tipo", "Note")],
        column_config={"Tipo": st.column_config.SelectboxColumn("Tipo", options=list(TYPES)),
                       **{column: st.column_config.NumberColumn(column, format="percent") for column in PROBABILITY_COLUMNS},
                       "Quota_presa": st.column_config.NumberColumn("Quota_presa", format="%.2f")},
    )
    session = st.session_state.setdefault("session_id", uuid.uuid4().hex[:12])
    log = PredictionLog(source_cache())
    if st.button("Salva nel registro", key="registry_save"):
        records = [{key: None if pd.isna(value) else value for key, value in row.items()}
                   for row in edited.to_dict("records")]
        new, updated = log.save(records, session)
        st.success(f"Registro: {new} righe nuove" + (f", {updated} aggiornate (stesso ID: niente doppioni)." if updated else ".")
                   + " Le righe si sommano a quelle delle altre partite della giornata (tabella qui sotto).")
