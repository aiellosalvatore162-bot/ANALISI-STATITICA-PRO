"""Memoria delle partite analizzate nella giornata ed Excel della giornata (salva e riprendi).

Ogni partita simulata diventa una voce con tutto ciò che serve per riaprirla
(blocco dati, quote dei campi, incollata Eurobet, risposta di Claude) e un
riassunto delle probabilità principali con quote ed EV. La chiave è
data|casa - ospite: rianalizzare la stessa partita aggiorna la voce.

L'Excel della giornata ha i fogli:
- «Registro»: colonne A–S del file Registro_Previsioni.xlsx;
- «Analisi»: una riga per partita (probabilità principali, quote, EV);
- «Schede tattiche»: una riga per squadra (fase Q), ripristinabile dal foglio tecnico;
- «Tecnico» (nascosto): le voci complete in JSON, per «Riprendi da file».

Solo presentazione e salvataggio: nessun calcolo del modello.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from tactical_sheets import SHEET_COLUMNS, TacticalSheet, sheet_row


ANALYSIS_KEYS = (
    "1", "X", "2", "1X", "X2", "12",
    "Over 1.5 gol", "Under 1.5 gol", "Over 2.5 gol", "Under 2.5 gol", "Over 3.5 gol", "Under 3.5 gol",
    "Goal", "No Goal", "Multigol 1-3", "Multigol 2-4", "Multigol 2-5",
    "1 1T", "X 1T", "2 1T", "Over 0.5 gol 1T", "Over 1.5 gol 1T",
    "Over 8.5 corner", "Over 9.5 corner", "Over 10.5 corner",
    "Over 3.5 cartellini", "Over 4.5 cartellini", "Over 5.5 cartellini",
    # Fase Q (6b)
    "Over 4.5 gol", "Over 5.5 gol", "Goal + Over 2.5", "Multigol 1T 1-2", "Multigol 2T 1-3",
    "Over 4.5 corner 1T", "Over 1.5 cartellini 1T", "Corner totali 9-11", "Cartellini totali 4",
)
ANALYSIS_SHEET, REGISTRY_SHEET, TACTICAL_SHEET, TECHNICAL_SHEET = "Analisi", "Registro", "Schede tattiche", "Tecnico"
DUAL_SHEET = "Doppio pronostico"
REPORT_SHEET = "Report Analista"
SLIPS_SHEET = "Schedine"
TACTICAL_COLUMNS = SHEET_COLUMNS
_CHUNK = 30_000  # una cella Excel tiene al massimo 32.767 caratteri


def match_id(day: Any, home: str, away: str) -> str:
    day = day.isoformat() if isinstance(day, (date, datetime)) else str(day or "")
    return f"{day[:10]}|{' '.join(home.split())} - {' '.join(away.split())}"


def _clean(value: Any) -> Any:
    """Valori pronti per JSON ed Excel: niente NaN, date in ISO."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def make_record(result: Mapping[str, Any], *, block: str, odds: Mapping[str, float], day: Any, competition: str = "",
                eurobet_text: str = "", warnings: Iterable[str] = (), claude_answer: str = "",
                claude_applied: bool = False, claude_result: Mapping[str, Any] | None = None,
                simulations: int | None = None, seed: int | None = None, saved_at: datetime | None = None,
                flags: Iterable[str] = ()) -> dict:
    """Voce della memoria: dati per riaprire la partita e riassunto delle probabilità (in %)."""
    home, away = result["input"]["home"]["name"], result["input"]["away"]["name"]
    final = result["components"]["finale"]
    financial = {row["market"]: row for row in result["financial"]["markets"]}
    notes = [str(warning) for warning in warnings]
    notes += [f"valore sospetto su {market}" for market, row in financial.items() if row.get("suspicious_value")]
    record = {
        "id": match_id(day, home, away), "date": day, "competition": competition or "", "home": home, "away": away,
        "block": block, "odds": {key: float(value) for key, value in odds.items() if value and float(value) > 1.0},
        "eurobet_text": eurobet_text or "", "claude_answer": claude_answer or "", "claude_applied": bool(claude_applied),
        "flags": list(flags),
        "warnings": notes, "simulations": simulations, "seed": seed,
        "saved_at": (saved_at or datetime.now()).isoformat(timespec="seconds"),
        "summary": {
            "lambda": result["model"]["lambda"], "mu": result["model"]["mu"],
            "corner_mean": result["markets"]["corners"].get("mean"), "card_mean": result["markets"]["cards"].get("mean"),
            "probabilities": {key: final.get(key) for key in ANALYSIS_KEYS},
            "claude": ({key: claude_result["components"]["finale"].get(key) for key in ANALYSIS_KEYS}
                       if claude_result is not None else None),
            "ev": {market: row.get("ev_pct") for market, row in financial.items()},
            "value": [market for market, row in financial.items() if row.get("is_value")],
        },
    }
    return _clean(record)


def upsert(store: dict, record: Mapping[str, Any]) -> bool:
    """Aggiunge o aggiorna la voce (stessa chiave = stessa partita); ``True`` se esisteva già."""
    existed = record["id"] in store
    store[record["id"]] = dict(record)
    return existed


def analysis_rows(records: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Foglio «Analisi»: una riga per partita con probabilità finali, quote ed EV dei mercati principali."""
    rows = []
    for record in records:
        summary = record["summary"]
        row = {"ID": record["id"], "Data": record["date"], "Competizione": record.get("competition", ""),
               "Partita": f"{record['home']} - {record['away']}", "Gol attesi casa": summary.get("lambda"),
               "Gol attesi ospite": summary.get("mu"), "Corner attesi": summary.get("corner_mean"),
               "Cartellini attesi": summary.get("card_mean")}
        for key in ANALYSIS_KEYS:
            probability = summary["probabilities"].get(key)
            row[f"P {key}"] = None if probability is None else round(probability / 100.0, 4)
            row[f"Quota {key}"] = record["odds"].get(key)
            ev = summary["ev"].get(key)
            row[f"EV {key}"] = None if ev is None else round(ev / 100.0, 4)
        row["Valore (EV+)"] = ", ".join(summary.get("value") or [])
        row["Claude"] = "applicato" if record.get("claude_applied") and summary.get("claude") else (
            "risposta incollata" if record.get("claude_answer") else "")
        row["Eurobet"] = "incollata" if record.get("eurobet_text") else ""
        row["Segnalazioni"] = " · ".join(record.get("warnings") or [])
        row["Salvata"] = record.get("saved_at")
        rows.append(row)
    return rows


def day_workbook(registry_rows: Sequence[Mapping[str, Any]], records: Iterable[Mapping[str, Any]],
                 tactical_rows: Sequence[Mapping[str, Any]] = (), dual_choices: Sequence[Mapping[str, Any]] = (),
                 reports: Sequence[Mapping[str, Any]] = (), slips: Sequence[Mapping[str, Any]] = (),
                 dataset: Sequence[Mapping[str, Any]] = ()) -> bytes:
    """Un unico file: Registro (A–S), Analisi, Doppio pronostico, Schede tattiche e il foglio tecnico nascosto."""
    from openpyxl import Workbook

    from prediction_log import write_registry_sheet

    records = list(records)
    workbook = Workbook()
    registry = workbook.active
    registry.title = REGISTRY_SHEET
    write_registry_sheet(registry, registry_rows)

    analysis = workbook.create_sheet(ANALYSIS_SHEET)
    rows = analysis_rows(records)
    header = list(rows[0]) if rows else ["ID", "Data", "Competizione", "Partita"]
    analysis.append(header)
    for row in rows:
        analysis.append([row.get(column) for column in header])
    for index, column in enumerate(header, start=1):
        letter = analysis.cell(row=1, column=index).column_letter
        analysis.column_dimensions[letter].width = max(9, min(len(column) + 2, 28))
        if column.startswith(("P ", "EV ")):
            for cell in analysis[letter][1:]:
                cell.number_format = "0.0%"
    analysis.freeze_panes = "E2"

    from dual import dual_sheet_rows

    dual = workbook.create_sheet(DUAL_SHEET)
    dual_rows = dual_sheet_rows(dual_choices)
    dual_header = list(dual_rows[0]) if dual_rows else ["Data", "Partita", "Simulatore", "Osservatore", "Unita"]
    dual.append(dual_header)
    for row in dual_rows:
        dual.append([_clean(row.get(column)) for column in dual_header])
    for index, column in enumerate(dual_header, start=1):
        dual.column_dimensions[dual.cell(row=1, column=index).column_letter].width = max(10, min(len(column) + 2, 30))
        if column.startswith("Prob."):
            for cell in dual[dual.cell(row=1, column=index).column_letter][1:]:
                cell.number_format = "0.0%"

    report_sheet = workbook.create_sheet(REPORT_SHEET)
    report_header = ["Report", "Salvato", "Partita del report", "Data del report", "Partita abbinata", "Correzioni applicate",
                     "Correzioni scartate", "Confidenza", "Non abbinato perché"]
    report_sheet.append(report_header)
    for report in reports:
        for row in report.get("rows", []):
            report_sheet.append([report.get("id"), report.get("saved_at"), *[row.get(column) for column in report_header[2:]]])
    for index, width in enumerate((14, 20, 30, 18, 30, 40, 40, 12, 50), start=1):
        report_sheet.column_dimensions[report_sheet.cell(row=1, column=index).column_letter].width = width

    from slips import Slip, sheet_rows

    slip_sheet = workbook.create_sheet(SLIPS_SHEET)
    slip_rows = sheet_rows([Slip.from_dict(slip) for slip in slips])
    slip_header = ["Schedina", "Creata", "Stato", "Partita", "Data", "Gamba", "Quota", "Probabilità", "Esito gamba", "Note"]
    slip_sheet.append(slip_header)
    for row in slip_rows:
        slip_sheet.append([_clean(row.get(column)) for column in slip_header])
    for index, width in enumerate((22, 20, 16, 30, 12, 26, 8, 12, 12, 40), start=1):
        slip_sheet.column_dimensions[slip_sheet.cell(row=1, column=index).column_letter].width = width

    tactical = workbook.create_sheet(TACTICAL_SHEET)
    tactical.append(list(TACTICAL_COLUMNS))
    for item in tactical_rows:
        row = sheet_row(TacticalSheet.from_dict(item))
        tactical.append([_clean(row.get(column)) for column in TACTICAL_COLUMNS])

    from analyst_dataset import SHEET as DATASET_SHEET, SHEET_COLUMNS as DATASET_COLUMNS, sheet_row as dataset_row

    # Fase Y: storico proprio dell'Analista (cumulativo), una riga per partita.
    archive = workbook.create_sheet(DATASET_SHEET)
    archive.append(list(DATASET_COLUMNS))
    for item in dataset:
        row = dataset_row(item)
        archive.append([_clean(row.get(column)) for column in DATASET_COLUMNS])

    technical = workbook.create_sheet(TECHNICAL_SHEET)
    technical.append(["Tipo", "ID", "JSON (diviso su più colonne se lungo)"])
    for kind, items in (("partita", records), ("scheda", tactical_rows), ("doppio", dual_choices), ("report", reports),
                        ("schedina", slips), ("dataset", dataset)):
        for item in items:
            text = json.dumps(_clean(item), ensure_ascii=False)
            technical.append([kind, item.get("id") or item.get("ID"), *[text[i:i + _CHUNK] for i in range(0, len(text), _CHUNK)]])
    technical.sheet_state = "hidden"
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@dataclass
class DayFile:
    registry_rows: list[dict] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)
    tactical_rows: list[dict] = field(default_factory=list)
    dual_choices: list[dict] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    slips: list[dict] = field(default_factory=list)
    dataset: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def read_day_workbook(content: bytes) -> DayFile:
    """Registro, partite analizzate e schede tattiche da un Excel della giornata (o dal solo registro dell'utente)."""
    from openpyxl import load_workbook

    from performance import RegistryError, read_registry
    from prediction_log import COLUMNS

    result = DayFile()
    try:
        registry = read_registry(content)
    except RegistryError as exc:
        result.warnings.append(f"Registro non letto: {exc}")
    else:
        for record in registry.frame.to_dict("records"):
            row = {column: _clean(None if _missing(record.get(column)) else record.get(column)) for column in COLUMNS}
            if row["ID"]:
                result.registry_rows.append(row)
        result.warnings.extend(warning for warning in registry.warnings if "non contiene righe" not in warning)
    workbook = load_workbook(BytesIO(content), read_only=True)
    if TECHNICAL_SHEET in workbook.sheetnames:
        for values in workbook[TECHNICAL_SHEET].iter_rows(min_row=2, values_only=True):
            if not values or values[0] not in ("partita", "scheda", "doppio", "report", "schedina", "dataset"):
                continue
            try:
                item = json.loads("".join(str(part) for part in values[2:] if part is not None))
            except ValueError:
                result.warnings.append(f"Voce tecnica {values[1]} illeggibile: saltata.")
                continue
            {"partita": result.records, "scheda": result.tactical_rows, "doppio": result.dual_choices,
             "report": result.reports, "schedina": result.slips, "dataset": result.dataset}[values[0]].append(item)
    elif ANALYSIS_SHEET in workbook.sheetnames:
        result.warnings.append("Foglio tecnico assente: le partite del foglio Analisi non si possono riaprire.")
    workbook.close()
    return result


def _missing(value: Any) -> bool:
    try:
        return value is None or (isinstance(value, float) and math.isnan(value))
    except TypeError:
        return False


def summary_label(registry_rows: Sequence[Mapping[str, Any]]) -> str:
    """«12 selezioni da 5 partite»."""
    matches = {row.get("Partita") for row in registry_rows if row.get("Partita")}
    selections = len(registry_rows)
    return (f"{selections} {'selezione' if selections == 1 else 'selezioni'} da {len(matches)} "
            f"{'partita' if len(matches) == 1 else 'partite'}")
