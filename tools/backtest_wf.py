"""Banco walk-forward (fase AD): confronta due configurazioni del motore su più campionati e mercati.

Ogni partita è prevista SOLO con quello che si sapeva prima: le feature (``tools.dataset.build_features``) e il profilo di
stile (``style_profile``) usano gare con data precedente; il coefficiente ``phi`` della forma reale è ristimato ogni
mese sul passato (finestra espandibile, penalità ridge) e applicato al mese successivo. I parametri globali del modello
gol (``config/goal_model.json``) sono congelati e identici nelle due configurazioni (il confronto è appaiato).
Il proxy xG dei tiri per le feature è stimato sulle stagioni precedenti alla prima stagione di prova.

Mercati: 1X2, Over/Under gol, GG/NG, primo e secondo tempo, corner e gialli (totali e per squadra), gol e corner per
squadra, combo. Misure: log-loss, Brier, ECE per fasce; differenza appaiata con errore standard; le quote di chiusura dei
CSV sono un riferimento a parte (1X2, Over/Under 2.5). Output: ``docs/backtest/<nome>.md`` e ``.csv``.

    python -m tools.backtest_wf --nome forma_reale --campionati I1 E0 D1 SC0 D2 --stagioni 2324 2425 2526
    run(config_attuale, config_nuova, campionati, stagioni, mercati)     # da codice, per la fase AK

Opzioni di configurazione: ``forma_reale`` (bool), ``phi`` (numero o ``"walkforward"``), ``k_xg`` (peso xG con poche gare),
``ridge`` (penalità di phi).
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import binom

import engine
import style_profile
from datasources.cache import SourceCache
from datasources.sources import COMPETITIONS, Understat
from tools import baseline, dataset
from tools.calibrate import CARD_LINES, CORNER_LINES, count_sf, score_matrices

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "backtest"
CACHE = ROOT / "data" / "cache" / "ad"
DEFAULT_LEAGUES = ("I1", "E0", "D1", "SC0", "D2")
DEFAULT_SEASONS = ("2324", "2425", "2526")
ATTUALE = {"forma_reale": False}
MIN_PRIOR_MATCHES = 400
MAX_GOALS = 12
TEAM_CORNER_LINE = 4.5


# --- Dati ---------------------------------------------------------------------------------------------------------

def _season_start(code: str) -> int:
    return 2000 + int(code[:2])


def _understat_frames(leagues: Sequence[str], seasons: Sequence[str]) -> pd.DataFrame | None:
    names = {entry["footballdata"]: entry["understat"] for entry in COMPETITIONS.values() if entry["understat"]}
    understat = Understat(SourceCache())
    frames = []
    for code in leagues:
        if code not in names:
            continue
        for season in seasons:
            frame = understat.league(names[code], _season_start(season), timedelta(days=3650)).data
            if len(frame):
                frames.append(frame.assign(league=code))
    return pd.concat(frames, ignore_index=True) if frames else None


def _slug(*parts: Any) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def prepare(leagues: Sequence[str], seasons: Sequence[str], refresh: bool = False) -> tuple[pd.DataFrame, style_profile.StyleStore]:
    """Feature pre-partita (solo passato) con colonne di forma reale, e archivio di stile. Cache su disco."""
    CACHE.mkdir(parents=True, exist_ok=True)
    first = min(seasons)
    all_seasons = tuple(season for season in dataset.ALL_SEASONS if season <= max(seasons))
    path = CACHE / f"feature_{_slug(sorted(leagues), all_seasons)}.pkl"
    if path.exists() and not refresh:
        return pd.read_pickle(path)
    raw = dataset.load_raw(tuple(leagues), all_seasons)
    before = raw[raw["season"] < first]
    xg_model = dataset.fit_shot_xg(before.assign(season="1920"))     # solo stagioni precedenti alla prima di prova
    features = dataset.build_features(raw, xg_model)
    features = features[dataset.usable(features)].reset_index(drop=True)
    proxy = {"a_tiri_in_porta": xg_model.on_target, "b_altri_tiri": xg_model.off_target}
    understat = _understat_frames(leagues, all_seasons)
    store = style_profile.StyleStore(style_profile.build_table(raw, understat, proxy))
    features = features.join(style_profile.forma_reale_columns(store, features))
    pd.to_pickle((features, store), path)
    return features, store


# --- Stima di phi (walk-forward) ---------------------------------------------------------------------------------

def _fit_phi(delta: np.ndarray, goals_home: np.ndarray, goals_away: np.ndarray, lam: np.ndarray, mu: np.ndarray,
             ridge: float) -> float:
    shift = 0.5 * delta

    def loss(phi: float) -> float:
        return float(np.mean(lam * np.exp(shift * phi) - goals_home * shift * phi
                             + mu * np.exp(-shift * phi) + goals_away * shift * phi) + ridge * phi ** 2)

    return float(minimize_scalar(loss, bounds=(-1.0, 3.0), method="bounded").x)


def walkforward_phi(features: pd.DataFrame, lam: np.ndarray, mu: np.ndarray, ridge: float) -> tuple[np.ndarray, dict[str, float]]:
    """phi per partita: ristimato ogni mese su TUTTE le partite con data < primo giorno del mese (mai sul futuro)."""
    dates = pd.to_datetime(features["date"]).to_numpy()
    delta = np.nan_to_num((features["home_forma_reale"] - features["away_forma_reale"]).to_numpy(float))
    month = pd.to_datetime(features["date"]).dt.to_period("M")
    phi = np.zeros(len(features))
    history = {}
    goals_home, goals_away = features["home_goals"].to_numpy(float), features["away_goals"].to_numpy(float)
    for period in sorted(month.unique()):
        start = period.start_time.to_datetime64()
        past = dates < start
        value = _fit_phi(delta[past], goals_home[past], goals_away[past], lam[past], mu[past], ridge) \
            if past.sum() >= MIN_PRIOR_MATCHES else 0.0
        phi[(month == period).to_numpy()] = value
        history[str(period)] = round(value, 4)
    return phi, history


# --- Previsioni ---------------------------------------------------------------------------------------------------

def _row_config(row: Mapping[str, Any], style_on: bool, k_xg: float) -> engine.MatchConfig:
    style = None
    if style_on and np.isfinite(row["home_forma_reale"]) and np.isfinite(row["away_forma_reale"]):
        style = {"home": {"forma_reale": row["home_forma_reale"], "n_gare": row["home_forma_n"]},
                 "away": {"forma_reale": row["away_forma_reale"], "n_gare": row["away_forma_n"]}}
    return baseline.config_for_row(row, style=style, style_model=engine.StyleModelParams(style_on, 0.0, k_xg if style_on else 0.0))


def predict(features: pd.DataFrame, option: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """λ, μ e medie dei conteggi di una configurazione; con ``phi`` walk-forward applicato in forma chiusa."""
    style_on = bool(option.get("forma_reale", False))
    k_xg = float(option.get("k_xg", 0.0) if "k_xg" in option else (engine.DEFAULT_STYLE_MODEL.k_xg if style_on else 0.0))
    lam, mu, corner_home, corner_away, cards = [], [], [], [], []
    for row in features.to_dict("records"):
        config = _row_config(row, style_on, k_xg)
        value_lambda, value_mu, _ = engine.expected_goals(config)
        home, away = engine.corner_signals(config)
        lam.append(value_lambda), mu.append(value_mu), corner_home.append(home), corner_away.append(away)
        cards.append(engine.card_total_mean(config))
    result = {"lambda": np.array(lam), "mu": np.array(mu), "corner_home": np.array(corner_home),
              "corner_away": np.array(corner_away), "cards": np.array(cards), "phi": np.zeros(len(features))}
    result["lambda0"], result["mu0"] = result["lambda"].copy(), result["mu"].copy()
    if style_on:
        phi_option = option.get("phi", "walkforward")
        if phi_option == "walkforward":
            phi, history = walkforward_phi(features, result["lambda"], result["mu"], float(option.get("ridge", 0.01)))
            result["phi_history"] = history
        else:
            phi = np.full(len(features), float(phi_option))
        delta = np.nan_to_num((features["home_forma_reale"] - features["away_forma_reale"]).to_numpy(float))
        result["lambda"] = np.clip(result["lambda"] * np.exp(0.5 * phi * delta), 0.05, 5.0)
        result["mu"] = np.clip(result["mu"] * np.exp(-0.5 * phi * delta), 0.05, 5.0)
        result["phi"] = phi
    return result


# --- Mercati ------------------------------------------------------------------------------------------------------

def _second_half(matrix: np.ndarray, lam: np.ndarray, mu: np.ndarray) -> dict[str, np.ndarray]:
    half = engine.DEFAULT_HALF_TIME
    goals = np.arange(matrix.shape[1])
    home_share, away_share = engine.first_half_shares(lam, mu, half)
    second_home = np.clip(1.0 - np.broadcast_to(home_share, lam.shape), 0.05, 0.95)
    second_away = np.clip(1.0 - np.broadcast_to(away_share, lam.shape), 0.05, 0.95)
    thin_home = binom.pmf(goals[None, None, :], goals[None, :, None], second_home[:, None, None])
    thin_away = binom.pmf(goals[None, None, :], goals[None, :, None], second_away[:, None, None])
    joint = np.einsum("ngk,ngh,nhl->nkl", thin_home, matrix, thin_away)
    total = np.add.outer(goals, goals)
    return {"Over 0.5 2T": joint[:, total >= 1].sum(axis=1), "Over 1.5 2T": joint[:, total >= 2].sum(axis=1)}


def market_table(features: pd.DataFrame, prediction: Mapping[str, np.ndarray]) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """mercato -> (probabilità (N, K) , esito (N,) , maschera di righe valide)."""
    rho = engine.DEFAULT_GOAL_PARAMS.dixon_coles_rho
    lam, mu = prediction["lambda"], prediction["mu"]
    matrix = score_matrices(lam, mu, rho, MAX_GOALS)
    goals = np.arange(matrix.shape[1])
    home_idx, away_idx = np.indices(matrix.shape[1:])
    total = home_idx + away_idx
    home = features["home_goals"].to_numpy(int)
    away = features["away_goals"].to_numpy(int)
    full = np.ones(len(features), dtype=bool)
    out: dict[str, tuple] = {}

    def add(name: str, probability: np.ndarray, outcome: np.ndarray, mask: np.ndarray = full) -> None:
        probability = np.asarray(probability, dtype=float)
        out[name] = (probability if probability.ndim == 2 else baseline.binary(probability), outcome.astype(int), mask)

    add("1X2", np.column_stack([matrix[:, home_idx > away_idx].sum(axis=1), matrix[:, home_idx == away_idx].sum(axis=1),
                                matrix[:, home_idx < away_idx].sum(axis=1)]),
        np.select([home > away, home == away], [0, 1], 2))
    for line in (1.5, 2.5, 3.5):
        add(f"Over {line:g} gol", matrix[:, total > line].sum(axis=1), (home + away) > line)
    add("GG", matrix[:, 1:, 1:].sum(axis=(1, 2)), (home > 0) & (away > 0))
    for side, prob_goals, scored in (("Casa", matrix.sum(axis=2), home), ("Ospite", matrix.sum(axis=1), away)):
        for line in (0.5, 1.5):
            add(f"{side} Over {line:g} gol", prob_goals[:, goals > line].sum(axis=1), scored > line)
    add("Over 2.5 + GG", matrix[:, (total > 2) & (home_idx > 0) & (away_idx > 0)].sum(axis=1),
        ((home + away) > 2) & (home > 0) & (away > 0))
    add("Casa vince + Over 1.5", matrix[:, (home_idx > away_idx) & (total > 1)].sum(axis=1), (home > away) & ((home + away) > 1))
    add("Under 2.5 + NG", matrix[:, (total < 3) & ((home_idx == 0) | (away_idx == 0))].sum(axis=1),
        ((home + away) < 3) & ((home == 0) | (away == 0)))

    # primo e secondo tempo
    has_half = features[["home_ht_goals", "away_ht_goals"]].notna().all(axis=1).to_numpy()
    half_markets = baseline.secondary_markets(lam, mu, rho, engine.DEFAULT_HALF_TIME)
    ht = features[["home_ht_goals", "away_ht_goals"]].fillna(0).to_numpy(int)
    home_ht, away_ht = ht[:, 0], ht[:, 1]
    add("1X2 1T", half_markets["1X2 1T"], np.select([home_ht > away_ht, home_ht == away_ht], [0, 1], 2), has_half)
    add("Over 0.5 1T", half_markets["Over 0.5 1T"], (home_ht + away_ht) >= 1, has_half)
    add("Over 1.5 1T", half_markets["Over 1.5 1T"], (home_ht + away_ht) >= 2, has_half)
    second = (home - home_ht) + (away - away_ht)
    for name, probability in _second_half(matrix, lam, mu).items():
        add(name, probability, second >= (1 if "0.5" in name else 2), has_half)

    # corner e gialli (totali e per squadra); distribuzione come nel motore
    counts = engine.DEFAULT_COUNT_MODEL
    shape_corner = counts.corner_dispersion if counts.active else 0.0
    shape_card = counts.card_dispersion if counts.active else 0.0
    corners = features[["home_corners", "away_corners"]]
    yellows = features[["home_yellows", "away_yellows"]]
    has_corner, has_card = corners.notna().all(axis=1).to_numpy(), yellows.notna().all(axis=1).to_numpy()
    corner_total = corners.fillna(0).sum(axis=1).to_numpy()
    card_total = yellows.fillna(0).sum(axis=1).to_numpy()
    for line in CORNER_LINES:
        add(f"Corner Over {line:g}", count_sf(line, prediction["corner_home"] + prediction["corner_away"], shape_corner),
            corner_total > line, has_corner)
    for line in CARD_LINES:
        add(f"Gialli Over {line:g}", count_sf(line, prediction["cards"], shape_card), card_total > line, has_card)
    for side, mean_key, column in (("Casa", "corner_home", "home_corners"), ("Ospite", "corner_away", "away_corners")):
        add(f"Corner {side} Over {TEAM_CORNER_LINE:g}", count_sf(TEAM_CORNER_LINE, prediction[mean_key], shape_corner),
            features[column].fillna(0).to_numpy() > TEAM_CORNER_LINE, has_corner)
    return out


def metrics(table: Mapping[str, tuple], scope: np.ndarray) -> dict[str, dict[str, float]]:
    result = {}
    for name, (probability, outcome, mask) in table.items():
        rows = scope & mask
        if rows.sum() >= 30:
            result[name] = {"n": int(rows.sum()), **baseline.summarize(probability[rows], outcome[rows])}
    return result


def _losses(probability: np.ndarray, outcome: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(probability[np.arange(len(outcome)), outcome], 1e-12, 1.0))


def closing_reference(features: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Quote di chiusura dei CSV senza margine: riferimento a parte (1X2 e Over/Under 2.5)."""
    home, away = features["home_goals"].to_numpy(int), features["away_goals"].to_numpy(int)
    have_1x2 = features[["close_home", "close_draw", "close_away"]].gt(1.0).all(axis=1).to_numpy()
    have_ou = features[["close_over25", "close_under25"]].gt(1.0).all(axis=1).to_numpy()
    odds_1x2 = features[["close_home", "close_draw", "close_away"]].fillna(2.0).to_numpy(float)
    odds_ou = features[["close_over25", "close_under25"]].fillna(2.0).to_numpy(float)
    return {"1X2": (baseline.de_vig(*odds_1x2.T), np.select([home > away, home == away], [0, 1], 2), have_1x2),
            "Over 2.5 gol": (baseline.de_vig(odds_ou[:, 1], odds_ou[:, 0]), ((home + away) > 2).astype(int), have_ou)}


# --- Banco ----------------------------------------------------------------------------------------------------------

def run(config_attuale: Mapping[str, Any] | None, config_nuova: Mapping[str, Any] | None,
        campionati: Sequence[str] = DEFAULT_LEAGUES, stagioni: Sequence[str] = DEFAULT_SEASONS,
        mercati: Sequence[str] | None = None, nome: str = "banco", refresh: bool = False, write: bool = True) -> dict[str, Any]:
    """Confronta due configurazioni; scrive ``docs/backtest/<nome>.md`` e ``.csv`` e ritorna le tabelle."""
    before, after = dict(config_attuale or ATTUALE), dict(config_nuova or {"forma_reale": True})
    features, _ = prepare(campionati, stagioni, refresh)
    test = features["season"].isin(stagioni).to_numpy()
    cache_path = CACHE / f"previsioni_{_slug(sorted(campionati), sorted(stagioni), before, after)}.pkl"
    if cache_path.exists() and not refresh:
        predictions = pd.read_pickle(cache_path)
    else:
        predictions = {"prima": predict(features, before), "dopo": predict(features, after)}
        pd.to_pickle(predictions, cache_path)
    tables = {name: market_table(features, prediction) for name, prediction in predictions.items()}
    reference = closing_reference(features)
    rows = []
    scopes = {"tutti": test}
    scopes.update({f"stagione {season}": (features["season"] == season).to_numpy() & test for season in stagioni})
    scopes.update({f"campionato {league}": (features["league"] == league).to_numpy() & test for league in campionati})
    for scope_name, scope in scopes.items():
        base, new = metrics(tables["prima"], scope), metrics(tables["dopo"], scope)
        for market in base:
            if mercati and market not in mercati:
                continue
            probability_a, outcome, mask = tables["prima"][market]
            probability_b = tables["dopo"][market][0]
            rows_ok = scope & mask
            delta = _losses(probability_b[rows_ok], outcome[rows_ok]) - _losses(probability_a[rows_ok], outcome[rows_ok])
            row = {"mercato": market, "ambito": scope_name, "n": base[market]["n"],
                   "log_loss_prima": base[market]["log_loss"], "log_loss_dopo": new[market]["log_loss"],
                   "differenza": float(delta.mean()), "errore_standard": float(delta.std(ddof=1) / np.sqrt(len(delta))),
                   "brier_prima": base[market]["brier"], "brier_dopo": new[market]["brier"],
                   "ece_prima": base[market]["ece"], "ece_dopo": new[market]["ece"]}
            if market in reference:
                ref_probability, ref_outcome, ref_mask = reference[market]
                ok = scope & ref_mask & mask
                row["log_loss_chiusura"] = float(baseline.log_loss(ref_probability[ok], ref_outcome[ok])) if ok.sum() >= 30 else np.nan
            rows.append(row)
    frame = pd.DataFrame(rows)
    result = {"metriche": frame, "predizioni": predictions, "feature": features, "tabelle": tables,
              "phi": predictions["dopo"].get("phi_history", {}), "config": {"prima": before, "dopo": after},
              "campionati": list(campionati), "stagioni": list(stagioni)}
    if write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        frame.to_csv(OUT_DIR / f"{nome}.csv", index=False)
        (OUT_DIR / f"{nome}.md").write_text(render(nome, result, test), encoding="utf-8")
    return result


def _fmt(value: Any, digits: int = 4) -> str:
    return "—" if value is None or (isinstance(value, float) and np.isnan(value)) else f"{value:.{digits}f}"


def render(nome: str, result: Mapping[str, Any], test: np.ndarray) -> str:
    frame = result["metriche"]
    lines = [f"# Banco walk-forward: {nome}", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.backtest_wf`. Campionati {', '.join(result['campionati'])}, "
             f"stagioni di prova {', '.join(result['stagioni'])} ({int(test.sum())} partite). "
             f"Prima = `{json.dumps(result['config']['prima'], ensure_ascii=False)}`, dopo = `{json.dumps(result['config']['dopo'], ensure_ascii=False)}`.", "",
             "Metodo: feature e profilo di stile solo dal passato; phi ristimato ogni mese sul passato; parametri globali del "
             "modello gol congelati e uguali nelle due configurazioni (confronto appaiato). Previsioni del solo modello (non "
             "ancorato alle quote). La differenza di log-loss è dopo − prima: negativa = migliora.", ""]
    overall = frame[frame["ambito"] == "tutti"]
    lines += ["## Tutti i campionati e le stagioni", "",
              "| Mercato | N | Log-loss prima | Log-loss dopo | Differenza ± e.s. | Brier prima→dopo | ECE prima→dopo | Chiusura |",
              "|---|---|---|---|---|---|---|---|"]
    for row in overall.itertuples():
        lines.append(f"| {row.mercato} | {row.n} | {_fmt(row.log_loss_prima)} | {_fmt(row.log_loss_dopo)} | "
                     f"{row.differenza:+.5f} ± {row.errore_standard:.5f} | {_fmt(row.brier_prima)}→{_fmt(row.brier_dopo)} | "
                     f"{_fmt(row.ece_prima)}→{_fmt(row.ece_dopo)} | {_fmt(getattr(row, 'log_loss_chiusura', None))} |")
    for prefix, title in (("stagione", "Per stagione"), ("campionato", "Per campionato")):
        lines += ["", f"## {title}", "", "| Ambito | Mercato | N | Differenza ± e.s. | Log-loss prima→dopo |", "|---|---|---|---|---|"]
        part = frame[frame["ambito"].str.startswith(prefix) & frame["mercato"].isin(["1X2", "Over 2.5 gol", "GG", "Over 1.5 1T"])]
        for row in part.itertuples():
            lines.append(f"| {row.ambito} | {row.mercato} | {row.n} | {row.differenza:+.5f} ± {row.errore_standard:.5f} | "
                         f"{_fmt(row.log_loss_prima)}→{_fmt(row.log_loss_dopo)} |")
    table = result["tabelle"]
    for name in ("prima", "dopo"):
        probability, outcome, mask = table[name]["1X2"]
        scope = test & mask
        calibration = baseline.calibration_table(probability[scope], outcome[scope])
        lines += ["", f"## Calibrazione 1X2 per fasce ({name})", "", "| Fascia | N | Prevista | Osservata |", "|---|---|---|---|"]
        lines += [f"| {r.fascia} | {r.n} | {r.prevista:.3f} | {r.osservata:.3f} |" for r in calibration.itertuples()]
    if result["phi"]:
        lines += ["", "## phi della forma reale per mese (stimato solo sul passato)", "",
                  ", ".join(f"{month}: {value:+.3f}" for month, value in result["phi"].items() if month >= f"20{min(result['stagioni'])[:2]}")]
    return "\n".join(lines) + "\n"


def fit_final_phi(result: Mapping[str, Any], ridge: float = 0.01) -> dict[str, Any]:
    """phi unico per l'app: stimato su tutte le partite fino ad oggi (le previsioni walk-forward restano quelle del banco)."""
    features, prediction = result["feature"], result["predizioni"]["dopo"]
    delta = np.nan_to_num((features["home_forma_reale"] - features["away_forma_reale"]).to_numpy(float))
    phi = _fit_phi(delta, features["home_goals"].to_numpy(float), features["away_goals"].to_numpy(float),
                   prediction["lambda0"], prediction["mu0"], ridge)
    return {"phi": round(float(phi), 5), "stimato": {"data": date.today().isoformat(), "partite": int(len(features)),
                                                      "campionati": result["campionati"], "ridge": ridge,
                                                      "ultima_stagione": str(features["season"].max())}}


def save_phi(estimate: Mapping[str, Any], path: Path = ROOT / "config" / "stile.json") -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["forma_reale"]["phi"] = estimate["phi"]
    data["forma_reale"]["stimato"] = estimate["stimato"]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--nome", default="forma_reale")
    parser.add_argument("--campionati", nargs="+", default=list(DEFAULT_LEAGUES))
    parser.add_argument("--stagioni", nargs="+", default=list(DEFAULT_SEASONS))
    parser.add_argument("--nuova", default='{"forma_reale": true, "phi": "walkforward"}')
    parser.add_argument("--attuale", default=json.dumps(ATTUALE))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--salva-phi", action="store_true", help="scrive in config/stile.json il phi stimato su tutto il passato")
    args = parser.parse_args()
    result = run(json.loads(args.attuale), json.loads(args.nuova), args.campionati, args.stagioni, nome=args.nome, refresh=args.refresh)
    if args.salva_phi:
        estimate = fit_final_phi(result)
        save_phi(estimate)
        print("phi salvato:", estimate)
    overall = result["metriche"][result["metriche"]["ambito"] == "tutti"]
    print(overall[["mercato", "n", "log_loss_prima", "log_loss_dopo", "differenza", "errore_standard"]].to_string(index=False))


if __name__ == "__main__":
    main()
