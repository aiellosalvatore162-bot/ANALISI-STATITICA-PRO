"""Storico Football-Data.co.uk con input pre-partita nel formato del motore.

Ogni riga contiene il risultato reale, le quote di chiusura medie e gli input
che l'utente inserirebbe nel parser (Attacco, Difesa, Elo, Forma, xG, corner,
cartellini, arbitro), calcolati SOLO con partite giocate in date precedenti.

Uso: ``python -m tools.dataset`` scarica i CSV in ``data/cache`` (ignorata da
git) e stampa un riepilogo.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from scipy.optimize import nnls


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache"
BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

LEAGUES = ("I1", "E0", "SP1", "D1")
WARMUP_SEASONS = ("1920", "2021", "2122", "2223", "2324")
CALIBRATION_SEASONS = ("2425", "2526")
HOLDOUT_SEASONS = ("2627",)
ALL_SEASONS = (*WARMUP_SEASONS, *CALIBRATION_SEASONS, *HOLDOUT_SEASONS)

# Finestra delle medie mobili e minimo di partite precedenti richieste.
WINDOW = 10
MIN_HISTORY = 5
FORM_LENGTH = 5

# Elo in stile ClubElo: K costante, moltiplicatore sullo scarto reti,
# vantaggio casa solo nell'aggiornamento (l'input del motore resta il rating).
ELO_START = 1500.0
ELO_K = 20.0
ELO_HFA = 65.0

_COLUMNS = {
    "Date": "date", "HomeTeam": "home_team", "AwayTeam": "away_team",
    "FTHG": "home_goals", "FTAG": "away_goals", "HTHG": "home_ht_goals", "HTAG": "away_ht_goals",
    "HS": "home_shots", "AS": "away_shots", "HST": "home_sot", "AST": "away_sot",
    "HF": "home_fouls", "AF": "away_fouls", "HC": "home_corners", "AC": "away_corners",
    "HY": "home_yellows", "AY": "away_yellows", "Referee": "referee",
    "HxG": "home_xg_real", "AxG": "away_xg_real",
    "AvgCH": "close_home", "AvgCD": "close_draw", "AvgCA": "close_away",
    "AvgC>2.5": "close_over25", "AvgC<2.5": "close_under25",
}


def _download(league: str, season: str, *, refresh: bool = False, timeout: float = 30.0) -> bytes | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{league}_{season}.csv"
    # La stagione in corso cambia ogni settimana: si riscarica solo se richiesto.
    if path.exists() and not refresh:
        return path.read_bytes()
    request = Request(BASE_URL.format(season=season, league=league), headers={"User-Agent": "Simulpro calibration/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"football-data.co.uk non raggiungibile ({league} {season}): {exc}") from exc
    path.write_bytes(content)
    return content


def frame_from_csv(content: bytes, league: str, season: str) -> pd.DataFrame:
    """Un CSV football-data.co.uk normalizzato nello schema del progetto."""
    raw = pd.read_csv(BytesIO(content), encoding="latin-1", low_memory=False)
    frame = raw[[column for column in _COLUMNS if column in raw]].rename(columns=_COLUMNS)
    for column in _COLUMNS.values():
        if column not in frame:
            frame[column] = np.nan
    frame["league"] = league
    frame["season"] = season
    return frame


def clean_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    data = pd.concat(frames, ignore_index=True)
    data["date"] = pd.to_datetime(data["date"], dayfirst=True, errors="coerce")
    data = data.dropna(subset=["date", "home_team", "away_team", "home_goals", "away_goals"])
    numeric = [column for column in _COLUMNS.values() if column not in {"date", "home_team", "away_team", "referee"}]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    data["home_goals"] = data["home_goals"].astype(int)
    data["away_goals"] = data["away_goals"].astype(int)
    return data.sort_values(["league", "date", "home_team"]).reset_index(drop=True)


def load_raw(leagues=LEAGUES, seasons=ALL_SEASONS, *, refresh_current: bool = False) -> pd.DataFrame:
    frames = []
    for league in leagues:
        for season in seasons:
            content = _download(league, season, refresh=refresh_current and season == seasons[-1])
            if content is not None:
                frames.append(frame_from_csv(content, league, season))
    return clean_frames(frames)


@dataclass(frozen=True)
class ShotXgModel:
    """Proxy xG lineare: gol ~ a * tiri in porta + b * tiri fuori porta."""

    on_target: float
    off_target: float

    def __call__(self, shots, shots_on_target):
        shots = np.asarray(shots, dtype=float)
        sot = np.asarray(shots_on_target, dtype=float)
        return self.on_target * sot + self.off_target * np.clip(shots - sot, 0.0, None)


def fit_shot_xg(data: pd.DataFrame) -> ShotXgModel:
    """Minimi quadrati non negativi senza intercetta, solo sulle stagioni di riscaldamento."""
    warmup = data[data["season"].isin(WARMUP_SEASONS)]
    sot = np.concatenate([warmup["home_sot"], warmup["away_sot"]])
    shots = np.concatenate([warmup["home_shots"], warmup["away_shots"]])
    goals = np.concatenate([warmup["home_goals"], warmup["away_goals"]])
    valid = np.isfinite(sot) & np.isfinite(shots)
    design = np.column_stack([sot[valid], np.clip(shots[valid] - sot[valid], 0.0, None)])
    coefficients, _ = nnls(design, goals[valid].astype(float))
    return ShotXgModel(float(coefficients[0]), float(coefficients[1]))


def _goal_multiplier(goal_difference: int) -> float:
    margin = abs(goal_difference)
    if margin <= 1:
        return 1.0
    if margin == 2:
        return 1.5
    return (11.0 + margin) / 8.0


def _form_string(results: deque) -> str:
    return "-".join(results)


def build_features(data: pd.DataFrame, xg_model: ShotXgModel | None = None) -> pd.DataFrame:
    """Input pre-partita per ogni gara, senza usare partite dello stesso giorno o successive."""
    xg_model = xg_model or fit_shot_xg(data)
    data = data.copy()
    data["home_xg"] = xg_model(data["home_shots"], data["home_sot"])
    data["away_xg"] = xg_model(data["away_shots"], data["away_sot"])
    rows = []
    for league, league_data in data.groupby("league", sort=False):
        rows.extend(_league_features(league_data))
    features = pd.DataFrame(rows)
    return features.sort_values(["date", "league", "home_team"]).reset_index(drop=True)


def _league_features(league_data: pd.DataFrame) -> list[dict]:
    history: dict[str, deque] = defaultdict(lambda: deque(maxlen=WINDOW))
    form: dict[str, deque] = defaultdict(lambda: deque(maxlen=FORM_LENGTH))
    elo: dict[str, float] = {}
    league_window: deque = deque(maxlen=WINDOW * 20)
    referee_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=WINDOW * 2))
    # L'elenco partecipanti di una stagione è noto prima del via: non è un dato futuro.
    season_teams = {
        season: set(group["home_team"]) | set(group["away_team"])
        for season, group in league_data.groupby("season", sort=False)
    }
    previous_teams: set[str] = set()
    current_season = None
    rows: list[dict] = []

    for _, day in league_data.groupby("date", sort=True):
        season = day["season"].iloc[0]
        if season != current_season:
            # Le neopromosse partono dalla media Elo delle retrocesse della stagione prima.
            leaving = previous_teams - season_teams[season]
            entry_rating = float(np.mean([elo[team] for team in leaving])) if leaving else ELO_START
            for team in season_teams[season]:
                elo.setdefault(team, entry_rating)
            previous_teams = season_teams[season]
            current_season = season

        for match in day.itertuples(index=False):
            rows.append(_match_row(match, history, form, elo, league_window, referee_history))

        for match in day.itertuples(index=False):
            _update_state(match, history, form, elo, league_window, referee_history)
    return rows


def _team_mean(records: deque, key: str) -> float:
    values = [record[key] for record in records if np.isfinite(record[key])]
    return float(np.mean(values)) if values else float("nan")


def _match_row(match, history, form, elo, league_window, referee_history) -> dict:
    home_history, away_history = history[match.home_team], history[match.away_team]
    league_goals = _team_mean(league_window, "goals")
    league_yellows = _team_mean(league_window, "match_yellows")
    league_fouls = _team_mean(league_window, "match_fouls")
    referee_records = referee_history.get(match.referee) if isinstance(match.referee, str) else None
    has_referee = bool(referee_records) and len(referee_records) >= MIN_HISTORY

    def team_inputs(records: deque, team: str) -> dict:
        goals_for = _team_mean(records, "goals_for")
        goals_against = _team_mean(records, "goals_against")
        return {
            "attack": goals_for / league_goals if league_goals > 0 else float("nan"),
            "defense": league_goals / goals_against if goals_against > 0 else float("nan"),
            "elo": elo[team],
            "form": _form_string(form[team]),
            "xg_for": _team_mean(records, "xg_for"),
            "xg_against": _team_mean(records, "xg_against"),
            "corners_for": _team_mean(records, "corners_for"),
            "corners_against": _team_mean(records, "corners_against"),
            "cards_for": _team_mean(records, "yellows_for"),
            "history": len(records),
        }

    row = {
        "league": match.league, "season": match.season, "date": match.date,
        "home_team": match.home_team, "away_team": match.away_team,
        "home_goals": match.home_goals, "away_goals": match.away_goals,
        "home_ht_goals": match.home_ht_goals, "away_ht_goals": match.away_ht_goals,
        "home_corners": match.home_corners, "away_corners": match.away_corners,
        "home_yellows": match.home_yellows, "away_yellows": match.away_yellows,
        "close_home": match.close_home, "close_draw": match.close_draw, "close_away": match.close_away,
        "close_over25": match.close_over25, "close_under25": match.close_under25,
        "home_xg_real": match.home_xg_real, "away_xg_real": match.away_xg_real,
        "home_xg_proxy": match.home_xg, "away_xg_proxy": match.away_xg,
        "league_goals_per_team": league_goals,
        "referee_yellow_avg": _team_mean(referee_records, "match_yellows") if has_referee else league_yellows,
        "referee_fouls_avg": _team_mean(referee_records, "match_fouls") if has_referee else league_fouls,
        "referee_source": "arbitro" if has_referee else "media_lega",
    }
    for prefix, records, team in (("home", home_history, match.home_team), ("away", away_history, match.away_team)):
        for key, value in team_inputs(records, team).items():
            row[f"{prefix}_{key}"] = value
    return row


def _update_state(match, history, form, elo, league_window, referee_history) -> None:
    match_yellows = match.home_yellows + match.away_yellows
    match_fouls = match.home_fouls + match.away_fouls
    for team, scored, conceded, xg_for, xg_against, corners_for, corners_against, yellows in (
        (match.home_team, match.home_goals, match.away_goals, match.home_xg, match.away_xg,
         match.home_corners, match.away_corners, match.home_yellows),
        (match.away_team, match.away_goals, match.home_goals, match.away_xg, match.home_xg,
         match.away_corners, match.home_corners, match.away_yellows),
    ):
        history[team].append({
            "goals_for": scored, "goals_against": conceded, "xg_for": xg_for, "xg_against": xg_against,
            "corners_for": corners_for, "corners_against": corners_against, "yellows_for": yellows,
        })
        form[team].append("W" if scored > conceded else "D" if scored == conceded else "L")
        league_window.append({"goals": scored, "match_yellows": match_yellows, "match_fouls": match_fouls})
    if isinstance(match.referee, str):
        referee_history[match.referee].append({"match_yellows": match_yellows, "match_fouls": match_fouls})

    expected_home = 1.0 / (1.0 + 10.0 ** (-(elo[match.home_team] - elo[match.away_team] + ELO_HFA) / 400.0))
    actual_home = 1.0 if match.home_goals > match.away_goals else 0.5 if match.home_goals == match.away_goals else 0.0
    change = ELO_K * _goal_multiplier(match.home_goals - match.away_goals) * (actual_home - expected_home)
    elo[match.home_team] += change
    elo[match.away_team] -= change


def usable(features: pd.DataFrame) -> pd.Series:
    """Partite con storico sufficiente per entrambe le squadre e input completi."""
    required = [
        f"{side}_{key}" for side in ("home", "away")
        for key in ("attack", "defense", "xg_for", "xg_against", "corners_for", "corners_against", "cards_for")
    ]
    enough = (features["home_history"] >= MIN_HISTORY) & (features["away_history"] >= MIN_HISTORY)
    return enough & features[required].notna().all(axis=1) & np.isfinite(features[required]).all(axis=1)


def load_features(*, refresh_current: bool = False) -> pd.DataFrame:
    return build_features(load_raw(refresh_current=refresh_current))


if __name__ == "__main__":
    raw = load_raw(refresh_current=True)
    xg_model = fit_shot_xg(raw)
    features = build_features(raw, xg_model)
    mask = usable(features)
    print(f"Partite scaricate: {len(raw)}; utilizzabili: {int(mask.sum())}")
    print(f"Proxy xG: {xg_model}")
    print(features[mask].groupby("season").size().to_string())


def match_elos(raw: pd.DataFrame) -> pd.DataFrame:
    """Elo pre-partita di casa e ospite per ogni gara (stessa procedura di ``elo_table``), indice di ``raw``."""
    elo: dict[str, float] = {}
    previous: set[str] = set()
    result = pd.DataFrame(index=raw.index, columns=["home_elo", "away_elo"], dtype=float)
    for league, league_data in raw.groupby("league", sort=False):
        elo, previous = {}, set()
        for season, matches in league_data.sort_values("date").groupby("season", sort=False):
            teams = set(matches["home_team"]) | set(matches["away_team"])
            leaving = previous - teams
            entry = float(np.mean([elo[team] for team in leaving])) if leaving else ELO_START
            for team in teams:
                elo.setdefault(team, entry)
            previous = teams
            for index, match in zip(matches.index, matches.itertuples(index=False)):
                result.loc[index] = (elo[match.home_team], elo[match.away_team])
                expected = 1.0 / (1.0 + 10.0 ** (-(elo[match.home_team] - elo[match.away_team] + ELO_HFA) / 400.0))
                actual = 1.0 if match.home_goals > match.away_goals else 0.5 if match.home_goals == match.away_goals else 0.0
                change = ELO_K * _goal_multiplier(match.home_goals - match.away_goals) * (actual - expected)
                elo[match.home_team] += change
                elo[match.away_team] -= change
    return result


def elo_table(raw: pd.DataFrame, before: pd.Timestamp | None = None) -> dict[str, tuple[float, pd.Timestamp]]:
    """Elo stile ClubElo calcolato dai risultati di un campionato (ripiego se ClubElo non risponde).

    Stessa procedura della taratura: partenza 1500, neopromosse alla media delle
    retrocesse. La scala è vicina a quella di ClubElo solo con più stagioni.
    """
    data = raw if before is None else raw[raw["date"] < before]
    elo: dict[str, float] = {}
    last: dict[str, pd.Timestamp] = {}
    previous: set[str] = set()
    for season, matches in data.sort_values("date").groupby("season", sort=False):
        teams = set(matches["home_team"]) | set(matches["away_team"])
        leaving = previous - teams
        entry = float(np.mean([elo[team] for team in leaving])) if leaving else ELO_START
        for team in teams:
            elo.setdefault(team, entry)
        previous = teams
        for match in matches.itertuples(index=False):
            expected = 1.0 / (1.0 + 10.0 ** (-(elo[match.home_team] - elo[match.away_team] + ELO_HFA) / 400.0))
            actual = 1.0 if match.home_goals > match.away_goals else 0.5 if match.home_goals == match.away_goals else 0.0
            change = ELO_K * _goal_multiplier(match.home_goals - match.away_goals) * (actual - expected)
            elo[match.home_team] += change
            elo[match.away_team] -= change
            last[match.home_team] = last[match.away_team] = match.date
    return {team: (rating, last[team]) for team, rating in elo.items() if team in last}
