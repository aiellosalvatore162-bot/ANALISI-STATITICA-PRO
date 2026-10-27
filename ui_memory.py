"""Partite analizzate nella giornata (barra laterale), registro cumulativo ed Excel della giornata.

Le partite stanno in ``st.session_state["analyzed_matches"]`` (chiave data|casa - ospite), le righe del
registro nella tabella SQLite della sessione (``PredictionLog``). Online la sessione si perde al riavvio
dell'app: l'Excel della giornata e «Riprendi da file» la ricostruiscono.
"""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import uuid

import pandas as pd
import streamlit as st

from match_memory import day_workbook, make_record, read_day_workbook, summary_label, upsert
from prediction_log import PROBABILITY_COLUMNS, PredictionLog
from ui_data import source_cache


RESTART_WARNING = "Online i dati si perdono se l'app si riavvia: scarica l'Excel ogni 3-4 partite."
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def flags_key(home: str, away: str) -> str:
    """Chiave del campo «Segnalazioni da osservatore» della scheda: una per partita."""
    return f"observer_flags|{' '.join(home.split())}|{' '.join(away.split())}"


def _store() -> dict:
    return st.session_state.setdefault("analyzed_matches", {})


def session_id() -> str:
    return st.session_state.setdefault("session_id", uuid.uuid4().hex[:12])


def registry_log() -> PredictionLog:
    return PredictionLog(source_cache())


def remember(result: dict, *, block: str, odds: dict, simulations: int, seed: int, warnings=(), flags=()) -> dict:
    """Salva (o aggiorna) la partita appena simulata nella memoria della giornata."""
    from ui_eurobet import _find

    meta = st.session_state.get("match_meta") or {}
    home, away = result["input"]["home"]["name"], result["input"]["away"]["name"]
    paste = _find("eurobet_pastes", home, away)
    previous = _store().get(st.session_state.get("current_match_id") or "")
    same_match = previous is not None and (previous["home"], previous["away"]) == (home, away)
    if not same_match:
        # Partita diversa: la risposta di Claude incollata per la precedente non vale per questa.
        st.session_state["claude_answer"] = ""
        st.session_state["claude_apply"] = False
    record = make_record(
        result, block=block, odds=odds, day=meta.get("date") or date.today(), competition=meta.get("competition") or "",
        eurobet_text=paste["text"] if paste else "", warnings=warnings, simulations=simulations, seed=seed,
        claude_answer=previous.get("claude_answer", "") if same_match else "",
        claude_applied=previous.get("claude_applied", False) if same_match else False, flags=flags,
    )
    upsert(_store(), record)
    st.session_state["current_match_id"] = record["id"]
    return record


def remember_claude(result: dict, claude_result: dict | None) -> None:
    """Aggiunge alla voce della partita corrente la risposta di Claude incollata e, se applicate, le sue probabilità."""
    record = _store().get(st.session_state.get("current_match_id") or "")
    answer = st.session_state.get("claude_answer") or ""
    if record is None or (not answer and not record.get("claude_answer")):
        return
    applied = bool(st.session_state.get("claude_apply")) and claude_result is not None
    claude = ({key: claude_result["components"]["finale"].get(key) for key in record["summary"]["probabilities"]}
              if applied else None)
    if (record.get("claude_answer"), record.get("claude_applied"), record["summary"].get("claude")) != (answer, applied, claude):
        record.update(claude_answer=answer, claude_applied=applied)
        record["summary"]["claude"] = claude


def _reopen(record_id: str) -> None:
    """Callback: rimette blocco, quote dei campi, incollata Eurobet e risposta di Claude, poi risimula."""
    from eurobet import parse_eurobet
    from market_catalog import MARKET_CATALOG
    from ui_eurobet import _store as store_paste

    record = _store()[record_id]
    block = record["block"]
    st.session_state["input_text"] = block
    st.session_state["pending_input_mode"] = "Copia-incolla"
    token = str(abs(hash(block)))  # stessa chiave dei campi quota della scheda partita
    for definition in MARKET_CATALOG:
        st.session_state[f"odd_{token}_{definition.key}"] = float(record["odds"].get(definition.event_key, 0.0))
    if record.get("eurobet_text"):
        store_paste("eurobet_pastes", record["home"], record["away"], text=record["eurobet_text"],
                    paste=parse_eurobet(record["eurobet_text"]))
    st.session_state[flags_key(record["home"], record["away"])] = list(record.get("flags") or [])
    st.session_state["claude_answer"] = record.get("claude_answer", "")
    st.session_state["claude_apply"] = bool(record.get("claude_applied"))
    st.session_state.pop("claude_signature", None)
    day = record.get("date")
    st.session_state["match_meta"] = {"date": date.fromisoformat(day[:10]) if day else None,
                                      "competition": record.get("competition", "")}
    st.session_state["current_match_id"] = record_id
    st.session_state["auto_simulate"] = True


def _forget(record_id: str) -> None:
    _store().pop(record_id, None)
    if st.session_state.get("current_match_id") == record_id:
        st.session_state.pop("current_match_id", None)


def day_file_bytes() -> bytes:
    return day_workbook(registry_log().rows(session_id()), list(_store().values()),
                        st.session_state.get("tactical_sheets", []), st.session_state.get("dual_choices", []),
                        st.session_state.get("analyst_reports", []))


def render_download(key: str) -> None:
    rows = registry_log().rows(session_id())
    st.download_button(
        "Scarica Excel della giornata", day_file_bytes(), file_name=f"giornata_{date.today():%Y%m%d}.xlsx", mime=XLSX,
        key=key, width="stretch",
        help=f"Fogli Registro (A–S, {summary_label(rows)}), Analisi ({len(_store())} partite), Schede tattiche "
             "e un foglio tecnico nascosto per «Riprendi da file».")


def render_sidebar() -> None:
    """Elenco delle partite analizzate: riapri, elimina, scarica e riprendi da file."""
    st.markdown("**Partite analizzate**")
    records = sorted(_store().values(), key=lambda record: record.get("date") or "")  # a parità, ordine di analisi
    if not records:
        st.caption("Nessuna partita simulata in questa sessione.")
    current = st.session_state.get("current_match_id")
    for record in records:
        columns = st.columns([5, 1])
        day = record.get("date") or ""
        label = f"{record['home']} - {record['away']}" + (f" · {day[8:10]}/{day[5:7]}" if len(day) >= 10 else "")
        columns[0].button(("▶ " if record["id"] == current else "") + label, key=f"memory_open_{record['id']}",
                          on_click=_reopen, args=(record["id"],), width="stretch",
                          help="Riapre la partita con blocco, quote, Eurobet e Claude già compilati e la risimula.")
        columns[1].button("", icon=":material/close:", key=f"memory_delete_{record['id']}", on_click=_forget, args=(record["id"],),
                          help="Elimina la partita dall'elenco (le righe del registro restano).")
    render_download("memory_download")
    upload = st.file_uploader("Riprendi da file", type=["xlsx"], key="memory_upload",
                              help="Carica un Excel della giornata scaricato prima: tornano registro, partite e schede tattiche.")
    if upload is not None:
        content = upload.getvalue()
        signature = hashlib.sha256(content).hexdigest()
        if st.session_state.get("memory_upload_signature") != signature:
            restore(content)
            st.session_state["memory_upload_signature"] = signature
        st.caption(st.session_state.get("memory_upload_report", ""))


def restore(content: bytes) -> None:
    day = read_day_workbook(content)
    new, updated = registry_log().save(day.registry_rows, session_id()) if day.registry_rows else (0, 0)
    for record in day.records:
        upsert(_store(), record)
    if day.tactical_rows:
        known = {row.get("ID") for row in st.session_state.get("tactical_sheets", [])}
        st.session_state["tactical_sheets"] = st.session_state.get("tactical_sheets", []) + \
            [row for row in day.tactical_rows if row.get("ID") not in known]
    if day.reports:
        known = {report.get("id") for report in day.reports}
        st.session_state["analyst_reports"] = [report for report in st.session_state.get("analyst_reports", [])
                                               if report.get("id") not in known] + day.reports
    if day.dual_choices:
        known = {choice.get("id") for choice in day.dual_choices}
        st.session_state["dual_choices"] = [choice for choice in st.session_state.get("dual_choices", [])
                                            if choice.get("id") not in known] + day.dual_choices
    st.session_state["memory_upload_report"] = (
        f"Ripreso: {new} righe del registro nuove, {updated} già presenti; {len(day.records)} partite; "
        f"{len(day.tactical_rows)} schede tattiche." + ("".join(f" {warning}" for warning in day.warnings)))


def render_registry_table() -> None:
    """Tutte le righe del registro della sessione: filtro per partita, contatore, eliminazione, download."""
    log, session = registry_log(), session_id()
    rows = log.rows(session)
    st.markdown(f"**Registro della giornata: {summary_label(rows)}**")
    if not rows:
        st.caption("Nessuna selezione salvata: scegli le selezioni qui sopra (dopo una simulazione) e premi «Salva nel registro».")
        render_download("registry_day_download")
        return
    frame = pd.DataFrame(rows)
    matches = sorted(frame["Partita"].dropna().unique())
    chosen = st.selectbox("Filtro per partita", ["Tutte le partite", *matches], key="registry_filter")
    shown = frame if chosen == "Tutte le partite" else frame[frame["Partita"] == chosen]
    st.dataframe(shown, hide_index=True, width="stretch",
                 column_config={column: st.column_config.NumberColumn(column, format="percent") for column in PROBABILITY_COLUMNS})
    remove = st.multiselect("Righe da eliminare", list(shown["ID"]), key="registry_remove", placeholder="Scegli le righe (ID)")
    if remove:
        st.button(f"Elimina {len(remove)} {'riga' if len(remove) == 1 else 'righe'}", key="registry_remove_button",
                  on_click=_delete_rows)
    if st.session_state.get("registry_remove_report"):
        st.success(st.session_state.pop("registry_remove_report"))
    render_download("registry_day_download")


def _delete_rows() -> None:
    deleted = registry_log().delete(st.session_state.get("registry_remove") or [], session_id())
    st.session_state["registry_remove"] = []
    st.session_state["registry_remove_report"] = f"{deleted} {'riga eliminata' if deleted == 1 else 'righe eliminate'}."
