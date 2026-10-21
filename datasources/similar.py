"""Analisi degli avversari simili: come ha reso una squadra contro avversari
di stile e qualità simili a quello di oggi, rispetto alla sua media.

Profilo dell'avversario al momento della partita (nessun dato futuro): medie
delle 20 gare precedenti, z-score nel proprio campionato a quella data, più
l'Elo pre-partita. La somiglianza usa la distanza su tutte le metriche
disponibili (non l'etichetta dell'archetipo); con un profilo parziale la
distanza usa solo le metriche presenti e lo shrinkage è più forte.

Le quote di xG da transizioni e piazzati non entrano: Understat le pubblica
solo come totale di stagione, che includerebbe partite future.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import math

import numpy as np
import pandas as pd

from datasources.names import match_team


ROLLING_MATCHES = 20
UNDERSTAT_FEATURES = ("pressing", "block_height", "build_up", "xg_for", "xg_against")
FOOTBALLDATA_FEATURES = ("corners_for", "corners_against", "fouls", "cards", "shots")
FEATURES = UNDERSTAT_FEATURES + FOOTBALLDATA_FEATURES
ELO_SCALE = 100.0  # 100 punti Elo pesano come una deviazione standard di stile
STATS = ("xg_for", "xg_against", "goals_for", "goals_against", "ht_goals", "corners_for", "corners_against",
         "cards", "fouls")
BOUNDS = {"goals": (0.85, 1.15), "first_half": (0.85, 1.15), "corners": (0.80, 1.20), "cards": (0.80, 1.20)}
STAT_LABELS = {
    "xg_for": "xG fatti", "xg_against": "xG subiti", "goals_for": "gol fatti", "goals_against": "gol subiti",
    "ht_goals": "gol nel primo tempo", "corners_for": "corner prodotti", "corners_against": "corner concessi",
    "cards": "cartellini", "fouls": "falli",
}


# --- Storico con profili al momento della partita -------------------------------------------

def match_history(matches: pd.DataFrame, understat: pd.DataFrame | None, elos: pd.DataFrame) -> pd.DataFrame:
    """Una riga per squadra e partita con esito, media precedente della squadra e profilo dell'avversario.

    ``matches``: CSV football-data normalizzati (``tools.dataset.clean_frames``) di un campionato;
    ``understat``: righe di ``sources.parse_understat`` dello stesso campionato (o vuoto);
    ``elos``: Elo pre-partita allineato a ``matches`` (``home_elo``, ``away_elo``).
    """
    matches = matches.join(elos[["home_elo", "away_elo"]]).sort_values("date")
    us = _understat_lookup(matches, understat)
    rows = []
    for index, match in zip(matches.index, matches.itertuples(index=False)):
        for side, other in (("home", "away"), ("away", "home")):
            team, opponent = getattr(match, f"{side}_team"), getattr(match, f"{other}_team")
            key = (team, match.date.normalize())
            understat_row = us.get(key, {})
            rows.append({
                "match_id": index, "league": match.league, "season": match.season, "date": match.date,
                "team": team, "opponent": opponent, "venue": side,
                "team_elo": getattr(match, f"{side}_elo"), "opponent_elo": getattr(match, f"{other}_elo"),
                "goals_for": getattr(match, f"{side}_goals"), "goals_against": getattr(match, f"{other}_goals"),
                "ht_goals": _num(getattr(match, f"{side}_ht_goals")) + _num(getattr(match, f"{other}_ht_goals")),
                "corners_for": _num(getattr(match, f"{side}_corners")), "corners_against": _num(getattr(match, f"{other}_corners")),
                "cards": _num(getattr(match, f"{side}_yellows")), "fouls": _num(getattr(match, f"{side}_fouls")),
                "shots": _num(getattr(match, f"{side}_shots")),
                "xg_for": understat_row.get("xg_for", _num(getattr(match, f"{side}_xg_real"))),
                "xg_against": understat_row.get("xg_against", _num(getattr(match, f"{other}_xg_real"))),
                "ppda": understat_row.get("ppda", np.nan), "ppda_allowed": understat_row.get("ppda_allowed", np.nan),
                "deep_allowed": understat_row.get("deep_allowed", np.nan),
            })
    history = pd.DataFrame(rows)
    return _add_profiles(history)


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _understat_lookup(matches: pd.DataFrame, understat: pd.DataFrame | None) -> dict:
    if understat is None or understat.empty:
        return {}
    teams = pd.concat([matches["home_team"], matches["away_team"]]).unique()
    names = {title: match_team(title, teams) for title in understat["team"].unique()}
    lookup = {}
    for row in understat.itertuples(index=False):
        name = names.get(row.team)
        if name:
            lookup[(name, pd.Timestamp(row.date).normalize())] = {
                "xg_for": row.xg_for, "xg_against": row.xg_against, "ppda": row.ppda,
                "ppda_allowed": row.ppda_allowed, "deep_allowed": row.deep_allowed,
            }
    return lookup


def _profile(records: deque) -> dict[str, float]:
    frame = pd.DataFrame(records)

    def mean(column: str) -> float:
        values = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        return float(values.mean()) if len(values) else float("nan")

    ppda, allowed = mean("ppda"), mean("ppda_allowed")
    return {
        "pressing": -math.log(ppda) if ppda > 0 else float("nan"),
        "deep_allowed": mean("deep_allowed"),
        "build_up": math.log(allowed) if allowed > 0 else float("nan"),
        "xg_for": mean("xg_for"), "xg_against": mean("xg_against"),
        "corners_for": mean("corners_for"), "corners_against": mean("corners_against"),
        "fouls": mean("fouls"), "cards": mean("cards"), "shots": mean("shots"),
        **{f"base_{stat}": mean(stat) for stat in STATS},
    }


def _add_profiles(history: pd.DataFrame) -> pd.DataFrame:
    """Profilo grezzo pre-partita di ogni squadra, z-score nel campionato alla data, e quello dell'avversario."""
    window: dict[str, deque] = defaultdict(lambda: deque(maxlen=ROLLING_MATCHES))
    current: dict[str, dict] = {}
    profiles: dict[int, dict] = {}
    for day, today in history.groupby("date", sort=True):
        for index, row in today.iterrows():
            if len(window[row.team]) >= 5:
                current[row.team] = _profile(window[row.team])
        # z-score sui profili più recenti di tutte le squadre del campionato a questa data
        league_frame = pd.DataFrame(current).T if current else pd.DataFrame()
        if not league_frame.empty and "deep_allowed" in league_frame:
            league_frame["block_height"] = _z(league_frame["pressing"]) - _z(league_frame["deep_allowed"])
        stats = {key: (league_frame[key].mean(), league_frame[key].std(ddof=0)) for key in FEATURES
                 if not league_frame.empty and key in league_frame}
        for index, row in today.iterrows():
            profile = current.get(row.team)
            if profile is None or len(window[row.team]) < 5:
                continue
            raw = dict(profile)
            if "block_height" in league_frame and row.team in league_frame.index:
                raw["block_height"] = league_frame.loc[row.team, "block_height"]
            z = {f"z_{key}": (raw[key] - stats[key][0]) / stats[key][1]
                 for key in FEATURES if key in stats and stats[key][1] > 0 and np.isfinite(raw.get(key, np.nan))}
            profiles[index] = {**{key: value for key, value in raw.items() if key.startswith("base_")}, **z,
                               "history_matches": len(window[row.team])}
        for index, row in today.iterrows():
            window[row.team].append(row.to_dict())
    enriched = history.join(pd.DataFrame.from_dict(profiles, orient="index"))
    # Profilo dell'avversario = profilo pre-partita della riga dell'avversario nella stessa gara.
    opponent = enriched[["match_id", "team"] + [f"z_{key}" for key in FEATURES if f"z_{key}" in enriched]]
    opponent = opponent.rename(columns={"team": "opponent", **{f"z_{key}": f"opp_z_{key}" for key in FEATURES}})
    return enriched.merge(opponent, on=["match_id", "opponent"], how="left")


def _z(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    return (series - series.mean()) / std if std and np.isfinite(std) else series * 0.0


def profile_at(history: pd.DataFrame, team: str) -> tuple[dict[str, float], float, int] | None:
    """Ultimo profilo (z-score) ed Elo noti della squadra nello storico; ``None`` se non presente."""
    rows = history[(history["team"] == team)].dropna(subset=["history_matches"])
    if rows.empty:
        return None
    last = rows.iloc[-1]
    z = {key: float(last[f"z_{key}"]) for key in FEATURES if f"z_{key}" in last and pd.notna(last[f"z_{key}"])}
    return z, float(last["team_elo"]), int(last["history_matches"])


# --- Avversari simili e fattori ------------------------------------------------------------

@dataclass
class SimilarResult:
    team: str
    opponent: str
    matches: pd.DataFrame
    factors: dict[str, float]
    raw: dict[str, float]
    effective_matches: float
    features_used: list[str] = field(default_factory=list)


def similar_matches(history: pd.DataFrame, team: str, opponent_profile: dict[str, float], opponent_elo: float,
                    as_of: pd.Timestamp, *, k: int = 10, window_days: int = 730,
                    half_life_days: float = 365.0) -> tuple[pd.DataFrame, list[str]]:
    """Le ``k`` partite della squadra negli ultimi ``window_days`` contro gli avversari più simili."""
    start = as_of - pd.Timedelta(days=window_days)
    candidates = history[(history["team"] == team) & (history["date"] < as_of) & (history["date"] >= start)]
    candidates = candidates.dropna(subset=["history_matches"])
    features = [key for key in FEATURES if key in opponent_profile and f"opp_z_{key}" in candidates]
    if candidates.empty or not features:
        return candidates.iloc[0:0], features
    target = np.array([opponent_profile[key] for key in features])
    values = candidates[[f"opp_z_{key}" for key in features]].to_numpy(float)
    available = np.isfinite(values)
    squared = np.where(available, (values - target) ** 2, 0.0)
    # Distanza media per metrica disponibile (confrontabile tra profili completi e parziali) più l'Elo.
    style = squared.sum(axis=1) / np.maximum(available.sum(axis=1), 1)
    elo = ((candidates["opponent_elo"].to_numpy(float) - opponent_elo) / ELO_SCALE) ** 2
    distance = np.sqrt(style + elo)
    age = (as_of - candidates["date"]).dt.days.to_numpy(float)
    weight = 0.5 ** (age / half_life_days) / (1.0 + distance)
    selected = candidates.assign(distance=distance, weight=weight).nsmallest(k, "distance")
    return selected, features


def correction_factors(selected: pd.DataFrame, *, tau: dict[str, float], feature_ratio: float = 1.0) -> tuple[dict, dict, float]:
    """Fattori rispetto alla media della squadra con shrinkage verso 1.

    log(fattore) = n_eff / (n_eff + tau·r) · log(somma pesata esito / somma pesata media), dove n_eff
    è il numero effettivo di partite e r = metriche totali / metriche usate (profilo parziale: più shrinkage).
    """
    if selected.empty:
        return {stat: 1.0 for stat in STATS}, {stat: 1.0 for stat in STATS}, 0.0
    weights = selected["weight"].to_numpy(float)
    effective = float(weights.sum() ** 2 / (weights ** 2).sum())
    factors, raw = {}, {}
    for stat in STATS:
        observed = pd.to_numeric(selected[stat], errors="coerce").to_numpy(float)
        baseline = pd.to_numeric(selected[f"base_{stat}"], errors="coerce").to_numpy(float)
        valid = np.isfinite(observed) & np.isfinite(baseline)
        if valid.sum() == 0 or (weights[valid] * baseline[valid]).sum() <= 0:
            factors[stat] = raw[stat] = 1.0
            continue
        ratio = (weights[valid] * observed[valid]).sum() / (weights[valid] * baseline[valid]).sum()
        ratio = max(ratio, 0.05)
        n_eff = float(weights[valid].sum() ** 2 / (weights[valid] ** 2).sum())
        strength = tau[_family(stat)] * feature_ratio
        raw[stat] = ratio
        factors[stat] = math.exp(n_eff / (n_eff + strength) * math.log(ratio))
    return factors, raw, effective


def _family(stat: str) -> str:
    if stat in ("xg_for", "xg_against", "goals_for", "goals_against"):
        return "goals"
    if stat == "ht_goals":
        return "first_half"
    if stat in ("corners_for", "corners_against"):
        return "corners"
    return "cards"


def _clip(value: float, family: str) -> float:
    low, high = BOUNDS[family]
    return float(min(max(value, low), high))


def match_factors(home: dict[str, float], away: dict[str, float]) -> dict[str, float]:
    """Fattori della partita dai fattori di casa (contro avversari simili all'ospite) e ospite."""
    def share(team: dict[str, float]) -> float:
        # Quota del primo tempo: variazione dei gol nel primo tempo divisa per quella dei gol totali.
        total = math.sqrt(team["goals_for"] * team["goals_against"])
        return team["ht_goals"] / total if total > 0 else 1.0

    first_half = math.sqrt(share(home) * share(away))
    return {
        "lambda": _clip(math.sqrt(home["xg_for"] * away["xg_against"]), "goals"),
        "mu": _clip(math.sqrt(away["xg_for"] * home["xg_against"]), "goals"),
        "first_half": _clip(first_half, "first_half"),
        "corners_home": _clip(math.sqrt(home["corners_for"] * away["corners_against"]), "corners"),
        "corners_away": _clip(math.sqrt(away["corners_for"] * home["corners_against"]), "corners"),
        "cards": _clip(math.sqrt(home["cards"] * away["cards"]), "cards"),
    }


def summary_sentence(result: SimilarResult, opponent_label: str) -> str:
    """Frase in italiano con le variazioni più marcate (es. «+20% corner, -10% xG»)."""
    changes = sorted(((stat, value) for stat, value in result.factors.items() if abs(value - 1) >= 0.03
                      and stat in ("xg_for", "xg_against", "corners_for", "corners_against", "cards", "ht_goals")),
                     key=lambda item: -abs(item[1] - 1))[:3]
    if result.matches.empty:
        return f"{result.team}: nessuna partita contro avversari simili a {opponent_label} negli ultimi 2 anni."
    if not changes:
        return (f"Contro avversari simili a {opponent_label} {result.team} rende in linea con la sua media "
                f"({len(result.matches)} partite, {result.effective_matches:.1f} effettive).")
    parts = [f"{(value - 1) * 100:+.0f}% {STAT_LABELS[stat]}" for stat, value in changes]
    return (f"Contro avversari simili a {opponent_label} {result.team} ha " + ", ".join(parts) +
            f" rispetto alla sua media ({len(result.matches)} partite, {result.effective_matches:.1f} effettive, "
            "dopo lo shrinkage).")
