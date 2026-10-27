"""Fase O: stima delle regole del motore minuto per minuto (blocchi di 5 minuti).

Dati (cache di ``tools.minute_data``, fuori dal repo):
- Understat, 5 campionati principali, stagioni 2023/24 e 2024/25: tiri con minuto, xG ed esito,
  espulsioni dei titolari (minuti giocati) → profilo dei minuti dei gol, moltiplicatori per stato del
  punteggio (svantaggio/parità/vantaggio per fascia di minuti) ed effetto dell'espulsione;
- StatsBomb Open Data 2015/16 (Premier League, Liga, Serie A, Bundesliga, Ligue 1; «Data: StatsBomb Open
  Data»): stessa stima sugli xG StatsBomb come verifica, corner legati alla pressione offensiva
  (esponente γ sui moltiplicatori dei tiri), cartellini per minuto e per partita in parità, tempi delle
  espulsioni.

Stime con effetto fisso di squadra-partita (adattamento proporzionale iterativo, Poisson) e shrinkage
verso 1 con ``SHRINK`` unità fittizie: dove i dati sono pochi il moltiplicatore resta vicino a 1.
Uso: ``python -m tools.minute_model [--salva] [--output docs/BASELINE.md]``.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools.minute_data import CACHE

BLOCKS = 18
BANDS = ((0, 30), (30, 60), (60, 75), (75, 90))
STATES = (-2, -1, 0, 1, 2)
SHRINK = {"stato": 15.0, "espulsioni": 8.0, "corner": 15.0, "cartellini": 15.0}


def block_of(minute: int, period: int | None = None) -> int:
    """Blocco di 5 minuti (0-17); i recuperi stanno nell'ultimo blocco del tempo."""
    first = period == 1 if period is not None else minute <= 45
    if first:
        return min(max(minute - 1, 0), 44) // 5
    return 9 + min(max(minute - 46, 0), 44) // 5


def band_of(minute: int) -> int:
    return next(index for index, (low, high) in enumerate(BANDS) if minute <= high or index == len(BANDS) - 1)


# --- Linee temporali per squadra-partita ------------------------------------------------------------

def understat_timelines() -> list[dict]:
    """Per partita: minuti dei gol per lato, xG per minuto e lato, espulsioni (titolari) per minuto e lato."""
    matches = []
    for path in sorted(CACHE.glob("understat_*.json.gz")):
        for row in json.load(gzip.open(path, "rt", encoding="utf-8")):
            goals, xg = [], defaultdict(float)
            for shot in row["shots"]:
                minute = max(1, min(int(shot["minute"]), 95))
                xg[(shot["h_a"], minute)] += float(shot["xG"])
                if shot["result"] == "Goal":
                    goals.append((minute, shot["h_a"]))
                elif shot["result"] == "OwnGoal":
                    goals.append((minute, "a" if shot["h_a"] == "h" else "h"))
            reds = [(red["minute"], red["h_a"]) for red in row["reds"] if red.get("position") != "Sub" and 0 < red["minute"] < 90]
            matches.append({"source": "understat", "league": row["league"], "goals": goals, "xg": xg, "reds": reds,
                            "corners": {}, "cards": {}})
    return matches


def statsbomb_timelines() -> list[dict]:
    matches = []
    for path in sorted(CACHE.glob("statsbomb_*.json.gz")):
        for row in json.load(gzip.open(path, "rt", encoding="utf-8")):
            goals, reds = [], []
            xg, corners, cards = defaultdict(float), defaultdict(float), defaultdict(float)
            for event in row["events"]:
                minute = event["minute"] + 1 if event["period"] == 1 else event["minute"] + 1
                minute = min(minute, 45) if event["period"] == 1 else max(46, min(minute, 95))
                side = event["h_a"]
                if event["kind"] == "shot":
                    xg[(side, minute)] += float(event["xg"] or 0.0)
                    if event["goal"]:
                        goals.append((minute, side))
                elif event["kind"] == "own_goal_for":
                    goals.append((minute, side))
                elif event["kind"] == "corner":
                    corners[(side, minute)] += 1
                elif event["kind"] in ("foul", "card_other") and event.get("card"):
                    if event["card"] in ("Yellow Card", "Second Yellow"):
                        cards[(side, minute)] += 1
                    if event["card"] in ("Red Card", "Second Yellow") and event["period"] in (1, 2):
                        reds.append((minute, side))
            matches.append({"source": "statsbomb", "league": "", "goals": goals, "xg": xg, "reds": reds,
                            "corners": corners, "cards": cards})
    return matches


def team_minutes(matches: list[dict]) -> pd.DataFrame:
    """Una riga per squadra-partita-minuto (1-90; recuperi nel 45° e nel 90°): stato, superiorità, eventi."""
    rows = []
    for index, match in enumerate(matches):
        goals = sorted(match["goals"])
        reds = sorted(match["reds"])
        for side, other in (("h", "a"), ("a", "h")):
            for minute in range(1, 91):
                before = [goal for goal in goals if goal[0] < minute or (minute == 90 and False)]
                scored = sum(1 for goal in before if goal[1] == side)
                conceded = len(before) - scored
                red_for = sum(1 for red in reds if red[1] == side and red[0] < minute)
                red_against = sum(1 for red in reds if red[1] == other and red[0] < minute)
                minutes_in = [minute] if minute not in (45, 90) else list(range(minute, minute + 6))
                rows.append({
                    "team_match": 2 * index + (side == "a"), "match": index, "source": match["source"], "minute": minute,
                    "block": block_of(minute), "band": band_of(minute),
                    "state": int(np.clip(scored - conceded, -2, 2)), "level": int(scored == conceded),
                    "advantage": int(np.clip(red_against - red_for, -1, 1)),
                    "xg": sum(match["xg"].get((side, value), 0.0) for value in minutes_in),
                    "corners": sum(match["corners"].get((side, value), 0.0) for value in minutes_in),
                    "cards": sum(match["cards"].get((side, value), 0.0) for value in minutes_in),
                })
    return pd.DataFrame(rows)


# --- Stima ------------------------------------------------------------------------------------------

def fit_state_model(data: pd.DataFrame, column: str, *, iterations: int = 60, shrink: float = 15.0,
                    with_advantage: bool = True) -> dict:
    """Intensità = base(squadra-partita) · peso(blocco) · S(stato, fascia) · R(superiorità), Poisson, IPF.

    S(0, ·) = R(0) = 1 (riferimento); S e R ridotti verso 1 con ``shrink`` unità fittizie.
    """
    cells = data.groupby(["team_match", "block", "band", "state", "advantage"], as_index=False).agg(
        exposure=("minute", "size"), count=(column, "sum"))
    weights = np.ones(BLOCKS)
    state = {(s, b): 1.0 for s in STATES for b in range(len(BANDS))}
    advantage = {-1: 1.0, 0: 1.0, 1: 1.0}
    team = cells["team_match"].to_numpy()
    for _ in range(iterations):
        factor = (weights[cells["block"]] * np.array([state[(s, b)] for s, b in zip(cells["state"], cells["band"])])
                  * np.array([advantage[a] for a in cells["advantage"]]))
        expected_per_team = np.bincount(team, cells["exposure"] * factor)
        base = np.bincount(team, cells["count"]) / np.maximum(expected_per_team, 1e-12)
        mean = base[team] * cells["exposure"].to_numpy() * factor
        for block in range(BLOCKS):
            mask = cells["block"].to_numpy() == block
            weights[block] *= cells["count"].to_numpy()[mask].sum() / max(mean[mask].sum(), 1e-12)
        weights /= weights.mean()
        factor = (weights[cells["block"]] * np.array([state[(s, b)] for s, b in zip(cells["state"], cells["band"])])
                  * np.array([advantage[a] for a in cells["advantage"]]))
        mean = base[team] * cells["exposure"].to_numpy() * factor
        for key in state:
            if key[0] == 0:
                continue
            mask = ((cells["state"] == key[0]) & (cells["band"] == key[1])).to_numpy()
            observed, expected = cells["count"].to_numpy()[mask].sum(), mean[mask].sum() / state[key]
            state[key] = (observed + shrink) / (expected + shrink)
        if with_advantage:
            factor = (weights[cells["block"]] * np.array([state[(s, b)] for s, b in zip(cells["state"], cells["band"])])
                      * np.array([advantage[a] for a in cells["advantage"]]))
            mean = base[team] * cells["exposure"].to_numpy() * factor
            for key in (-1, 1):
                mask = (cells["advantage"] == key).to_numpy()
                observed, expected = cells["count"].to_numpy()[mask].sum(), mean[mask].sum() / advantage[key]
                advantage[key] = (observed + SHRINK["espulsioni"]) / (expected + SHRINK["espulsioni"])
    exposure = cells.groupby(["state", "band"])["exposure"].sum()
    return {"pesi_blocchi": [round(float(value), 4) for value in weights],
            "stato": {str(s): [round(state[(s, b)], 4) for b in range(len(BANDS))] for s in STATES},
            "superiorita": {"meno_uomini": round(advantage[-1], 4), "piu_uomini": round(advantage[1], 4)},
            "minuti_per_stato": {f"{s}|{b}": int(exposure.get((s, b), 0)) for s in STATES for b in range(len(BANDS))},
            "eventi": float(cells["count"].sum())}


def fit_corner_gamma(data: pd.DataFrame, goal_model: dict) -> dict:
    """Corner ∝ base · peso(blocco) · (S·R dei tiri)^γ: γ per massima verosimiglianza (base di squadra-partita profilata)."""
    from scipy.optimize import minimize_scalar

    state = goal_model["stato"]
    pressure = np.array([state[str(s)][b] for s, b in zip(data["state"], data["band"])]) * \
        np.where(data["advantage"] < 0, goal_model["superiorita"]["meno_uomini"],
                 np.where(data["advantage"] > 0, goal_model["superiorita"]["piu_uomini"], 1.0))
    blocks = data.groupby("block")["corners"].sum().reindex(range(BLOCKS), fill_value=0).to_numpy(float)
    weights = blocks / blocks.mean()
    team = data["team_match"].to_numpy()
    counts = data["corners"].to_numpy(float)
    exposure = (np.where(data["minute"].isin([45, 90]), 6, 1)).astype(float)

    def nll(gamma: float) -> float:
        intensity = weights[data["block"]] * exposure * pressure ** gamma
        base = np.bincount(team, counts) / np.maximum(np.bincount(team, intensity), 1e-12)
        mean = np.maximum(base[team] * intensity, 1e-12)
        return float(np.sum(mean - counts * np.log(mean)))

    gamma = float(minimize_scalar(nll, bounds=(0.0, 3.0), method="bounded").x)
    return {"pesi_blocchi": [round(float(value), 4) for value in weights / np.mean(weights)], "gamma": round(gamma, 4),
            "nll_gamma": nll(gamma), "nll_gamma_0": nll(0.0), "eventi": float(counts.sum())}


def fit_card_timing(data: pd.DataFrame) -> dict:
    """Cartellini della partita (entrambe le squadre): peso per blocco e moltiplicatore per parità per fascia."""
    match = data[data["team_match"] % 2 == 0][["match", "minute", "block", "band", "level"]].copy()
    both = data.groupby(["match", "minute"], as_index=False)["cards"].sum()
    match = match.merge(both, on=["match", "minute"])
    blocks = match.groupby("block")["cards"].sum().reindex(range(BLOCKS), fill_value=0).to_numpy(float)
    weights = blocks / blocks.mean()
    level = []
    for band in range(len(BANDS)):
        subset = match[match["band"] == band]
        expected = weights[subset["block"]]
        rate = lambda mask: (subset["cards"][mask].sum() + SHRINK["cartellini"] * 0) / max(expected[mask].sum(), 1e-12)
        on, off = subset["level"] == 1, subset["level"] == 0
        observed_on, expected_on = subset["cards"][on].sum(), expected[on].sum()
        observed_off, expected_off = subset["cards"][off].sum(), expected[off].sum()
        ratio = ((observed_on + SHRINK["cartellini"]) / (expected_on * observed_off / max(expected_off, 1e-12) + SHRINK["cartellini"]))
        level.append(round(float(ratio), 4))
    return {"pesi_blocchi": [round(float(value), 4) for value in weights], "parita": level, "eventi": float(match["cards"].sum())}


def red_timing(matches: list[dict]) -> list[float]:
    counts = np.zeros(BLOCKS)
    for match in matches:
        for minute, _ in match["reds"]:
            counts[block_of(minute)] += 1
    counts += 1.0  # shrinkage verso il profilo piatto
    return [round(float(value), 4) for value in counts / counts.mean()]


def estimate() -> tuple[dict, dict]:
    understat = understat_timelines()
    statsbomb = statsbomb_timelines()
    us_data, sb_data = team_minutes(understat), team_minutes(statsbomb)
    goals = fit_state_model(us_data, "xg", shrink=SHRINK["stato"])
    check = fit_state_model(sb_data, "xg", shrink=SHRINK["stato"])
    corners = fit_corner_gamma(sb_data, goals)
    cards = fit_card_timing(sb_data)
    params = {
        "data": date.today().isoformat(),
        "blocchi": BLOCKS, "bande_minuti": [list(band) for band in BANDS],
        "gol": {"pesi_blocchi": goals["pesi_blocchi"], "stato": goals["stato"], "superiorita": goals["superiorita"]},
        "corner": {"pesi_blocchi": corners["pesi_blocchi"], "gamma": corners["gamma"]},
        "cartellini": {"pesi_blocchi": cards["pesi_blocchi"], "parita": cards["parita"]},
        "espulsioni_pesi_blocchi": red_timing(understat + statsbomb),
        "fonti": {"understat_partite": len(understat), "statsbomb_partite": len(statsbomb),
                  "understat": "EPL, Liga, Bundesliga, Serie A, Ligue 1, stagioni 2023/24 e 2024/25",
                  "statsbomb": "StatsBomb Open Data 2015/16: Premier League, Liga, Serie A, Bundesliga, Ligue 1"},
    }
    return params, {"understat": goals, "statsbomb": check, "corner": corners, "cartellini": cards}


def report(params: dict, details: dict) -> str:
    us, sb = details["understat"], details["statsbomb"]
    lines = ["## Motore minuto per minuto: regole stimate (fase O)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.minute_model`. Understat: "
             f"{params['fonti']['understat_partite']} partite ({params['fonti']['understat']}). StatsBomb: "
             f"{params['fonti']['statsbomb_partite']} partite ({params['fonti']['statsbomb']}; Data: StatsBomb Open Data). "
             f"Effetto fisso di squadra-partita, shrinkage verso 1 ({SHRINK}).", "",
             "### Ritmo degli xG per stato del punteggio (squadra che…), per fascia di minuti: Understat / StatsBomb", "",
             "| Stato | " + " | ".join(f"{low}-{high}'" for low, high in BANDS) + " |", "|---|" + "---|" * len(BANDS)]
    names = {-2: "perde di 2+", -1: "perde di 1", 0: "pareggia (rif.)", 1: "vince di 1", 2: "vince di 2+"}
    for state in STATES:
        cells = [f"{us['stato'][str(state)][band]:.2f} / {sb['stato'][str(state)][band]:.2f}" for band in range(len(BANDS))]
        lines.append(f"| {names[state]} | " + " | ".join(cells) + " |")
    lines += ["", f"Espulsioni (ritmo xG di chi è in 10 / della squadra in superiorità): Understat "
                  f"{us['superiorita']['meno_uomini']:.2f} / {us['superiorita']['piu_uomini']:.2f}; StatsBomb "
                  f"{sb['superiorita']['meno_uomini']:.2f} / {sb['superiorita']['piu_uomini']:.2f}.", "",
              "Pesi dei blocchi di 5 minuti (gol, Understat): " + ", ".join(f"{value:.2f}" for value in us["pesi_blocchi"]), "",
              f"Corner ∝ pressione offensiva^γ: γ = {details['corner']['gamma']:.2f} (log-verosimiglianza negativa "
              f"{details['corner']['nll_gamma']:.1f} contro {details['corner']['nll_gamma_0']:.1f} con γ = 0; "
              f"{details['corner']['eventi']:.0f} corner).", "",
              "Cartellini: moltiplicatore se la partita è in parità, per fascia: "
              + ", ".join(f"{low}-{high}' {value:.2f}" for (low, high), value in zip(BANDS, details["cartellini"]["parita"]))
              + f"; pesi dei blocchi: " + ", ".join(f"{value:.2f}" for value in details["cartellini"]["pesi_blocchi"])
              + f" ({details['cartellini']['eventi']:.0f} cartellini).", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true", help="Scrive i parametri in config/goal_model.json (minuto_per_minuto)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    params, details = estimate()
    markdown = report(params, details)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva:
        from tools.calibrate import _update_config

        config = json.loads(Path("config/goal_model.json").read_text(encoding="utf-8")).get("minuto_per_minuto", {})
        _update_config({"minuto_per_minuto": {**config, "parametri": params}})


if __name__ == "__main__":
    main()
