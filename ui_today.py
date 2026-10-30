"""Pagina Streamlit «Oggi» (fase S): partite del giorno, analisi in blocco, giocate di valore e multiple.

Layout pensato per il computer. Le analisi stanno in ``st.session_state["today_analyses"]`` e ogni
partita simulata entra anche nella memoria della giornata (``ui_memory``): «Apri scheda» la riapre
nella pagina Partita con tutte le tab.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
import time

import pandas as pd
import streamlit as st

from match_memory import make_record, upsert
from multiples import (
    OBJECTIVES, Leg, Multiple, build_doubles, comparison_line, format_probability, build_long, build_short, candidate_legs, filter_legs, load_settings,
    multiple_row,
)
from timing import registra
from ui_manual import manual_for
from today import (
    Analysis, TodayMatch, analyze, match_ids, multi_analysis_prompt, parse_multi_response, mark_failed, prepare, problem_rows, simulate,
    split_multi_response, value_picks,
)


def _analyses() -> list[Analysis]:
    return st.session_state.setdefault("today_analyses", [])


def _record_id(analysis: Analysis) -> str:
    from match_memory import match_id

    return match_id(analysis.match.commence_time.date(), analysis.result["input"]["home"]["name"],
                    analysis.result["input"]["away"]["name"])


def _remember(analysis: Analysis) -> None:
    """La partita analizzata entra nella memoria della giornata (riapribile dalla barra laterale)."""
    from ui_memory import _store

    record = make_record(analysis.result, block=analysis.block, odds=analysis.odds,
                         day=analysis.match.commence_time.date(), competition=analysis.match.competition,
                         warnings=[*analysis.warnings, *([analysis.note()] if analysis.note() else [])],
                         flags=analysis.flags, claude_answer=analysis.claude_text,
                         claude_applied=analysis.claude is not None and analysis.claude.adjustment() is not None)
    from ui_memory import form_for

    record["form"] = form_for(analysis.match.label)  # colonna «Forma» del foglio Analisi (informativa)
    record["fields"] = list(analysis.sources)  # valore, origine (manuale/automatico/proxy-stima) e fonte di ogni campo
    upsert(_store(), record)


def _open_card(index: int) -> None:
    """Callback di «Apri scheda»: pagina Partita con blocco, quote e tab della partita."""
    from ui_memory import _reopen

    analysis = _analyses()[index]
    _remember(analysis)
    _reopen(_record_id(analysis))
    st.session_state["page"] = "Partita"


def _with_quotes(analysis: Analysis) -> bool:
    """Quote dell'archivio della giornata per EV, semaforo e ancoraggio (sharp per i gol, scala Eurobet per corner e
    cartellini, fase N3); una sola simulazione in più. False se la partita non ha quote: resta «solo modello»."""
    from eurobet import anchor_odds
    from ui_quotes import entry_for

    entry = entry_for(analysis.match.home, analysis.match.away, analysis.match.commence_time.date())
    if entry is None or analysis.config is None:
        return False
    import day_archive

    extra = day_archive.engine_odds(entry)
    if not extra:
        return False
    paste = day_archive.eurobet_paste(entry)
    anchor, _ = anchor_odds({**analysis.odds, **extra}, day_archive.sharp_odds(entry), paste)
    analysis.config = replace(analysis.config, anchor_odds=anchor)
    simulate(analysis, extra_odds=extra)
    return True


# --- Pagina ---------------------------------------------------------------------------------------

def render_today() -> None:
    from datasources.oddsapi import competition_label, is_european_soccer
    from ui_odds import _run, odds_client

    settings = load_settings()
    api = odds_client()
    st.title("Oggi")
    st.caption("Cerca le partite (gratis), scegli le selezionate (e le «Da giocare»), incolla o raccogli le quote, poi "
               "«Prepara» e «Analizza tutte». «Analizza tutte» non chiama mai l'API a crediti: usa solo le quote già "
               "presenti nella giornata.")
    from ui_quick import render_slips

    render_slips()
    render_analyst_report()
    columns = st.columns([4, 1, 1, 1])
    labels: dict[str, str] = {}
    if api.configured:
        sports = _run(api.sports, "Elenco competizioni")
        if sports is not None:
            labels = {sport["key"]: competition_label(sport["key"], sport.get("title"))
                      for sport in sports.payload if sport.get("active") and is_european_soccer(sport)}
    else:
        st.info("Serve ODDS_API_KEY in .streamlit/secrets.toml per l'elenco gratuito delle partite e le quote dell'API. "
                "Le partite già selezionate (anche da «Riprendi da file») restano utilizzabili con le quote incollate.")
    defaults = [key for key in api.settings.get("competizioni_predefinite", []) if key in labels]
    chosen = columns[0].multiselect("Competizioni", list(labels), defaults, format_func=labels.get, key="today_sports")
    day = columns[1].date_input("Giorno", key="today_day", **({} if "today_day" in st.session_state else {"value": date.today()}))
    mode = columns[2].radio("Modalità", ["Veloce", "Approfondita"], key="today_mode",
                            help="Veloce: giocate con valore e multiple. Approfondita: in più Claude per tutte le "
                                 "partite analizzate.")
    simulations = int(columns[3].number_input("Simulazioni", 5_000, 100_000, int(settings["simulazioni"]), 5_000,
                                              key="today_simulations"))
    if st.button("Cerca le partite del giorno (gratis)", key="today_events_button", disabled=not chosen):
        events, _, warnings = api.sports_with_matches(chosen, day)
        for warning in warnings:
            st.warning(warning)
        st.session_state["today_events"] = (day, events)
    from ui_quotes import (archive, render_collection, render_combo, render_my_markets, render_paste_box,
                           render_paste_summary, render_quote_report, render_selection)

    found = st.session_state.get("today_events")
    events = found[1] if found else None
    if events is not None and not events.empty:
        events = events[events["sport"].isin(chosen)] if chosen else events
    st.subheader("Selezione del giorno")
    render_selection(events)
    import day_archive

    entries = day_archive.selected(archive())
    if not entries:
        return
    from ui_tactical import render_manager

    render_manager(sorted({entry["home"] for entry in entries} | {entry["away"] for entry in entries}))
    render_paste_box()
    render_paste_summary()
    render_collection(api)
    render_quote_report(api)
    _render_analyze_all(entries, simulations, settings)
    _render_problems()
    _render_timing()
    analyses = _analyses()
    if not analyses:
        return
    from ui_manual import render_manual_section

    render_manual_section(analyses, settings)
    _render_overview(analyses, settings)
    _render_team_cards_switch(settings)
    if mode == "Approfondita":
        _render_deep(api, analyses, settings)
    from ui_quick import render_quick_search

    render_quick_search(analyses, settings)
    _render_analyst(analyses, settings)
    _render_dual(analyses, settings)
    _render_sharp_list(analyses)
    render_my_markets(analyses)
    render_combo(analyses)
    _render_quick(analyses, settings)
    _render_builder(analyses, settings)


def _render_analyze_all(entries: list[dict], simulations: int, settings: dict) -> None:
    """Pulsanti «Prepara la giornata» e «Analizza tutte» sulle partite selezionate: nessuna chiamata a crediti."""
    st.subheader("Analisi")
    st.caption(f"{len(entries)} partite selezionate. «Analizza tutte» usa solo le quote già presenti (incollate, CSV, "
               "API già scaricate); senza quote la partita è «solo modello».")
    columns = st.columns(2)
    if columns[0].button("Prepara la giornata", key="today_prepare",
                         help="Scalda la cache (CSV, Understat, calendario, Elo da risultati) per le selezionate: "
                              "non simula e non usa crediti The Odds API."):
        _prepare_day(entries, simulations, settings)
    if columns[1].button("Analizza tutte", type="primary", key="today_analyze"):
        _analyze_day(entries, simulations, settings)


def _style_loader():
    """Archivio di stile per campionato (una volta al giorno, cache su disco); ``None`` se la fonte non risponde."""
    from datetime import date as _date

    import style_profile
    from ui_data import source_cache

    def load(league: str):
        return style_profile.load_store(league, _date.today(), source_cache())

    return load


def _analyze_day(entries: list[dict], simulations: int, settings: dict) -> None:
    from datasources.builder import DataProvider
    from datasources.sources import COMPETITIONS, CUP_COMPETITIONS, football_data_org_key
    import day_archive
    from ui_data import source_cache
    from ui_quotes import odds_fields
    from ui_tactical import saved_sheets

    provider = DataProvider(source_cache(), football_data_key=football_data_org_key())
    progress = st.progress(0.0, text="Analisi in corso…")
    analyses = []
    with registra() as registro:
        started = time.perf_counter()
        for position, entry in enumerate(entries, start=1):
            match = day_archive.today_match(entry)
            competition = match.competition if match.competition in COMPETITIONS or match.competition in CUP_COMPETITIONS else None
            analysis = analyze(match, provider.build, odds_fields(entry), simulations=simulations, competition=competition,
                               settings=settings, sheets=saved_sheets(), manual=manual_for(match),
                               keep_samples=bool(entry.get("to_play")), style_loader=_style_loader())
            if analysis.ok:
                try:
                    if not _with_quotes(analysis):
                        analysis.warnings.append("solo modello: nessuna quota raccolta o incollata per questa partita")
                    _remember(analysis)
                except Exception as exc:  # una partita in errore non ferma le altre e resta nella tabella
                    analysis.result = None
                    mark_failed(analysis, "salvataggio", "app", f"errore dopo la simulazione ({type(exc).__name__}: {str(exc)[:120]})")
            analyses.append(analysis)
            progress.progress(position / len(entries), text=f"{position}/{len(entries)} · {match.label}")
        elapsed = time.perf_counter() - started
    progress.empty()
    st.session_state["today_analyses"] = analyses
    st.session_state["today_problems"] = problem_rows(analyses)
    st.session_state["today_timing"] = {"label": "Analizza tutte", "total": elapsed, "phases": registro.breakdown(elapsed),
                                        "sources": registro.sources(), "matches": len(entries)}
    st.session_state.pop("today_overrides", None)


def _prepare_day(entries: list[dict], simulations: int, settings: dict) -> None:
    """«Prepara la giornata»: ``today.prepare`` per ogni selezionata (cache dei dati), senza simulare né The Odds API."""
    from datasources.builder import DataProvider
    from datasources.sources import COMPETITIONS, CUP_COMPETITIONS, football_data_org_key
    import day_archive
    from ui_data import source_cache
    from ui_quotes import odds_fields
    from ui_tactical import saved_sheets

    provider = DataProvider(source_cache(), football_data_key=football_data_org_key())
    progress = st.progress(0.0, text="Preparazione in corso…")
    live = st.empty()
    prepared = []
    with registra() as registro:
        started = time.perf_counter()
        for position, entry in enumerate(entries, start=1):
            match = day_archive.today_match(entry)
            competition = match.competition if match.competition in COMPETITIONS or match.competition in CUP_COMPETITIONS else None
            prepared.append(prepare(match, provider.build, odds_fields(entry), simulations=simulations, competition=competition,
                                    settings=settings, sheets=saved_sheets(), manual=manual_for(match),
                                    style_loader=_style_loader()))
            progress.progress(position / len(entries), text=f"{position}/{len(entries)} · {match.label}")
            live.dataframe(pd.DataFrame([{**source, "Partite da preparare": len(entries) - position}
                                         for source in registro.sources()]), hide_index=True, width="stretch")
        elapsed = time.perf_counter() - started
    progress.empty()
    live.empty()
    # Le partite preparate (o con dati da completare) entrano in elenco; quelle già analizzate restano come sono.
    done = {analysis.match.event_id or analysis.match.label: analysis for analysis in _analyses() if analysis.ok}
    st.session_state["today_analyses"] = [done.get(analysis.match.event_id or analysis.match.label, analysis) for analysis in prepared]
    problems = problem_rows(st.session_state["today_analyses"])
    st.session_state["today_problems"] = problems
    st.session_state["today_timing"] = {"label": "Prepara la giornata", "total": elapsed, "phases": registro.breakdown(elapsed),
                                        "sources": registro.sources(), "matches": len(entries)}
    st.success(f"Giornata preparata in {elapsed:.1f} s: {len(prepared) - len(problems)} partite pronte, "
               f"{len(problems)} con dati da sistemare (le trovi in «Modifica o completa i dati»). "
               "Ora «Analizza tutte» usa la cache.")


def _render_problems() -> None:
    """Tabella «Partite non analizzate» dell'ultimo giro (Prepara o Analizza): una riga per partita, mai nascoste."""
    problems = st.session_state.get("today_problems") or []
    if not problems:
        return
    st.subheader(f"Partite non analizzate ({len(problems)})")
    st.caption("Dati mancanti non vengono mai inventati. Le altre partite non sono state fermate.")
    st.dataframe(pd.DataFrame(problems), hide_index=True, width="stretch")


def _render_timing() -> None:
    """Expander «Tempi» (chiuso): fase / secondi, fonti con richieste HTTP, hit di cache ed errori, totale."""
    timing = st.session_state.get("today_timing")
    if not timing:
        return
    with st.expander(f"Tempi · {timing['label']}: {timing['total']:.1f} s per {timing['matches']} partite", expanded=False):
        st.dataframe(pd.DataFrame(timing["phases"]), hide_index=True, width="stretch")
        if timing["sources"]:
            st.markdown("**Fonti**")
            st.dataframe(pd.DataFrame(timing["sources"]), hide_index=True, width="stretch")
        st.caption("Ultimo giro. Le fasi sommano al totale (la riga «altro» raccoglie cicli e tabelle).")


def _pct(result: dict, key: str) -> float | None:
    value = result["components"]["finale"].get(key)
    return None if value is None else round(float(value), 1)


def _render_overview(analyses: list[Analysis], settings: dict) -> None:
    flags = list(settings["segnalazioni"])
    ok = [(index, analysis) for index, analysis in enumerate(analyses) if analysis.ok]
    skipped = [analysis for analysis in analyses if not analysis.ok and analysis.problem is not None]
    waiting = [analysis for analysis in analyses if not analysis.ok and analysis.problem is None]
    st.subheader(f"Partite analizzate: {len(ok)}" + (f" · da analizzare {len(waiting)}" if waiting else "")
                 + (f" · non analizzate {len(skipped)}" if skipped else ""))
    if not ok:
        return
    rows = []
    for index, analysis in ok:
        result = analysis.result
        rows.append({
            "Ora": f"{analysis.match.commence_time:%H:%M}", "Competizione": analysis.match.competition,
            "Partita": analysis.match.label, "1 %": _pct(result, "1"), "X %": _pct(result, "X"), "2 %": _pct(result, "2"),
            "Over 2.5 %": _pct(result, "Over 2.5 gol"), "Goal %": _pct(result, "Goal"),
            "Corner": round(result["markets"]["corners"]["mean"], 1), "Cartellini": round(result["markets"]["cards"]["mean"], 1),
            **{flag: flag in analysis.flags for flag in flags},
        })
    st.caption("Segnalazioni da osservatore: un clic sulla casella e la partita si ricalcola (effetti piccoli e limitati "
               "in config/oggi.json); finiscono in Note nel registro per misurarle nella pagina Prestazioni.")
    edited = st.data_editor(
        pd.DataFrame(rows), hide_index=True, width="stretch", key=f"today_overview_{len(analyses)}_{id(analyses)}",
        disabled=[column for column in rows[0] if column not in flags],
        column_config={flag: st.column_config.CheckboxColumn(flag, width="small") for flag in flags},
    )
    changed = False
    for (index, analysis), (_, row) in zip(ok, edited.iterrows()):
        chosen = tuple(flag for flag in flags if bool(row[flag]))
        if chosen != analysis.flags:
            simulate(analysis, flags=chosen, settings=settings)
            _remember(analysis)
            changed = True
    if changed:
        st.session_state.pop("today_overrides", None)
        st.rerun()
    columns = st.columns([4, 1])
    labels = {index: analysis.match.label for index, analysis in ok}
    target = columns[0].selectbox("Scheda completa della partita", list(labels), format_func=labels.get, key="today_card")
    columns[1].button("Apri scheda", key="today_open_card", on_click=_open_card, args=(target,), width="stretch",
                      help="Apre la partita nella pagina Partita con tutte le tab (Panoramica, Gol, Corner…, Registro).")


# --- Modalità veloce ---------------------------------------------------------------------------------

def _save_info(analysis: Analysis, kind: str):
    from prediction_log import SaveInfo, model_version

    claude = analysis.claude is not None and analysis.claude.adjustment() is not None
    local = analysis.match.commence_time.astimezone()
    return SaveInfo(local.date(), f"{local:%H:%M}", analysis.match.competition, kind,
                    model_version(analysis.config, claude=claude), analysis.note())


def _single_rows(analysis: Analysis, selections: list[str], kind: str) -> list[dict]:
    from prediction_log import prediction_rows

    claude = analysis.result if analysis.claude is not None and analysis.claude.adjustment() is not None else None
    from ui_eurobet import sharp_notes

    return prediction_rows(analysis.result, selections, _save_info(analysis, kind), claude=claude, odds=analysis.odds,
                           extra_notes=sharp_notes(analysis.match.home, analysis.match.away))


def _save(rows: list[dict]) -> None:
    from ui_memory import registry_log, session_id

    from ui_memory import with_form

    new, updated = registry_log().save(with_form(rows), session_id())
    st.success(f"Registro: {new} righe nuove" + (f", {updated} aggiornate (stesso ID)." if updated else ".")
               + " Le trovi nella tab Registro della pagina Partita e nell'Excel della giornata.")


# --- Cartellini per squadra (fase T) ---------------------------------------------------------------------

def _render_team_cards_switch(settings: dict) -> None:
    """1X2 cartellini e cartellini per squadra in liste e multiple: solo con verifica superata o per scelta manuale."""
    from today import team_cards_status

    allowed, why = team_cards_status(settings)
    include = st.toggle("Includi 1X2 cartellini e cartellini per squadra in liste e multiple", value=allowed,
                        key="team_cards_manual", help=f"Verifica fuori campione: {why}.")
    st.session_state["include_team_cards"] = include
    if include and not allowed:
        st.caption(f"Inclusi per tua scelta, anche se la verifica non è superata: {why}.")
    elif not include:
        st.caption(f"1X2 cartellini e cartellini per squadra esclusi da liste e multiple ({why if not allowed else 'scelta manuale'}).")


def _team_cards_filter(legs: list) -> list:
    from today import team_card_market

    if st.session_state.get("include_team_cards"):
        return legs
    return [leg for leg in legs if not any(team_card_market(selection) for selection in leg.selections)]


# --- Report dell'Analista ---------------------------------------------------------------------------------

def _render_analyst(analyses: list[Analysis], settings: dict) -> None:
    """Incolla il report dell'Analista: blocchi abbinati alle partite e correzioni con le regole della fase G."""
    import hashlib

    from analyst import Target, match_blocks, parse_report, report_rows

    text = st.session_state.get("analyst_text") or ""
    if not text.strip():
        return
    blocks = parse_report(text)
    if not blocks:
        return
    st.subheader("Report dell'Analista · partite di oggi")
    targets = [Target(index, analysis.match.home, analysis.match.away, analysis.match.commence_time.astimezone().date())
               for index, analysis in enumerate(analyses) if analysis.ok]
    match_blocks(blocks, targets)
    names = {index: analysis.match.label for index, analysis in enumerate(analyses)}
    rows = report_rows(blocks, names)
    matched = [row for row, block in zip(rows, blocks) if block.matched is not None]
    unmatched = [row for row, block in zip(rows, blocks) if block.matched is None]
    st.caption(f"{len(blocks)} blocchi nel report: {len(matched)} abbinati, {len(unmatched)} non abbinati. Correzioni con le "
               "regole della fase G: limiti, fonte obbligatoria, media dell'arbitro avvicinata alla media.")
    if matched:
        st.dataframe(pd.DataFrame(matched).drop(columns=["Non abbinato perché"]), hide_index=True, width="stretch")
        _render_forms(blocks, analyses)
    if unmatched:
        st.markdown("**Blocchi non abbinati**")
        st.dataframe(pd.DataFrame(unmatched)[["Partita del report", "Data del report", "Non abbinato perché"]],
                     hide_index=True, width="stretch")
    apply = st.toggle("Applica le correzioni del report", value=True, key="analyst_apply")
    signature = (hashlib.sha256(text.encode()).hexdigest(), apply, len(analyses), id(analyses))
    if st.session_state.get("analyst_signature") != signature:
        by_index = {block.matched: block for block in blocks if block.matched is not None}
        previous = set(st.session_state.get("analyst_applied", []))
        for index, analysis in enumerate(analyses):
            block = by_index.get(index)
            if not analysis.ok or (block is None and index not in previous):
                continue
            use = block is not None and apply and block.response is not None
            analysis.claude_text = block.full_text if use else ""  # correzioni e chiavi del match
            simulate(analysis, claude=block.response if use else None, keep_claude=False, settings=settings)
            _remember(analysis)
        st.session_state["analyst_applied"] = [index for index, block in by_index.items() if apply and block.response]
        _record_dataset(analyses, by_index)
        _store_report(text, rows)
        st.session_state["analyst_signature"] = signature
        st.session_state.pop("today_overrides", None)
        st.rerun()
    st.caption("Correzioni applicate dopo l'ancoraggio al mercato; «Apri scheda» le porta nella tab Claude della partita."
               if apply else "Correzioni lette ma non applicate.")


def _render_forms(blocks, analyses: list[Analysis]) -> None:
    """Schede «Forma» accanto alle correzioni: solo informazione, mai nel calcolo (colonna «Forma» del registro)."""
    import dashboard
    from ui_memory import remember_form

    cards = []
    for block in blocks:
        if block.matched is None:
            continue
        match = analyses[block.matched].match
        remember_form(match.home, match.away, block.form.summary() if block.form is not None else "")
        if block.form is not None:
            cards.append(dashboard.form_card(match.home, match.away, block.form))
            for warning in block.form.warnings:
                st.caption(f"{match.label}: {warning}")
    if cards:
        st.html(dashboard.grid(cards))


def _record_dataset(analyses: list[Analysis], by_index: dict) -> None:
    """Fase Y: le partite abbinate entrano nel dataset dell'Analista con i profili alla data della partita."""
    from analyst_dataset import from_result, upsert
    from tactical_sheets import find_sheet
    from ui_memory import analyst_records, save_analyst_records
    from ui_tactical import saved_sheets

    records = analyst_records()
    for index in by_index:
        analysis = analyses[index]
        if not analysis.ok:
            continue
        home, away = analysis.match.home, analysis.match.away
        records = upsert(records, from_result(analysis.match.commence_time.astimezone().date(), analysis.match.competition,
                                              home, away, analysis.result, analysis.odds, find_sheet(saved_sheets(), home),
                                              find_sheet(saved_sheets(), away), analysis.tactical))
    save_analyst_records(records)


def render_analyst_report() -> None:
    """Report dell'Analista (fasi W e Y): esiti di ieri, profili tattici e storico proprio; le correzioni delle
    partite di oggi si abbinano più sotto, dopo «Analizza tutte»."""
    import hashlib

    from analyst import fill_registry, fill_slips, merge_profiles, parse_full
    from analyst_dataset import attach_outcome
    from ui_memory import analyst_records, registry_log, save_analyst_records, session_id
    from ui_tactical import STATE_KEY, saved_sheets

    st.subheader("Report dell'Analista")
    text = st.text_area("Incolla report dell'Analista", key="analyst_text", height=160,
                        help="L'intero report: blocchi ESITO (partite di ieri), PARTITA con CORREZIONI_CLAUDE e "
                             "CHIAVI_MATCH (partite di oggi, abbinate dopo «Analizza tutte») e PROFILO_TATTICO (squadre). "
                             "Il testo libero viene ignorato.")
    if not text.strip():
        return
    report = parse_full(text, date.today())
    signature = hashlib.sha256(text.encode()).hexdigest()
    outcomes = report.outcomes
    if outcomes:
        st.markdown("**Esiti delle partite di ieri**")
        st.dataframe(pd.DataFrame([{"Partita": block.label, "Data": f"{block.when:%d/%m/%Y}" if block.when else "",
                                    "Competizione": block.competition, "Per tempo": "sì" if block.has_halves else "no",
                                    "Fonte": block.source or "", "Stato": block.error or "valido"} for block in outcomes]),
                     hide_index=True, width="stretch")
        if st.session_state.get("analyst_outcome_signature") != signature:
            log, session = registry_log(), session_id()
            changed, settled = fill_registry(log.rows(session), outcomes)
            if changed:
                log.save(changed, session)
            slips, legs = fill_slips(st.session_state.get("saved_slips", []), outcomes)
            st.session_state["saved_slips"] = slips
            records, added = analyst_records(), 0
            for block in outcomes:
                if not block.error:
                    records, status = attach_outcome(records, block)
                    added += status != "già presente"
            save_analyst_records(records)
            st.session_state["analyst_outcome_signature"] = signature
            st.session_state["analyst_outcome_report"] = (
                f"Registro: {settled} selezioni con esito; schedine: {legs} gambe; dataset: {added} esiti aggiunti. "
                "Esiti già presenti mai sovrascritti; fonte e data in Note.")
        st.caption(st.session_state.get("analyst_outcome_report", ""))
    if report.profiles or report.warnings:
        st.markdown("**Profili tattici**")
        for warning in report.warnings:
            st.warning(warning)
        if st.session_state.get("analyst_profile_signature") != signature:
            sheets, changes, pending = merge_profiles(saved_sheets(), report.profiles)
            st.session_state[STATE_KEY] = sheets
            st.session_state["analyst_profile_pending"] = (changes, [sheet.to_dict() for sheet in pending])
            st.session_state["analyst_profile_signature"] = signature
        changes, pending = st.session_state.get("analyst_profile_pending", ([], []))
        st.caption(f"{len(report.profiles)} profili letti: aggiornati subito quelli senza valori diversi dai precedenti.")
        if changes:
            st.warning("Alcuni profili cambiano valori già salvati: conferma per aggiornarli.")
            st.dataframe(pd.DataFrame(changes), hide_index=True, width="stretch")
            if st.button("Conferma i cambi dei profili", key="analyst_profile_confirm"):
                from tactical_sheets import TacticalSheet, upsert as upsert_sheets

                st.session_state[STATE_KEY] = upsert_sheets(saved_sheets(), [TacticalSheet.from_dict(item) for item in pending])
                st.session_state["analyst_profile_pending"] = ([], [])
                st.rerun()
    st.caption(f"Dataset dell'Analista: {len(analyst_records())} partite nell'archivio locale (foglio «Dataset Analista» "
               "dell'Excel della giornata).")


def _store_report(text: str, rows: list[dict]) -> None:
    """Report nella memoria della giornata (e quindi nell'Excel): uno per testo, l'ultimo sostituisce i precedenti uguali."""
    import hashlib

    report_id = hashlib.sha1(text.encode()).hexdigest()[:12]
    reports = [report for report in st.session_state.get("analyst_reports", []) if report["id"] != report_id]
    reports.append({"id": report_id, "date": date.today().isoformat(), "saved_at": datetime.now().isoformat(timespec="seconds"),
                    "text": text, "rows": rows})
    st.session_state["analyst_reports"] = reports


# --- Doppio pronostico ---------------------------------------------------------------------------------

def _render_dual(analyses: list[Analysis], settings: dict) -> None:
    """Simulatore, la mia giocata e Unita per ogni partita; salvataggio con la fonte in Note."""
    from dual import DualChoice, choice_record, observer_options, pick_for, simulator_pick
    from prediction_log import TYPES

    st.subheader("Doppio pronostico: Simulatore · Osservatore · Unita")
    threshold = float(settings.get("soglia_disaccordo_forte", 0.45))
    st.caption("Simulatore = la giocata singola più probabile che non sia una trappola. «La mia giocata» la scegli tu tra "
               f"i mercati con quota. Unita = la conferma se coincidono, altrimenti scegli tu (di default la tua). In giallo "
               f"i disaccordi forti: per la tua scelta il simulatore dà meno del {threshold:.0%}.")
    trap = float(st.session_state.get("today_trap", settings["trappola_ev"]))
    min_odds = float(st.session_state.get("today_min_odds", settings["quota_minima_gamba"]))
    header = st.columns([3, 3.2, 3.6, 1.3, 3.6])
    for column, title in zip(header, ("Partita", "Simulatore", "La mia giocata", "Quota", "Unita")):
        column.markdown(f"**{title}**")
    choices = []
    for index, analysis in enumerate(analyses):
        if not analysis.ok:
            continue
        key = analysis.match.event_id
        legs = _team_cards_filter(candidate_legs(str(index), analysis.match.label, analysis.result, analysis.odds))
        sim_leg = simulator_pick(legs, trap_ev=trap, min_odds=min_odds)
        simulator = pick_for(sim_leg.selections[0], analysis.result, sim_leg.odds) if sim_leg else None
        options = observer_options(analysis.result, analysis.odds)
        columns = st.columns([3, 3.2, 3.6, 1.3, 3.6])
        columns[0].markdown(f"{analysis.match.label}  \n:gray[{analysis.match.competition} · {analysis.match.commence_time:%H:%M}]")
        columns[1].markdown(simulator.label() if simulator else ":gray[nessuna giocata non-trappola]")
        mine = columns[2].selectbox("La mia giocata", ["—", *options], key=f"dual_obs_{key}", label_visibility="collapsed",
                                    format_func=lambda option, final=analysis.result["components"]["finale"]:
                                    option if option == "—" else f"{option} (simulatore {final[option]:.0f}%)")
        observer = None
        if mine != "—":
            odds = columns[3].number_input("Quota", 1.01, 1000.0, float(analysis.odds[mine]), 0.01, format="%.2f",
                                           key=f"dual_odds_{key}_{mine}", label_visibility="collapsed")
            observer = pick_for(mine, analysis.result, float(odds))
        if observer is None or simulator is None or observer.selection == simulator.selection:
            unita = observer or simulator
            columns[4].markdown(("✓ confermata: " if observer and simulator else "") + (unita.label() if unita else "—"))
        else:
            chosen = columns[4].radio("Unita", ["La mia", "Simulatore"], key=f"dual_unita_{key}", horizontal=True,
                                      label_visibility="collapsed")
            unita = observer if chosen == "La mia" else simulator
        choice = DualChoice(_record_id(analysis), analysis.match.label, simulator, observer, unita)
        if choice.strong_disagreement(threshold):
            columns[4].warning(f"Disaccordo forte: per {observer.selection} il simulatore dà {observer.probability:.0%}.")
        choices.append((analysis, choice))
    # Si aggiornano le partite di questa pagina; restano le altre (es. riprese da file).
    merged = {item["id"]: item for item in st.session_state.get("dual_choices", [])}
    merged.update({record["id"]: record for record in (choice_record(choice, analysis.match.commence_time.date(), threshold)
                                                       for analysis, choice in choices)})
    st.session_state["dual_choices"] = list(merged.values())
    columns = st.columns([2, 3])
    kind = columns[0].radio("Tipo", TYPES, index=1, horizontal=True, key="dual_kind")
    if columns[1].button("Salva il doppio pronostico nel registro", key="dual_save", disabled=not choices):
        _save([row for analysis, choice in choices for row in _dual_rows(analysis, choice, kind)])


def _dual_rows(analysis: Analysis, choice, kind: str) -> list[dict]:
    """Una riga per selezione con le fonti in Note; Prob_finale del simulatore anche per l'osservatore."""
    from dataclasses import replace as replace_info

    from dual import source_note, sources_by_selection
    from prediction_log import prediction_rows

    claude = analysis.result if analysis.claude is not None and analysis.claude.adjustment() is not None else None
    rows = []
    for selection, (sources, odds) in sources_by_selection(choice).items():
        info = _save_info(analysis, kind)
        info = replace_info(info, note="; ".join(part for part in (info.note, source_note(sources)) if part))
        rows += prediction_rows(analysis.result, [selection], info, claude=claude, odds={selection: odds})
    return rows


def _render_sharp_list(analyses: list[Analysis]) -> None:
    """Fase Y (0b): quote Eurobet sopra il prezzo equo sharp in tutte le partite con incollata e riferimento API."""
    from sharp_value import above, compare, threshold_pct
    from ui_eurobet import find_paste, sharp_for

    rows = []
    for analysis in analyses:
        paste, sharp = find_paste(analysis.match.home, analysis.match.away), sharp_for(analysis.match.home, analysis.match.away)
        if paste is not None and sharp:
            rows += [{"Partita": analysis.match.label, **row} for row in above(compare(paste.odds(), sharp))]
    if rows:
        st.subheader("Quote Eurobet sopra il prezzo equo sharp")
        st.caption(f"Quota Eurobet almeno {threshold_pct():g}% sopra la quota equa (senza margine) del riferimento sharp "
                   "dell'API. Nel registro queste giocate portano «eurobet_vs_sharp: +x%» in Note, per misurarne CLV e "
                   "rendimento nella pagina Prestazioni.")
        st.dataframe(pd.DataFrame(rows).sort_values("Scarto %", ascending=False), hide_index=True, width="stretch")


def _render_quick(analyses: list[Analysis], settings: dict) -> None:
    from prediction_log import TYPES

    st.subheader("Giocate con valore")
    picks = value_picks(analyses, settings, include_team_cards=bool(st.session_state.get("include_team_cards")))
    if not picks:
        st.info("Nessuna giocata sopra la soglia EV del proprio mercato (soglie in config/oggi.json).")
        return
    st.caption("Sopra la soglia EV del mercato (" + ", ".join(f"{group} {value:g}%" for group, value in settings["soglie_ev"].items())
               + "), ordinate per EV.")
    table = pd.DataFrame([{"Salva": False, "Partita": pick.match, "Giocata": pick.selection, "Prob. %": pick.probability,
                           "Quota": pick.odds, "EV %": round(pick.ev, 1), "Perché": pick.reason} for pick in picks])
    edited = st.data_editor(table, hide_index=True, width="stretch", key=f"today_picks_{len(picks)}_{id(analyses)}",
                            disabled=[column for column in table.columns if column != "Salva"],
                            column_config={"Salva": st.column_config.CheckboxColumn("Salva", width="small"),
                                           "Perché": st.column_config.TextColumn("Perché", width="large")})
    kind = st.radio("Tipo", TYPES, index=1, horizontal=True, key="today_picks_kind")
    chosen = [pick for pick, flag in zip(picks, edited["Salva"]) if flag]
    if st.button(f"Salva nel registro ({len(chosen)} giocate)", key="today_picks_save", disabled=not chosen):
        rows = []
        for pick in chosen:
            rows += _single_rows(analyses[pick.analysis_index], [pick.selection], kind)
        _save(rows)


# --- Modalità approfondita ------------------------------------------------------------------------------

def _render_deep(api, analyses: list[Analysis], settings: dict) -> None:
    from claude_bridge import ResponseError, changes_table
    from ui_data import COPY_HINT

    st.subheader("Analisi approfondita")
    ok = {index: analysis.match.label for index, analysis in enumerate(analyses) if analysis.ok}
    selected = st.multiselect("Partite selezionate", list(ok), list(ok), format_func=ok.get, key="today_deep_selected")
    if not selected:
        return
    st.caption("Quote di corner e cartellini: raccoglile con il livello B in «Raccolta quote» (solo «Da giocare», con "
               "pre-conto) o incollale; qui nessuno scarico a crediti.")

    st.markdown("**Claude: un solo testo per tutte le partite selezionate**")
    if st.button("Prepara analisi per Claude", key="today_claude_prepare"):
        st.session_state["today_claude_prompt"] = multi_analysis_prompt(analyses, selected, day=date.today())
    prompt = st.session_state.get("today_claude_prompt")
    if prompt:
        st.caption(COPY_HINT)
        st.code(prompt, language="text")
    answer = st.text_area("Incolla la risposta di Claude (un blocco CORREZIONI_CLAUDE per partita, con l'ID)",
                          key="today_claude_answer", height=180)
    if not answer.strip():
        return
    ids = match_ids(analyses)
    try:
        texts, _ = split_multi_response(answer, ids)
        responses, warnings = parse_multi_response(answer, ids)
    except ResponseError as exc:
        st.error(str(exc))
        return
    for warning in warnings:
        st.warning(warning)
    names = {index: match_id for match_id, index in ids.items()}
    for index, response in responses.items():
        with st.expander(f"{names[index]} · {analyses[index].match.label}", expanded=False):
            st.dataframe(pd.DataFrame(changes_table(response)), hide_index=True, width="stretch")
            for warning in response.warnings:
                st.caption(warning)
    apply = st.toggle("Applica le correzioni di Claude", key="today_claude_apply")
    signature = (answer, apply)
    if st.session_state.get("today_claude_signature") != signature:
        for index, analysis in enumerate(analyses):
            if analysis.ok and (index in responses or analysis.claude is not None):
                analysis.claude_text = texts.get(index, "")  # torna nella tab Claude della scheda
                simulate(analysis, claude=responses.get(index) if apply else None, keep_claude=False, settings=settings)
                _remember(analysis)
        st.session_state["today_claude_signature"] = signature
        st.session_state.pop("today_overrides", None)
        st.rerun()
    st.caption("Correzioni applicate dopo l'ancoraggio al mercato, con i limiti e la regola delle fonti della fase G."
               if apply else "Correzioni lette ma non applicate.")


# --- Costruttore di multiple ----------------------------------------------------------------------------

def _leg_pool(analyses: list[Analysis], settings: dict) -> list[Leg]:
    from ui_eurobet import find_paste

    real = st.session_state.get("cb_real_odds", {})
    legs = []
    for index, analysis in enumerate(analyses):
        if not analysis.ok:
            continue
        paste = find_paste(analysis.match.home, analysis.match.away)
        combinable = paste.combinable() if paste is not None and not paste.empty else None
        legs += candidate_legs(str(index), analysis.match.label, analysis.result, analysis.odds, combinable,
                               cb_discount=float(settings.get("sconto_cb", 0.85)), cb_real_odds=real)
    return _team_cards_filter(legs)


def _leg_table(multiple: Multiple) -> pd.DataFrame:
    return pd.DataFrame([{
        "Partita": leg.match, "Gamba": leg.label, "Tipo": leg.kind, "Prob. %": round(leg.probability * 100, 1),
        "Quota": leg.odds, "Quota CB": ("stimata" if leg.estimated_odds else "reale") if leg.kind == "combo builder" else "",
        "Quota equa": round(leg.fair_odds, 2) if leg.fair_odds else None,
        "EV %": round(leg.ev * 100, 1) if leg.ev is not None else None,
    } for leg in multiple.legs])


def _render_cb_catalog(pool: list[Leg]) -> None:
    """Le combo più probabili di ogni partita (anche quelle escluse come trappole) con il campo della quota vera."""
    best: dict[str, list[Leg]] = {}
    for leg in pool:
        if leg.kind == "combo builder":
            best.setdefault(leg.match_id, []).append(leg)
    legs = [leg for group in best.values() for leg in sorted(group, key=lambda leg: -leg.probability)[:3]]
    if not legs:
        return
    with st.expander(f"Quote reali dei Combo Builder ({len(legs)} combo, le 3 più probabili per partita)", expanded=False):
        _render_cb_odds(Multiple("Combo Builder", legs), "cb_catalog")


def _render_cb_odds(multiple: Multiple, key: str) -> None:
    """Campo «Quota CB Eurobet» per ogni Combo Builder: con la quota vera, EV e quota totale usano quella."""
    combos = [leg for leg in multiple.legs if leg.kind == "combo builder"]
    if not combos:
        return
    real = st.session_state.setdefault("cb_real_odds", {})
    table = pd.DataFrame([{"Partita": leg.match, "Combo Builder": leg.label, "Prodotto": leg.product_odds,
                           "Quota usata": leg.odds, "Quota CB Eurobet": real.get(leg.key)} for leg in combos])
    st.caption("Quota CB Eurobet: scrivi la quota vera del Combo Builder che vedi su Eurobet. Vuota = stimata "
               "(prodotto × sconto CB di config/oggi.json).")
    edited = st.data_editor(table, hide_index=True, width="stretch", key=f"{key}_cb",
                            disabled=["Partita", "Combo Builder", "Prodotto", "Quota usata"],
                            column_config={"Quota CB Eurobet": st.column_config.NumberColumn(min_value=1.01, step=0.01, format="%.2f")})
    changed = False
    for leg, value in zip(combos, edited["Quota CB Eurobet"]):
        value = None if pd.isna(value) or float(value) <= 1.0 else float(value)
        if value != real.get(leg.key):
            if value is None:
                real.pop(leg.key, None)
            else:
                real[leg.key] = value
            changed = True
    if changed:
        st.rerun()


def _render_multiple(multiple: Multiple, pool: list[Leg], analyses: list[Analysis], key: str, kind: str) -> Multiple | None:
    overrides = st.session_state.setdefault("today_overrides", {})
    if key in overrides:
        # Gambe scelte a mano, aggiornate con le quote correnti (es. quota CB inserita dopo la sostituzione).
        current = {(leg.match_id, leg.selections): leg for leg in pool}
        multiple = replace(multiple, legs=[current.get((leg.match_id, leg.selections), leg) for leg in overrides[key]])
    if not multiple.legs:
        st.info("Nessuna gamba disponibile.")
        return None
    probability = format_probability(multiple.probability)
    metrics = st.columns(4)
    metrics[0].metric("Probabilità", probability)
    metrics[1].metric("Quota" + (" (con bonus)" if multiple.bonus_pct else ""), f"{multiple.odds:,.2f}".replace(",", ".") if multiple.odds else "—")
    metrics[2].metric("Quota equa", f"{multiple.fair_odds:,.2f}".replace(",", ".") if multiple.fair_odds else "—")
    metrics[3].metric("EV", f"{multiple.ev:+.1%}" if multiple.ev is not None else "—")
    st.markdown(f"**{multiple.sentence().capitalize()}** · {len(multiple.legs)} gambe")
    st.dataframe(_leg_table(multiple), hide_index=True, width="stretch")
    _render_cb_odds(multiple, key)
    warnings = multiple.leg_warnings()
    if warnings:
        st.warning("\n".join(f"- {warning}" for warning in warnings))
    with st.expander("Sostituisci una gamba", expanded=False):
        columns = st.columns([2, 4, 1])
        slot = columns[0].selectbox("Gamba", range(len(multiple.legs)), key=f"{key}_slot",
                                    format_func=lambda i: f"{i + 1} · {multiple.legs[i].match}")
        used = {leg.match_id for position, leg in enumerate(multiple.legs) if position != slot}
        options = [position for position, leg in enumerate(pool) if leg.match_id not in used]
        choice = columns[1].selectbox("Nuova gamba", options, key=f"{key}_choice",
                                      format_func=lambda i: f"{pool[i].match} · {pool[i].label} · {pool[i].probability:.0%} @ {pool[i].odds:.2f}")
        if columns[2].button("Sostituisci", key=f"{key}_replace") and choice is not None:
            overrides[key] = multiple.with_leg(slot, pool[choice]).legs
            st.rerun()
        if key in overrides and st.button("Torna alla proposta del sistema", key=f"{key}_reset"):
            overrides.pop(key)
            st.rerun()
    from ui_quick import render_save_slip

    dates = {str(index): analysis.match.commence_time.astimezone().date() for index, analysis in enumerate(analyses)}
    render_save_slip(multiple.legs, dates, key, f"{multiple.name} {date.today():%d/%m}")
    if st.button("Salva nel registro (gambe e riga Multipla)", key=f"{key}_save"):
        rows = []
        for leg in multiple.legs:
            rows += _single_rows(analyses[int(leg.match_id)], list(leg.selections), kind)
        first = analyses[int(multiple.legs[0].match_id)]
        info = _save_info(first, kind)
        rows.append(multiple_row(multiple, day=info.day, time=info.time, competition="", kind=kind, version=info.version))
        _save(rows)
    return multiple


def _render_builder(analyses: list[Analysis], settings: dict) -> None:
    from prediction_log import TYPES

    st.subheader("Costruttore di multiple")
    columns = st.columns(5)
    objective = columns[0].radio("Obiettivo", OBJECTIVES, index=OBJECTIVES.index(settings.get("obiettivo", "probabilità")),
                                 horizontal=True, key="today_objective",
                                 help="Probabilità: gambe più probabili anche a quota bassa. Valore: EV più alto.")
    trap = columns[1].number_input("Trappole: EV sotto %", -50.0, 0.0, float(settings["trappola_ev"]), 1.0, key="today_trap")
    min_odds = columns[2].number_input("Quota minima per gamba", 1.01, 3.0, float(settings["quota_minima_gamba"]), 0.05,
                                       key="today_min_odds")
    bonus = columns[3].number_input("Bonus multipla % (Eurobet)", 0.0, 100.0, float(settings["bonus_multipla_pct"]), 1.0,
                                    key="today_bonus", help="Incluso nella quota e nell'EV; vale se ogni gamba ha almeno la quota minima.")
    kind = columns[4].radio("Tipo", TYPES, index=1, horizontal=True, key="today_builder_kind")
    pool = _leg_pool(analyses, settings)
    _render_cb_catalog(pool)
    filtered = filter_legs(pool, trap_ev=trap, min_odds=min_odds)
    if filtered.traps:
        with st.expander(f"Trappole escluse ({len(filtered.traps)}): EV sotto {trap:g}%", expanded=False):
            st.dataframe(_leg_table(Multiple("", filtered.traps)), hide_index=True, width="stretch")
    if filtered.below_min:
        st.caption(f"{len(filtered.below_min)} gambe sotto la quota minima {min_odds:.2f} escluse.")
    legs = filtered.kept
    if not legs:
        st.info("Nessuna gamba con quota disponibile: servono quote (passaggio economico, mirato o Eurobet).")
        return
    tabs = st.tabs(["Singole e doppie", "Multipla corta (3-5)", "Multipla lunga (12-13)"])
    with tabs[0]:
        singles = Multiple("Singole", [])
        from multiples import best_singles

        for position, leg in enumerate(best_singles(legs, objective, 5), start=1):
            st.markdown(f"**Singola {position}** · {leg.match} · {leg.label}")
            _render_multiple(replace(singles, name=f"Singola {position}", legs=[leg]), legs, analyses, f"single_{position}", kind)
        for double in build_doubles(legs, objective, 3, bonus):
            st.markdown(f"**{double.name}**")
            _render_multiple(double, legs, analyses, f"double_{double.name}", kind)
    with tabs[1]:
        size = st.slider("Gambe", 3, 5, int(settings["multipla_corta_gambe"]), key="today_short_size")
        _render_multiple(build_short(legs, size, objective, bonus), legs, analyses, f"short_{size}_{objective}", kind)
    with tabs[2]:
        options = st.columns(2)
        total = options[0].radio("Gambe", [12, 13], index=[12, 13].index(int(settings["multipla_lunga_gambe"])),
                                 horizontal=True, key="today_long_total")
        combos = options[1].slider("Combo Builder", 0, 5, int(settings["multipla_lunga_combo"]), key="today_long_combos")
        comparison = st.empty()  # riga di confronto, scritta quando le due versioni sono pronte
        versions = st.columns(2)
        shown = {}
        for column, version, title in ((versions[0], "probabilità", "Più probabile"), (versions[1], "valore", "Più valore")):
            with column:
                st.markdown(f"**{title}**" + (" (obiettivo scelto)" if version == objective else ""))
                long = build_long(legs, total=total, combos=combos, objective=version, bonus_pct=bonus,
                                  name=f"Multipla lunga · {title.lower()}")
                shown[version] = _render_multiple(long, legs, analyses, f"long_{version}_{total}_{combos}", kind)
        line = comparison_line(shown.get("probabilità"), shown.get("valore"))
        if line:
            comparison.info(line)
