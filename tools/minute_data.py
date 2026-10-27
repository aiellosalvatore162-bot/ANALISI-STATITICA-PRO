"""Fase O: dati minuto per minuto per la taratura (solo sviluppo; cache in ``data/cache/minuto``, fuori dal repo).

- Understat (5 campionati principali): per ogni partita i tiri con minuto, xG ed esito e le formazioni
  (minuti giocati, cartellini) da cui si ricava il minuto delle espulsioni dei titolari.
- StatsBomb Open Data (licenza: StatsBomb Open Data User Agreement, citare «Data: StatsBomb Open Data»):
  eventi di una stagione completa per verificare gli effetti sui gol e stimare i tempi di corner,
  falli e cartellini. Dagli eventi si tengono solo minuto, squadra e tipo (il JSON grezzo non si salva).

Uso: ``python -m tools.minute_data --understat 2023 2024`` e ``python -m tools.minute_data --statsbomb``.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "minuto"
LEAGUES = ("EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1")
HEADERS = {"X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0 (analisi statistica personale)"}
SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
# Stagioni complete aperte dei 5 campionati 2015/16 (competition_id, season_id): Premier League, Liga,
# Serie A, Bundesliga, Ligue 1.
SB_SEASONS = ((2, 27), (11, 27), (12, 27), (9, 27), (7, 27))


def _get(url: str, retries: int = 3) -> requests.Response:
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            if response.status_code == 200:
                return response
        except requests.RequestException:
            pass
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download non riuscito: {url}")


def understat_match(match_id: str) -> dict:
    data = _get(f"https://understat.com/getMatchData/{match_id}").json()
    shots = [{key: shot[key] for key in ("minute", "h_a", "result", "xG", "situation")}
             for side in ("h", "a") for shot in data["shots"][side]]
    reds = []
    for side in ("h", "a"):
        roster = data.get("rosters", {}).get(side) or {}
        for player in (roster.values() if isinstance(roster, dict) else roster):
            if int(player.get("red_card", 0) or 0) > 0:
                reds.append({"h_a": side, "minute": int(player.get("time", 0) or 0), "position": player.get("position")})
    return {"shots": shots, "reds": reds}


def download_understat(seasons: list[int], workers: int = 4) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for league in LEAGUES:
        for season in seasons:
            target = CACHE / f"understat_{league}_{season}.json.gz"
            if target.exists():
                print(f"già in cache: {target.name}")
                continue
            dates = _get(f"https://understat.com/getLeagueData/{league}/{season}").json()["dates"]
            played = [match for match in dates if match.get("isResult")]

            def one(match: dict) -> dict:
                detail = understat_match(match["id"])
                return {"id": match["id"], "league": league, "season": season, "date": match["datetime"],
                        "home": match["h"]["title"], "away": match["a"]["title"],
                        "home_goals": int(match["goals"]["h"]), "away_goals": int(match["goals"]["a"]), **detail}

            with ThreadPoolExecutor(workers) as pool:
                rows = list(pool.map(one, played))
            with gzip.open(target, "wt", encoding="utf-8") as handle:
                json.dump(rows, handle)
            print(f"{target.name}: {len(rows)} partite")


def download_statsbomb(workers: int = 6) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for competition, season in SB_SEASONS:
        target = CACHE / f"statsbomb_{competition}_{season}.json.gz"
        if target.exists():
            print(f"già in cache: {target.name}")
            continue
        matches = _get(f"{SB_BASE}/matches/{competition}/{season}.json").json()

        def one(match: dict) -> dict:
            events = _get(f"{SB_BASE}/events/{match['match_id']}.json").json()
            home = match["home_team"]["home_team_name"]
            kept = []
            for event in events:
                kind = event["type"]["name"]
                side = "h" if event.get("team", {}).get("name") == home else "a"
                row = {"minute": event["minute"], "period": event["period"], "h_a": side}
                if kind == "Shot":
                    kept.append({**row, "kind": "shot", "xg": event["shot"].get("statsbomb_xg", 0.0),
                                 "goal": event["shot"]["outcome"]["name"] == "Goal"})
                elif kind == "Own Goal For":
                    kept.append({**row, "kind": "own_goal_for"})
                elif kind == "Pass" and event.get("pass", {}).get("type", {}).get("name") == "Corner":
                    kept.append({**row, "kind": "corner"})
                elif kind == "Foul Committed":
                    card = event.get("foul_committed", {}).get("card", {}).get("name")
                    kept.append({**row, "kind": "foul", "card": card})
                elif kind == "Bad Behaviour":
                    card = event.get("bad_behaviour", {}).get("card", {}).get("name")
                    if card:
                        kept.append({**row, "kind": "card_other", "card": card})
            return {"id": match["match_id"], "home": home, "away": match["away_team"]["away_team_name"],
                    "home_goals": match["home_score"], "away_goals": match["away_score"], "events": kept}

        with ThreadPoolExecutor(workers) as pool:
            rows = list(pool.map(one, matches))
        with gzip.open(target, "wt", encoding="utf-8") as handle:
            json.dump(rows, handle)
        print(f"{target.name}: {len(rows)} partite")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--understat", nargs="*", type=int, help="Stagioni Understat (anno d'inizio)")
    parser.add_argument("--statsbomb", action="store_true")
    args = parser.parse_args()
    if args.understat:
        download_understat(args.understat)
    if args.statsbomb:
        download_statsbomb()


if __name__ == "__main__":
    main()
