"""Esiti delle partite da tre fonti, unificati (fase AH): CSV football-data > blocco ESITO con fonte > ESITI_CLAUDE.

Una sola voce per partita: ogni campo (risultato, corner, gialli, …) viene dalla fonte con priorità più alta che lo ha;
se due fonti dicono cose diverse sullo stesso campo vince la più alta e il conflitto è SEMPRE mostrato (``Conflict``), mai
sovrascritto in silenzio. Il formato ESITI_CLAUDE (testo con ID E1…) è ancora accettato. ``lookup`` è il punto di aggancio
per la verifica delle gambe (settle_leg, Fase AA) e ``result_rows`` alimenta ``performance.fill_from_results``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from claude_bridge import ResponseError
from datasources.names import canonical_key

PRIORITY = {"CSV": 3, "ESITO": 2, "ESITI_CLAUDE": 1}
VALUE_COLUMNS = ("home_goals", "away_goals", "home_ht_goals", "away_ht_goals", "home_corners", "away_corners",
                 "home_yellows", "away_yellows", "home_reds", "away_reds")
OUTCOME_HEADER = "ESITI_CLAUDE:"
OUTCOME_MARKETS = ("Corner", "Cartellini")
_OUTCOME_BLOCK = re.compile(rf"{re.escape(OUTCOME_HEADER)}\s*(E\d+)", re.IGNORECASE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_PAIR = re.compile(r"\s*(\d+)\s*[-–:]\s*(\d+)\s*")
CLAUDE_FIELDS = {"risultato": ("home_goals", "away_goals"), "primo_tempo": ("home_ht_goals", "away_ht_goals"),
                 "corner": ("home_corners", "away_corners"), "gialli": ("home_yellows", "away_yellows"),
                 "rossi": ("home_reds", "away_reds")}


@dataclass
class Outcome:
    home: str
    away: str
    date: pd.Timestamp
    values: dict[str, int]
    source: str
    origin: str                       # «CSV», «ESITO», «ESITI_CLAUDE»
    sources: dict[str, str] = field(default_factory=dict)   # origine -> fonte, per tutte le fonti che hanno contribuito

    def as_row(self) -> dict[str, Any]:
        """Riga per ``performance.fill_from_results`` (stesso formato dei vecchi risultati ESITI_CLAUDE)."""
        return {"date": self.date, "home_team": self.home, "away_team": self.away, "source": self.source, **self.values}


@dataclass(frozen=True)
class Conflict:
    match: str
    field: str
    kept: int
    kept_origin: str
    discarded: int
    discarded_origin: str

    def text(self) -> str:
        return (f"{self.match}: {self.field} {self.kept} ({self.kept_origin}) contro {self.discarded} "
                f"({self.discarded_origin}): vale {self.kept_origin}.")


@dataclass
class Unified:
    records: list[Outcome] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --- Lettura delle tre fonti ----------------------------------------------------------------------------------------

def from_csv(frame: pd.DataFrame, source: str = "football-data.co.uk") -> list[Outcome]:
    """Risultati dal CSV (colonne ``date``, ``home_team``, ``away_team`` e le colonne di ``VALUE_COLUMNS`` presenti)."""
    outcomes = []
    for row in frame.to_dict("records"):
        values = {column: int(row[column]) for column in VALUE_COLUMNS if column in row and pd.notna(row[column])}
        if "home_goals" in values:
            outcomes.append(Outcome(row["home_team"], row["away_team"], pd.Timestamp(row["date"]).normalize(), values, source,
                                    "CSV", {"CSV": source}))
    return outcomes


def from_esito(blocks: Iterable[Any]) -> tuple[list[Outcome], list[str]]:
    """Blocchi ESITO validi (``analyst.OutcomeBlock``); quelli con ``error`` danno un avviso e non entrano."""
    outcomes, warnings = [], []
    for block in blocks:
        if block.error:
            warnings.append(f"ESITO {block.label}: {block.error}.")
            continue
        outcomes.append(Outcome(block.home, block.away, pd.Timestamp(block.when).normalize(), dict(block.values), block.source,
                                "ESITO", {"ESITO": block.source}))
    return outcomes, warnings


def parse_esiti_claude(text: str, targets: Sequence[Mapping[str, Any]]) -> tuple[list[Outcome], list[str]]:
    """Blocchi ``ESITI_CLAUDE: E1`` → esiti; senza fonte o senza risultato il blocco è ignorato con un avviso."""
    from performance import split_match

    by_id = {target["id"]: target for target in targets}
    found = list(_OUTCOME_BLOCK.finditer(text))
    if not found:
        raise ResponseError(f"Nella risposta non ci sono blocchi «{OUTCOME_HEADER} E1».")
    results, warnings = [], []
    for position, header in enumerate(found):
        target = by_id.get(header.group(1).upper())
        end = found[position + 1].start() if position + 1 < len(found) else len(text)
        if target is None:
            warnings.append(f"Blocco {header.group(1)}: ID non presente nel testo inviato, ignorato.")
            continue
        values: dict[str, int] = {}
        source = None
        for raw in text[header.end():end].splitlines():
            key, _, value = raw.strip().strip("`*-").strip().partition(":")
            key = key.strip().lower().replace(" ", "_")
            if key == "fonte":
                url = _URL.search(value)
                source = url.group(0).rstrip(").,;") if url else None
                continue
            pair, columns = _PAIR.fullmatch(value), CLAUDE_FIELDS.get(key)
            if columns and pair:
                values[columns[0]], values[columns[1]] = int(pair[1]), int(pair[2])
        if source is None:
            warnings.append(f"{target['id']} {target['match']}: senza fonte, ignorato.")
            continue
        if "home_goals" not in values:
            warnings.append(f"{target['id']} {target['match']}: manca il risultato finale, ignorato.")
            continue
        teams = split_match(target["match"]) or (target["match"], "")
        results.append(Outcome(teams[0], teams[1], pd.Timestamp(target["date"]).normalize(), values, source, "ESITI_CLAUDE",
                               {"ESITI_CLAUDE": source}))
    return results, warnings


# --- Unificazione -------------------------------------------------------------------------------------------------------

def unify(*groups: Iterable[Outcome]) -> Unified:
    """Una voce per partita (squadre normalizzate, data ±1 giorno); campo per campo vince la fonte con priorità più alta."""
    result = Unified()
    everything = sorted((item for group in groups for item in group), key=lambda item: -PRIORITY[item.origin])
    slots: list[tuple[tuple[str, str], Outcome]] = []
    for item in everything:
        key = (canonical_key(item.home), canonical_key(item.away))
        target = next((existing for existing_key, existing in slots
                       if existing_key == key and abs((existing.date - item.date).days) <= 1), None)
        if target is None:
            record = Outcome(item.home, item.away, item.date, dict(item.values), item.source, item.origin, dict(item.sources))
            slots.append((key, record))
            continue
        target.sources.update(item.sources)
        for column, value in item.values.items():
            if column not in target.values:
                target.values[column] = value             # campo mancante nella fonte più alta: lo completa la successiva
            elif target.values[column] != value:
                conflict = Conflict(f"{target.home} - {target.away}", column, target.values[column], target.origin, value, item.origin)
                result.conflicts.append(conflict)
                result.warnings.append(conflict.text())
    result.records = [record for _, record in slots]
    return result


def result_rows(unified: Unified) -> list[dict[str, Any]]:
    return [record.as_row() for record in unified.records]


def lookup(unified: Unified, home: str, away: str, day: Any) -> Outcome | None:
    """Esito di una partita (per la verifica delle gambe), con tolleranza di un giorno sulla data."""
    key, when = (canonical_key(home), canonical_key(away)), pd.Timestamp(day).normalize()
    for record in unified.records:
        if (canonical_key(record.home), canonical_key(record.away)) == key and abs((record.date - when).days) <= 1:
            return record
    return None
