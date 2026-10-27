"""Marcatori (fase X): probabilità «segna in qualsiasi momento» dai dati giocatore di Understat.

Per ogni giocatore della squadra (stagione Understat: xG, minuti, presenze):
- quota dei gol della squadra mentre è in campo = xG del giocatore / xG della squadra nei suoi minuti,
  ridotta verso una quota a priori (``PRIOR_SHARE``) con un peso di ``PRIOR_XG`` xG fittizi
  (shrinkage: pochi minuti = stima vicina alla media);
- minuti attesi = minuti medi per presenza (titolare non confermato: è una media, non la formazione);
- P(segna) = 1 − Σ_g P(gol squadra = g) · (1 − quota · minuti/90)^g, con la distribuzione dei gol della
  squadra delle simulazioni (``result["dashboard"]["goals_distribution"]``; «8+» conta come 8).

Nuovo calcolo NON verificato fuori campione: lo storico Understat per partita e per giocatore richiede
una chiamata per giocatore e non è nella cache; l'app lo dichiara accanto alla tabella.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


PRIOR_SHARE = 0.08     # quota media di un giocatore di movimento sui gol della squadra mentre è in campo
PRIOR_XG = 1.0         # peso del valore a priori, in xG
MIN_MINUTES = 90
CALIBRATION_NOTE = ("Non verificato: la calibrazione fuori campione richiede lo storico per partita di ogni giocatore "
                    "(Understat, una chiamata per giocatore), non disponibile. Usa le probabilità come stima indicativa.")


@dataclass(frozen=True)
class Player:
    name: str
    minutes: float
    games: int
    xg: float
    goals: int
    position: str

    @property
    def minutes_per_game(self) -> float:
        return self.minutes / self.games if self.games else 0.0


def players_from_understat(rows: Iterable[Mapping[str, Any]]) -> list[Player]:
    players = []
    for row in rows:
        try:
            players.append(Player(str(row["player_name"]), float(row["time"]), int(row["games"]), float(row["xG"]),
                                  int(row["goals"]), str(row.get("position", ""))))
        except (KeyError, TypeError, ValueError):
            continue
    return players


def team_xg_per_90(players: Sequence[Player]) -> float:
    """xG della squadra per 90 minuti: somma degli xG dei giocatori / partite giocate dalla squadra."""
    games = max((player.games for player in players), default=0)
    return sum(player.xg for player in players) / games if games else 0.0


def share(player: Player, team_xg90: float, prior_share: float = PRIOR_SHARE, prior_xg: float = PRIOR_XG) -> float:
    """Quota dei gol della squadra quando il giocatore è in campo, con shrinkage verso ``prior_share``."""
    team_xg_on_pitch = team_xg90 * player.minutes / 90.0
    return (player.xg + prior_xg * prior_share) / (team_xg_on_pitch + prior_xg) if team_xg_on_pitch + prior_xg > 0 else prior_share


def goal_distribution(result: Mapping[str, Any], side: str) -> dict[int, float]:
    """Distribuzione simulata dei gol della squadra (``side``: home/away), probabilità 0-1."""
    values = result["dashboard"]["goals_distribution"][side]
    return {goals: float(value) / 100.0 for goals, value in enumerate(values)}


def anytime_probability(per_goal: float, distribution: Mapping[int, float]) -> float:
    """P(almeno un gol del giocatore) se ogni gol della squadra è suo con probabilità ``per_goal``."""
    return 1.0 - sum(probability * (1.0 - per_goal) ** goals for goals, probability in distribution.items())


def scorer_rows(players: Sequence[Player], distribution: Mapping[int, float], *, limit: int = 12,
                confirmed: Iterable[str] = ()) -> list[dict]:
    """Tabella marcatori, dal più probabile: quota sui gol, minuti attesi, P(segna), quota equa."""
    confirmed = set(confirmed)
    team_xg90 = team_xg_per_90(players)
    rows = []
    for player in players:
        if player.minutes < MIN_MINUTES or "GK" in player.position.upper():
            continue
        player_share = share(player, team_xg90)
        minutes = 90.0 if player.name in confirmed else min(90.0, player.minutes_per_game)
        probability = anytime_probability(player_share * minutes / 90.0, distribution)
        rows.append({"Giocatore": player.name, "Ruolo": player.position, "Minuti attesi": round(minutes),
                     "xG/90": round(player.xg / player.minutes * 90.0, 2) if player.minutes else None,
                     "Quota gol squadra": round(player_share, 3), "Segna %": round(probability * 100.0, 1),
                     "Quota equa": round(1.0 / probability, 2) if probability > 0 else None,
                     "Titolare": "confermato" if player.name in confirmed else "non confermato"})
    return sorted(rows, key=lambda row: -row["Segna %"])[:limit]


def market_margin(rows: Sequence[Mapping[str, Any]], odds: Mapping[str, float]) -> float | None:
    """Margine implicito delle quote marcatore inserite: somma delle implicite / somma delle probabilità del modello − 1."""
    pairs = [(1.0 / float(odds[row["Giocatore"]]), row["Segna %"] / 100.0) for row in rows
             if odds.get(row["Giocatore"]) and float(odds[row["Giocatore"]]) > 1.0]
    if not pairs:
        return None
    implied, model = sum(pair[0] for pair in pairs), sum(pair[1] for pair in pairs)
    return implied / model - 1.0 if model > 0 else None
