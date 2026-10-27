"""Fase P, punto 2: assenze pesate con i dati giocatore di Understat.

Produzione offensiva di un giocatore = npxG + xA (xG senza rigori più xG dei passaggi chiave). Quota persa con
un'assenza = (produzione del giocatore per partita della squadra − produzione del sostituto tipico negli stessi
minuti) / produzione della squadra per partita. Sostituto tipico = media per 90 minuti, nello stesso ruolo, dei
giocatori della rosa con pochi minuti (meno di ``BENCH_SHARE`` dei minuti del più utilizzato); se non ce ne sono,
la media di ruolo del campionato. Fattore sui gol attesi della squadra = 1 − somma delle quote, nei limiti
``LIMITS`` (0.85-1.05). Stessa formula nell'app (totali di stagione) e nella verifica storica
(``tools/player_check.py``, totali fino alla partita).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

LIMITS = (0.85, 1.05)
BENCH_SHARE = 0.4
ROLES = ("difensore", "centrocampista", "attaccante")
# Riferimenti di ruolo (npxG + xA per 90) quando la rosa non ha riserve dello stesso ruolo: medie dei 5 campionati
# Understat 2025/26 (ricalcolate da ``tools/player_check.py``).
LEAGUE_ROLE_RATE = {"difensore": 0.107, "centrocampista": 0.239, "attaccante": 0.456}


def role_of(position: str) -> str | None:
    """Ruolo da posizione Understat: di stagione («F S», «D M S», «GK») o di partita («DC», «AMR», «FW»)."""
    text = (position or "").upper().split()
    first = text[0] if text else ""
    if first in ("GK", "") or first == "SUB":
        return None
    if first in ("FW", "FWR", "FWL", "AMR", "AML") or first == "F":
        return "attaccante"
    if first in ("DC", "DR", "DL") or first == "D":
        return "difensore"
    return "centrocampista"


@dataclass(frozen=True)
class SquadPlayer:
    name: str
    role: str | None
    minutes: float
    npxg: float
    xa: float

    @property
    def production(self) -> float:
        return self.npxg + self.xa


def squad_from_understat(rows: Iterable[Mapping]) -> list[SquadPlayer]:
    """Giocatori dalla pagina campionato Understat (totali di stagione)."""
    squad = []
    for row in rows:
        try:
            squad.append(SquadPlayer(str(row["player_name"]), role_of(str(row.get("position", ""))), float(row["time"]),
                                     float(row["npxG"]), float(row["xA"])))
        except (KeyError, TypeError, ValueError):
            continue
    return squad


def substitute_rate(squad: Sequence[SquadPlayer], role: str | None) -> float:
    if role is None:
        return 0.0
    top = max((player.minutes for player in squad), default=0.0)
    bench = [player for player in squad if player.role == role and 0 < player.minutes < BENCH_SHARE * top]
    minutes = sum(player.minutes for player in bench)
    if minutes >= 270:  # almeno tre partite intere di riserve dello stesso ruolo
        return 90.0 * sum(player.production for player in bench) / minutes
    return LEAGUE_ROLE_RATE.get(role, 0.0)


def absence_factor(squad: Sequence[SquadPlayer], absent: Iterable[str], team_games: int,
                   limits: tuple[float, float] = LIMITS) -> tuple[float, list[dict]]:
    """(fattore sui gol attesi della squadra, dettaglio per assente)."""
    from datasources.names import match_team

    names = [player.name for player in squad]
    by_name = {player.name: player for player in squad}
    team_production = sum(player.production for player in squad) / team_games if team_games else 0.0
    details, lost = [], 0.0
    for name in absent:
        found = match_team(name, names) if names else None
        if found is None or team_production <= 0:
            details.append({"Giocatore": name, "Quota persa": None, "Nota": "non trovato nella rosa Understat"})
            continue
        player = by_name[found]
        minutes_per_game = player.minutes / team_games
        replacement = substitute_rate(squad, player.role) * minutes_per_game / 90.0
        share = (player.production / team_games - replacement) / team_production
        lost += share
        details.append({"Giocatore": found, "Ruolo": player.role, "Minuti per partita": round(minutes_per_game),
                        "npxG+xA per partita": round(player.production / team_games, 3),
                        "Sostituto": round(replacement, 3), "Quota persa": round(share, 3)})
    factor = min(max(1.0 - lost, limits[0]), limits[1])
    return factor, details


def is_active() -> bool:
    """Sezione ``assenze`` di ``config/goal_model.json`` (``tools/player_check.py --salva``): il fattore cambia i
    gol attesi solo se la verifica fuori campione l'ha acceso; altrimenti resta un'informazione."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent / "config" / "goal_model.json"
    if not path.exists():
        return False
    return bool(json.loads(path.read_text(encoding="utf-8")).get("assenze", {}).get("attiva", False))
