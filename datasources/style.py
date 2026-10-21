"""Profili di stile delle squadre, z-score per campionato e archetipi.

Metriche (per partita, sulle ultime gare di campionato):

- da Understat (5 campionati top): pressing (PPDA), altezza del blocco
  (derivata), manovra vs gioco diretto (derivata dal PPDA concesso),
  pericolosità in transizione (quota di xG da azioni veloci), pericolosità sui
  calci piazzati (quota di xG da corner e punizioni), xG fatti e subiti;
- da football-data.co.uk (tutti i campionati coperti): corner prodotti e
  concessi, falli, cartellini, tiri, quota di gol nel primo tempo, xG.

Possesso e uso di fasce/cross non sono disponibili da nessuna fonte gratuita
funzionante (FBref è bloccata): sono esclusi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from datasources.cache import SourceCache
from datasources.names import match_team


ARCHETYPES_PATH = Path(__file__).resolve().parents[1] / "config" / "style_archetypes.json"
PROFILE_MATCHES = 20


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    source: str
    high: str
    low: str


METRICS = (
    Metric("pressing", "Intensità del pressing", "Understat (PPDA)",
           "pressa alto e recupera palla presto", "pressa poco e lascia giocare l'avversario"),
    Metric("block_height", "Altezza del blocco (derivato)", "Understat (PPDA, deep concessi)",
           "difende alto e concede pochi ingressi vicino all'area", "si chiude in un blocco basso vicino all'area"),
    Metric("build_up", "Manovra vs gioco diretto (derivato)", "Understat (PPDA concesso)",
           "costruisce con il palleggio", "cerca il gioco diretto e verticale"),
    Metric("transitions", "Pericolosità in transizione", "Understat (xG da azioni veloci)",
           "è pericolosa in contropiede", "segna poco in transizione"),
    Metric("set_pieces", "Pericolosità sui piazzati", "Understat (xG da corner e punizioni)",
           "crea molto sui calci piazzati", "dipende poco dai calci piazzati"),
    Metric("xg_for", "Produzione offensiva (xG)", "Understat / football-data.co.uk",
           "produce molte occasioni", "produce poche occasioni"),
    Metric("xg_against", "Occasioni concesse (xG subiti)", "Understat / football-data.co.uk",
           "concede molte occasioni", "concede poche occasioni"),
    Metric("shots", "Volume di tiri", "football-data.co.uk",
           "tira molto", "tira poco"),
    Metric("corners_for", "Corner prodotti", "football-data.co.uk",
           "conquista molti corner", "conquista pochi corner"),
    Metric("corners_against", "Corner concessi", "football-data.co.uk",
           "concede molti corner", "concede pochi corner"),
    Metric("fouls", "Falli commessi", "football-data.co.uk",
           "gioca in modo fisico e spezzettato", "commette pochi falli"),
    Metric("cards", "Cartellini", "football-data.co.uk",
           "riceve molti cartellini", "riceve pochi cartellini"),
    Metric("first_half_share", "Quota di gol nel primo tempo", "football-data.co.uk",
           "segna soprattutto nei primi tempi", "segna soprattutto nei secondi tempi"),
)
METRIC_BY_KEY = {metric.key: metric for metric in METRICS}
UNDERSTAT_METRICS = ("pressing", "block_height", "build_up", "transitions", "set_pieces")
EXCLUDED_METRICS = {
    "possesso": "nessuna fonte gratuita funzionante (FBref bloccata; Understat e football-data non lo pubblicano)",
    "uso delle fasce e cross": "nessuna fonte gratuita con i cross o le zone di attacco",
}


# --- Metriche grezze -----------------------------------------------------------------------

def footballdata_metrics(rows: pd.DataFrame, team: str, matches: int = PROFILE_MATCHES) -> dict[str, float]:
    """Medie per partita dalle ultime ``matches`` gare di campionato (formato lungo di stats.team_match_rows)."""
    own = rows[rows["team"] == team].sort_values("date").tail(matches)
    if own.empty:
        return {}

    def mean(column: str) -> float:
        values = pd.to_numeric(own[column], errors="coerce").dropna()
        return float(values.mean()) if len(values) else float("nan")

    goals = float(own["goals_for"].sum())
    first_half = float(pd.to_numeric(own["ht_goals_for"], errors="coerce").fillna(0).sum())
    metrics = {
        "corners_for": mean("corners_for"), "corners_against": mean("corners_against"),
        "fouls": mean("fouls_for"), "cards": mean("yellows_for"),
        # Quota dei gol nel primo tempo, avvicinata al 45% con 2 gol fittizi (campioni piccoli).
        "first_half_share": (first_half + 0.9) / (goals + 2.0),
        "xg_for": mean("xg_real_for"), "xg_against": mean("xg_real_against"),
        "matches": float(len(own)),
    }
    if "shots_for" in own:
        metrics["shots"] = mean("shots_for")
    return metrics


def understat_league_metrics(rows: pd.DataFrame, team: str, matches: int = PROFILE_MATCHES) -> dict[str, float]:
    """PPDA, deep concessi e xG dalle ultime partite (dati di lega Understat)."""
    own = rows[rows["team"] == team].sort_values("date").tail(matches)
    if own.empty:
        return {}
    ppda = own["ppda"].replace([np.inf, -np.inf], np.nan).dropna()
    ppda_allowed = own["ppda_allowed"].replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "pressing": -math.log(float(ppda.mean())) if len(ppda) else float("nan"),
        "deep_allowed": float(own["deep_allowed"].mean()),
        "build_up": math.log(float(ppda_allowed.mean())) if len(ppda_allowed) else float("nan"),
        "xg_for": float(own["xg_for"].mean()), "xg_against": float(own["xg_against"].mean()),
    }


def understat_team_metrics(payload: dict) -> dict[str, float]:
    """Quote di xG da azioni veloci e da calci piazzati (endpoint squadra di Understat)."""
    statistics = payload.get("statistics", {})

    def xg(section: str, keys) -> float:
        return float(sum(statistics.get(section, {}).get(key, {}).get("xG", 0.0) for key in keys))

    total = xg("situation", statistics.get("situation", {}).keys())
    if total <= 0:
        return {}
    speed_total = xg("attackSpeed", statistics.get("attackSpeed", {}).keys())
    return {
        "transitions": xg("attackSpeed", ["Fast"]) / speed_total if speed_total > 0 else float("nan"),
        "set_pieces": xg("situation", ["FromCorner", "SetPiece", "DirectFreekick"]) / total,
    }


# --- Profili ---------------------------------------------------------------------------------

@dataclass
class StyleProfile:
    team: str
    league: str
    raw: dict[str, float]
    z: dict[str, float]
    partial: bool
    matches: int
    computed_at: str
    archetype: str | None = None
    archetype_distance: float | None = None
    missing: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "StyleProfile":
        return cls(**json.loads(text))


def league_profiles(raw: dict[str, dict[str, float]], league: str, *, partial: bool) -> dict[str, StyleProfile]:
    """Z-score di ogni metrica rispetto alle squadre dello stesso campionato."""
    frame = pd.DataFrame(raw).T
    if "deep_allowed" in frame and "pressing" in frame:
        # Blocco alto: pressing intenso e pochi ingressi concessi vicino all'area.
        z_press = (frame["pressing"] - frame["pressing"].mean()) / frame["pressing"].std(ddof=0)
        z_deep = (frame["deep_allowed"] - frame["deep_allowed"].mean()) / frame["deep_allowed"].std(ddof=0)
        frame["block_height"] = (z_press - z_deep) / 2.0
    now = datetime.now(timezone.utc).isoformat()
    profiles = {}
    for team, values in frame.iterrows():
        z, raw_values, missing = {}, {}, []
        for metric in METRICS:
            value = values.get(metric.key, np.nan)
            column = frame[metric.key] if metric.key in frame else pd.Series(dtype=float)
            std = float(column.std(ddof=0)) if len(column.dropna()) > 2 else 0.0
            if pd.isna(value) or std <= 0:
                missing.append(metric.key)
                continue
            raw_values[metric.key] = float(value)
            z[metric.key] = float((value - column.mean()) / std)
        profiles[team] = StyleProfile(team, league, raw_values, z, partial or any(key in missing for key in UNDERSTAT_METRICS),
                                      int(values.get("matches", 0) or 0), now, missing=missing)
    return profiles


# --- Archetipi ------------------------------------------------------------------------------

def kmeans(points: np.ndarray, k: int, *, seed: int = 0, restarts: int = 25, iterations: int = 100):
    """k-means con inizializzazione k-means++ e più ripartenze; restituisce (etichette, centroidi, inerzia)."""
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(restarts):
        centroids = [points[rng.integers(len(points))]]
        for _ in range(1, k):
            distance = np.min(((points[:, None, :] - np.array(centroids)[None]) ** 2).sum(axis=2), axis=1)
            centroids.append(points[rng.choice(len(points), p=distance / distance.sum())])
        centroids = np.array(centroids)
        for _ in range(iterations):
            labels = np.argmin(((points[:, None, :] - centroids[None]) ** 2).sum(axis=2), axis=1)
            updated = np.array([points[labels == index].mean(axis=0) if np.any(labels == index) else centroids[index]
                                for index in range(k)])
            if np.allclose(updated, centroids):
                break
            centroids = updated
        inertia = float(((points - centroids[labels]) ** 2).sum())
        if best is None or inertia < best[2]:
            best = (labels, centroids, inertia)
    return best


def silhouette(points: np.ndarray, labels: np.ndarray) -> float:
    distances = np.sqrt(((points[:, None, :] - points[None]) ** 2).sum(axis=2))
    scores = []
    for index, label in enumerate(labels):
        same = labels == label
        if same.sum() <= 1:
            scores.append(0.0)
            continue
        intra = distances[index, same].sum() / (same.sum() - 1)
        inter = min(distances[index, labels == other].mean() for other in set(labels) if other != label)
        scores.append((inter - intra) / max(intra, inter))
    return float(np.mean(scores))


_NAME_PARTS = {
    "pressing": ("pressing alto", "attesa senza pressing"),
    "block_height": ("difesa alta", "blocco basso"),
    "build_up": ("possesso manovrato", "gioco diretto"),
    "transitions": ("transizioni veloci", "attacco posizionale"),
    "set_pieces": ("forza sui piazzati", None),
    "xg_for": ("attacco dominante", "attacco sterile"),
    "xg_against": ("difesa fragile", "difesa solida"),
    "fouls": ("gioco fisico", None),
    "cards": ("molti cartellini", None),
    "corners_for": ("spinta costante", None),
}


def archetype_name(centroid: dict[str, float]) -> str:
    """Nome leggibile dai due tratti più marcati del centroide."""
    ranked = sorted(centroid.items(), key=lambda item: -abs(item[1]))
    parts = []
    for key, value in ranked:
        high, low = _NAME_PARTS.get(key, (None, None))
        label = high if value > 0 else low
        if label and abs(value) >= 0.3 and label not in parts:
            parts.append(label)
        if len(parts) == 2:
            break
    return " e ".join(parts).capitalize() if parts else "Profilo equilibrato"


def describe(profile: StyleProfile, count: int = 3) -> str:
    """Breve descrizione in italiano dei tratti più marcati rispetto al campionato."""
    ranked = sorted(profile.z.items(), key=lambda item: -abs(item[1]))[:count]
    traits = [METRIC_BY_KEY[key].high if value > 0 else METRIC_BY_KEY[key].low for key, value in ranked]
    if not traits:
        return f"{profile.team}: dati insufficienti per un profilo di stile."
    sentence = f"{profile.team} " + ", ".join(traits[:-1]) + (" e " if len(traits) > 1 else "") + traits[-1] + "."
    strongest = ranked[0][1]
    if abs(strongest) >= 1.5:
        sentence += f" Il tratto principale è tra i più marcati del campionato (z = {strongest:+.1f})."
    if profile.partial:
        sentence += " Profilo parziale: " + ", ".join(METRIC_BY_KEY[key].label.lower() for key in profile.missing) + " non disponibili."
    return sentence


def load_archetypes(path: Path = ARCHETYPES_PATH) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def assign_archetype(profile: StyleProfile, archetypes: dict | None) -> StyleProfile:
    """Archetipo più vicino (distanza euclidea sugli z-score disponibili)."""
    if not archetypes:
        return profile
    features = [key for key in archetypes["features"] if key in profile.z]
    if len(features) < 3:
        return profile
    vector = np.array([profile.z[key] for key in features])
    best = min(
        archetypes["groups"],
        key=lambda group: float(np.linalg.norm(vector - np.array([group["centroid"][key] for key in features]))),
    )
    profile.archetype = best["name"] + (" (indicativo: profilo parziale)" if profile.partial else "")
    profile.archetype_distance = float(np.linalg.norm(vector - np.array([best["centroid"][key] for key in features])))
    return profile


# --- Cache ---------------------------------------------------------------------------------

class ProfileStore:
    """Profili salvati in SQLite (stesso database della cache delle fonti)."""

    def __init__(self, cache: SourceCache) -> None:
        self.path = cache.path
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS style_profiles (league TEXT, team TEXT, computed_at TEXT, profile TEXT, "
                "PRIMARY KEY (league, team))"
            )

    def save(self, profiles: dict[str, StyleProfile]) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO style_profiles VALUES (?, ?, ?, ?)",
                [(profile.league, profile.team, profile.computed_at, profile.to_json()) for profile in profiles.values()],
            )

    def invalidate(self, league: str) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM style_profiles WHERE league = ?", (league,))

    def load(self, league: str, max_age: timedelta) -> dict[str, StyleProfile] | None:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT computed_at, profile FROM style_profiles WHERE league = ?", (league,)).fetchall()
        if not rows:
            return None
        oldest = min(datetime.fromisoformat(row[0]) for row in rows)
        if datetime.now(timezone.utc) - oldest > max_age:
            return None
        profiles = [StyleProfile.from_json(row[1]) for row in rows]
        return {profile.team: profile for profile in profiles}


def find_profile(profiles: dict[str, StyleProfile], team: str) -> StyleProfile | None:
    name = match_team(team, list(profiles))
    return profiles.get(name) if name else None


def radar_percentiles(profile: StyleProfile) -> dict[str, float]:
    """Z-score convertiti in percentile (0-100) del campionato, per il radar."""
    return {key: 50.0 * (1.0 + math.erf(value / math.sqrt(2.0))) for key, value in profile.z.items()}

