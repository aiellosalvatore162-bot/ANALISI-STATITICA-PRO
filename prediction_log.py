"""Registro delle previsioni nel formato del file Excel dell'utente (colonne A–S del foglio «Registro»).

Una riga per selezione salvata. Le probabilità sono in decimali (0,62 = 62%),
come vogliono le formule Brier del file. ``Quota_chiusura`` ed ``Esito``
restano vuote al salvataggio: si compilano a mano o dalla pagina «Prestazioni».
L'``ID`` (data + partita + mercato + selezione) è la chiave: salvare di nuovo
la stessa selezione aggiorna la riga invece di duplicarla.

Le righe della sessione stanno nella tabella SQLite ``registro`` della cache
delle fonti; il registro minimo della fase G (``registro_previsioni``) viene
convertito in questo formato alla prima apertura e poi eliminato.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from io import BytesIO
import re
import sqlite3
from typing import Any, Mapping, Sequence

from datasources.cache import SourceCache


COLUMNS = (
    "ID", "Data", "Ora", "Competizione", "Partita", "Mercato", "Selezione", "Prob_finale", "Prob_mercato",
    "Prob_modello", "Prob_stile", "Prob_Claude", "Quota_presa", "Puntata", "Tipo", "Versione_modello",
    "Quota_chiusura", "Esito", "Note",
)
PROBABILITY_COLUMNS = ("Prob_finale", "Prob_mercato", "Prob_modello", "Prob_stile", "Prob_Claude")
# Stessi nomi, stesso ordine della tabella «per mercato» del foglio Riepilogo («Multipla»: schedine con più partite, fase S).
MARKETS = ("1X2", "Doppia chance", "DNB", "Over 1.5", "Under 1.5", "Over 2.5", "Under 2.5", "Over 3.5", "Under 3.5",
           "Goal/NoGoal", "Multigol", "Multigol casa", "Multigol ospite", "Primo tempo", "Over 0.5 1T", "Over 1.5 1T",
           "Corner", "Cartellini", "Combo", "Risultati esatti", "Multipla")
TYPES = ("Reale", "A carta")
# Selezioni proposte di default quando non ci sono quote inserite.
DEFAULT_SELECTIONS = ("1", "X", "2", "Over 1.5 gol", "Over 2.5 gol", "Under 2.5 gol", "Goal", "No Goal",
                      "Over 0.5 gol 1T", "Over 9.5 corner", "Over 4.5 cartellini")


_FIXED_MARKETS = {
    "1": "1X2", "X": "1X2", "2": "1X2", "1X": "Doppia chance", "X2": "Doppia chance", "12": "Doppia chance",
    "Casa DNB": "DNB", "Ospite DNB": "DNB", "Goal": "Goal/NoGoal", "No Goal": "Goal/NoGoal",
    "1 1T": "Primo tempo", "X 1T": "Primo tempo", "2 1T": "Primo tempo",
    "Over 0.5 gol 1T": "Over 0.5 1T", "Over 1.5 gol 1T": "Over 1.5 1T",
    **{f"{side} {line} gol": f"{side} {line}" for side in ("Over", "Under") for line in ("1.5", "2.5", "3.5")},
}
# Gruppo di risultati esatti: «1-0/2-0/2-1» (vedi exact_scores.group_selection).
_EXACT_GROUP = re.compile(r"^\d{1,2}-\d{1,2}(?:/\d{1,2}-\d{1,2})*$")
_MULTIGOL = re.compile(r"^Multigol (?:(?P<team>Casa|Ospite) )?\d+-\d+$")
# Quote rimborsate (DNB con pareggio): l'evento «push» del motore con lo stesso prefisso.
PUSH_SELECTIONS = ("Casa DNB", "Ospite DNB")


def market_of(selection: str) -> str | None:
    """Mercato del Riepilogo a cui appartiene una chiave evento del motore (``None`` se non registrabile).

    Le linee senza un nome nella tabella del Riepilogo (es. Over 4.5, Goal 1T) restano non registrabili.
    """
    key = selection.strip()
    if " + " in key:
        return "Combo"
    if _EXACT_GROUP.match(key):
        return "Risultati esatti"
    if key in _FIXED_MARKETS:
        return _FIXED_MARKETS[key]
    if "corner" in key and not key.endswith(" 1T"):
        return "Corner"
    if "cartellini" in key:
        return "Cartellini"
    multigol = _MULTIGOL.match(key)
    if multigol:
        return {None: "Multigol", "Casa": "Multigol casa", "Ospite": "Multigol ospite"}[multigol["team"]]
    return None


def _day(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "").strip()


def selection_id(day: Any, match: str, market: str, selection: str) -> str:
    return f"{_day(day)}|{' '.join(str(match).split())}|{market}|{selection.strip()}"


def model_version(config, *, claude: bool = False) -> str:
    """Etichetta leggibile della configurazione che ha prodotto la probabilità finale."""
    parts = [config.goal_model, f"ancoraggio {config.market_anchor.market_weight:g}"]
    switches = [name for name, active in asdict(config.tactical_switches).items() if active] \
        if getattr(config, "tactical", None) is not None else []
    if switches:
        parts.append("stile " + "+".join(switches))
    if claude:
        parts.append("Claude")
    return " · ".join(parts)


@dataclass(frozen=True)
class SaveInfo:
    day: date
    time: str
    competition: str
    kind: str
    version: str
    note: str = ""


def _probability(result: Mapping[str, Any] | None, component: str, selection: str) -> float | None:
    """Probabilità decimale; per il DNB è condizionata al non rimborso (vinta / (vinta + persa))."""
    if result is None:
        return None
    if _EXACT_GROUP.match(selection):
        from exact_scores import group_probability, group_scores

        distribution = (result.get("exact_scores") or {}).get(component)
        return None if distribution is None else round(group_probability(distribution, group_scores(selection)), 4)
    values = result["components"].get(component) or {}
    value = values.get(selection)
    if value is None:
        return None
    if selection in PUSH_SELECTIONS:
        push = float(values.get(f"{selection} push", 0.0))
        return round(float(value) / (100.0 - push), 4) if push < 100.0 else None
    return round(float(value) / 100.0, 4)


def prediction_rows(base: Mapping[str, Any], selections: Sequence[str], info: SaveInfo, *,
                    styled: Mapping[str, Any] | None = None, claude: Mapping[str, Any] | None = None,
                    odds: Mapping[str, float] | None = None, stakes: Mapping[str, float] | None = None) -> list[dict]:
    """Una riga per selezione.

    ``base`` è la simulazione senza correzioni di stile né di Claude: da qui
    vengono ``Prob_mercato`` (solo quote) e ``Prob_modello`` (solo modello).
    ``styled`` è la simulazione con lo scenario tattico attivo, ``claude``
    quella con le correzioni di Claude; ``Prob_finale`` è l'ultima disponibile.
    """
    match = f"{base['input']['home']['name']} - {base['input']['away']['name']}"
    final = claude if claude is not None else styled if styled is not None else base
    rows = []
    for selection in selections:
        market = market_of(selection)
        if market is None or (market != "Risultati esatti" and selection not in final["components"]["finale"]):
            raise ValueError(f"Selezione «{selection}»: mercato non previsto dal registro.")
        rows.append({
            "ID": selection_id(info.day, match, market, selection), "Data": info.day, "Ora": info.time,
            "Competizione": info.competition, "Partita": match, "Mercato": market, "Selezione": selection,
            "Prob_finale": _probability(final, "finale", selection),
            "Prob_mercato": _probability(base, "mercato", selection),
            "Prob_modello": _probability(base, "modello", selection),
            "Prob_stile": _probability(styled, "finale", selection),
            "Prob_Claude": _probability(claude, "finale", selection),
            "Quota_presa": (odds or {}).get(selection), "Puntata": (stakes or {}).get(selection),
            "Tipo": info.kind, "Versione_modello": info.version, "Quota_chiusura": None, "Esito": None,
            "Note": info.note,
        })
    return rows


def to_excel(rows: Sequence[Mapping[str, Any]], *, sheet: str = "Registro") -> bytes:
    """File .xlsx con le sole colonne A–S, pronte da incollare nel foglio Registro."""
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    write_registry_sheet(worksheet, rows)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def write_registry_sheet(worksheet, rows: Sequence[Mapping[str, Any]]) -> None:
    """Intestazione e righe A–S con i formati del file dell'utente (date, probabilità in percentuale)."""
    worksheet.append(list(COLUMNS))
    for row in rows:
        values = []
        for column in COLUMNS:
            value = row.get(column)
            if column == "Data" and isinstance(value, str) and value:
                value = date.fromisoformat(value[:10])
            values.append(value)
        worksheet.append(values)
    for index, column in enumerate(COLUMNS, start=1):
        letter = worksheet.cell(row=1, column=index).column_letter
        worksheet.column_dimensions[letter].width = max(10, len(column) + 2)
        for cell in worksheet[letter][1:]:
            if column == "Data":
                cell.number_format = "DD/MM/YYYY"
            elif column in PROBABILITY_COLUMNS:
                cell.number_format = "0.0%"
    worksheet.freeze_panes = "A2"


class PredictionLog:
    """Righe del registro salvate dall'app, per sessione, con ``ID`` come chiave primaria."""

    TABLE = "registro"

    def __init__(self, cache: SourceCache) -> None:
        self.path = cache.path
        columns = ", ".join(f'"{column}"' + (" PRIMARY KEY" if column == "ID" else "") for column in COLUMNS)
        with sqlite3.connect(self.path) as connection:
            connection.execute(f"CREATE TABLE IF NOT EXISTS {self.TABLE} ({columns}, sessione TEXT)")
            self._migrate(connection)

    def _migrate(self, connection: sqlite3.Connection) -> None:
        """Converte il registro minimo della fase G nel formato A–S e lo elimina."""
        if not connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='registro_previsioni'").fetchone():
            return
        connection.row_factory = sqlite3.Row
        for old in connection.execute("SELECT * FROM registro_previsioni ORDER BY id").fetchall():
            market = market_of(old["Mercato"] or "")
            if market is None:
                continue
            created = datetime.fromisoformat(old["Data"])
            model = None if old["Prob_modello"] is None else round(old["Prob_modello"] / 100.0, 4)
            claude = None if old["Prob_Claude"] is None else round(old["Prob_Claude"] / 100.0, 4)
            note = "; ".join(part for part in ("migrata dal registro della fase G", old["Note"],
                                               f"confidenza Claude {old['Confidenza_Claude']}" if old["Confidenza_Claude"] else "") if part)
            self._upsert(connection, {
                "ID": selection_id(created, old["Partita"], market, old["Mercato"]), "Data": created.date().isoformat(),
                "Ora": created.strftime("%H:%M"), "Competizione": "", "Partita": old["Partita"], "Mercato": market,
                "Selezione": old["Mercato"], "Prob_finale": claude if claude is not None else model,
                "Prob_modello": model, "Prob_Claude": claude, "Quota_presa": old["Quota"], "Tipo": "A carta",
                "Versione_modello": "fase G", "Note": note,
            }, old["sessione"])
        connection.row_factory = None
        connection.execute("DROP TABLE registro_previsioni")

    def _upsert(self, connection: sqlite3.Connection, row: Mapping[str, Any], session: str) -> bool:
        exists = connection.execute(f'SELECT 1 FROM {self.TABLE} WHERE "ID" = ?', (row["ID"],)).fetchone() is not None
        values = [_day(row.get(column)) if column == "Data" else row.get(column) for column in COLUMNS]
        names = ", ".join(f'"{column}"' for column in COLUMNS)
        connection.execute(
            f"INSERT OR REPLACE INTO {self.TABLE} ({names}, sessione) VALUES ({', '.join('?' * (len(COLUMNS) + 1))})",
            (*values, session))
        return exists

    def save(self, rows: Sequence[Mapping[str, Any]], session: str) -> tuple[int, int]:
        """Salva le righe; restituisce (nuove, aggiornate perché l'ID esisteva già)."""
        with sqlite3.connect(self.path) as connection:
            updated = sum(self._upsert(connection, row, session) for row in rows)
        return len(rows) - updated, updated

    def delete(self, ids: Sequence[str], session: str) -> int:
        """Elimina le righe con questi ``ID`` della sessione; restituisce quante."""
        with sqlite3.connect(self.path) as connection:
            return sum(connection.execute(f'DELETE FROM {self.TABLE} WHERE "ID" = ? AND sessione = ?',
                                          (row_id, session)).rowcount for row_id in ids)

    def rows(self, session: str | None = None) -> list[dict]:
        query = f"SELECT * FROM {self.TABLE}" + (" WHERE sessione = ?" if session else "") + " ORDER BY rowid"
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            return [{column: row[column] for column in COLUMNS}
                    for row in connection.execute(query, (session,) if session else ())]
