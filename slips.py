"""Schedine salvate (fase X): nome, gambe e stato gamba per gamba (in attesa / vinta / persa).

Gli esiti si aggiornano con i punteggi gratuiti di football-data.co.uk (``update_from_results``, stesse
definizioni degli eventi del motore) oppure a mano; si salvano nell'Excel della giornata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
from typing import Iterable, Mapping, Sequence

import pandas as pd


PENDING, WON, LOST = "in attesa", "vinta", "persa"
STATUSES = (PENDING, WON, LOST)


@dataclass
class Slip:
    name: str
    created: str
    legs: list[dict] = field(default_factory=list)   # match, date (ISO), selection, odds, probability, status, note

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.name}|{self.created}".encode()).hexdigest()[:12]

    def counts(self) -> tuple[int, int]:
        return sum(leg["status"] == WON for leg in self.legs), len(self.legs)

    def score(self) -> str:
        won, total = self.counts()
        return f"{won}/{total}"

    @property
    def state(self) -> str:
        if any(leg["status"] == LOST for leg in self.legs):
            return LOST
        if self.legs and all(leg["status"] == WON for leg in self.legs):
            return WON
        return PENDING

    @property
    def odds(self) -> float | None:
        prices = [leg.get("odds") for leg in self.legs]
        return round(float(pd.Series(prices).prod()), 2) if prices and all(prices) else None

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "created": self.created, "legs": [dict(leg) for leg in self.legs]}

    @classmethod
    def from_dict(cls, data: Mapping) -> "Slip":
        return cls(str(data["name"]), str(data["created"]), [dict(leg) for leg in data.get("legs", [])])


def make_slip(name: str, legs: Iterable, dates: Mapping[str, date], *, created: datetime | None = None) -> Slip:
    """Schedina dalle gambe proposte (``multiples.Leg``); ``dates``: data della partita per ``Leg.match_id``."""
    rows = []
    for leg in legs:
        day = dates.get(leg.match_id)
        for selection in leg.selections:
            rows.append({"match": leg.match, "date": day.isoformat() if day else "", "selection": selection,
                         "odds": leg.odds if len(leg.selections) == 1 else None,
                         "probability": round(leg.probability, 4) if len(leg.selections) == 1 else None,
                         "status": PENDING, "note": ""})
    return Slip(name.strip() or "Schedina", (created or datetime.now()).isoformat(timespec="seconds"), rows)


def update_from_results(slip: Slip, results: pd.DataFrame, source: str = "football-data.co.uk") -> int:
    """Esiti delle gambe ancora in attesa dai risultati reali; restituisce quante gambe sono cambiate."""
    from performance import find_result, settle

    changed = 0
    for leg in slip.legs:
        if leg["status"] != PENDING or not leg.get("date"):
            continue
        match = find_result(results, leg["match"], date.fromisoformat(leg["date"][:10]), before=1, after=3)
        if match is None:
            continue
        outcome = settle(leg["selection"], match)
        if outcome is None:
            continue
        leg["status"] = WON if outcome else LOST
        leg["note"] = f"esito da {source} ({int(match['home_goals'])}-{int(match['away_goals'])})"
        changed += 1
    return changed


def registry_like(slip: Slip) -> pd.DataFrame:
    """Forma del registro per ``performance.collect_results`` (date e competizioni da scaricare)."""
    return pd.DataFrame([{"Data": date.fromisoformat(leg["date"][:10]) if leg.get("date") else None, "Partita": leg["match"],
                          "Competizione": "", "Esito": None if leg["status"] == PENDING else 1.0, "Quota_chiusura": 1.0}
                         for leg in slip.legs])


def sheet_rows(slips: Sequence[Slip]) -> list[dict]:
    """Foglio «Schedine» dell'Excel della giornata."""
    return [{"Schedina": slip.name, "Creata": slip.created, "Stato": f"{slip.state} ({slip.score()})",
             "Partita": leg["match"], "Data": leg.get("date"), "Gamba": leg["selection"], "Quota": leg.get("odds"),
             "Probabilità": leg.get("probability"), "Esito gamba": leg["status"], "Note": leg.get("note", "")}
            for slip in slips for leg in slip.legs]
