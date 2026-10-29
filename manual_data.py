"""Dati inseriti a mano per le partite di Oggi (fase R): «Modifica o completa i dati».

Per ogni partita (chiave data|Casa - Ospite) si conservano solo i campi inseriti a mano: valore, origine
(«manuale»), fonte («inserito a mano») e momento. La scheda finale si compone con la precedenza fissa
**manuale > automatico > proxy/stima**: ``apply_manual`` mette i manuali sopra la scheda automatica, quindi un nuovo
«Prepara» o «Analizza» non li tocca; l'etichetta resta finché non si usa «Ripristina dati automatici».

Il blocco incollato si legge con il parser esistente in modalità parziale (``parser.parse_partial_input``): niente
secondo parser. Le squadre dell'intestazione si confrontano con ``datasources.names.match_team``; se non
corrispondono alla partita non si applica nulla.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import re
from typing import Any, Mapping, Sequence

from datasources.builder import MatchSheet, TEAM_FIELDS, _format
from datasources.names import match_team
from datasources.stats import MANUAL_SOURCE, FieldValue
from parser import PartialBlock, parse_partial_input

SIDES = ("home", "away", "referee")
REFEREE_FIELDS = (("yellow", "Gialli medi"), ("fouls", "Falli medi"))
LABELS = {**dict(TEAM_FIELDS), "cards_provoked": "Cartellini provocati", **dict(REFEREE_FIELDS)}
SIDE_LABEL = {"home": "Casa", "away": "Ospite", "referee": "Arbitro"}

REPLACES, COMPLETES, SAME = "sostituisce", "completa MANCANTE", "uguale"
UNRECOGNIZED, INVALID = "riga non riconosciuta", "valore non valido: non applicato"


def empty_entry(label: str = "") -> dict:
    return {"partita": label, "home": {}, "away": {}, "referee": {}}


def has_manual(entry: Mapping | None) -> bool:
    return bool(entry) and any(entry.get(side) for side in SIDES)


def entry_values(entry: Mapping | None) -> dict[str, dict[str, Any]]:
    """Solo i valori: lato -> chiave -> valore."""
    return {side: {key: item["value"] for key, item in (entry or {}).get(side, {}).items()} for side in SIDES}


# --- Controllo delle squadre ------------------------------------------------------------------------------

def check_teams(block: PartialBlock, home: str, away: str) -> str | None:
    """Messaggio d'errore se il blocco non corrisponde alla partita (casa/ospite), altrimenti ``None``."""
    for side, name, expected, other in (("CASA", block.home_name, home, away), ("OSPITE", block.away_name, away, home)):
        section = block.home if side == "CASA" else block.away
        if name is None:
            if section:
                return f"Il blocco {side}: non indica la squadra: scrivi «{side}: <squadra>» prima dei campi."
            continue
        if match_team(name, [expected]):
            continue
        if match_team(name, [other]):
            return f"«{side}: {name}» è la squadra {'ospite' if side == 'CASA' else 'di casa'} di questa partita: nulla applicato."
        return f"«{side}: {name}» non corrisponde alla partita {home} - {away}: nulla applicato."
    return None


# --- Anteprima --------------------------------------------------------------------------------------------

def _shown(key: str, value: Any) -> str:
    if value is None:
        return "MANCANTE"
    if key in ("yellow", "fouls"):
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    return _format(key, value)


def _fields_for(sheet: MatchSheet, side: str) -> dict[str, FieldValue]:
    return {"home": sheet.home_fields, "away": sheet.away_fields, "referee": sheet.referee_fields}[side]


def _classify(block: PartialBlock, auto_sheet: MatchSheet, entry: Mapping | None):
    """(lato, chiave, valore, riga di anteprima, cosa succede) per ogni campo valido del blocco."""
    entry = entry or empty_entry()
    for side in SIDES:
        values = {"home": block.home, "away": block.away, "referee": block.referee}[side]
        fields = _fields_for(auto_sheet, side)
        for key, value in values.items():
            auto = fields.get(key)
            auto_text = "MANCANTE" if auto is None or auto.missing else f"{_shown(key, auto.value)} ({auto.source})"
            previous = (entry.get(side) or {}).get(key)
            current = previous["value"] if previous else (None if auto is None or auto.missing else auto.value)
            if current is not None and _shown(key, current) == _shown(key, value):
                action = SAME
            elif previous:
                action = f"{REPLACES} (manuale precedente: {_shown(key, previous['value'])})"
            elif auto is None or auto.missing:
                action = COMPLETES
            else:
                action = REPLACES
            yield side, key, value, {"Campo": f"{SIDE_LABEL[side]} · {LABELS.get(key, key)}", "Automatico": auto_text,
                                     "Blocco": _shown(key, value), "Cosa succede": action}, action


def preview(block: PartialBlock, auto_sheet: MatchSheet, entry: Mapping | None = None) -> list[dict]:
    """Righe «campo | automatico (con fonte) | blocco | cosa succede» per il blocco incollato."""
    rows = [row for *_, row, _ in _classify(block, auto_sheet, entry)]
    rows += [{"Campo": line, "Automatico": "", "Blocco": "", "Cosa succede": UNRECOGNIZED} for line in block.unrecognized]
    rows += [{"Campo": message, "Automatico": "", "Blocco": "", "Cosa succede": INVALID} for message in block.errors]
    return rows


def changes(block: PartialBlock, auto_sheet: MatchSheet, entry: Mapping | None) -> dict[str, dict[str, Any]]:
    """Campi da memorizzare come manuali: quelli che sostituiscono o completano (gli «uguale» no)."""
    result: dict[str, dict[str, Any]] = {side: {} for side in SIDES}
    for side, key, value, _, action in _classify(block, auto_sheet, entry):
        if action != SAME:
            result[side][key] = value
    return result


def merge(entry: Mapping | None, new_values: Mapping[str, Mapping[str, Any]], label: str = "",
          when: datetime | None = None) -> dict:
    """Voce aggiornata: i nuovi manuali si sommano a quelli già presenti (stesso campo = ultimo valore)."""
    updated = {side: dict((entry or {}).get(side, {})) for side in SIDES}
    stamp = (when or datetime.now().astimezone()).isoformat(timespec="seconds")
    for side in SIDES:
        for key, value in new_values.get(side, {}).items():
            updated[side][key] = {"value": value, "origin": "manuale", "source": MANUAL_SOURCE, "when": stamp}
    return {"partita": label or (entry or {}).get("partita", ""), **updated}


# --- Composizione della scheda ----------------------------------------------------------------------------

def apply_manual(sheet: MatchSheet, entry: Mapping | None) -> MatchSheet:
    """Scheda con i manuali sopra l'automatico (precedenza fissa); senza manuali la scheda resta la stessa."""
    if not has_manual(entry):
        return sheet
    sides = {}
    for side in SIDES:
        fields = dict(_fields_for(sheet, side))
        for key, item in entry.get(side, {}).items():
            when = datetime.fromisoformat(item["when"])
            fields[key] = FieldValue(item["value"], item.get("source", MANUAL_SOURCE), when, None,
                                     f"inserito a mano il {when:%d/%m/%Y %H:%M}", "ok")
        sides[side] = fields
    return replace(sheet, home_fields=sides["home"], away_fields=sides["away"], referee_fields=sides["referee"])


def field_table(sheet: MatchSheet) -> list[dict]:
    """Per ogni campo: valore, origine (manuale / automatico / proxy-stima / mancante) e fonte."""
    rows = []
    for side, subject in (("home", sheet.home), ("away", sheet.away), ("referee", "Arbitro")):
        labels = REFEREE_FIELDS if side == "referee" else TEAM_FIELDS
        fields = _fields_for(sheet, side)
        for key, label in labels:
            if key in fields:
                value = fields[key]
                rows.append({"Soggetto": subject, "Campo": label, "Valore": "" if value.missing else _shown(key, value.value),
                             "Origine": value.origin, "Fonte": value.source})
    return rows


def parse_block(text: str) -> PartialBlock:
    return parse_partial_input(text)


# --- Excel della giornata ---------------------------------------------------------------------------------

MANUAL_COLUMNS = ("Partita", "Soggetto", "Campo", "Valore", "Origine", "Fonte", "Quando")


def sheet_rows(entries: Sequence[Mapping]) -> list[dict]:
    """Righe leggibili del foglio «Manuali» (i dati veri tornano dal foglio tecnico)."""
    rows = []
    for entry in entries:
        for side in SIDES:
            for key, item in entry.get(side, {}).items():
                rows.append({"Partita": entry.get("partita", ""), "Soggetto": SIDE_LABEL[side], "Campo": LABELS.get(key, key),
                             "Valore": _shown(key, item["value"]), "Origine": item.get("origin", "manuale"),
                             "Fonte": item.get("source", MANUAL_SOURCE), "Quando": item.get("when", "")})
    return rows


# --- Pagina Partita (fase Z): i dati a mano della giornata nel blocco di testo ------------------------------

_HEADER = re.compile(r"^\s*(CASA|OSPITE|ARBITRO)\s*:", re.IGNORECASE)


def _field_text(side: str, key: str, value: Any) -> tuple[str, str]:
    label = LABELS[key]
    if side == "referee":
        return label, f"{label} {_shown(key, value)}"
    return label, f"{label}: {_shown(key, value)}"


def block_differences(block_text: str, entry: Mapping | None) -> list[dict]:
    """Campi a mano della giornata diversi dal blocco (o assenti): campo | blocco | a mano. Righe # ignorate."""
    if not has_manual(entry):
        return []
    parsed = parse_partial_input(block_text)
    current = {"home": parsed.home, "away": parsed.away, "referee": parsed.referee}
    rows = []
    for side in SIDES:
        for key, item in entry.get(side, {}).items():
            value = current[side].get(key)
            if value is None or _shown(key, value) != _shown(key, item["value"]):
                rows.append({"Campo": f"{SIDE_LABEL[side]} · {LABELS.get(key, key)}",
                             "Blocco": "assente" if value is None else _shown(key, value), "A mano": _shown(key, item["value"])})
    return rows


def overlay_block(block_text: str, entry: Mapping | None) -> str:
    """Il blocco con i valori a mano al posto di quelli scritti (o aggiunti alla riga d'intestazione della sezione)."""
    if not has_manual(entry):
        return block_text
    lines = block_text.splitlines()
    sections: dict[str, list[int]] = {"home": [], "away": [], "referee": []}
    current = None
    for index, line in enumerate(lines):
        header = _HEADER.match(line)
        if header:
            current = {"casa": "home", "ospite": "away", "arbitro": "referee"}[header[1].lower()]
        if current and not line.lstrip().startswith("#"):
            sections[current].append(index)
    for side in SIDES:
        for key, item in entry.get(side, {}).items():
            label, replacement = _field_text(side, key, item["value"])
            pattern = (re.compile(rf"{re.escape(label)}\s+[-+]?\d+(?:[.,]\d+)?", re.IGNORECASE) if side == "referee"
                       else re.compile(rf"{re.escape(label)}\s*:\s*[^|]+?(?=\s*(?:\||$))", re.IGNORECASE))
            done = False
            for index in sections[side]:
                if pattern.search(lines[index]):
                    lines[index] = pattern.sub(replacement, lines[index], count=1)
                    done = True
                    break
            if not done and sections[side]:
                first = sections[side][0]
                lines[first] = f"{lines[first].rstrip()} | {replacement}"
    return "\n".join(lines)
