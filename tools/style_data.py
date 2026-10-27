"""Fase Q, punto 5: misure di stile per squadra-partita dagli eventi StatsBomb Open Data (solo sviluppo).

Per le stagioni complete 2015/16 dei 5 campionati (Data: StatsBomb Open Data) si tengono, per squadra e
partita: passaggi, progressione verso la porta per passaggio (verticalità), altezza media delle azioni
difensive (pressioni, contrasti, intercetti, recuperi), pressioni, cross, passaggi sulle fasce, tiri, xG,
corner e falli. Il JSON grezzo non si salva: solo il riassunto in ``data/cache/minuto/stili_statsbomb.json.gz``.
Uso: ``python -m tools.style_data``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gzip
import json

from tools.minute_data import CACHE, SB_BASE, SB_SEASONS, _get

DEFENSIVE = {"Pressure", "Duel", "Interception", "Ball Recovery", "Block", "Clearance"}


def summarize(match: dict, season: tuple[int, int]) -> list[dict]:
    events = _get(f"{SB_BASE}/events/{match['match_id']}.json").json()
    home = match["home_team"]["home_team_name"]
    teams = {home: "h", match["away_team"]["away_team_name"]: "a"}
    stats = {side: {"passes": 0, "progress": 0.0, "def_x": 0.0, "def_n": 0, "pressures": 0, "crosses": 0, "wide": 0,
                    "shots": 0, "xg": 0.0, "corners": 0, "fouls": 0} for side in ("h", "a")}
    for event in events:
        side = teams.get(event.get("team", {}).get("name"))
        if side is None:
            continue
        kind = event["type"]["name"]
        row = stats[side]
        location = event.get("location") or [None, None]
        if kind == "Pass":
            details = event.get("pass", {})
            if details.get("type", {}).get("name") == "Corner":
                row["corners"] += 1
            end = details.get("end_location")
            if end and location[0] is not None and "outcome" not in details:
                row["passes"] += 1
                row["progress"] += end[0] - location[0]
                if location[1] < 18 or location[1] > 62:
                    row["wide"] += 1
            if details.get("cross"):
                row["crosses"] += 1
        elif kind == "Shot":
            row["shots"] += 1
            row["xg"] += float(event["shot"].get("statsbomb_xg") or 0.0)
        elif kind == "Foul Committed":
            row["fouls"] += 1
        if kind in DEFENSIVE and location[0] is not None:
            row["def_x"] += location[0]
            row["def_n"] += 1
            if kind == "Pressure":
                row["pressures"] += 1
    rows = []
    for name, side in teams.items():
        other = "a" if side == "h" else "h"
        rows.append({"season": f"{season[0]}_{season[1]}", "match": match["match_id"], "date": match["match_date"],
                     "team": name, "opponent": next(team for team in teams if team != name), "venue": side,
                     **stats[side], "opp_passes": stats[other]["passes"]})
    return rows


def main() -> None:
    target = CACHE / "stili_statsbomb.json.gz"
    rows = []
    for competition, season in SB_SEASONS:
        matches = _get(f"{SB_BASE}/matches/{competition}/{season}.json").json()
        with ThreadPoolExecutor(6) as pool:
            for part in pool.map(lambda match: summarize(match, (competition, season)), matches):
                rows.extend(part)
        print(f"{competition}/{season}: {len(matches)} partite")
    with gzip.open(target, "wt", encoding="utf-8") as handle:
        json.dump(rows, handle)
    print(f"{target.name}: {len(rows)} righe squadra-partita")


if __name__ == "__main__":
    main()
