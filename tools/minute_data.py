"""Fase O: dati minuto per minuto per la taratura (solo sviluppo; cache in ``data/cache/minuto``, fuori dal repo).

- Understat (5 campionati principali): per ogni partita i tiri con minuto, xG ed esito e le formazioni
  (minuti giocati, cartellini) da cui si ricava il minuto delle espulsioni dei titolari.
- StatsBomb Open Data (licenza: StatsBomb Open Data User Agreement, citare «Data: StatsBomb Open Data»):
  eventi di una stagione completa per verificare gli effetti sui gol e stimare i tempi di corner,
  falli e cartellini. Dagli eventi si tengono solo minuto, squadra e tipo (il JSON grezzo non si salva).

Fase AK: ``--statsbomb-dettaglio`` scarica UNA volta, in sequenza e con pausa tra le richieste, un riassunto più ricco degli
stessi eventi in una cache separata (``statsbomb_dettaglio_<comp>_<stagione>.json.gz``): tipo, parte del corpo, schema di gioco,
esito e zona dei tiri (anche se nati da un cross), origine dei corner (tiro parato/deviato, cross, altro), zona e corsia dei falli,
duelli per squadra. Il JSON grezzo non si salva. Fonte da citare: «Data: StatsBomb Open Data» (StatsBomb Open Data User Agreement).

Uso: ``python -m tools.minute_data --understat 2023 2024``, ``--statsbomb``, ``--statsbomb-dettaglio``.
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


SAVED = {"Saved", "Blocked", "Saved Off Target", "Saved to Post", "Saved To Post"}


def _zone(location, team_side_x: bool = True) -> tuple[str, str, bool]:
    """(terzo, corsia, in area) da una posizione StatsBomb (campo 120×80, squadra che attacca verso x = 120)."""
    if not location:
        return "", "", False
    x, y = float(location[0]), float(location[1])
    third = "difesa" if x < 40 else "centro" if x < 80 else "attacco"
    lane = "sinistra" if y < 80 / 3 else "destra" if y > 160 / 3 else "centro"
    return third, lane, x >= 102 and 18 <= y <= 62


def detail_events(events: list[dict], home: str) -> dict:
    """Riassunto compatto degli eventi di una partita per la fase AK (funzione pura, senza rete)."""
    def clock(event):
        return 60 * int(event.get("minute", 0)) + int(event.get("second", 0))

    shots, corners, fouls, cards = [], [], [], []
    duels = {"h": 0, "a": 0}
    passes_by_id = {event["id"]: event for event in events if event["type"]["name"] == "Pass"}
    for index, event in enumerate(events):
        kind = event["type"]["name"]
        side = "h" if event.get("team", {}).get("name") == home else "a"
        base = {"m": event["minute"], "p": event["period"], "s": side}
        if kind == "Shot":
            shot = event["shot"]
            third, lane, box = _zone(event.get("location"))
            key_pass = passes_by_id.get(shot.get("key_pass_id"))
            shots.append({**base, "xg": shot.get("statsbomb_xg", 0.0), "g": shot["outcome"]["name"] == "Goal",
                          "t": shot.get("type", {}).get("name", ""), "b": shot.get("body_part", {}).get("name", ""),
                          "pp": event.get("play_pattern", {}).get("name", ""), "o": shot["outcome"]["name"], "area": box,
                          "c": lane, "cross": bool(key_pass and key_pass.get("pass", {}).get("cross"))})
        elif kind == "Pass" and event.get("pass", {}).get("type", {}).get("name") == "Corner":
            origin = "altro"
            for previous in reversed(events[max(0, index - 40):index]):
                if clock(event) - clock(previous) > 60 or previous.get("period") != event.get("period"):
                    break
                same = previous.get("team", {}).get("name") == event.get("team", {}).get("name")
                if previous["type"]["name"] == "Shot" and same and previous["shot"]["outcome"]["name"] in SAVED:
                    origin = "tiro"
                    break
                if previous["type"]["name"] == "Pass" and same and previous.get("pass", {}).get("cross"):
                    origin = "cross"
                    break
            corners.append({**base, "o": origin})
        elif kind == "Foul Committed":
            third, lane, _ = _zone(event.get("location"))
            fouls.append({**base, "z": third, "c": lane, "card": event.get("foul_committed", {}).get("card", {}).get("name")})
        elif kind == "Bad Behaviour":
            card = event.get("bad_behaviour", {}).get("card", {}).get("name")
            if card:
                cards.append({**base, "card": card})
        elif kind == "Duel":
            duels[side] += 1
    return {"shots": shots, "corners": corners, "fouls": fouls, "cards": cards, "duels": duels}


def download_statsbomb_detail(pause: float = 1.0) -> None:
    """Riassunti «dettaglio» delle stagioni StatsBomb, in sequenza, con pausa e ripresa da dove si era fermato."""
    CACHE.mkdir(parents=True, exist_ok=True)
    for competition, season in SB_SEASONS:
        target = CACHE / f"statsbomb_dettaglio_{competition}_{season}.json.gz"
        partial = CACHE / f"statsbomb_dettaglio_{competition}_{season}.parziale.json.gz"
        if target.exists():
            print(f"già in cache: {target.name}", flush=True)
            continue
        matches = _get(f"{SB_BASE}/matches/{competition}/{season}.json").json()
        rows = json.load(gzip.open(partial, "rt", encoding="utf-8")) if partial.exists() else []
        done = {row["id"] for row in rows}
        for position, match in enumerate(matches, start=1):
            if match["match_id"] in done:
                continue
            events = _get(f"{SB_BASE}/events/{match['match_id']}.json").json()
            home = match["home_team"]["home_team_name"]
            rows.append({"id": match["match_id"], "date": match.get("match_date"), "home": home,
                         "away": match["away_team"]["away_team_name"], "home_goals": match["home_score"],
                         "away_goals": match["away_score"], "referee": (match.get("referee") or {}).get("name"),
                         **detail_events(events, home)})
            time.sleep(pause)
            if position % 25 == 0:
                with gzip.open(partial, "wt", encoding="utf-8") as handle:
                    json.dump(rows, handle)
                print(f"{competition}_{season}: {position}/{len(matches)}", flush=True)
        with gzip.open(target, "wt", encoding="utf-8") as handle:
            json.dump(rows, handle)
        partial.unlink(missing_ok=True)
        print(f"{target.name}: {len(rows)} partite", flush=True)


def starting_positions(lineups: list[dict]) -> dict[str, list[str]]:
    """Posizioni StatsBomb dei titolari per squadra («Right Back», «Left Wing»…), dalla formazione iniziale."""
    out = {}
    for team in lineups:
        out[team["team_name"]] = [position["position"] for player in team.get("lineup", [])
                                  for position in player.get("positions", [])[:1]
                                  if position.get("start_reason") == "Starting XI"]
    return out


def download_statsbomb_lineups(pause: float = 0.3) -> None:
    """Fase AO: posizioni iniziali (moduli e corsie) delle stesse partite, una volta, con ripresa dal file parziale."""
    CACHE.mkdir(parents=True, exist_ok=True)
    for competition, season in SB_SEASONS:
        target = CACHE / f"statsbomb_formazioni_{competition}_{season}.json.gz"
        partial = CACHE / f"statsbomb_formazioni_{competition}_{season}.parziale.json.gz"
        if target.exists():
            print(f"già in cache: {target.name}", flush=True)
            continue
        matches = _get(f"{SB_BASE}/matches/{competition}/{season}.json").json()
        rows = json.load(gzip.open(partial, "rt", encoding="utf-8")) if partial.exists() else []
        done = {row["id"] for row in rows}
        for position, match in enumerate(matches, start=1):
            if match["match_id"] in done:
                continue
            lineups = _get(f"{SB_BASE}/lineups/{match['match_id']}.json").json()
            rows.append({"id": match["match_id"], "home": match["home_team"]["home_team_name"],
                         "away": match["away_team"]["away_team_name"], "posizioni": starting_positions(lineups)})
            time.sleep(pause)
            if position % 50 == 0:
                with gzip.open(partial, "wt", encoding="utf-8") as handle:
                    json.dump(rows, handle)
                print(f"{competition}_{season}: {position}/{len(matches)}", flush=True)
        with gzip.open(target, "wt", encoding="utf-8") as handle:
            json.dump(rows, handle)
        partial.unlink(missing_ok=True)
        print(f"{target.name}: {len(rows)} partite", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--understat", nargs="*", type=int, help="Stagioni Understat (anno d'inizio)")
    parser.add_argument("--statsbomb", action="store_true")
    parser.add_argument("--statsbomb-dettaglio", action="store_true", help="riassunto ricco per la fase AK (una volta)")
    parser.add_argument("--statsbomb-formazioni", action="store_true", help="posizioni iniziali per la fase AO (una volta)")
    args = parser.parse_args()
    if args.understat:
        download_understat(args.understat)
    if args.statsbomb:
        download_statsbomb()
    if args.statsbomb_dettaglio:
        download_statsbomb_detail()
    if args.statsbomb_formazioni:
        download_statsbomb_lineups()


if __name__ == "__main__":
    main()
