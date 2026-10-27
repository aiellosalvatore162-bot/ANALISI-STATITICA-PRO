"""Pagina Streamlit «Prestazioni»: carica il file Excel del registro e mostra le misure di ``performance``."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib

import altair as alt
import pandas as pd
import streamlit as st

from dashboard import GLOSSARY, missing_as_dash
from performance import (
    MIN_SELECTIONS, RegistryError, bankroll, calibration_table, clv_by_market, collect_results, component_comparison,
    FillReport, edge_verdicts, fill_from_results, observed_cb_discount, read_registry, scores_over_time, settle_multiples, tactical_comparison, updated_workbook,
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
    if open_rows and report is None:
        report = _odds_api_fill(frame, signature)
    current, changes = (report.frame, list(report.changes)) if report is not None else (frame, [])
    if report is not None:
        for warning in st.session_state.get("performance_fill_warnings", []):
            st.warning(warning)
        if report.changes:
            st.success(f"Compilati {report.outcomes} esiti e {report.closings} quote di chiusura (fonte e data in colonna Note)."
                       + (f" {report.pushes} DNB rimborsate per pareggio: Esito lasciato vuoto." if report.pushes else ""))
            st.dataframe(missing_as_dash(pd.DataFrame(report.changes).drop(columns=["_riga"])), hide_index=True, width="stretch")
        else:
            st.info("Nessun esito o quota di chiusura ricavabile dalle fonti.")
        if report.not_found:
            st.caption("Partite non trovate (data, nomi o competizione non coperta): " + ", ".join(report.not_found))
    claude = _claude_outcome_fill(current, signature)
    if claude is not None and claude.changes:
        current, changes = claude.frame, changes + claude.changes
    multiples = settle_multiples(current)
    if multiples.changes:
        st.success(f"{multiples.outcomes} multiple con esito dalle loro gambe.")
        current, changes = multiples.frame, changes + multiples.changes
    if changes:
        st.download_button("Scarica il file aggiornato", updated_workbook(original, registry.sheet, changes),
                           file_name="Registro_Previsioni_aggiornato.xlsx", mime=XLSX, key="performance_download",
                           help="Il tuo file con le sole colonne Quota_chiusura, Esito e Note compilate: formule e fogli restano uguali.")
    return current


def _dual_section(frame: pd.DataFrame) -> None:
    """Doppio pronostico: classifiche affiancate di Simulatore, Osservatore e Unita, disaccordi e suggerimenti."""
    from dual import LABELS, SOURCES, disagreements, exploded, leaderboard, suggestions
    from multiples import load_settings

    if exploded(frame).empty:
        return
    settings = load_settings()
    st.subheader("Doppio pronostico: Simulatore · Osservatore · Unita")
    st.caption("Dalle righe con «fonte: …» in Note. Attese = probabilità media del simulatore (anche per le scelte "
               "dell'osservatore); ROI a puntata fissa 1 sulla quota presa; Brier più basso = meglio.")
    view = st.radio("Dividi per", ["Totale", "Mercato", "Weekend"], horizontal=True, key="dual_view")
    table = leaderboard(frame, None if view == "Totale" else view)
    columns = st.columns(3)
    for column, source in zip(columns, SOURCES):
        with column:
            st.markdown(f"**{LABELS[source]}**")
            subset = table[table["Fonte"] == LABELS[source]].drop(columns=["Fonte"])
            st.dataframe(missing_as_dash(_percent(subset, ["% vinte", "Attese", "ROI"]).round({"Brier": 4})),
                         hide_index=True, width="stretch")
    summary, details = disagreements(frame)
    st.markdown("**Disaccordi: chi ha avuto ragione**")
    if details.empty:
        st.caption("Nessun disaccordo con l'esito di entrambe le giocate.")
    else:
        st.dataframe(summary.set_index("Ha ragione").T, width="stretch")
        with st.expander(f"Tutti i disaccordi ({len(details)})", expanded=False):
            st.dataframe(missing_as_dash(_percent(details, ["Prob. simulatore per l'osservatore"])), hide_index=True, width="stretch")
    needed = int(settings.get("min_weekend_suggerimento", 4))
    lines, weekends = suggestions(frame, min_weekends=needed,
                                  min_selections=int(settings.get("min_selezioni_mercato_suggerimento", 5)))
    if weekends < needed:
        st.caption(f"Suggerimenti per mercato dopo {needed} weekend con esiti (finora {weekends}).")
    elif lines:
        st.info("\n".join(f"- {line}" for line in lines))
    else:
        st.caption("Nessun mercato con abbastanza selezioni di entrambe le fonti per un suggerimento.")


def _cb_discount_note(frame: pd.DataFrame) -> None:
    """Sconto medio osservato dei Combo Builder (quota reale Eurobet / prodotto), per aggiornare «sconto_cb»."""
    from multiples import load_settings

    settings = load_settings()
    count, mean = observed_cb_discount(frame)
    needed = int(settings.get("min_cb_reali_per_sconto", 20))
    if not count:
        return
    if count >= needed:
        st.info(f"Sconto Combo Builder osservato: quota reale = {mean:.3f} × prodotto delle quote, su {count} combo con quota "
                f"reale (in config/oggi.json «sconto_cb» vale {float(settings.get('sconto_cb', 0.85)):.2f}: aggiornalo se diverso).")
    else:
        st.caption(f"Sconto Combo Builder: {count} combo con quota reale su {needed} necessarie per stimarlo "
                   f"(media provvisoria {mean:.3f}).")


def _claude_outcome_fill(frame: pd.DataFrame, signature: str) -> FillReport | None:
    """«Prepara verifica esiti per Claude»: un testo con tutte le partite di corner e cartellini ancora senza esito."""
    from claude_bridge import ResponseError
    from today import outcome_prompt, outcome_targets, parse_outcomes
    from ui_data import COPY_HINT

    targets = outcome_targets(frame)
    if not targets:
        return None
    with st.expander(f"Verifica esiti con Claude: {len(targets)} partite con corner o cartellini senza esito "
                     "(utile per le coppe)", expanded=False):
        st.caption("I punteggi di The Odds API e football-data.co.uk non coprono corner e cartellini delle coppe: "
                   "Claude cerca i tabellini sul web e la risposta compila solo gli esiti mancanti, con la fonte in Note.")
        if st.button("Prepara verifica esiti per Claude", key="performance_claude_prepare"):
            st.session_state["performance_claude_prompt"] = outcome_prompt(targets)
        prompt = st.session_state.get("performance_claude_prompt")
        if prompt:
            st.caption(COPY_HINT)
            st.code(prompt, language="text")
        answer = st.text_area("Incolla la risposta di Claude (blocchi ESITI_CLAUDE)", key="performance_claude_answer", height=160)
        if not answer.strip():
            return None
        try:
            results, warnings = parse_outcomes(answer, targets)
        except ResponseError as exc:
            st.error(str(exc))
            return None
        for warning in warnings:
            st.warning(warning)
        report, current = FillReport(frame), frame
        for result in results:
            step = fill_from_results(current, pd.DataFrame([result]), source=f"Claude ({result['source']})")
            current = step.frame
            report.outcomes += step.outcomes
            report.changes += step.changes
        report.frame = current
        st.success(f"{report.outcomes} esiti compilati dalla verifica di Claude.")
        return report


def _odds_api_fill(frame: pd.DataFrame, signature: str):
    """Esiti dei mercati gol (anche coppe) dai punteggi di The Odds API e chiusure dalle istantanee salvate."""
    from datasources.oddsapi import results_from_scores, scores_plan
    from ui_odds import _approve, _run, odds_client

    api = odds_client()
    if not api.configured:
        return None
    plan = scores_plan(frame, date.today(), api.closing_snapshots())
    if not plan["rows"]:
        return None
    with st.expander("Esiti da The Odds API (partite degli ultimi 3 giorni, anche coppe)", expanded=False):
        st.caption(f"{plan['rows']} righe senza esito negli ultimi 3 giorni; punteggi delle sole "
                   f"{len(plan['sports'])} competizioni con giocate nel registro (daysFrom={plan['days_from']}, "
                   "2 crediti ciascuna). Solo risultato finale: si compilano i mercati "
                   "decisi dai gol a fine partita; primo tempo, corner e cartellini restano a football-data.co.uk o a mano. "
                   "Le quote di chiusura vengono dalle istantanee già salvate (gratis).")
        if plan["unknown"]:
            st.caption("Competizione non riconosciuta (colonna Competizione vuota e nessuna istantanea delle quote): "
                       + ", ".join(plan["unknown"]) + ". Per queste righe non si scaricano punteggi.")
        if plan["too_old"]:
            st.caption(f"{plan['too_old']} righe più vecchie di 3 giorni: fuori dalla finestra dell'endpoint dei punteggi.")
        if not plan["sports"]:
            return None
        cost, cached = 0, 0
        for sport in plan["sports"]:
            if api.is_cached(f"/sports/{sport}/scores", api.scores_params(plan["days_from"])):
                cached += 1
            else:
                cost += 2
        approved = _approve(api, cost, cached, "performance_scores_confirm")
        if approved is None or not st.button("Scarica i punteggi", key="performance_scores_button"):
            return None
        payloads = []
        for sport in plan["sports"]:
            result = _run(lambda: api.scores(sport, plan["days_from"], **approved), sport)
            if result is not None:
                payloads.append(result.payload)
        results = results_from_scores(payloads, api.closing_snapshots(), api.settings.get("riferimento"))
    report = fill_from_results(frame, results, source="The Odds API (punteggi)")
    st.session_state["performance_fill"] = report
    st.session_state["performance_fill_signature"] = signature
    st.session_state["performance_fill_warnings"] = []
    return report


def render_performance() -> None:
    st.subheader("Prestazioni")
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
    _cb_discount_note(frame)
    _dual_section(frame)
    if not settled:
        st.info("Servono righe con Esito (1 = vinta, 0 = persa) per calcolare le misure.")
        return

    st.subheader("Vantaggio per mercato")
    st.caption(f"«Vantaggio dimostrato» solo con almeno {MIN_SELECTIONS} selezioni con esito e CLV medio positivo.")
    verdicts = _percent(edge_verdicts(frame), ["% vinte", "Prob. media finale", "CLV medio", "ROI"])
    st.dataframe(missing_as_dash(verdicts.round({"Brier finale": 4})), hide_index=True, width="stretch")

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
        st.dataframe(missing_as_dash(subset), hide_index=True, width="stretch")
        st.caption("Sulla diagonale = tarato. Sotto la diagonale le probabilità sono troppo alte, sopra troppo basse.")

    st.subheader("Brier e log-loss nel tempo", help=GLOSSARY["Brier"])
    period = st.radio("Periodo", ["Mese", "Settimana"], horizontal=True, key="performance_period")
    scores = scores_over_time(frame, "M" if period == "Mese" else "W")
    if not scores.empty:
        long = scores.melt("Periodo", ["Brier cumulato", "Log-loss cumulato"], var_name="Misura", value_name="Valore")
        st.altair_chart(alt.Chart(long).mark_line(point=True).encode(
            x=alt.X("Periodo:T"), y="Valore", color="Misura", tooltip=["Periodo:T", "Misura", alt.Tooltip("Valore", format=".4f")]),
            width="stretch")
        st.dataframe(missing_as_dash(scores.round(4)), hide_index=True, width="stretch")

    st.subheader("CLV medio per mercato", help=GLOSSARY["CLV"])
    clv = clv_by_market(frame)
    if clv.empty:
        st.info("Nessuna riga con quota presa e quota di chiusura.")
    else:
        st.dataframe(missing_as_dash(_percent(clv, ["CLV medio", "Quote battute"])), hide_index=True, width="stretch")
        st.caption("CLV = quota presa / quota di chiusura − 1. Positivo = hai preso una quota migliore della chiusura.")

    st.subheader("ROI e saldo")
    summary, timeline = bankroll(frame)
    st.dataframe(missing_as_dash(_percent(summary, ["ROI", "CLV medio"]).round({"Puntata totale": 2, "Profitto": 2})), hide_index=True, width="stretch")
    if not timeline.empty:
        timeline = timeline.assign(Ordine=range(1, len(timeline) + 1))
        st.altair_chart(alt.Chart(timeline).mark_line(point=True).encode(
            x=alt.X("Ordine", title="Selezioni in ordine di data"), y=alt.Y("Saldo", title="Saldo cumulato"), color="Tipo",
            tooltip=["Data", "Partita", "Selezione", "Profitto", "Saldo"]), width="stretch")
        st.caption("Reale e A carta hanno saldi separati.")

    st.subheader("Quale componente migliora davvero")
    st.dataframe(missing_as_dash(component_comparison(frame).round(4)), hide_index=True, width="stretch")
    st.caption("Brier e log-loss più bassi = meglio. Nei confronti a coppie si usano solo le selezioni con entrambe le "
               "probabilità; «migliora davvero» richiede una differenza di Brier negativa oltre due errori standard.")
    tactical = tactical_comparison(frame)
    if tactical["Selezioni"].sum():
        st.markdown("**Schede tattiche**")
        st.dataframe(missing_as_dash(tactical.round(4)), hide_index=True, width="stretch")
        st.caption("Dalla nota «scheda tattica: sì/no» del registro. I gruppi contengono partite diverse: il confronto "
                   "è indicativo, non appaiato.")
