"""Riquadro «Formazione» (fase AL): XI atteso, minuti, assenti pesati, rigorista, chi performa sopra/sotto l'xG, con la fonte di ogni riga."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import lineup as lineup_module
import players


@st.cache_resource(show_spinner=False)
def player_store() -> players.PlayerStore | None:
    """Rose Understat dalla cache locale (stagioni dell'anno corrente e precedenti); ``None`` se non c'è nulla."""
    start = date.today().year if date.today().month >= 7 else date.today().year - 1
    table = players.load_table(list(players.UNDERSTAT_LEAGUES), (start - 1, start, start + 1))
    return players.PlayerStore(table) if len(table) else None


def side_tables(side: dict) -> dict[str, pd.DataFrame]:
    xi = pd.DataFrame(side.get("xi", []) + side.get("panchina", []))
    if len(xi):
        xi = xi.rename(columns={"giocatore": "Giocatore", "ruolo": "Ruolo", "come": "Ruolo in partita", "minuti_attesi": "Minuti attesi",
                                "npxg90": "npxG/90", "xa90": "xA/90", "quota_npxg": "Quota npxG", "quota_xa": "Quota xA",
                                "minuti_campione": "Minuti campione", "origine": "Origine"})[
            ["Giocatore", "Ruolo", "Ruolo in partita", "Minuti attesi", "npxG/90", "xA/90", "Quota npxG", "Quota xA", "Minuti campione", "Origine"]]
    absent = pd.DataFrame(side.get("assenti", []))
    if len(absent):
        absent = absent.rename(columns={"giocatore": "Giocatore", "ruolo": "Ruolo", "motivo": "Motivo", "fonte": "Fonte",
                                        "quota_persa": "Quota di produzione persa", "effetto_gol_attesi": "Effetto sui gol attesi"})[
            ["Giocatore", "Ruolo", "Motivo", "Quota di produzione persa", "Effetto sui gol attesi", "Fonte"]]
    performing = pd.DataFrame(side.get("performando", {}).get("giocatori", []))
    if len(performing):
        performing = performing.rename(columns={"giocatore": "Giocatore", "gol_senza_rigori": "Gol (no rigori)", "npxg": "npxG",
                                                "differenza_grezza": "Gol − npxG", "differenza_ridimensionata": "Ridimensionata",
                                                "etichetta": "Etichetta", "fonte": "Fonte"})
    return {"xi": xi, "assenti": absent, "performando": performing}


def render_side(label: str, side: dict) -> None:
    st.markdown(f"**{label}: {side.get('squadra', '')}**")
    if not side.get("disponibile"):
        for message in side.get("avvisi", []):
            st.caption(message)
        return
    tables = side_tables(side)
    attack, defense = side["fattore_attacco"], side["fattore_difesa"]
    st.caption(f"{side['origine_formazione']}. Fattore attacco {attack['valore']:.3f} (grezzo {attack['valore_grezzo']:.3f}, esponente "
               f"{attack['esponente']:g}); fattore difesa {defense['valore']:.3f} ({defense['fonte']}).")
    if attack.get("avviso"):
        st.warning(attack["avviso"])
    st.dataframe(tables["xi"], hide_index=True, width="stretch")
    if len(tables["assenti"]):
        st.markdown("Assenti pesati (non contati):")
        st.dataframe(tables["assenti"], hide_index=True, width="stretch")
    penalty = side.get("rigorista") or {}
    if penalty.get("rigorista"):
        text = f"Rigorista: {penalty['rigorista']} ({penalty['stato']})"
        if penalty.get("sostituto"):
            text += f", sostituto {penalty['sostituto']}"
        st.caption(f"{text}; conversione {penalty.get('conversione')} su {penalty.get('campione', 0)} rigori; {penalty.get('fonte', '')}.")
    else:
        st.caption(f"Rigorista: {penalty.get('stato', 'non noto')}.")
    team = (side.get("performando") or {}).get("squadra")
    if team:
        st.caption(f"Squadra: gol − npxG ridimensionato {team['differenza_ridimensionata']:+.2f} ({team['fonte']}).")
    if len(tables["performando"]):
        st.markdown("Chi sta performando sopra/sotto l'xG:")
        st.dataframe(tables["performando"], hide_index=True, width="stretch")
    for message in side.get("avvisi", [])[:4]:
        st.caption(message)


def render_lineups(analyses) -> None:
    """Un riquadro per partita; con un report dell'Analista (formazione/assenti) si ricalcola sul momento, senza rete."""
    ready = [analysis for analysis in analyses if analysis.ok and analysis.lineup]
    if not ready:
        return
    st.subheader("Formazioni")
    st.caption("Fonti: giocatori Understat (5 grandi campionati, cache locale), report dell'Analista per formazione e assenti. "
               "Fuori da Understat non c'è nulla: nessun valore inventato.")
    store = player_store()
    for analysis in ready:
        data = analysis.lineup
        report = lineup_module.report_from_response(analysis.claude)
        if report and store is not None and analysis.config is not None:
            data = lineup_module.get_lineup_params(analysis.match.home, analysis.match.away, analysis.match.commence_time.date(),
                                                   store, league=analysis.config.league, report=report)
        with st.expander(f"Formazione · {analysis.match.label}", expanded=False):
            render_side("Casa", data["casa"])
            render_side("Ospite", data["ospite"])
