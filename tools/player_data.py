"""Fase P, punti 2 e 7b: storico partita per partita dei giocatori da Understat (solo sviluppo, una volta).

Per ogni partita dei 5 campionati (stagioni indicate, anno d'inizio) si salvano le formazioni (minuti, gol,
autogol, xG, xA, tiri, ruolo, entrato/uscito) e i rigori calciati (giocatore, xG, esito). Al massimo ``WORKERS`` richieste
insieme, ognuna seguita da una pausa (``PAUSE`` secondi) per non pesare sul sito; le partite già scaricate restano nel file di cache e
non si richiedono di nuovo. Cache: ``data/cache/fase_p/giocatori_<campionato>_<stagione>.json.gz`` (fuori dal
repository). Uso: ``python -m tools.player_data 2024 2025``.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import time

from tools.minute_data import LEAGUES, _get
from tools.v2common import CACHE

PAUSE = 1.0
WORKERS = 3
ROSTER_FIELDS = ("player_id", "player", "position", "time", "goals", "own_goals", "xG", "xA", "shots", "roster_in",
                 "roster_out", "positionOrder")


def match_players(match_id: str) -> dict:
    data = _get(f"https://understat.com/getMatchData/{match_id}").json()
    players = []
    for side in ("h", "a"):
        roster = data.get("rosters", {}).get(side) or {}
        for player in (roster.values() if isinstance(roster, dict) else roster):
            players.append({"side": side, **{key: player.get(key) for key in ROSTER_FIELDS}})
    penalties = [{"side": side, "player_id": shot.get("player_id"), "player": shot.get("player"), "xG": shot.get("xG"),
                  "result": shot.get("result")}
                 for side in ("h", "a") for shot in data.get("shots", {}).get(side, []) if shot.get("situation") == "Penalty"]
    return {"players": players, "penalties": penalties}


def path_for(league: str, season: int):
    return CACHE / f"giocatori_{league}_{season}.json.gz"


def load(league: str, season: int) -> list[dict]:
    path = path_for(league, season)
    return json.load(gzip.open(path, "rt", encoding="utf-8")) if path.exists() else []


def download(seasons: list[int]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for season in seasons:
        for league in LEAGUES:
            rows = load(league, season)
            done = {row["id"] for row in rows}
            dates = _get(f"https://understat.com/getLeagueData/{league}/{season}").json()["dates"]
            played = [match for match in dates if match.get("isResult") and match["id"] not in done]

            def one(match: dict) -> dict | None:
                try:
                    detail = match_players(match["id"])
                except RuntimeError as exc:
                    print(f"saltata {match['id']}: {exc}", flush=True)
                    return None
                finally:
                    time.sleep(PAUSE)  # pausa dopo ogni richiesta, in ciascuno dei WORKERS flussi
                return {"id": match["id"], "league": league, "season": season, "date": match["datetime"],
                        "home": match["h"]["title"], "away": match["a"]["title"],
                        "home_goals": int(match["goals"]["h"]), "away_goals": int(match["goals"]["a"]), **detail}

            with ThreadPoolExecutor(WORKERS) as pool:
                for position, row in enumerate(pool.map(one, played), start=1):
                    if row is not None:
                        rows.append(row)
                    if position % 100 == 0:  # salvataggio intermedio: un'interruzione non fa perdere il lavoro
                        _save(league, season, rows)
                        print(f"{league} {season}: {position}/{len(played)}", flush=True)
            _save(league, season, rows)
            print(f"{league} {season}: {len(rows)} partite", flush=True)


def _save(league: str, season: int, rows: list[dict]) -> None:
    with gzip.open(path_for(league, season), "wt", encoding="utf-8") as handle:
        json.dump(rows, handle)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("seasons", nargs="+", type=int)
    download(parser.parse_args().seasons)


if __name__ == "__main__":
    main()
