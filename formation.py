"""Messa in campo per zone e corsie (fase AK): modulo → ruoli per linea e corsia, accoppiamenti tra corsie.

Il gioco si descrive per corsie (sinistra, centro, destra) e linee (difesa, centrocampo, attacco), mai con coordinate continue.
La fascia destra di una squadra affronta la fascia sinistra dell'altra. ``lane_shares`` dice dove nascono le azioni d'attacco
(quota per corsia) in base a chi presidia la corsia contro chi la difende; il motore usa queste quote per cross e corner.
"""

from __future__ import annotations

import re

LANES = ("sinistra", "centro", "destra")
MIRROR = {"sinistra": "destra", "centro": "centro", "destra": "sinistra"}
# Pesi di presenza per linea (attacco e difesa di una corsia): dichiarati, uguali per tutti, solo per ripartire le azioni.
ATTACK_WEIGHT = {"difesa": 0.3, "centrocampo": 0.6, "attacco": 1.0}
DEFENSE_WEIGHT = {"difesa": 1.0, "centrocampo": 0.6, "attacco": 0.2}
DEFAULT_MODULE = "4-4-2"


def parse_module(text: str | None) -> tuple[list[int], str | None]:
    """«4-2-3-1» → [4, 2, 3, 1]; modulo non valido → modulo di base dichiarato e avviso."""
    numbers = [int(value) for value in re.findall(r"\d", text or "")]
    if len(numbers) >= 2 and sum(numbers) == 10:
        return numbers, None
    fallback = [int(value) for value in DEFAULT_MODULE.split("-")]
    warning = None if not text else f"modulo «{text}» non valido (servono 10 giocatori di movimento): uso {DEFAULT_MODULE}, segnalato."
    return fallback, warning


def _lanes(count: int, wide: bool) -> list[str]:
    if count == 1:
        return ["centro"]
    if count == 2:
        return ["centro", "centro"]
    if count == 3:
        return ["sinistra", "centro", "destra"] if wide else ["centro"] * 3
    return ["sinistra", *["centro"] * (count - 2), "destra"]


def roles(module: str | None) -> tuple[list[dict], list[str]]:
    """Ruoli per linea e corsia: terzino/centrale, esterno/mediano/trequartista, ala/punta."""
    lines, warning = parse_module(module)
    names = ["difesa"] + ["centrocampo"] * (len(lines) - 2) + ["attacco"]
    out = []
    for position, (count, line) in enumerate(zip(lines, names)):
        last = position == len(lines) - 1
        behind_single = position == len(lines) - 2 and lines[-1] == 1
        for lane in _lanes(count, wide=last or behind_single):
            if line == "difesa":
                role = "terzino" if lane != "centro" else "centrale"
            elif line == "attacco":
                role = "ala" if lane != "centro" else "punta"
            else:
                role = "esterno" if lane != "centro" else ("trequartista" if behind_single else "mediano")
            out.append({"linea": line, "corsia": lane, "ruolo": role})
    return out, [warning] if warning else []


def presence(module: str | None) -> dict[str, dict[str, float]]:
    players, _ = roles(module)
    out = {lane: {"attacco": 0.0, "difesa": 0.0} for lane in LANES}
    for player in players:
        out[player["corsia"]]["attacco"] += ATTACK_WEIGHT[player["linea"]]
        out[player["corsia"]]["difesa"] += DEFENSE_WEIGHT[player["linea"]]
    return out


def lane_shares(attack_module: str | None, defense_module: str | None) -> dict[str, float]:
    """Quota delle azioni d'attacco per corsia: presenza offensiva nella corsia / presenza difensiva nella corsia speculare."""
    attack, defense = presence(attack_module), presence(defense_module)
    raw = {lane: attack[lane]["attacco"] / (1.0 + defense[MIRROR[lane]]["difesa"]) for lane in LANES}
    total = sum(raw.values())
    return {lane: value / total for lane, value in raw.items()}


def matchups(home_module: str | None, away_module: str | None) -> list[dict]:
    """Accoppiamenti per zona: fascia contro fascia speculare, centro contro centro."""
    home, away = presence(home_module), presence(away_module)
    return [{"corsia_casa": lane, "corsia_ospite": MIRROR[lane], "attacco_casa": home[lane]["attacco"],
             "difesa_ospite": away[MIRROR[lane]]["difesa"], "attacco_ospite": away[MIRROR[lane]]["attacco"],
             "difesa_casa": home[lane]["difesa"]} for lane in LANES]


# Fase AO: giocatori larghi del modulo, le stesse misure usate nella stima sulle posizioni StatsBomb (``tools.ao_corsie``).
SB_WIDE_ATTACK = ("Right Wing Back", "Left Wing Back", "Right Midfield", "Left Midfield", "Right Wing", "Left Wing")
SB_WIDE_DEFENSE = ("Right Back", "Left Back", "Right Wing Back", "Left Wing Back", "Right Midfield", "Left Midfield")


def wide_players(module: str | None) -> dict[str, float]:
    """{«attacco»: esterni e ali, «difesa»: terzini ed esterni} del modulo (chi spinge e chi copre le fasce), allineato alle
    posizioni StatsBomb: difesa a 5 = quinti (spingono e coprono), linea di 3 dietro una punta sola = ali (solo attacco)."""
    lines, _ = parse_module(module)
    players, _ = roles(module)
    out = {"attacco": 0.0, "difesa": 0.0}
    start = 0
    for position, count in enumerate(lines):
        line_players = players[start:start + count]
        start += count
        behind_single = position == len(lines) - 2 and lines[-1] == 1 and position > 0
        for player in line_players:
            if player["corsia"] == "centro":
                continue
            if player["linea"] == "difesa":
                out["difesa"] += 1
                out["attacco"] += 1 if count >= 5 else 0
            elif player["linea"] == "attacco" or (behind_single and count == 3):
                out["attacco"] += 1
            else:
                out["attacco"] += 1
                out["difesa"] += 1
    return out


def wide_from_positions(positions: list[str]) -> dict[str, float]:
    """Le stesse misure dalle posizioni iniziali StatsBomb di una squadra."""
    return {"attacco": float(sum(position in SB_WIDE_ATTACK for position in positions)),
            "difesa": float(sum(position in SB_WIDE_DEFENSE for position in positions))}


UNDERSTAT_WIDE_ATTACK = ("DMR", "DML", "MR", "ML", "AMR", "AML", "FWR", "FWL")
UNDERSTAT_WIDE_DEFENSE = ("DR", "DL", "DMR", "DML", "MR", "ML")


def wide_from_understat(positions: list[str]) -> dict[str, float]:
    """Le stesse misure dalle posizioni Understat dei titolari (DR/DL terzini, DMR/DML quinti, MR/ML esterni, AMR/AML e FWR/FWL ali)."""
    return {"attacco": float(sum(position in UNDERSTAT_WIDE_ATTACK for position in positions)),
            "difesa": float(sum(position in UNDERSTAT_WIDE_DEFENSE for position in positions))}
