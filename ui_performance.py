"""Pagina Streamlit «Prestazioni»: carica il file Excel del registro e mostra le misure di ``performance``."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib

import altair as alt
import pandas as pd
import streamlit as st

from performance import (
    MIN_SELECTIONS, RegistryError, bankroll, calibration_table, clv_by_market, collect_results, component_comparison,
    edge_verdicts, fill_from_results, read_registry, scores_over_time, updated_workbook,
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _percent(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Frazioni → punti percentuali arrotondati, solo per la visualizzazione."""
    shown = frame.copy()
    for column in columns:
        shown[column] = (pd.to_numeric(shown[column], errors="coerce") * 100).round(1)
    return shown


def _fetch_season(league: str, start: int) -> pd.DataFrame:
    from datasources.sources import FootballDataCoUk, season_start
    from ui_data import source_cache

    current = start == season_start(date.today())
    frame = FootballDataCoUk(source_cache()).season(league, start, timedelta(hours=6) if current else timedelta(days=30))
    st.session_state.setdefault("performance_source_warnings", []).extend(frame.warnings)
    return frame.data


def _fill_section(registry, original: bytes, signature: str) -> pd.DataFrame:
    """Compila esiti e quote di chiusura mancanti; restituisce il registro da misurare."""
    from datasources.sources import COMPETITIONS

    frame = registry.frame
    open_rows = int((frame["Esito"].isna() | frame["Quota_chiusura"].isna()).sum())
    report = st.session_state.get("performance_fill") if st.session_state.get("performance_fill_signature") == signature else None
    if open_rows and report is None:
        st.info(f"{open_rows} righe senza esito o quota di chiusura.")
        if st.button("Cerca esiti e quote di chiusura nelle fonti", key="performance_fill_button",
                     help="Risultati finali e al 45', corner, gialli (i rossi non sono contati) e quote medie di chiusura (1X2, Over/Under 2.5) da football-data.co.uk. "
                          "I valori già presenti nel file non vengono mai sovrascritti."):
            st.session_state["performance_source_warnings"] = []
            with st.spinner("Scarico i risultati da football-data.co.uk…"):
                results, warnings = collect_results(frame, _fetch_season, COMPETITIONS)
            report = fill_from_results(frame, results)
            st.session_state["performance_fill"] = report
            st.session_state["performance_fill_signature"] = signature
            st.session_state["performance_fill_warnings"] = warnings + list(dict.fromkeys(st.session_state["performance_source_warnings"]))
    if report is None:
        return frame
    for warning in st.session_state.get("performance_fill_warnings", []):
        st.warning(warning)
    if report.changes:
        st.success(f"Compilati {report.outcomes} esiti e {report.closings} quote di chiusura (fonte e data in colonna Note)."
                   + (f" {report.pushes} DNB rimborsate per pareggio: Esito lasciato vuoto." if report.pushes else ""))
        st.dataframe(pd.DataFrame(report.changes).drop(columns=["_riga"]), hide_index=True, width="stretch")
        st.download_button("Scarica il file aggiornato", updated_workbook(original, registry.sheet, report.changes),
                           file_name="Registro_Previsioni_aggiornato.xlsx", mime=XLSX, key="performance_download",
                           help="Il tuo file con le sole colonne Quota_chiusura, Esito e Note compilate: formule e fogli restano uguali.")
    else:
        st.info("Nessun esito o quota di chiusura ricavabile dalle fonti.")
    if report.not_found:
        st.caption("Partite non trovate (data, nomi o competizione non coperta): " + ", ".join(report.not_found))
    return report.frame


def render_performance() -> None:
    st.title("Prestazioni")
    st.caption("Carica il tuo Registro_Previsioni.xlsx: si leggono solo le colonne A–S del foglio Registro "
               "(le colonne grigie calcolate sono ignorate e ricalcolate qui).")
    upload = st.file_uploader("File Excel del registro", type=["xlsx"], key="performance_upload")
    if upload is None:
        return
    original = upload.getvalue()
    signature = hashlib.sha256(original).hexdigest()
    try:
        registry = read_registry(original)
    except RegistryError as exc:
        st.error(str(exc))
        return
    for warning in registry.warnings:
        st.warning(warning)
    if registry.frame.empty:
        return
    frame = _fill_section(registry, original, signature)
    settled = int(frame["Esito"].notna().sum())
    metrics = st.columns(3)
    metrics[0].metric("Selezioni", len(frame))
    metrics[1].metric("Con esito", settled)
    metrics[2].metric("Con quota di chiusura", int(frame["Quota_chiusura"].notna().sum()))
    if not settled:
        st.info("Servono righe con Esito (1 = vinta, 0 = persa) per calcolare le misure.")
        return

    st.subheader("Vantaggio per mercato")
    st.caption(f"«Vantaggio dimostrato» solo con almeno {MIN_SELECTIONS} selezioni con esito e CLV medio positivo.")
    verdicts = _percent(edge_verdicts(frame), ["% vinte", "Prob. media finale", "CLV medio", "ROI"])
    st.dataframe(verdicts.round({"Brier finale": 4}), hide_index=True, width="stretch")

    st.subheader("Calibrazione per mercato")
    calibration = calibration_table(frame)
    markets = list(dict.fromkeys(calibration["Mercato"]))
    if markets:
        chosen = st.selectbox("Mercato", markets, key="performance_market")
        subset = _percent(calibration[calibration["Mercato"] == chosen], ["Prob. prevista", "Frequenza reale", "Scarto"])
        diagonal = alt.Chart(pd.DataFrame({"x": [0, 100], "y": [0, 100]})).mark_line(strokeDash=[4, 4], color="gray").encode(x="x", y="y")
        points = alt.Chart(subset).mark_line(point=True).encode(
            x=alt.X("Prob. prevista", title="Probabilità prevista %", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("Frequenza reale", title="Frequenza reale %", scale=alt.Scale(domain=[0, 100])),
            tooltip=["Fascia", "Selezioni", "Prob. prevista", "Frequenza reale"])
        st.altair_chart(diagonal + points, width="stretch")
        st.dataframe(subset, hide_index=True, width="stretch")
        st.caption("Sulla diagonale = tarato. Sotto la diagonale le probabilità sono troppo alte, sopra troppo basse.")

    st.subheader("Brier e log-loss nel tempo")
    period = st.radio("Periodo", ["Mese", "Settimana"], horizontal=True, key="performance_period")
    scores = scores_over_time(frame, "M" if period == "Mese" else "W")
    if not scores.empty:
        long = scores.melt("Periodo", ["Brier cumulato", "Log-loss cumulato"], var_name="Misura", value_name="Valore")
        st.altair_chart(alt.Chart(long).mark_line(point=True).encode(
            x=alt.X("Periodo:T"), y="Valore", color="Misura", tooltip=["Periodo:T", "Misura", alt.Tooltip("Valore", format=".4f")]),
            width="stretch")
        st.dataframe(scores.round(4), hide_index=True, width="stretch")

    st.subheader("CLV medio per mercato")
    clv = clv_by_market(frame)
    if clv.empty:
        st.info("Nessuna riga con quota presa e quota di chiusura.")
    else:
        st.dataframe(_percent(clv, ["CLV medio", "Quote battute"]), hide_index=True, width="stretch")
        st.caption("CLV = quota presa / quota di chiusura − 1. Positivo = hai preso una quota migliore della chiusura.")

    st.subheader("ROI e saldo")
    summary, timeline = bankroll(frame)
    st.dataframe(_percent(summary, ["ROI", "CLV medio"]).round({"Puntata totale": 2, "Profitto": 2}), hide_index=True, width="stretch")
    if not timeline.empty:
        timeline = timeline.assign(Ordine=range(1, len(timeline) + 1))
        st.altair_chart(alt.Chart(timeline).mark_line(point=True).encode(
            x=alt.X("Ordine", title="Selezioni in ordine di data"), y=alt.Y("Saldo", title="Saldo cumulato"), color="Tipo",
            tooltip=["Data", "Partita", "Selezione", "Profitto", "Saldo"]), width="stretch")
        st.caption("Reale e A carta hanno saldi separati.")

    st.subheader("Quale componente migliora davvero")
    st.dataframe(component_comparison(frame).round(4), hide_index=True, width="stretch")
    st.caption("Brier e log-loss più bassi = meglio. Nei confronti a coppie si usano solo le selezioni con entrambe le "
               "probabilità; «migliora davvero» richiede una differenza di Brier negativa oltre due errori standard.")
