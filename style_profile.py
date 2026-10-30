"""Profilo di stile e forma reale delle squadre (fase AD), come INPUT per il motore.

Per squadra, sulle ultime ``finestra_gare`` gare con media esponenziale (``emivita_gare``), casa e trasferta
separate, con shrinkage ``n / (n + k)`` verso la media del campionato (k per componente in ``config/stile.json``).
Solo il passato: per la partita del giorno D si usano le gare con data < D. Valori esorbitanti (dati sbagliati,
campioni minuscoli) sono winsorizzati ai percentili del campionato calcolati con le gare precedenti; quando scatta
c'è un avviso nel parametro. Nessuna correzione sopra le correzioni: lo stile agisce per intero (gli interruttori
stanno in ``componenti``).

xG: Understat dove c'è (5 grandi); altrimenti proxy dai tiri (``config/proxy_xg.json``, usato solo se il suo R² ≥ 0.5);
altrimenti solo gol. Ogni parametro dichiara valore, campione e fonte. Possesso e cross veri non esistono da fonti
gratuite funzionanti: il possesso è la quota di tiri, i cross risultano «non disponibile».

    get_style_params(squadra, data, casa, store) -> {"parametri": {nome: {valore, campione, fonte, avviso}}, ...}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
from scipy.stats import poisson

from datasources.names import canonical_key

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "stile.json"
PROXY_PATH = ROOT / "config" / "proxy_xg.json"
CACHE_DIR = ROOT / "data" / "cache" / "stile"
HISTORY_YEARS = 3


# --- Parametri ----------------------------------------------------------------------------------------------------
# nome -> (componente, descrizione, fonte tipica)
PARAMS: dict[str, tuple[str, str, str]] = {
    "xg_diff": ("forma_reale", "xG − xGA per gara", "xG"),
    "gol_meno_xg": ("forma_reale", "gol fatti − xG", "xG"),
    "gs_meno_xga": ("forma_reale", "gol subiti − xGA", "xG"),
    "punti_meno_xpts": ("forma_reale", "punti reali − punti attesi da xG", "xG"),
    "quota_tiri": ("possesso", "quota di tiri (tiri fatti / tiri totali): sostituto del possesso", "tiri"),
    "deep": ("verticalita", "deep completions fatte", "Understat"),
    "tiri_transizione": ("verticalita", "quota di tiri da transizione (solo stagionale)", "Understat squadra"),
    "corner_per_tiro": ("fasce", "corner ottenuti per tiro", "tiri e corner"),
    "cross": ("fasce", "cross (non disponibile da fonti gratuite)", "—"),
    "ppda": ("blocco_pressing", "PPDA (passaggi avversari per azione difensiva)", "Understat"),
    "deep_concessi": ("blocco_pressing", "deep completions concesse (altezza del blocco)", "Understat"),
    "tiri_concessi": ("blocco_pressing", "tiri concessi", "tiri"),
    "falli_fatti": ("aggressivita", "falli fatti", "falli"),
    "falli_subiti": ("aggressivita", "falli subiti", "falli"),
    "gialli_per_fallo": ("aggressivita", "gialli per fallo fatto", "falli e gialli"),
    "quota_xg_palle_inattive": ("palle_inattive", "quota di xG da palla inattiva (solo stagionale)", "Understat squadra"),
}
MATCH_PARAMS = tuple(name for name in PARAMS if name not in ("tiri_transizione", "cross", "quota_xg_palle_inattive"))
SEASONAL_PARAMS = ("tiri_transizione", "quota_xg_palle_inattive")


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_proxy(path: Path = PROXY_PATH) -> dict | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if data.get("usabile") else None


# --- Tabella squadra-partita --------------------------------------------------------------------------------------

def _expected_points(xg_for: np.ndarray, xg_against: np.ndarray) -> np.ndarray:
    grid = np.arange(11)
    pf = poisson.pmf(grid[None, :], np.nan_to_num(xg_for, nan=1.0)[:, None])
    pa = poisson.pmf(grid[None, :], np.nan_to_num(xg_against, nan=1.0)[:, None])
    joint = pf[:, :, None] * pa[:, None, :]
    win = np.triu(np.ones((11, 11)), 1).T          # gol fatti > subiti
    draw = np.eye(11)
    points = 3.0 * (joint * win).sum(axis=(1, 2)) + (joint * draw).sum(axis=(1, 2))
    return np.where(np.isfinite(xg_for) & np.isfinite(xg_against), points, np.nan)


def build_table(raw: pd.DataFrame, understat: pd.DataFrame | None = None, proxy: Mapping | None = None) -> pd.DataFrame:
    """Una riga per squadra e partita, ordinata per data, con tutti i valori per gara dei parametri.

    ``raw``: partite in formato ``tools.dataset`` (football-data). ``understat``: ``parse_understat`` concatenato con la
    colonna ``league`` (codice football-data). ``proxy``: contenuto utilizzabile di ``config/proxy_xg.json``.
    """
    parts = []
    for side, other in (("home", "away"), ("away", "home")):
        part = pd.DataFrame({
            "league": raw["league"], "season": raw["season"], "date": pd.to_datetime(raw["date"]).dt.normalize(),
            "team": raw[f"{side}_team"], "opponent": raw[f"{other}_team"], "venue": side,
            "gf": raw[f"{side}_goals"], "ga": raw[f"{other}_goals"],
            "shots_for": raw[f"{side}_shots"], "shots_against": raw[f"{other}_shots"],
            "sot_for": raw[f"{side}_sot"], "sot_against": raw[f"{other}_sot"],
            "fouls_for": raw[f"{side}_fouls"], "fouls_against": raw[f"{other}_fouls"],
            "corners_for": raw[f"{side}_corners"], "yellows_for": raw[f"{side}_yellows"],
        })
        parts.append(part)
    table = pd.concat(parts, ignore_index=True)
    table["key"] = table["team"].map(canonical_key)
    for column in ("xg_for", "xg_against", "ppda", "deep", "deep_against"):
        table[column] = np.nan
    table["xg_source"] = "gol"
    if understat is not None and len(understat):
        us = understat.assign(key=understat["team"].map(canonical_key), date=pd.to_datetime(understat["date"]).dt.normalize())
        us = us.rename(columns={"deep_allowed": "deep_against"})[
            ["league", "key", "venue", "date", "xg_for", "xg_against", "ppda", "deep", "deep_against"]]
        merged = table.drop(columns=["xg_for", "xg_against", "ppda", "deep", "deep_against"]).merge(
            us, on=["league", "key", "venue", "date"], how="left")
        table = merged.assign(xg_source=np.where(merged["xg_for"].notna(), "Understat", "gol"))
    if proxy:
        a, b = float(proxy["a_tiri_in_porta"]), float(proxy["b_altri_tiri"])

        def estimate(shots, sot):
            return a * sot + b * np.clip(shots - sot, 0.0, None)

        own = estimate(table["shots_for"], table["sot_for"])
        opp = estimate(table["shots_against"], table["sot_against"])
        missing = table["xg_for"].isna() & own.notna() & opp.notna()
        table.loc[missing, "xg_for"] = own[missing]
        table.loc[missing, "xg_against"] = opp[missing]
        table.loc[missing, "xg_source"] = "proxy dai tiri"
    table["pts"] = np.select([table["gf"] > table["ga"], table["gf"] == table["ga"]], [3.0, 1.0], 0.0)
    xpts = _expected_points(table["xg_for"].to_numpy(float), table["xg_against"].to_numpy(float))
    table["xg_diff"] = table["xg_for"] - table["xg_against"]
    table["gol_meno_xg"] = table["gf"] - table["xg_for"]
    table["gs_meno_xga"] = table["ga"] - table["xg_against"]
    table["punti_meno_xpts"] = table["pts"] - xpts
    table["quota_tiri"] = table["shots_for"] / (table["shots_for"] + table["shots_against"])
    table["deep_concessi"] = table["deep_against"]
    table["corner_per_tiro"] = table["corners_for"] / table["shots_for"].where(table["shots_for"] > 0)
    table["tiri_concessi"] = table["shots_against"]
    table["falli_fatti"] = table["fouls_for"]
    table["falli_subiti"] = table["fouls_against"]
    table["gialli_per_fallo"] = table["yellows_for"] / table["fouls_for"].where(table["fouls_for"] > 0)
    table["gd"] = table["gf"] - table["ga"]
    return table.sort_values(["league", "date"]).reset_index(drop=True)


# --- Archivio ---------------------------------------------------------------------------------------------------

@dataclass
class StyleStore:
    """Tabella squadra-partita con ricerca veloce «ultime gare prima della data»."""

    table: pd.DataFrame
    config: dict = field(default_factory=load_config)
    seasonal: Mapping[str, Mapping[str, float]] = field(default_factory=dict)   # chiave squadra -> {tiri_transizione, ...}
    _teams: dict = field(default_factory=dict, init=False, repr=False)
    _leagues: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        for (league, key, venue), group in self.table.groupby(["league", "key", "venue"], sort=False):
            group = group.sort_values("date")
            self._teams[(league, key, venue)] = (group["date"].to_numpy("datetime64[ns]"), group)

    def leagues_of(self, key: str) -> list[str]:
        return sorted({league for league, team, _ in self._teams if team == key})

    def league_stats(self, league: str, venue: str, column: str, cutoff: pd.Timestamp) -> tuple[float, float, float, int]:
        """Media e percentili (winsorizzazione) del campionato con le gare dei 3 anni PRIMA del primo giorno del mese."""
        month_start = pd.Timestamp(cutoff.year, cutoff.month, 1)
        cache_key = (league, venue, column, month_start)
        if cache_key not in self._leagues:
            low, high = self.config["winsorizzazione"]["percentili"]
            data = self.table
            window = data[(data["league"] == league) & (data["venue"] == venue) & (data["date"] < month_start)
                          & (data["date"] >= month_start - pd.DateOffset(years=HISTORY_YEARS))][column].dropna().to_numpy(float)
            if len(window) < self.config["winsorizzazione"]["minimo_valori_campionato"]:
                self._leagues[cache_key] = (float(window.mean()) if len(window) else float("nan"), float("nan"), float("nan"), len(window))
            else:
                self._leagues[cache_key] = (float(window.mean()), float(np.percentile(window, low)),
                                            float(np.percentile(window, high)), len(window))
        return self._leagues[cache_key]


@dataclass(frozen=True)
class ParamValue:
    valore: float | None
    campione: int
    fonte: str
    avviso: str | None = None

    def to_dict(self) -> dict:
        return {"valore": self.valore, "campione": self.campione, "fonte": self.fonte, "avviso": self.avviso}


def _team_param(store: StyleStore, league: str, key: str, venue: str, when: pd.Timestamp, name: str) -> ParamValue:
    config = store.config
    component = PARAMS[name][0]
    if not config["componenti"].get(component, True):
        return ParamValue(None, 0, "componente spenta in config/stile.json")
    entry = store._teams.get((league, key, venue))
    mean, low, high, league_count = store.league_stats(league, venue, name, when)
    if entry is None or not np.isfinite(mean):
        return ParamValue(None, 0, "campione del campionato insufficiente")
    dates, group = entry
    end = int(np.searchsorted(dates, np.datetime64(when), side="left"))          # solo gare con data < quella della partita
    values = group[name].to_numpy(float)[max(0, end - config["finestra_gare"]):end]
    sources = group["xg_source"].to_numpy()[max(0, end - config["finestra_gare"]):end]
    finite = np.isfinite(values)
    values, sources = values[finite], sources[finite]
    warning = None
    if len(values) and np.isfinite(low):
        clipped = np.clip(values, low, high)
        changed = int(np.sum(clipped != values))
        if changed:
            warning = (f"{changed} valore/i fuori dal {config['winsorizzazione']['percentili'][0]:g}°-"
                       f"{config['winsorizzazione']['percentili'][1]:g}° percentile del campionato "
                       f"({low:.2f}…{high:.2f}) riportato/i al limite")
        values = clipped
    n = len(values)
    k = float(config["shrinkage_k"].get(component, 8.0))
    if n:
        weights = 0.5 ** (np.arange(n - 1, -1, -1) / float(config["emivita_gare"]))
        team_mean = float(np.average(values, weights=weights))
        value = (n * team_mean + k * mean) / (n + k)
    else:
        value = mean
    origin = ("Understat" if "Understat" in set(sources) else "proxy dai tiri" if "proxy dai tiri" in set(sources)
              else ("gol" if component == "forma_reale" else "football-data.co.uk"))
    if name in ("xg_diff", "gol_meno_xg", "gs_meno_xga", "punti_meno_xpts") and not n:
        origin = "xG non disponibile: media del campionato"
    fonte = f"{origin}, ultime {n} gare {'in casa' if venue == 'home' else 'in trasferta'}, shrinkage {n}/({n}+{k:g}) verso il campionato"
    return ParamValue(float(value), n, fonte, warning)


def forma_reale(store: StyleStore, league: str, key: str, venue: str, when: pd.Timestamp) -> ParamValue:
    """Forma reale = (xG − xGA) per gara, centrata sulla media del campionato per lo stesso campo.

    Con xG mancante (nessun proxy utilizzabile) si usa la differenza reti. Sostituisce la covariata W-D-L.
    """
    base = _team_param(store, league, key, venue, when, "xg_diff")
    if base.valore is not None and base.campione:
        mean = store.league_stats(league, venue, "xg_diff", when)[0]
        return ParamValue(base.valore - mean, base.campione, "forma reale: " + base.fonte, base.avviso)
    entry = store._teams.get((league, key, venue))
    if entry is None:
        return ParamValue(None, 0, "nessuna gara")
    # solo gol
    return _team_param_goal_diff(store, league, key, venue, when)


def _team_param_goal_diff(store: StyleStore, league: str, key: str, venue: str, when: pd.Timestamp) -> ParamValue:
    dates, group = store._teams[(league, key, venue)]
    end = int(np.searchsorted(dates, np.datetime64(when), side="left"))
    values = group["gd"].to_numpy(float)[max(0, end - store.config["finestra_gare"]):end]
    month_start = pd.Timestamp(when.year, when.month, 1)
    data = store.table
    league_values = data[(data["league"] == league) & (data["venue"] == venue) & (data["date"] < month_start)]["gd"].dropna()
    mean = float(league_values.mean()) if len(league_values) else 0.0
    n = len(values)
    k = float(store.config["shrinkage_k"]["forma_reale"])
    if not n:
        return ParamValue(0.0, 0, "differenza reti: nessuna gara, media del campionato")
    weights = 0.5 ** (np.arange(n - 1, -1, -1) / float(store.config["emivita_gare"]))
    value = (n * float(np.average(values, weights=weights)) + k * mean) / (n + k) - mean
    return ParamValue(float(value), n, f"forma reale solo gol (nessun xG): ultime {n} gare, shrinkage {n}/({n}+{k:g})")


def get_style_params(team: str, when: date | datetime | pd.Timestamp, home: bool, store: StyleStore,
                     league: str | None = None) -> dict[str, Any]:
    """Parametri di stile della squadra per una partita il giorno ``when`` (solo gare precedenti).

    ``home`` True = la squadra gioca in casa (si usano le sue gare in casa). Ritorna
    ``{"squadra", "campo", "campionato", "forma_reale": ParamValue-dict, "parametri": {nome: dict}, "avvisi": [...]}``.
    """
    key = canonical_key(team)
    when = pd.Timestamp(when).normalize()
    venue = "home" if home else "away"
    leagues = [league] if league else store.leagues_of(key)
    if not leagues:
        return {"squadra": team, "campo": venue, "campionato": None, "forma_reale": None, "parametri": {},
                "avvisi": [f"Nessuna gara trovata per {team}: stile non calcolabile."]}
    chosen = max(leagues, key=lambda code: len(store._teams.get((code, key, venue), (None, []))[1]))
    params = {name: _team_param(store, chosen, key, venue, when, name).to_dict() for name in MATCH_PARAMS}
    seasonal = store.seasonal.get(key, {})
    for name in SEASONAL_PARAMS:
        value = seasonal.get(name)
        params[name] = ParamValue(value, 1 if value is not None else 0,
                                  "Understat, dato di stagione (non per data: non entra nei backtest)" if value is not None
                                  else "non disponibile (serve la pagina squadra di Understat)").to_dict()
    params["cross"] = ParamValue(None, 0, "non disponibile da fonti gratuite funzionanti").to_dict()
    real = forma_reale(store, chosen, key, venue, when)
    warnings = [f"{name}: {item['avviso']}" for name, item in params.items() if item.get("avviso")]
    if real.avviso:
        warnings.append(f"forma_reale: {real.avviso}")
    return {"squadra": team, "campo": venue, "campionato": chosen, "data": when.date().isoformat(),
            "forma_reale": real.to_dict(), "parametri": params, "avvisi": warnings}


# --- Per il banco walk-forward -------------------------------------------------------------------------------------

def forma_reale_columns(store: StyleStore, matches: pd.DataFrame) -> pd.DataFrame:
    """``home_forma_reale``, ``away_forma_reale`` e relativi campioni per ogni partita (solo gare precedenti)."""
    rows = []
    for match in matches.itertuples():
        when = pd.Timestamp(match.date).normalize()
        home = forma_reale(store, match.league, canonical_key(match.home_team), "home", when)
        away = forma_reale(store, match.league, canonical_key(match.away_team), "away", when)
        rows.append({"home_forma_reale": home.valore if home.valore is not None else np.nan, "home_forma_n": home.campione,
                     "away_forma_reale": away.valore if away.valore is not None else np.nan, "away_forma_n": away.campione})
    return pd.DataFrame(rows, index=matches.index)


# --- Foglio «Stile» ---------------------------------------------------------------------------------------------

SHEET_COLUMNS = ("Squadra", "Campo", "Parametro", "Descrizione", "Valore", "Campione", "Fonte", "Avviso")


def sheet_rows(profiles: Iterable[Mapping]) -> list[dict]:
    rows = []
    for profile in profiles:
        if not profile or not profile.get("parametri") and not profile.get("forma_reale"):
            continue
        campo = "casa" if profile.get("campo") == "home" else "trasferta"
        entries = [("forma_reale", "forma reale = (xG−xGA) centrata sul campionato", profile.get("forma_reale"))]
        entries += [(name, PARAMS[name][1], item) for name, item in profile["parametri"].items()]
        for name, description, item in entries:
            if not item:
                continue
            value = item.get("valore")
            rows.append({"Squadra": profile["squadra"], "Campo": campo, "Parametro": name, "Descrizione": description,
                         "Valore": None if value is None else round(float(value), 4), "Campione": item.get("campione"),
                         "Fonte": item.get("fonte"), "Avviso": item.get("avviso") or ""})
    return rows
