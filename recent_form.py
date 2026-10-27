"""Frequenza storica recente (fase X): quante volte l'evento è uscito nelle ultime partite delle due squadre.

È un conteggio sui risultati reali di football-data.co.uk, separato dalla probabilità del modello: si
calcola solo per i mercati che non dipendono da quale squadra gioca in casa (totali di gol, corner e
cartellini, Goal/No Goal, multigol totale, totali del primo tempo). Con poche partite l'avviso
«campione piccolo».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

import pandas as pd


SMALL_SAMPLE = 8
_SYMMETRIC = re.compile(r"^(?:(?:Over|Under) \d+\.5 (?:gol|corner|cartellini)(?: 1T)?|Goal|No Goal|Goal 1T|No Goal 1T|"
                        r"Multigol \d+-\d+)$")


@dataclass(frozen=True)
class Frequency:
    selection: str
    hits: int
    total: int
    per_team: int

    @property
    def small(self) -> bool:
        return self.total < SMALL_SAMPLE

    def sentence(self) -> str:
        if self.total == 0:
            return "Storico recente non disponibile."
        text = (f"Nelle ultime {self.total} partite delle due squadre «{self.selection}» è uscito {self.hits} "
                f"{'volta' if self.hits == 1 else 'volte'} su {self.total}")
        return text + (" (campione piccolo: poco indicativo)." if self.small else ".")


def symmetric(selection: str) -> bool:
    return bool(_SYMMETRIC.match(selection))


def recent_frequency(selection: str, home: str, away: str, matches: pd.DataFrame, as_of: date,
                     per_team: int = 5) -> Frequency | None:
    """Conteggio nelle ultime ``per_team`` partite di ciascuna squadra prima di ``as_of``; ``None`` se il mercato
    dipende dal lato (casa/ospite) o non è valutabile."""
    from datasources.names import match_team
    from performance import settle

    if not symmetric(selection) or matches.empty:
        return None if not symmetric(selection) else Frequency(selection, 0, 0, per_team)
    before = matches[matches["date"] < pd.Timestamp(as_of)]
    names = pd.concat([before["home_team"], before["away_team"]]).unique()
    rows = []
    for team in (home, away):
        name = match_team(team, names)
        if name is None:
            continue
        played = before[(before["home_team"] == name) | (before["away_team"] == name)].sort_values("date").tail(per_team)
        rows.append(played)
    if not rows:
        return Frequency(selection, 0, 0, per_team)
    sample = pd.concat(rows).drop_duplicates(subset=["date", "home_team", "away_team"])
    outcomes = [settle(selection, row) for _, row in sample.iterrows()]
    outcomes = [outcome for outcome in outcomes if outcome is not None]
    return Frequency(selection, int(sum(outcomes)), len(outcomes), per_team)
