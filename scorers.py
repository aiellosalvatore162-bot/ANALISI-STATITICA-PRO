"""Marcatori (fase X): probabilità «segna in qualsiasi momento» dai dati giocatore di Understat.

Per ogni giocatore della squadra (stagione Understat: xG, minuti, presenze):
- quota dei gol della squadra mentre è in campo = xG del giocatore / xG della squadra nei suoi minuti,
  ridotta verso una quota a priori (``PRIOR_SHARE``) con un peso di ``PRIOR_XG`` xG fittizi
  (shrinkage: pochi minuti = stima vicina alla media);
- minuti attesi = minuti medi per presenza (titolare non confermato: è una media, non la formazione);
- P(segna) = 1 − Σ_g P(gol squadra = g) · (1 − quota · minuti/90)^g, con la distribuzione dei gol della
  squadra delle simulazioni (``result["dashboard"]["goals_distribution"]``; «8+» conta come 8).

Fase P (7b), versione «v2» usata quando ``config/goal_model.json`` ha la sezione ``marcatori``: xG senza rigori
(npxG) con riavvicinamento a un riferimento per ruolo (difensore/centrocampista/attaccante) con un peso in xG
fittizi (più forte con pochi minuti), più la quota dei gol su rigore solo per il rigorista della squadra (chi ha
segnato più rigori in stagione). Verifica fuori campione con ``python -m tools.player_check`` sullo storico
partita per partita di Understat; il risultato (``verificato``) decide se i marcatori possono uscire dal solo uso
informativo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from absences import role_of


PRIOR_SHARE = 0.08     # quota media di un giocatore di movimento sui gol della squadra mentre è in campo
PRIOR_XG = 1.0         # peso del valore a priori, in xG
MIN_MINUTES = 90
CALIBRATION_NOTE = ("Non verificato fuori campione: le probabilità sono una stima indicativa e i marcatori restano "
                    "fuori da multiple e lista delle giocate.")


def calibration_note() -> str:
    """Nota accanto alla tabella: esito della verifica di ``tools/player_check.py`` (se fatta)."""
    params = load_params()
    if params is None:
        return CALIBRATION_NOTE
    return params.note or (CALIBRATION_NOTE if not params.verified else "Calibrazione verificata fuori campione.")


CONFIG_PATH = Path(__file__).resolve().parent / "config" / "goal_model.json"


@dataclass(frozen=True)
class ScorerParams:
    """Parametri della versione v2 (``tools/player_check.py --salva``)."""

    role_share: Mapping[str, float] = field(default_factory=lambda: {"difensore": 0.03, "centrocampista": 0.08,
                                                                      "attaccante": 0.2})
    prior_xg: float = 2.0
    penalty_share: float = 0.1     # quota dei gol della squadra che arrivano su rigore
    verified: bool = False
    note: str = ""


def load_params(path: Path = CONFIG_PATH) -> ScorerParams | None:
    if not path.exists():
        return None
    section = json.loads(path.read_text(encoding="utf-8")).get("marcatori")
    if not section:
        return None
    return ScorerParams(role_share=dict(section["quota_ruolo"]), prior_xg=float(section["xg_fittizi"]),
                        penalty_share=float(section["quota_rigori"]), verified=bool(section.get("verificato")),
                        note=str(section.get("nota", "")))


@dataclass(frozen=True)
class Player:
    name: str
    minutes: float
    games: int
    xg: float
    goals: int
    position: str
    npxg: float | None = None          # v2: xG senza rigori
    penalty_goals: int = 0             # v2: gol su rigore in stagione (per trovare il rigorista)

    @property
    def minutes_per_game(self) -> float:
        return self.minutes / self.games if self.games else 0.0


def players_from_understat(rows: Iterable[Mapping[str, Any]]) -> list[Player]:
    players = []
    for row in rows:
        try:
            goals = int(row["goals"])
            players.append(Player(str(row["player_name"]), float(row["time"]), int(row["games"]), float(row["xG"]),
                                  goals, str(row.get("position", "")), float(row.get("npxG", row["xG"])),
                                  max(0, goals - int(row.get("npg", goals)))))
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


def penalty_taker(players: Sequence[Player]) -> str | None:
    """Rigorista: chi ha segnato più rigori in stagione (nessuno se nessun rigore)."""
    best = max(players, key=lambda player: player.penalty_goals, default=None)
    return best.name if best is not None and best.penalty_goals > 0 else None


def share_v2(player: Player, team_npxg90: float, params: ScorerParams, taker: str | None) -> float:
    """Quota dei gol della squadra (con il giocatore in campo): parte senza rigori riavvicinata al riferimento del
    ruolo con ``prior_xg`` xG fittizi, più i rigori solo per il rigorista."""
    role = role_of(player.position) or "centrocampista"
    prior = params.role_share.get(role, 0.08)
    on_pitch = team_npxg90 * player.minutes / 90.0
    npxg = player.npxg if player.npxg is not None else player.xg
    open_play = (npxg + params.prior_xg * prior) / (on_pitch + params.prior_xg)
    return (1.0 - params.penalty_share) * open_play + params.penalty_share * (1.0 if player.name == taker else 0.0)


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
    params = load_params()
    team_xg90 = team_xg_per_90(players)
    games = max((player.games for player in players), default=0)
    team_npxg90 = sum(player.npxg if player.npxg is not None else player.xg for player in players) / games if games else 0.0
    taker = penalty_taker(players) if params is not None else None
    rows = []
    for player in players:
        if player.minutes < MIN_MINUTES or "GK" in player.position.upper():
            continue
        player_share = share_v2(player, team_npxg90, params, taker) if params is not None else share(player, team_xg90)
        minutes = 90.0 if player.name in confirmed else min(90.0, player.minutes_per_game)
        probability = anytime_probability(player_share * minutes / 90.0, distribution)
        rows.append({"Giocatore": player.name, "Ruolo": player.position, "Minuti attesi": round(minutes),
                     "xG/90": round(player.xg / player.minutes * 90.0, 2) if player.minutes else None,
                     "Quota gol squadra": round(player_share, 3), "Segna %": round(probability * 100.0, 1),
                     "Quota equa": round(1.0 / probability, 2) if probability > 0 else None,
                     "Titolare": "confermato" if player.name in confirmed else "non confermato",
                     "Rigorista": "sì" if player.name == taker else ""})
    return sorted(rows, key=lambda row: -row["Segna %"])[:limit]


def market_margin(rows: Sequence[Mapping[str, Any]], odds: Mapping[str, float]) -> float | None:
    """Margine implicito delle quote marcatore inserite: somma delle implicite / somma delle probabilità del modello − 1."""
    pairs = [(1.0 / float(odds[row["Giocatore"]]), row["Segna %"] / 100.0) for row in rows
             if odds.get(row["Giocatore"]) and float(odds[row["Giocatore"]]) > 1.0]
    if not pairs:
        return None
    implied, model = sum(pair[0] for pair in pairs), sum(pair[1] for pair in pairs)
    return implied / model - 1.0 if model > 0 else None
