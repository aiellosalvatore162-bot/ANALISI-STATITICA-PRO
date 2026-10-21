"""Offline, chronological evaluation of a fitted Dixon-Coles model.

The manual single-match simulator remains independent from this module. The
loader accepts local Football-Data.co.uk CSVs; an optional caller can fetch the
same public CSVs without credentials or a paid API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import math
import re
from typing import Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.special import gammaln
from scipy.stats import poisson


class HistoricalDataError(ValueError):
    """Raised when a historical CSV cannot support a valid backtest."""


PUBLIC_LEAGUES = {
    "E0": "Inghilterra · Premier League",
    "E1": "Inghilterra · Championship",
    "SC0": "Scozia · Premiership",
    "D1": "Germania · Bundesliga",
    "I1": "Italia · Serie A",
    "SP1": "Spagna · La Liga",
    "F1": "Francia · Ligue 1",
    "N1": "Paesi Bassi · Eredivisie",
    "B1": "Belgio · First Division A",
    "P1": "Portogallo · Primeira Liga",
    "T1": "Turchia · Super Lig",
    "G1": "Grecia · Super League",
}


_ALIASES = {
    "date": ("date", "matchdate", "kickoff"),
    "season": ("season", "campaign"),
    "league": ("league", "div", "competition"),
    "home_team": ("hometeam", "home_team"),
    "away_team": ("awayteam", "away_team"),
    "home_goals": ("fthg", "homegoals", "home_goals"),
    "away_goals": ("ftag", "awaygoals", "away_goals"),
    "odds_home": ("b365h", "psh", "oddshome", "odds_home"),
    "odds_draw": ("b365d", "psd", "oddsdraw", "odds_draw"),
    "odds_away": ("b365a", "psa", "oddsaway", "odds_away"),
    "home_corners": ("hc", "homecorners", "home_corners"),
    "away_corners": ("ac", "awaycorners", "away_corners"),
    "home_yellows": ("hy", "homeyellows", "home_yellows"),
    "away_yellows": ("ay", "awayyellows", "away_yellows"),
}


def _column_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _season_from_filename(filename: str) -> str | None:
    match = re.search(r"(?<!\d)((?:19|20)\d{2})[-_](\d{2}|(?:19|20)\d{2})(?!\d)", filename)
    if match:
        start, end = match.groups()
        return f"{start}-{end[-2:]}"
    single_year = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", filename)
    if single_year:
        start = int(single_year.group(1))
        return f"{start}-{(start + 1) % 100:02d}"
    return None


def _league_from_filename(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    prefix = re.split(r"[_-]?(?:19|20)\d{2}", stem, maxsplit=1)[0]
    return prefix.strip("_- ") or "league"


def normalize_match_frame(frame: pd.DataFrame, *, filename: str = "") -> pd.DataFrame:
    """Convert canonical or Football-Data.co.uk columns into one schema."""
    keys = {_column_key(column): column for column in frame.columns}
    selected: dict[str, object] = {}
    for target, aliases in _ALIASES.items():
        source = next((keys[_column_key(alias)] for alias in aliases if _column_key(alias) in keys), None)
        if source is not None:
            selected[target] = frame[source]

    required = ("date", "home_team", "away_team", "home_goals", "away_goals")
    missing = [column for column in required if column not in selected]
    season = selected.get("season")
    if season is None:
        parsed_season = _season_from_filename(filename)
        if parsed_season is None:
            missing.append("season (colonna o anno nel nome del file)")
    if missing:
        raise HistoricalDataError(f"Colonne mancanti: {', '.join(missing)}")

    result = pd.DataFrame({key: value for key, value in selected.items()})
    if "season" not in result:
        result["season"] = _season_from_filename(filename)
    if "league" not in result:
        result["league"] = _league_from_filename(filename)
    result["date"] = pd.to_datetime(result["date"], dayfirst=True, errors="coerce", utc=True).dt.tz_localize(None)
    result["season"] = result["season"].astype("string").str.strip()
    result["league"] = result["league"].astype("string").str.strip().fillna("league")
    for column in ("home_team", "away_team"):
        result[column] = result[column].astype("string").str.strip()
    for column in (
        "home_goals", "away_goals", "odds_home", "odds_draw", "odds_away",
        "home_corners", "away_corners", "home_yellows", "away_yellows",
    ):
        if column not in result:
            result[column] = np.nan
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result = result.dropna(subset=[*required, "season", "league"])
    if result.empty:
        raise HistoricalDataError("Il file non contiene partite complete con data, squadre e risultato finale.")
    if (result[["home_goals", "away_goals"]] < 0).any().any():
        raise HistoricalDataError("I gol non possono essere negativi.")
    result["home_goals"] = result["home_goals"].astype(int)
    result["away_goals"] = result["away_goals"].astype(int)
    result = result.drop_duplicates(subset=["league", "season", "date", "home_team", "away_team"])
    return result.sort_values(["league", "date", "home_team", "away_team"]).reset_index(drop=True)


def load_football_data_uploads(files: Iterable[object]) -> pd.DataFrame:
    """Load multiple uploaded CSVs; season can be a column or in each filename."""
    frames = []
    for uploaded in files:
        filename = getattr(uploaded, "name", "matches.csv")
        content = uploaded.getvalue() if hasattr(uploaded, "getvalue") else uploaded
        try:
            raw = pd.read_csv(BytesIO(content), encoding="latin-1", low_memory=False)
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            raise HistoricalDataError(f"Impossibile leggere {filename}: {exc}") from exc
        frames.append(normalize_match_frame(raw, filename=filename))
    if not frames:
        raise HistoricalDataError("Seleziona almeno un CSV storico.")
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["league", "season", "date", "home_team", "away_team"])
    return combined.sort_values(["league", "date"]).reset_index(drop=True)


def fetch_public_history(
    league_code: str,
    seasons: int = 7,
    *,
    as_of: date | None = None,
    timeout: float = 12.0,
) -> pd.DataFrame:
    """Fetch free public season CSVs; no credentials, API key, or paid endpoint."""
    if league_code not in PUBLIC_LEAGUES:
        raise HistoricalDataError(f"Codice campionato non supportato: {league_code}")
    if not 3 <= int(seasons) <= 12:
        raise HistoricalDataError("Seleziona tra 3 e 12 stagioni storiche.")
    today = as_of or date.today()
    current_start = today.year if today.month >= 7 else today.year - 1
    first_start = current_start - int(seasons) + 1
    frames = []
    for start_year in range(first_start, current_start + 1):
        end_year = start_year + 1
        season_code = f"{start_year % 100:02d}{end_year % 100:02d}"
        filename = f"{league_code}_{start_year}-{end_year % 100:02d}.csv"
        url = f"https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv"
        request = Request(url, headers={"User-Agent": "Simulpro historical backtest/1.0"})
        try:
            with urlopen(request, timeout=timeout) as response:
                raw_bytes = response.read()
        except HTTPError as exc:
            if exc.code == 404:
                continue
            raise HistoricalDataError(f"Fonte storica ha risposto HTTP {exc.code} per la stagione {season_code}.") from exc
        except (URLError, TimeoutError) as exc:
            raise HistoricalDataError(f"Fonte storica non raggiungibile ({season_code}): {exc}") from exc
        try:
            raw = pd.read_csv(BytesIO(raw_bytes), encoding="latin-1", low_memory=False)
            frames.append(normalize_match_frame(raw, filename=filename))
        except (pd.errors.ParserError, UnicodeDecodeError, HistoricalDataError) as exc:
            raise HistoricalDataError(f"CSV storico non valido ({season_code}): {exc}") from exc
    if not frames:
        raise HistoricalDataError("La fonte non ha restituito stagioni con risultati disponibili per questo campionato.")
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["league", "season", "date", "home_team", "away_team"])
    return combined.sort_values(["league", "date"]).reset_index(drop=True)


def resolve_team_name(requested: str, available: Iterable[str]) -> str | None:
    """Resolve an exact or close public-data team name without guessing among ties."""
    from difflib import get_close_matches

    teams = sorted({str(team) for team in available if pd.notna(team)})
    normalized = re.sub(r"[^a-z0-9]", "", requested.casefold())
    exact = [team for team in teams if re.sub(r"[^a-z0-9]", "", team.casefold()) == normalized]
    if len(exact) == 1:
        return exact[0]
    aliases = {"fc", "afc", "cf", "ac", "calcio", "footballclub"}

    def compact(value: str) -> str:
        parts = re.sub(r"[^a-z0-9 ]", " ", value.casefold()).split()
        return "".join(part for part in parts if part not in aliases)

    requested_key = compact(requested)
    alias_matches = [team for team in teams if compact(team) == requested_key]
    if len(alias_matches) == 1:
        return alias_matches[0]
    candidates = get_close_matches(requested_key, [compact(team) for team in teams], n=2, cutoff=0.82)
    if len(candidates) == 1:
        matching = [team for team in teams if compact(team) == candidates[0]]
        return matching[0] if len(matching) == 1 else None
    return None


def identify_public_leagues(
    home_name: str,
    away_name: str,
    league_teams: Mapping[str, Iterable[str]],
) -> list[dict[str, str]]:
    """Return leagues where both pasted team names resolve uniquely."""
    matches = []
    for code, teams in league_teams.items():
        home = resolve_team_name(home_name, teams)
        away = resolve_team_name(away_name, teams)
        if home and away and home != away:
            matches.append({
                "code": code,
                "league": PUBLIC_LEAGUES.get(code, code),
                "home_team": home,
                "away_team": away,
            })
    return matches


def _fetch_latest_team_catalog(league_code: str, *, as_of: date | None = None, timeout: float = 4.0) -> list[str]:
    """Fetch only the newest available public season needed to identify teams."""
    today = as_of or date.today()
    current_start = today.year if today.month >= 7 else today.year - 1
    for start_year in range(current_start, current_start - 4, -1):
        end_year = start_year + 1
        season_code = f"{start_year % 100:02d}{end_year % 100:02d}"
        filename = f"{league_code}_{start_year}-{end_year % 100:02d}.csv"
        url = f"https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv"
        request = Request(url, headers={"User-Agent": "Simulpro historical team lookup/1.0"})
        try:
            with urlopen(request, timeout=timeout) as response:
                content = response.read()
        except HTTPError as exc:
            if exc.code == 404:
                continue
            raise HistoricalDataError(f"HTTP {exc.code} cercando le squadre di {league_code}.") from exc
        except (URLError, TimeoutError) as exc:
            raise HistoricalDataError(f"Fonte non raggiungibile cercando {league_code}: {exc}") from exc
        try:
            raw = pd.read_csv(BytesIO(content), encoding="latin-1", low_memory=False)
            normalized = normalize_match_frame(raw, filename=filename)
        except (pd.errors.ParserError, UnicodeDecodeError, HistoricalDataError) as exc:
            raise HistoricalDataError(f"Catalogo squadre non valido per {league_code}: {exc}") from exc
        teams = sorted(set(normalized.home_team.dropna()) | set(normalized.away_team.dropna()))
        if teams:
            return teams
    return []


def fetch_public_match_history(
    home_name: str,
    away_name: str,
    *,
    seasons: int = 7,
    as_of: date | None = None,
    timeout: float = 4.0,
) -> dict:
    """Automatically resolve pasted team names, then fetch one league's history.

    Failures and ambiguous league matches are returned as manual-only status;
    they never prevent the caller from running the pasted-data model.
    """
    def fetch_catalog(code: str) -> tuple[str, list[str]]:
        try:
            return code, _fetch_latest_team_catalog(code, as_of=as_of, timeout=timeout)
        except HistoricalDataError:
            return code, []

    with ThreadPoolExecutor(max_workers=min(8, len(PUBLIC_LEAGUES))) as executor:
        catalogs = dict(executor.map(fetch_catalog, PUBLIC_LEAGUES))
    league_matches = identify_public_leagues(home_name, away_name, catalogs)
    if not league_matches:
        return {
            "status": "manual_only",
            "reason": "Non ho trovato entrambe le squadre nella stessa lega pubblica supportata.",
        }
    if len(league_matches) > 1:
        return {
            "status": "manual_only",
            "reason": "I nomi corrispondono a più leghe: per evitare un abbinamento errato uso i soli dati manuali.",
            "candidates": [match["league"] for match in league_matches],
        }
    selected = league_matches[0]
    try:
        history = fetch_public_history(selected["code"], seasons=seasons, as_of=as_of, timeout=timeout)
    except HistoricalDataError as exc:
        return {"status": "manual_only", "reason": str(exc)}
    return {"status": "ready", **selected, "history": history}


def _season_start(season: object) -> tuple[int, str]:
    match = re.search(r"(?:19|20)\d{2}", str(season))
    return (int(match.group()) if match else 0, str(season))


@dataclass
class _DixonColesFit:
    teams: list[str]
    attack: np.ndarray
    defence: np.ndarray
    home_advantage: float
    intercept: float
    rho: float

    def expected_goals(self, home_team: str, away_team: str) -> tuple[float, float]:
        index = {team: i for i, team in enumerate(self.teams)}
        home_index = index.get(home_team)
        away_index = index.get(away_team)
        home_attack = self.attack[home_index] if home_index is not None else 0.0
        home_defence = self.defence[home_index] if home_index is not None else 0.0
        away_attack = self.attack[away_index] if away_index is not None else 0.0
        away_defence = self.defence[away_index] if away_index is not None else 0.0
        home_rate = np.exp(self.intercept + self.home_advantage + home_attack - away_defence)
        away_rate = np.exp(self.intercept + away_attack - home_defence)
        return float(home_rate), float(away_rate)


def _fit_dixon_coles(matches: pd.DataFrame, half_life_days: float = 365.0) -> _DixonColesFit:
    teams = sorted(set(matches["home_team"]) | set(matches["away_team"]))
    if len(matches) < 30 or len(teams) < 2:
        raise HistoricalDataError("Servono almeno 30 partite e due squadre per addestrare il modello.")
    team_index = {team: index for index, team in enumerate(teams)}
    home = matches["home_team"].map(team_index).to_numpy()
    away = matches["away_team"].map(team_index).to_numpy()
    home_goals = matches["home_goals"].to_numpy(dtype=float)
    away_goals = matches["away_goals"].to_numpy(dtype=float)
    age = (matches["date"].max() - matches["date"]).dt.days.to_numpy(dtype=float)
    weights = np.exp(-math.log(2.0) * age / half_life_days)
    count = len(teams)
    average_goals = max(float(np.mean((home_goals + away_goals) / 2.0)), 0.2)

    def unpack(parameters):
        return (
            parameters[:count], parameters[count:2 * count],
            parameters[-3], parameters[-2], parameters[-1],
        )

    def objective(parameters):
        attack, defence, home_advantage, intercept, rho = unpack(parameters)
        log_home = np.clip(intercept + home_advantage + attack[home] - defence[away], -3.0, 2.5)
        log_away = np.clip(intercept + attack[away] - defence[home], -3.0, 2.5)
        home_rate, away_rate = np.exp(log_home), np.exp(log_away)
        tau = np.ones(len(matches), dtype=float)
        score00 = (home_goals == 0) & (away_goals == 0)
        score01 = (home_goals == 0) & (away_goals == 1)
        score10 = (home_goals == 1) & (away_goals == 0)
        score11 = (home_goals == 1) & (away_goals == 1)
        tau[score00] = 1.0 - home_rate[score00] * away_rate[score00] * rho
        tau[score01] = 1.0 + home_rate[score01] * rho
        tau[score10] = 1.0 + away_rate[score10] * rho
        tau[score11] = 1.0 - rho
        tau = np.clip(tau, 1e-9, None)
        log_likelihood = (
            home_goals * log_home - home_rate - gammaln(home_goals + 1.0)
            + away_goals * log_away - away_rate - gammaln(away_goals + 1.0)
            + np.log(tau)
        )
        regularization = 0.02 * (np.mean(attack ** 2) + np.mean(defence ** 2))
        centering = 2.0 * (attack.mean() ** 2 + defence.mean() ** 2)
        return -float(np.average(log_likelihood, weights=weights)) + regularization + centering

    initial = np.zeros(2 * count + 3)
    initial[-2] = np.log(average_goals)
    initial[-3] = 0.15
    initial[-1] = -0.05
    bounds = [(-2.5, 2.5)] * (2 * count) + [(-0.8, 0.8), (-1.0, 1.0), (-0.2, 0.2)]
    fitted = minimize(objective, initial, method="L-BFGS-B", bounds=bounds, options={"maxiter": 350})
    if not np.isfinite(fitted.fun):
        raise HistoricalDataError("L’addestramento Dixon-Coles non ha trovato parametri finiti.")
    attack, defence, home_advantage, intercept, rho = unpack(fitted.x)
    return _DixonColesFit(
        teams, attack - attack.mean(), defence - defence.mean(),
        float(home_advantage), float(intercept), float(rho),
    )


def _score_matrix(home_rate: float, away_rate: float, rho: float, max_goals: int = 10) -> np.ndarray:
    goals = np.arange(max_goals + 1)
    matrix = np.outer(poisson.pmf(goals, home_rate), poisson.pmf(goals, away_rate))
    matrix[0, 0] *= max(1e-9, 1.0 - home_rate * away_rate * rho)
    matrix[0, 1] *= max(1e-9, 1.0 + home_rate * rho)
    matrix[1, 0] *= max(1e-9, 1.0 + away_rate * rho)
    matrix[1, 1] *= max(1e-9, 1.0 - rho)
    return matrix / matrix.sum()


def _match_probabilities(model: _DixonColesFit, matches: pd.DataFrame) -> np.ndarray:
    probabilities = []
    for row in matches.itertuples(index=False):
        home_rate, away_rate = model.expected_goals(row.home_team, row.away_team)
        matrix = _score_matrix(home_rate, away_rate, model.rho)
        probabilities.append([np.tril(matrix, -1).sum(), np.trace(matrix), np.triu(matrix, 1).sum()])
    return np.asarray(probabilities, dtype=float)


def _temperature_scale(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    logits = np.log(np.clip(probabilities, 1e-12, 1.0)) / temperature
    logits -= logits.max(axis=1, keepdims=True)
    scaled = np.exp(logits)
    return scaled / scaled.sum(axis=1, keepdims=True)


def _fit_temperature(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    if len(outcomes) < 20 or len(np.unique(outcomes)) < 2:
        return 1.0

    def loss(log_temperature):
        scaled = _temperature_scale(probabilities, float(np.exp(log_temperature)))
        return float(-np.log(np.clip(scaled[np.arange(len(outcomes)), outcomes], 1e-12, 1.0)).mean())

    fitted = minimize_scalar(loss, bounds=(-1.4, 1.4), method="bounded")
    return float(np.exp(fitted.x))


def _metrics(probabilities: np.ndarray, outcomes: np.ndarray) -> dict[str, float]:
    clipped = np.clip(probabilities, 1e-12, 1.0)
    one_hot = np.eye(3)[outcomes]
    log_loss = -np.log(clipped[np.arange(len(outcomes)), outcomes]).mean()
    brier = np.square(clipped - one_hot).sum(axis=1).mean()
    rps = np.square(np.cumsum(clipped, axis=1)[:, :2] - np.cumsum(one_hot, axis=1)[:, :2]).mean()
    confidence_bins = np.minimum((clipped * 10).astype(int), 9)
    ece = 0.0
    for outcome in range(3):
        for bin_index in range(10):
            selected = confidence_bins[:, outcome] == bin_index
            if selected.any():
                ece += selected.mean() * abs(clipped[selected, outcome].mean() - one_hot[selected, outcome].mean()) / 3.0
    return {
        "log_loss": float(log_loss), "brier": float(brier),
        "rps": float(rps), "ece": float(ece),
    }


def _paired_day_bootstrap(model_probabilities, market_probabilities, outcomes, dates, rounds=1000, seed=7):
    model_losses = -np.log(np.clip(model_probabilities[np.arange(len(outcomes)), outcomes], 1e-12, 1.0))
    market_losses = -np.log(np.clip(market_probabilities[np.arange(len(outcomes)), outcomes], 1e-12, 1.0))
    differences = model_losses - market_losses
    blocks = np.asarray(dates).astype(str)
    groups = [np.flatnonzero(blocks == block) for block in np.unique(blocks)]
    if not groups:
        return {"mean_log_loss_delta": float("nan"), "ci95_low": float("nan"), "ci95_high": float("nan")}
    rng = np.random.default_rng(seed)
    boot_means = np.empty(rounds)
    for index in range(rounds):
        chosen = rng.integers(0, len(groups), len(groups))
        sample = np.concatenate([groups[group_index] for group_index in chosen])
        boot_means[index] = differences[sample].mean()
    return {
        "mean_log_loss_delta": float(differences.mean()),
        "ci95_low": float(np.quantile(boot_means, 0.025)),
        "ci95_high": float(np.quantile(boot_means, 0.975)),
    }


def _recent_team_auxiliary(matches: pd.DataFrame, team: str, window: int = 10) -> dict[str, float | int]:
    """Recent pro/conceded corners and yellows, using only the supplied past rows."""
    home_rows = matches[matches.home_team == team]
    away_rows = matches[matches.away_team == team]
    home_view = pd.DataFrame({
        "date": home_rows.date,
        "corners_for": home_rows.home_corners,
        "corners_against": home_rows.away_corners,
        "yellows_for": home_rows.home_yellows,
    })
    away_view = pd.DataFrame({
        "date": away_rows.date,
        "corners_for": away_rows.away_corners,
        "corners_against": away_rows.home_corners,
        "yellows_for": away_rows.away_yellows,
    })
    recent = pd.concat([home_view, away_view], ignore_index=True).sort_values("date").tail(window)
    return {
        "matches": int(len(recent)),
        "corners_for": float(recent.corners_for.mean()),
        "corners_against": float(recent.corners_against.mean()),
        "yellows_for": float(recent.yellows_for.mean()),
    }


def _weighted_optional(historical: float, manual: float, manual_weight: float) -> float | None:
    has_historical = np.isfinite(historical)
    has_manual = np.isfinite(manual)
    if has_historical and has_manual:
        return float((1.0 - manual_weight) * historical + manual_weight * manual)
    if has_historical:
        return float(historical)
    if has_manual:
        return float(manual)
    return None


def _de_vig_market(matches: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    odds = matches[["odds_home", "odds_draw", "odds_away"]].to_numpy(dtype=float)
    valid = np.isfinite(odds).all(axis=1) & (odds > 1.0).all(axis=1)
    probabilities = np.full_like(odds, np.nan, dtype=float)
    implied = 1.0 / odds[valid]
    probabilities[valid] = implied / implied.sum(axis=1, keepdims=True)
    return probabilities, valid


def run_walk_forward(matches: pd.DataFrame, *, bootstrap_rounds: int = 1000) -> dict:
    """Use prior seasons for fitting, one season for calibration, next for test."""
    all_predictions = []
    skipped = []
    for league, league_matches in matches.groupby("league", dropna=True):
        seasons = sorted(league_matches["season"].unique(), key=_season_start)
        if len(seasons) < 3:
            skipped.append(f"{league}: servono almeno 3 stagioni, trovate {len(seasons)}")
            continue
        for test_index in range(2, len(seasons)):
            train_seasons = seasons[:test_index - 1]
            validation_season = seasons[test_index - 1]
            test_season = seasons[test_index]
            train = league_matches[league_matches.season.isin(train_seasons)]
            validation = league_matches[league_matches.season == validation_season]
            test = league_matches[league_matches.season == test_season]
            if len(train) < 30 or validation.empty or test.empty:
                skipped.append(f"{league}/{test_season}: dati insufficienti nel train/validation/test")
                continue
            try:
                model = _fit_dixon_coles(train)
                validation_probabilities = _match_probabilities(model, validation)
                validation_outcomes = np.where(
                    validation.home_goals > validation.away_goals,
                    0,
                    np.where(validation.home_goals == validation.away_goals, 1, 2),
                )
                temperature = _fit_temperature(validation_probabilities, validation_outcomes)
                test_probabilities = _match_probabilities(model, test)
            except (HistoricalDataError, ValueError, FloatingPointError) as exc:
                skipped.append(f"{league}/{test_season}: {exc}")
                continue
            outcomes = np.where(
                test.home_goals > test.away_goals,
                0,
                np.where(test.home_goals == test.away_goals, 1, 2),
            )
            calibrated = _temperature_scale(test_probabilities, temperature)
            fold = test[["league", "season", "date", "home_team", "away_team", "home_goals", "away_goals"]].copy()
            fold["train_through_season"] = train_seasons[-1]
            fold["validation_season"] = validation_season
            fold["outcome"] = outcomes
            for column, index in (("p_home", 0), ("p_draw", 1), ("p_away", 2)):
                fold[column] = calibrated[:, index]
                fold[f"raw_{column}"] = test_probabilities[:, index]
            fold["temperature"] = temperature
            market_probabilities, market_valid = _de_vig_market(test)
            fold["market_valid"] = market_valid
            for column, index in (("market_home", 0), ("market_draw", 1), ("market_away", 2)):
                fold[column] = market_probabilities[:, index]
            fold["home_corners"] = test.home_corners.to_numpy()
            fold["away_corners"] = test.away_corners.to_numpy()
            fold["home_yellows"] = test.home_yellows.to_numpy()
            fold["away_yellows"] = test.away_yellows.to_numpy()
            for suffix, home_column, away_column in (
                ("corners", "home_corners", "away_corners"),
                ("yellows", "home_yellows", "away_yellows"),
            ):
                training_totals = train[home_column] + train[away_column]
                fold[f"training_mean_{suffix}"] = float(training_totals.mean())
            all_predictions.append(fold)

    if not all_predictions:
        details = "; ".join(skipped[:5])
        raise HistoricalDataError(
            "Nessun fold out-of-sample valido. Servono almeno tre stagioni complete per lega. "
            f"Dettagli: {details or 'nessuna lega utilizzabile'}"
        )
    predictions = pd.concat(all_predictions, ignore_index=True)
    outcomes = predictions.outcome.to_numpy(dtype=int)
    calibrated = predictions[["p_home", "p_draw", "p_away"]].to_numpy()
    raw = predictions[["raw_p_home", "raw_p_draw", "raw_p_away"]].to_numpy()
    uniform = np.full_like(calibrated, 1.0 / 3.0)
    metric_rows = []
    for name, probabilities in (("Dixon-Coles calibrato", calibrated), ("Dixon-Coles grezzo", raw), ("Uniforme", uniform)):
        metric_rows.append({"Modello": name, "N": len(outcomes), **_metrics(probabilities, outcomes)})

    market_valid = predictions.market_valid.to_numpy(dtype=bool)
    comparison = None
    if market_valid.any():
        market = predictions.loc[market_valid, ["market_home", "market_draw", "market_away"]].to_numpy()
        matched_model = calibrated[market_valid]
        matched_outcomes = outcomes[market_valid]
        metric_rows.append({"Modello": "Quote bookmaker senza margine", "N": len(matched_outcomes), **_metrics(market, matched_outcomes)})
        comparison = _paired_day_bootstrap(
            matched_model, market, matched_outcomes,
            predictions.loc[market_valid, "date"].dt.strftime("%Y-%m-%d").to_numpy(),
            rounds=bootstrap_rounds,
        )

    count_rows = []
    for measure, home_column, away_column, prediction_column in (
        ("Corner totali", "home_corners", "away_corners", "training_mean_corners"),
        ("Gialli totali", "home_yellows", "away_yellows", "training_mean_yellows"),
    ):
        valid = predictions[[home_column, away_column, prediction_column]].notna().all(axis=1)
        if valid.any():
            actual = predictions.loc[valid, home_column].to_numpy() + predictions.loc[valid, away_column].to_numpy()
            expected = predictions.loc[valid, prediction_column].to_numpy()
            count_rows.append({
                "Misura": measure,
                "N": int(valid.sum()),
                "Media osservata": float(actual.mean()),
                "Media prevista da training": float(expected.mean()),
                "MAE baseline media storica": float(np.abs(actual - expected).mean()),
            })

    return {
        "metrics": pd.DataFrame(metric_rows),
        "predictions": predictions,
        "market_comparison": comparison,
        "count_baselines": pd.DataFrame(count_rows),
        "fold_count": int(predictions[["league", "season"]].drop_duplicates().shape[0]),
        "match_count": int(len(predictions)),
        "skipped": skipped,
    }


def predict_historical_match(
    matches: pd.DataFrame,
    league: str,
    home_team: str,
    away_team: str,
    kickoff_date: object,
    *,
    manual_rates: tuple[float, float] | None = None,
    manual_rho: float = -0.11,
    manual_weight: float = 0.75,
    manual_auxiliary: dict[str, float] | None = None,
) -> dict:
    """Fit on past matches and optionally blend a manual recent-input score matrix."""
    if not 0.51 <= manual_weight <= 1.0:
        raise HistoricalDataError(
            "Il peso manuale deve essere tra 0.51 e 1.0: i dati inseriti devono avere sempre la maggioranza."
        )
    cutoff = pd.Timestamp(kickoff_date)
    history = matches[(matches.league == league) & (matches.date < cutoff)].copy()
    seasons = sorted(history.season.unique(), key=_season_start)
    if len(seasons) < 3:
        raise HistoricalDataError("Per una previsione calibrata servono almeno tre stagioni complete prima della data partita.")
    if len(history) < 60:
        raise HistoricalDataError("Servono almeno 60 partite storiche prima della data selezionata.")

    calibration_temperature = 1.0
    validation_season = None
    calibration_matches = 0
    completed_seasons = []
    for candidate_season in seasons:
        start_year = _season_start(candidate_season)[0]
        season_rows = history[history.season == candidate_season]
        if start_year and season_rows.date.max() >= pd.Timestamp(start_year + 1, 5, 15):
            completed_seasons.append(candidate_season)
    for candidate_season in reversed(completed_seasons):
        candidate_validation = history[history.season == candidate_season]
        candidate_train = history[
            history.season.map(_season_start).map(lambda key: key < _season_start(candidate_season))
        ]
        candidate_outcomes = np.where(
            candidate_validation.home_goals > candidate_validation.away_goals,
            0,
            np.where(candidate_validation.home_goals == candidate_validation.away_goals, 1, 2),
        )
        if len(candidate_train) >= 30 and len(candidate_validation) >= 60 and len(np.unique(candidate_outcomes)) >= 2:
            validation_season = candidate_season
            calibration_train = candidate_train
            validation = candidate_validation
            break
    calibration_fitted = validation_season is not None
    if calibration_fitted:
        calibration_model = _fit_dixon_coles(calibration_train)
        validation_probabilities = _match_probabilities(calibration_model, validation)
        validation_outcomes = np.where(
            validation.home_goals > validation.away_goals,
            0,
            np.where(validation.home_goals == validation.away_goals, 1, 2),
        )
        calibration_temperature = _fit_temperature(validation_probabilities, validation_outcomes)
        calibration_matches = int(len(validation))

    fitted_model = _fit_dixon_coles(history)
    unseen_teams = [team for team in (home_team, away_team) if team not in fitted_model.teams]
    if unseen_teams:
        raise HistoricalDataError(
            "Squadra/e assenti nello storico: " + ", ".join(unseen_teams)
            + ". Usa la previsione 100% manuale invece di assegnare forza media di lega."
        )
    home_rate, away_rate = fitted_model.expected_goals(home_team, away_team)
    raw_matrix = _score_matrix(home_rate, away_rate, fitted_model.rho)
    home_scores, away_scores = np.indices(raw_matrix.shape)
    result_grid = np.where(home_scores > away_scores, 0, np.where(home_scores == away_scores, 1, 2))
    raw_1x2 = np.array([raw_matrix[result_grid == result].sum() for result in range(3)])
    calibrated_1x2 = _temperature_scale(raw_1x2.reshape(1, 3), calibration_temperature)[0]

    # Reweight within each 1X2 partition to preserve one joint score distribution.
    calibrated_matrix = raw_matrix.copy()
    for result in range(3):
        mask = result_grid == result
        if raw_1x2[result] > 0.0:
            calibrated_matrix[mask] *= calibrated_1x2[result] / raw_1x2[result]
    calibrated_matrix /= calibrated_matrix.sum()

    historical_matrix = calibrated_matrix.copy()
    historical_probabilities = calibrated_1x2.copy()
    manual_probabilities = None
    if manual_rates is not None:
        manual_matrix = _score_matrix(float(manual_rates[0]), float(manual_rates[1]), manual_rho)
        manual_result_grid = np.where(home_scores > away_scores, 0, np.where(home_scores == away_scores, 1, 2))
        manual_probabilities = np.array([
            manual_matrix[manual_result_grid == result].sum() for result in range(3)
        ])
        calibrated_matrix = (1.0 - manual_weight) * historical_matrix + manual_weight * manual_matrix
        calibrated_matrix /= calibrated_matrix.sum()
        calibrated_1x2 = np.array([
            calibrated_matrix[result_grid == result].sum() for result in range(3)
        ])

    favorite = int(np.argmax(calibrated_1x2))
    favorite_mask = result_grid == favorite
    favorite_scores = np.argwhere(favorite_mask)
    favorite_probabilities = calibrated_matrix[favorite_mask]
    fixed_score = favorite_scores[int(np.argmax(favorite_probabilities))]
    global_score = np.unravel_index(int(np.argmax(calibrated_matrix)), calibrated_matrix.shape)
    score_order = np.argsort(calibrated_matrix.ravel())[::-1][:5]
    top_scores = []
    for flat_index in score_order:
        home_goals, away_goals = np.unravel_index(int(flat_index), calibrated_matrix.shape)
        top_scores.append({
            "score": f"{home_goals}-{away_goals}",
            "probability_pct": float(calibrated_matrix[home_goals, away_goals] * 100.0),
        })
    home_aux = _recent_team_auxiliary(history, home_team)
    away_aux = _recent_team_auxiliary(history, away_team)
    historical_corner_mean = (
        (home_aux["corners_for"] + away_aux["corners_against"]
         + away_aux["corners_for"] + home_aux["corners_against"]) / 2.0
    )
    historical_card_mean = np.nan
    manual_corner_mean = np.nan
    manual_card_mean = np.nan
    if manual_auxiliary is not None:
        manual_corner_mean = (
            manual_auxiliary["home_corners_for"] + manual_auxiliary["away_corners_against"]
            + manual_auxiliary["away_corners_for"] + manual_auxiliary["home_corners_against"]
        ) / 2.0
        historical_card_mean = (
            home_aux["yellows_for"] + away_aux["yellows_for"]
        ) * (manual_auxiliary["referee_yellow_avg"] / 4.5) * (manual_auxiliary["referee_fouls_avg"] / 24.0)
        manual_card_mean = (
            manual_auxiliary["home_yellows_for"] + manual_auxiliary["away_yellows_for"]
        ) * (manual_auxiliary["referee_yellow_avg"] / 4.5) * (manual_auxiliary["referee_fouls_avg"] / 24.0)
    blended_corner_mean = _weighted_optional(historical_corner_mean, manual_corner_mean, manual_weight)
    blended_card_mean = _weighted_optional(historical_card_mean, manual_card_mean, manual_weight)
    return {
        "source_mode": "historical_blend",
        "league": league,
        "home_team": home_team,
        "away_team": away_team,
        "kickoff_date": cutoff,
        "data_through": history.date.max(),
        "training_matches": int(len(history)),
        "calibration_temperature": calibration_temperature,
        "calibration_season": validation_season,
        "calibration_matches": calibration_matches,
        "calibration_fitted": calibration_fitted,
        "calibration_note": (
            "Calibrata sull’ultima stagione conclusa con almeno 60 partite."
            if calibration_fitted
            else "Nessuna stagione conclusa sufficientemente ampia: temperatura neutra, probabilità non calibrate."
        ),
        "lambda_home": home_rate,
        "lambda_away": away_rate,
        "manual_lambda_home": float(manual_rates[0]) if manual_rates is not None else None,
        "manual_lambda_away": float(manual_rates[1]) if manual_rates is not None else None,
        "manual_weight_pct": float(manual_weight * 100.0) if manual_rates is not None else 0.0,
        "favorite_sign": ("1", "X", "2")[favorite],
        "probabilities_1x2_pct": {
            "1": float(calibrated_1x2[0] * 100.0),
            "X": float(calibrated_1x2[1] * 100.0),
            "2": float(calibrated_1x2[2] * 100.0),
        },
        "historical_probabilities_1x2_pct": {
            "1": float(historical_probabilities[0] * 100.0),
            "X": float(historical_probabilities[1] * 100.0),
            "2": float(historical_probabilities[2] * 100.0),
        },
        "manual_probabilities_1x2_pct": (
            {
                "1": float(manual_probabilities[0] * 100.0),
                "X": float(manual_probabilities[1] * 100.0),
                "2": float(manual_probabilities[2] * 100.0),
            }
            if manual_probabilities is not None
            else None
        ),
        "fixed_score": {
            "score": f"{fixed_score[0]}-{fixed_score[1]}",
            "unconditional_probability_pct": float(calibrated_matrix[tuple(fixed_score)] * 100.0),
            "conditional_probability_pct": float(calibrated_matrix[tuple(fixed_score)] / calibrated_1x2[favorite] * 100.0),
        },
        "most_likely_exact_score": f"{global_score[0]}-{global_score[1]}",
        "top_scorelines": top_scores,
        "over_2_5_pct": float(calibrated_matrix[home_scores + away_scores > 2.5].sum() * 100.0),
        "goal_pct": float(calibrated_matrix[(home_scores > 0) & (away_scores > 0)].sum() * 100.0),
        "count_predictions": {
            "corner_mean_historical": float(historical_corner_mean),
            "corner_mean_manual": float(manual_corner_mean) if np.isfinite(manual_corner_mean) else None,
            "corner_mean_blended": blended_corner_mean,
            "corner_over_8_5_pct": float(poisson.sf(8, blended_corner_mean) * 100.0) if blended_corner_mean is not None else None,
            "yellow_mean_historical": float(historical_card_mean) if np.isfinite(historical_card_mean) else None,
            "yellow_mean_manual": float(manual_card_mean) if np.isfinite(manual_card_mean) else None,
            "yellow_mean_blended": blended_card_mean,
            "yellow_over_4_5_pct": float(poisson.sf(4, blended_card_mean) * 100.0) if blended_card_mean is not None else None,
            "home_matches_used": home_aux["matches"],
            "away_matches_used": away_aux["matches"],
        },
        "unseen_teams": unseen_teams,
    }


def predict_manual_only(match_input, *, simulations: int = 100_000, seed: int = 42, reason: str = "") -> dict:
    """Return a candidate-compatible prediction from the existing manual engine only."""
    from engine import config_from_input, simulate_match

    result = simulate_match(config_from_input(match_input, simulations=simulations, seed=seed))
    summary = result["summary"]
    probabilities = {
        key: float(result["markets"]["1x2"][key]["percentage"])
        for key in ("1", "X", "2")
    }
    modal_score = summary["modal_score"]
    score_distribution = result["dashboard"]["exact_score_distribution"]
    score_labels = score_distribution["labels"]
    score_rows = [
        {
            "score": f"{home}-{away}",
            "probability_pct": score_distribution["probabilities_pct"][home_index][away_index],
        }
        for home_index, home in enumerate(score_labels)
        for away_index, away in enumerate(score_labels)
    ]
    top_scorelines = sorted(score_rows, key=lambda row: row["probability_pct"], reverse=True)[:5]
    count_markets = result["markets"]
    return {
        "source_mode": "manual_only",
        "league": None,
        "home_team": match_input.home.name,
        "away_team": match_input.away.name,
        "kickoff_date": None,
        "data_through": None,
        "training_matches": 0,
        "calibration_temperature": 1.0,
        "calibration_season": None,
        "calibration_matches": 0,
        "calibration_fitted": False,
        "calibration_note": "Storico non disponibile: previsione al 100% dai dati manuali.",
        "fallback_reason": reason,
        "lambda_home": float(result["model"]["lambda"]),
        "lambda_away": float(result["model"]["mu"]),
        "manual_lambda_home": float(result["model"]["lambda"]),
        "manual_lambda_away": float(result["model"]["mu"]),
        "manual_weight_pct": 100.0,
        "favorite_sign": summary["favorite_sign"],
        "probabilities_1x2_pct": probabilities,
        "historical_probabilities_1x2_pct": None,
        "manual_probabilities_1x2_pct": probabilities,
        "fixed_score": {
            "score": f'{modal_score["home"]}-{modal_score["away"]}',
            "unconditional_probability_pct": modal_score["share_pct"],
            "conditional_probability_pct": modal_score["conditional_share_pct"],
        },
        "most_likely_exact_score": f'{summary["most_likely_exact_score"]["home"]}-{summary["most_likely_exact_score"]["away"]}',
        "top_scorelines": top_scorelines,
        "over_2_5_pct": float(count_markets["over_under"]["Over_2.5"]["percentage"]),
        "goal_pct": float(count_markets["goal_no_goal"]["Goal"]["percentage"]),
        "count_predictions": {
            "corner_mean_historical": None,
            "corner_mean_manual": float(count_markets["corners"]["mean"]),
            "corner_mean_blended": float(count_markets["corners"]["mean"]),
            "corner_over_8_5_pct": float(count_markets["corners"]["Over_8.5"]["percentage"]),
            "yellow_mean_historical": None,
            "yellow_mean_manual": float(count_markets["cards"]["mean"]),
            "yellow_mean_blended": float(count_markets["cards"]["mean"]),
            "yellow_over_4_5_pct": float(count_markets["cards"]["Over_4.5"]["percentage"]),
            "home_matches_used": 0,
            "away_matches_used": 0,
        },
        "unseen_teams": [],
    }