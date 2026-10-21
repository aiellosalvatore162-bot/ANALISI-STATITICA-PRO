"""Lettori delle fonti: Understat, football-data.co.uk e football-data.org.

Ogni lettore passa da ``SourceCache`` e restituisce un ``SourceFrame``: i dati
normalizzati più data di aggiornamento ed eventuale avviso (fonte non
raggiungibile, uso della cache).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from io import BytesIO
import json
import os
import re

import numpy as np
import pandas as pd

from datasources.cache import SourceCache
from tools.dataset import clean_frames, frame_from_csv


# Competizioni nazionali coperte da football-data.co.uk e Understat.
COMPETITIONS = {
    "Serie A": {"footballdata": "I1", "understat": "Serie_A"},
    "Premier League": {"footballdata": "E0", "understat": "EPL"},
    "La Liga": {"footballdata": "SP1", "understat": "La_liga"},
    "Bundesliga": {"footballdata": "D1", "understat": "Bundesliga"},
    "Ligue 1": {"footballdata": "F1", "understat": "Ligue_1"},
    # Campionati senza Understat: tiri, corner, falli, cartellini, gol e xG da football-data.co.uk.
    "Primeira Liga": {"footballdata": "P1", "understat": None},
    "Eredivisie": {"footballdata": "N1", "understat": None},
    "Jupiler Pro League": {"footballdata": "B1", "understat": None},
    "Süper Lig": {"footballdata": "T1", "understat": None},
    "Super League Grecia": {"footballdata": "G1", "understat": None},
    "Premiership scozzese": {"footballdata": "SC0", "understat": None},
}
CUP_COMPETITIONS = {"Champions League": "CL"}


def season_start(day: date) -> int:
    return day.year if day.month >= 7 else day.year - 1


def footballdata_season_code(start: int) -> str:
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


@dataclass
class SourceFrame:
    data: pd.DataFrame
    source: str
    updated: datetime | None
    warnings: list[str] = field(default_factory=list)


def _merge(results: list[SourceFrame], source: str) -> SourceFrame:
    frames = [result.data for result in results if not result.data.empty]
    updated = [result.updated for result in results if result.updated is not None]
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if "date" in data:
        data = data.sort_values("date", kind="stable").reset_index(drop=True)
    return SourceFrame(
        data,
        source,
        max(updated) if updated else None,
        [warning for result in results for warning in result.warnings],
    )


class Understat:
    """xG, xGA, PPDA e deep completions partita per partita (campionati top)."""

    URL = "https://understat.com/getLeagueData/{league}/{season}"
    TEAM_URL = "https://understat.com/getTeamData/{team}/{season}"

    def __init__(self, cache: SourceCache) -> None:
        self.cache = cache

    def team(self, title: str, season: int, max_age: timedelta) -> tuple[dict | None, list[str]]:
        """Statistiche per situazione, velocità d'azione e minuto di una squadra (stagione)."""
        result = self.cache.get(
            self.TEAM_URL.format(team=title.replace(" ", "_"), season=season), source="understat", max_age=max_age,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        warnings = [result.warning] if result.warning else []
        if not result.ok:
            return None, warnings
        try:
            return json.loads(result.body), warnings
        except ValueError:
            return None, warnings + [f"Understat: risposta non valida per {title}."]

    def league(self, league: str, season: int, max_age: timedelta) -> SourceFrame:
        result = self.cache.get(
            self.URL.format(league=league, season=season), source="understat", max_age=max_age,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        warnings = [result.warning] if result.warning else []
        if not result.ok:
            return SourceFrame(pd.DataFrame(), "Understat", None, warnings)
        return SourceFrame(parse_understat(result.body), "Understat", result.fetched_at, warnings)


def _ratio(value: object) -> float:
    if isinstance(value, dict) and value.get("def"):
        return float(value["att"]) / float(value["def"])
    return float("nan")


def parse_understat(body: bytes) -> pd.DataFrame:
    payload = json.loads(body)
    rows = []
    for team in payload.get("teams", {}).values():
        for match in team.get("history", []):
            rows.append({
                "team": team["title"],
                "date": pd.Timestamp(match["date"]).normalize(),
                "venue": "home" if match["h_a"] == "h" else "away",
                "xg_for": float(match["xG"]),
                "xg_against": float(match["xGA"]),
                "npxg_for": float(match["npxG"]),
                "npxg_against": float(match["npxGA"]),
                "ppda": _ratio(match.get("ppda")),
                "ppda_allowed": _ratio(match.get("ppda_allowed")),
                "deep": float(match.get("deep", np.nan)),
                "deep_allowed": float(match.get("deep_allowed", np.nan)),
                "goals_for": int(match["scored"]),
                "goals_against": int(match["missed"]),
            })
    return pd.DataFrame(rows).sort_values(["team", "date"]).reset_index(drop=True) if rows else pd.DataFrame()


class FootballDataCoUk:
    """Risultati, quote, corner, cartellini, falli, primo tempo e arbitro (solo Premier)."""

    SEASON_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
    FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"

    def __init__(self, cache: SourceCache) -> None:
        self.cache = cache

    def season(self, league: str, start: int, max_age: timedelta) -> SourceFrame:
        code = footballdata_season_code(start)
        result = self.cache.get(self.SEASON_URL.format(season=code, league=league),
                                source="football-data.co.uk", max_age=max_age)
        warnings = [result.warning] if result.warning else []
        if not result.ok:
            return SourceFrame(pd.DataFrame(), "football-data.co.uk", None, warnings)
        try:
            data = clean_frames([frame_from_csv(result.body, league, code)])
        except (ValueError, KeyError, pd.errors.ParserError) as exc:
            return SourceFrame(pd.DataFrame(), "football-data.co.uk", result.fetched_at,
                               warnings + [f"football-data.co.uk {league} {code}: CSV non leggibile ({exc})."])
        return SourceFrame(data, "football-data.co.uk", result.fetched_at, warnings)

    def recent(self, league: str, today: date, max_age: timedelta, seasons: int = 2) -> SourceFrame:
        """Stagione in corso (aggiornata con ``max_age``) più le precedenti (cache lunga)."""
        current = season_start(today)
        results = [self.season(league, current, max_age)]
        results += [self.season(league, current - offset, timedelta(days=30)) for offset in range(1, seasons)]
        return _merge(results, "football-data.co.uk")

    def fixtures(self, max_age: timedelta) -> SourceFrame:
        result = self.cache.get(self.FIXTURES_URL, source="football-data.co.uk", max_age=max_age)
        warnings = [result.warning] if result.warning else []
        if not result.ok:
            return SourceFrame(pd.DataFrame(), "football-data.co.uk", None, warnings)
        return SourceFrame(parse_fixtures(result.body), "football-data.co.uk", result.fetched_at, warnings)


def parse_fixtures(body: bytes) -> pd.DataFrame:
    raw = pd.read_csv(BytesIO(body), encoding="latin-1", low_memory=False)
    raw.columns = [re.sub(r"^(\ufeff|ï»¿)", "", str(column)) for column in raw.columns]
    columns = {
        "Div": "league", "Date": "date", "Time": "time", "HomeTeam": "home_team", "AwayTeam": "away_team",
        "Referee": "referee", "AvgH": "odds_home", "AvgD": "odds_draw", "AvgA": "odds_away",
        "Avg>2.5": "odds_over25", "Avg<2.5": "odds_under25",
    }
    frame = raw[[column for column in columns if column in raw]].rename(columns=columns)
    frame["date"] = pd.to_datetime(frame["date"], dayfirst=True, errors="coerce")
    return frame.dropna(subset=["date", "home_team", "away_team"]).reset_index(drop=True)


def football_data_org_key() -> str | None:
    """Chiave da ``st.secrets["FOOTBALL_DATA_KEY"]`` o dall'ambiente; mai nel codice."""
    try:
        import streamlit as st

        key = st.secrets.get("FOOTBALL_DATA_KEY")
        if key:
            return str(key)
    except Exception:  # nessun secrets.toml o fuori da Streamlit
        pass
    return os.environ.get("FOOTBALL_DATA_KEY") or None


class FootballDataOrg:
    """Calendario e Champions League (piano gratuito, richiede la chiave)."""

    URL = "https://api.football-data.org/v4/competitions/{code}/matches?dateFrom={start}&dateTo={end}"

    def __init__(self, cache: SourceCache, key: str | None = None) -> None:
        self.cache = cache
        self.key = key

    def matches(self, code: str, start: date, end: date, max_age: timedelta) -> SourceFrame:
        if not self.key:
            return SourceFrame(pd.DataFrame(), "football-data.org", None,
                               ["football-data.org saltata: chiave FOOTBALL_DATA_KEY non configurata."])
        result = self.cache.get(self.URL.format(code=code, start=start, end=end), source="football-data.org",
                                max_age=max_age, headers={"X-Auth-Token": self.key})
        warnings = [result.warning] if result.warning else []
        if not result.ok:
            return SourceFrame(pd.DataFrame(), "football-data.org", None, warnings)
        return SourceFrame(parse_football_data_org(result.body), "football-data.org", result.fetched_at, warnings)


def parse_football_data_org(body: bytes) -> pd.DataFrame:
    payload = json.loads(body)
    rows = [{
        "competition": match.get("competition", {}).get("name") or payload.get("competition", {}).get("name"),
        "date": pd.Timestamp(match["utcDate"]).tz_convert(None).normalize(),
        "home_team": match["homeTeam"]["name"],
        "away_team": match["awayTeam"]["name"],
        "status": match.get("status"),
        "referee": next((ref["name"] for ref in match.get("referees", []) if ref.get("type") == "REFEREE"), None),
    } for match in payload.get("matches", [])]
    return pd.DataFrame(rows)
