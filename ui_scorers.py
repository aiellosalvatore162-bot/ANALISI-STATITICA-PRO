"""Sezione «Marcatori» della scheda partita (fase X): dati giocatore Understat, P(segna), quote inseribili."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from scorers import CALIBRATION_NOTE, goal_distribution, market_margin, players_from_understat, scorer_rows


def _players(team: str) -> tuple[list[dict] | None, str]:
    """Giocatori Understat della squadra nella stagione in corso, con un messaggio se non disponibili."""
    from datasources.builder import DataProvider
    from datasources.names import match_team
    from datasources.sources import COMPETITIONS, season_start
    from ui_data import source_cache

    provider = DataProvider(source_cache())
    competition = provider.competition_of(team)
    if competition is None or not COMPETITIONS[competition].get("understat"):
        return None, f"{team}: campionato non coperto da Understat."
    frame, _ = provider.understat_matches(competition)
    titles = frame["team"].unique() if not frame.empty else []
    title = match_team(team, titles)
    if title is None:
        return None, f"{team}: squadra non trovata su Understat."
    data, warnings = provider.understat.team(title, season_start(date.today()), timedelta(hours=24))
    if not data or not data.get("players"):
        return None, f"{team}: dati giocatore non disponibili. " + " ".join(warnings)
    return data["players"], f"Understat, stagione {season_start(date.today())}/{season_start(date.today()) + 1 - 2000}, {title}"


def render_scorers(result: dict) -> None:
    with st.expander("Marcatori: segna in qualsiasi momento (Understat)", expanded=False):
        st.caption("Quota dei gol della squadra di ogni giocatore (xG stagionali, ridotta verso la media se ha pochi minuti) "
                   "× minuti medi per presenza; la probabilità usa la distribuzione dei gol della squadra delle simulazioni.")
        st.warning(CALIBRATION_NOTE)
        home, away = result["input"]["home"]["name"], result["input"]["away"]["name"]
        store = st.session_state.setdefault("scorer_players", {})
        if st.button("Carica i giocatori delle due squadre", key="scorers_load"):
            with st.spinner("Scarico i dati giocatore da Understat…"):
                for team in (home, away):
                    try:
                        store[team] = _players(team)
                    except Exception as exc:  # fonte remota: avviso, mai un blocco della scheda
                        store[team] = (None, f"{team}: Understat non raggiungibile ({type(exc).__name__}).")
        for side, team in (("home", home), ("away", away)):
            if team not in store:
                continue
            players, source = store[team]
            st.markdown(f"**{team}**")
            if players is None:
                st.caption(source)
                continue
            st.caption(f"Fonte: {source}. Titolari non confermati: minuti attesi = media per presenza; spunta chi è "
                       "titolare confermato (90 minuti).")
            confirmed = st.session_state.setdefault(f"scorer_confirmed_{team}", [])
            rows = scorer_rows(players_from_understat(players), goal_distribution(result, side), confirmed=confirmed)
            odds_state = st.session_state.setdefault(f"scorer_odds_{team}", {})
            table = pd.DataFrame(rows).assign(**{"Titolare confermato": [row["Giocatore"] in confirmed for row in rows],
                                                 "Quota marcatore": [odds_state.get(row["Giocatore"]) for row in rows]})
            table["EV %"] = [round((row["Segna %"] / 100 * odds_state[row["Giocatore"]] - 1) * 100, 1)
                             if odds_state.get(row["Giocatore"]) else None for row in rows]
            edited = st.data_editor(
                table.drop(columns=["Titolare"]), hide_index=True, width="stretch", key=f"scorer_editor_{team}",
                disabled=[column for column in table.columns if column not in ("Titolare confermato", "Quota marcatore")],
                column_config={"Quota marcatore": st.column_config.NumberColumn(min_value=1.01, step=0.05, format="%.2f")})
            new_confirmed = [name for name, flag in zip(edited["Giocatore"], edited["Titolare confermato"]) if flag]
            new_odds = {name: float(value) for name, value in zip(edited["Giocatore"], edited["Quota marcatore"])
                        if pd.notna(value) and float(value) > 1.0}
            if new_confirmed != confirmed or new_odds != odds_state:
                st.session_state[f"scorer_confirmed_{team}"] = new_confirmed
                st.session_state[f"scorer_odds_{team}"] = new_odds
                st.rerun()
            margin = market_margin(rows, odds_state)
            if margin is not None:
                st.caption(f"Le quote marcatore inserite implicano il {margin:+.0%} rispetto alle probabilità del modello: "
                           "il margine di questo mercato è alto (spesso 20-40%), un EV positivo è raro.")
