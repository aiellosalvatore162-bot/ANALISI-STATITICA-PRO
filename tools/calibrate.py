"""Taratura dei parametri del modello gol su partite storiche reali.

Minimizza log-loss 1X2 + log-loss Over/Under 2.5 sulle stagioni di taratura,
usando la stessa ``engine.goal_rates`` dell'app. Il modello tarato diventa
attivo solo se migliora la formula originale sulla stagione fuori campione;
altrimenti il file lo salva ma lascia ``modello_attivo = "legacy"``.

Con ``--primo-tempo`` tara invece la quota di gol del primo tempo (casa e
ospite, eventualmente in funzione dei gol attesi totali).

Uso: ``python -m tools.calibrate [--primo-tempo]`` (aggiorna
``config/goal_model.json`` lasciando intatte le altre sezioni).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, fields, replace
from datetime import date
import json
import math

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

import engine
from tools import baseline, dataset


MAX_GOALS = 10
BOUNDS = {
    "base_goals": (0.9, 2.0),
    "home_advantage": (0.0, 0.6),
    "attack_weight": (0.0, 2.0),
    "defense_weight": (0.0, 2.0),
    "attack_xg_share": (0.0, 1.0),
    "defense_xg_share": (0.0, 1.0),
    "elo_k": (0.0, 4.0),
    "form_weight": (-0.5, 0.5),
    "dixon_coles_rho": (-0.2, 0.1),
}
PARAMETER_NAMES = [item.name for item in fields(engine.GoalModelParams)]
# Componenti che si possono spegnere e soglia minima di guadagno (log-loss)
# fuori campione per lasciarle attive.
OPTIONAL_COMPONENTS = {"forma": {"form_weight": 0.0}}
MIN_IMPROVEMENT = 0.001


def score_matrices(lambda_: np.ndarray, mu: np.ndarray, rho: float, max_goals: int = MAX_GOALS) -> np.ndarray:
    """Matrici Dixon-Coles (N, G, G) vettoriali, equivalenti a ``engine.dixon_coles_matrix``."""
    goals = np.arange(max_goals + 1)
    home = poisson.pmf(goals[None, :], np.asarray(lambda_)[:, None])
    away = poisson.pmf(goals[None, :], np.asarray(mu)[:, None])
    matrix = home[:, :, None] * away[:, None, :]
    matrix[:, 0, 0] *= np.clip(1.0 - lambda_ * mu * rho, 0.0, None)
    matrix[:, 0, 1] *= np.clip(1.0 + mu * rho, 0.0, None)
    matrix[:, 1, 0] *= np.clip(1.0 + lambda_ * rho, 0.0, None)
    matrix[:, 1, 1] *= max(0.0, 1.0 - rho)
    return matrix / matrix.sum(axis=(1, 2), keepdims=True)


def market_probabilities(matrix: np.ndarray) -> dict[str, np.ndarray]:
    home_goals, away_goals = np.indices(matrix.shape[1:])
    return {
        "1x2": np.stack([
            matrix[:, home_goals > away_goals].sum(axis=1),
            matrix[:, home_goals == away_goals].sum(axis=1),
            matrix[:, home_goals < away_goals].sum(axis=1),
        ], axis=1),
        "over25": matrix[:, home_goals + away_goals > 2].sum(axis=1),
    }


def model_inputs(features: pd.DataFrame) -> dict[str, np.ndarray]:
    """Gli stessi input che ``engine.expected_goals`` riceve dal parser."""
    return {
        "home_attack": features["home_attack"].to_numpy(float),
        "home_defense": features["home_defense"].to_numpy(float),
        "home_xg_for": features["home_xg_for"].to_numpy(float),
        "home_xg_against": features["home_xg_against"].to_numpy(float),
        "home_form": features["home_form"].map(engine.form_score).to_numpy(float),
        "away_attack": features["away_attack"].to_numpy(float),
        "away_defense": features["away_defense"].to_numpy(float),
        "away_xg_for": features["away_xg_for"].to_numpy(float),
        "away_xg_against": features["away_xg_against"].to_numpy(float),
        "away_form": features["away_form"].map(engine.form_score).to_numpy(float),
        "elo_diff": (features["home_elo"] - features["away_elo"]).to_numpy(float),
    }


def outcomes(features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    result = np.select(
        [features["home_goals"] > features["away_goals"], features["home_goals"] == features["away_goals"]], [0, 1], 2
    )
    over = ((features["home_goals"] + features["away_goals"]) > 2).to_numpy().astype(int)
    return result, over


def objective(params: engine.GoalModelParams, inputs: dict[str, np.ndarray], result: np.ndarray, over: np.ndarray) -> float:
    lambda_, mu, _ = engine.goal_rates(params, **inputs)
    probabilities = market_probabilities(score_matrices(lambda_, mu, params.dixon_coles_rho))
    return (baseline.log_loss(probabilities["1x2"], result)
            + baseline.log_loss(baseline.binary(probabilities["over25"]), over))


def fit(features: pd.DataFrame, fixed: dict[str, float] | None = None) -> tuple[engine.GoalModelParams, float]:
    """Stima i parametri liberi; quelli in ``fixed`` restano al valore dato."""
    fixed = fixed or {}
    free = [name for name in PARAMETER_NAMES if name not in fixed]
    inputs = model_inputs(features)
    result, over = outcomes(features)
    start = np.array([getattr(engine.GoalModelParams(), name) for name in free])

    def build(vector: np.ndarray) -> engine.GoalModelParams:
        return engine.GoalModelParams(**fixed, **dict(zip(free, (float(value) for value in vector))))

    fitted = minimize(
        lambda vector: objective(build(vector), inputs, result, over),
        start, method="L-BFGS-B", bounds=[BOUNDS[name] for name in free],
    )
    if not fitted.success:
        raise RuntimeError(f"Taratura non convergente: {fitted.message}")
    params = engine.GoalModelParams(**{name: round(value, 6) for name, value in asdict(build(fitted.x)).items()})
    return params, float(fitted.fun)


def select_components(train: pd.DataFrame, holdout: pd.DataFrame) -> tuple[engine.GoalModelParams, float, dict]:
    """Tiene una componente opzionale solo se migliora il fuori campione di almeno MIN_IMPROVEMENT."""
    holdout_inputs, (holdout_result, holdout_over) = model_inputs(holdout), outcomes(holdout)
    fixed: dict[str, float] = {}
    report = {}
    for component, disabled in OPTIONAL_COMPONENTS.items():
        with_component, _ = fit(train, fixed)
        without_component, _ = fit(train, {**fixed, **disabled})
        gain = (objective(without_component, holdout_inputs, holdout_result, holdout_over)
                - objective(with_component, holdout_inputs, holdout_result, holdout_over))
        active = gain >= MIN_IMPROVEMENT
        report[component] = {"attiva": bool(active), "miglioramento_fuori_campione": round(float(gain), 5)}
        if not active:
            fixed.update(disabled)
    params, train_loss = fit(train, fixed)
    return params, train_loss, report


def holdout_loss(features: pd.DataFrame, **overrides) -> float:
    """Log-loss 1X2 + O/U 2.5 calcolato con il motore vero (``baseline.predict``)."""
    predictions = baseline.predict(features, **overrides)
    result, over = outcomes(features)
    return (baseline.log_loss(predictions[["p_home", "p_draw", "p_away"]].to_numpy(), result)
            + baseline.log_loss(baseline.binary(predictions["p_over25"]), over))


def _update_config(sections: dict) -> dict:
    """Aggiorna solo le sezioni indicate del file di configurazione."""
    path = engine.GOAL_MODEL_PATH
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(sections)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def _logit(value: float) -> float:
    return math.log(value / (1.0 - value))


def half_time_nll(params: engine.HalfTimeParams, data: pd.DataFrame) -> float:
    """Verosimiglianza binomiale dei gol del primo tempo dato il risultato finale."""
    home_share, away_share = engine.first_half_shares(data["final_lambda"], data["final_mu"], params)
    loss = 0.0
    for share, first, total in (
        (home_share, data["home_ht_goals"], data["home_goals"]),
        (away_share, data["away_ht_goals"], data["away_goals"]),
    ):
        loss -= np.sum(first * np.log(share) + (total - first) * np.log(1.0 - share))
    return float(loss / len(data))


def fit_half_time(data: pd.DataFrame, *, with_slope: bool) -> engine.HalfTimeParams:
    reference = round(float((data["final_lambda"] + data["final_mu"]).mean()), 2)

    def build(vector: np.ndarray) -> engine.HalfTimeParams:
        home, away = 1.0 / (1.0 + np.exp(-vector[:2]))
        return engine.HalfTimeParams(float(home), float(away), float(vector[2]) if with_slope else 0.0, reference)

    start = np.array([0.0, 0.0, 0.0][: 3 if with_slope else 2])
    fitted = minimize(lambda vector: half_time_nll(build(vector), data), start, method="L-BFGS-B")
    if not fitted.success:
        raise RuntimeError(f"Taratura primo tempo non convergente: {fitted.message}")
    params = build(fitted.x)
    return engine.HalfTimeParams(**{key: round(value, 6) for key, value in asdict(params).items()})


def first_half_loss(params: engine.HalfTimeParams, data: pd.DataFrame, rho: float) -> float:
    """Somma dei log-loss dei mercati del primo tempo (1X2 1T, Over 0.5/1.5 1T, GG 1T)."""
    markets = baseline.secondary_markets(data["final_lambda"], data["final_mu"], rho, params)
    observed = baseline.secondary_outcomes(data)
    mask = np.ones(len(data), dtype=bool)
    scores = baseline.secondary_scores({name: markets[name] for name in baseline.FIRST_HALF_MARKETS}, observed, mask)
    return float(sum(score["log_loss"] for score in scores.values()))


def calibrate_half_time() -> dict:
    features = baseline.secondary_features(baseline.load_usable_features())
    data = features.assign(**baseline.secondary_rates(features))
    train = data[data["season"].isin(dataset.CALIBRATION_SEASONS)]
    holdout = data[data["season"].isin(dataset.HOLDOUT_SEASONS)]
    rho = engine.DEFAULT_GOAL_PARAMS.dixon_coles_rho

    candidates = {
        "metà e metà": engine.HalfTimeParams(),
        "quote fisse casa/ospite": fit_half_time(train, with_slope=False),
        "quote in funzione dei gol attesi": fit_half_time(train, with_slope=True),
    }
    metrics = {
        name: {
            "nll_binomiale_taratura": round(half_time_nll(params, train), 5),
            "nll_binomiale_fuori_campione": round(half_time_nll(params, holdout), 5),
            "logloss_mercati_1T_taratura": round(first_half_loss(params, train, rho), 5),
            "logloss_mercati_1T_fuori_campione": round(first_half_loss(params, holdout, rho), 5),
        }
        for name, params in candidates.items()
    }
    fixed, sloped = "quote fisse casa/ospite", "quote in funzione dei gol attesi"
    gain = metrics[fixed]["logloss_mercati_1T_fuori_campione"] - metrics[sloped]["logloss_mercati_1T_fuori_campione"]
    chosen = sloped if gain >= MIN_IMPROVEMENT else fixed
    section = {
        "parametri": asdict(candidates[chosen]),
        "taratura": {
            "data": date.today().isoformat(),
            "scelta": chosen,
            "regola": f"la dipendenza dai gol attesi resta solo se migliora il log-loss 1T fuori campione di almeno {MIN_IMPROVEMENT}",
            "gol_attesi": "finali, ancorati alle quote di chiusura 1X2 e O/U 2.5",
            "partite_taratura": int(len(train)),
            "partite_fuori_campione": int(len(holdout)),
            "candidati": {name: {"parametri": asdict(params), **metrics[name]} for name, params in candidates.items()},
        },
    }
    _update_config({"primo_tempo": section})
    return section


# --- Corner e cartellini ----------------------------------------------------------------

CORNER_LINES = (8.5, 9.5, 10.5)
CARD_LINES = (3.5, 4.5, 5.5)


def count_data(features: pd.DataFrame) -> pd.DataFrame:
    """Partite con input e risultati di corner e gialli disponibili."""
    required = ["home_corners", "away_corners", "home_yellows", "away_yellows", "referee_yellow_avg", "referee_fouls_avg"]
    return features.dropna(subset=required)


def count_means(params: engine.CountModelParams, data: pd.DataFrame) -> dict[str, np.ndarray]:
    """Versione vettoriale di ``engine.corner_signals`` e ``engine.card_total_mean``."""
    def log(column: str) -> np.ndarray:
        return np.log(np.maximum(data[column].to_numpy(float), 0.1))

    if params.active:
        home = np.exp(params.corner_home_intercept + params.corner_for_weight * log("home_corners_for")
                      + params.corner_against_weight * log("away_corners_against"))
        away = np.exp(params.corner_away_intercept + params.corner_for_weight * log("away_corners_for")
                      + params.corner_against_weight * log("home_corners_against"))
        team_cards = (data["home_cards_for"] + data["away_cards_for"]).to_numpy(float)
        cards = np.exp(params.card_intercept + params.card_team_weight * np.log(np.maximum(team_cards, 1e-9))
                       + params.card_referee_yellow_weight * np.log(data["referee_yellow_avg"].to_numpy(float))
                       + params.card_referee_fouls_weight * np.log(data["referee_fouls_avg"].to_numpy(float)))
    else:
        home = ((data["home_corners_for"] + data["away_corners_against"]) / 2.0).to_numpy(float)
        away = ((data["away_corners_for"] + data["home_corners_against"]) / 2.0).to_numpy(float)
        cards = ((data["home_cards_for"] + data["away_cards_for"]) * np.maximum(data["referee_yellow_avg"] / 4.5, 0)
                 * np.maximum(data["referee_fouls_avg"] / 24.0, 0)).to_numpy(float)
    return {"corner_home": home, "corner_away": away, "cards": cards}


def count_logpmf(counts: np.ndarray, mean: np.ndarray, dispersion: float) -> np.ndarray:
    from scipy.stats import nbinom

    mean = np.maximum(mean, 1e-9)
    if dispersion > 0:
        return nbinom.logpmf(counts, dispersion, dispersion / (dispersion + mean))
    return poisson.logpmf(counts, mean)


def count_sf(threshold: float, mean: np.ndarray, dispersion: float) -> np.ndarray:
    """P(conteggio > threshold) con la stessa distribuzione del motore."""
    from scipy.stats import nbinom

    mean = np.maximum(mean, 1e-9)
    if dispersion > 0:
        return nbinom.sf(np.floor(threshold), dispersion, dispersion / (dispersion + mean))
    return poisson.sf(np.floor(threshold), mean)


def corner_nll(params: engine.CountModelParams, data: pd.DataFrame) -> float:
    """Totale binomiale negativo/Poisson più ripartizione binomiale casa/ospite, come nel motore."""
    from scipy.stats import binom

    means = count_means(params, data)
    total_mean = means["corner_home"] + means["corner_away"]
    home, away = data["home_corners"].to_numpy(int), data["away_corners"].to_numpy(int)
    dispersion = params.corner_dispersion if params.active else 0.0
    loglik = count_logpmf(home + away, total_mean, dispersion) + binom.logpmf(home, home + away, means["corner_home"] / total_mean)
    return float(-np.mean(loglik))


def card_nll(params: engine.CountModelParams, data: pd.DataFrame) -> float:
    total = (data["home_yellows"] + data["away_yellows"]).to_numpy(int)
    dispersion = params.card_dispersion if params.active else 0.0
    return float(-np.mean(count_logpmf(total, count_means(params, data)["cards"], dispersion)))


def _fit_counts(data: pd.DataFrame, names: list[str], loss, fixed: dict) -> engine.CountModelParams:
    start = {"corner_home_intercept": 0.0, "corner_away_intercept": 0.0, "corner_for_weight": 0.5,
             "corner_against_weight": 0.5, "corner_dispersion": 1.0, "card_intercept": 0.0, "card_team_weight": 1.0,
             "card_referee_yellow_weight": 0.5, "card_referee_fouls_weight": 0.0, "card_dispersion": 1.0}

    def build(vector: np.ndarray) -> engine.CountModelParams:
        values = dict(zip(names, vector))
        for key in ("corner_dispersion", "card_dispersion"):
            if key in values:
                values[key] = float(np.exp(values[key]))
        return engine.CountModelParams(active=True, **fixed, **values)

    initial = [math.log(start[name]) if name.endswith("dispersion") else start[name] for name in names]
    fitted = minimize(lambda vector: loss(build(vector), data), initial, method="L-BFGS-B")
    params = build(fitted.x)
    return engine.CountModelParams(**{key: (round(value, 6) if isinstance(value, float) else value)
                                      for key, value in asdict(params).items()})


def calibrate_counts() -> dict:
    features = baseline.load_usable_features()
    data = count_data(features)
    train = data[data["season"].isin(dataset.CALIBRATION_SEASONS)]
    holdout = data[data["season"].isin(dataset.HOLDOUT_SEASONS)]
    corner_names = ["corner_home_intercept", "corner_away_intercept", "corner_for_weight", "corner_against_weight"]
    card_names = ["card_intercept", "card_team_weight"]
    referee_names = ["card_referee_yellow_weight", "card_referee_fouls_weight"]
    choices: dict[str, dict] = {}

    # Corner: Poisson oppure binomiale negativa.
    poisson_fit = _fit_counts(train, corner_names, corner_nll, {"corner_dispersion": 0.0})
    nb_fit = _fit_counts(train, corner_names + ["corner_dispersion"], corner_nll, {})
    gain = corner_nll(poisson_fit, holdout) - corner_nll(nb_fit, holdout)
    corners = nb_fit if gain >= MIN_IMPROVEMENT else poisson_fit
    choices["corner_dispersione"] = {"attiva": bool(gain >= MIN_IMPROVEMENT), "miglioramento_fuori_campione": round(gain, 5)}

    # Cartellini: variabili dell'arbitro e dispersione.
    no_referee = {"card_referee_yellow_weight": 0.0, "card_referee_fouls_weight": 0.0}
    without_ref = _fit_counts(train, card_names + ["card_dispersion"], card_nll, no_referee)
    with_ref = _fit_counts(train, card_names + referee_names + ["card_dispersion"], card_nll, {})
    gain = card_nll(without_ref, holdout) - card_nll(with_ref, holdout)
    use_referee = gain >= MIN_IMPROVEMENT
    choices["cartellini_arbitro"] = {"attiva": bool(use_referee), "miglioramento_fuori_campione": round(gain, 5)}
    names = card_names + (referee_names if use_referee else [])
    fixed = {} if use_referee else no_referee
    cards_nb = with_ref if use_referee else without_ref
    cards_poisson = _fit_counts(train, names, card_nll, {**fixed, "card_dispersion": 0.0})
    gain = card_nll(cards_poisson, holdout) - card_nll(cards_nb, holdout)
    cards = cards_nb if gain >= MIN_IMPROVEMENT else cards_poisson
    choices["cartellini_dispersione"] = {"attiva": bool(gain >= MIN_IMPROVEMENT), "miglioramento_fuori_campione": round(gain, 5)}

    corner_fields = {key: value for key, value in asdict(corners).items() if key.startswith("corner")}
    card_fields = {key: value for key, value in asdict(cards).items() if key.startswith("card")}
    calibrated = engine.CountModelParams(active=True, **corner_fields, **card_fields)
    legacy = engine.CountModelParams()
    metrics = {
        name: {
            "corner_nll": {"prima": round(corner_nll(legacy, subset), 5), "dopo": round(corner_nll(calibrated, subset), 5)},
            "cartellini_nll": {"prima": round(card_nll(legacy, subset), 5), "dopo": round(card_nll(calibrated, subset), 5)},
        }
        for name, subset in (("taratura", train), ("fuori_campione", holdout))
    }
    improves = (metrics["fuori_campione"]["corner_nll"]["dopo"] + metrics["fuori_campione"]["cartellini_nll"]["dopo"]
                < metrics["fuori_campione"]["corner_nll"]["prima"] + metrics["fuori_campione"]["cartellini_nll"]["prima"])
    section = {
        "parametri": asdict(replace(calibrated, active=bool(improves))),
        "taratura": {
            "data": date.today().isoformat(),
            "dati": "corner e gialli reali football-data.co.uk; input = medie mobili delle 10 gare precedenti; "
                    "arbitro = media mobile dell'arbitro (solo Premier League) o della lega",
            "obiettivo": "log-verosimiglianza del totale (e ripartizione casa/ospite per i corner)",
            "partite_taratura": int(len(train)),
            "partite_fuori_campione": int(len(holdout)),
            "componenti": choices,
            "metriche": metrics,
            "regola": "attivo solo se migliora la log-verosimiglianza fuori campione rispetto alle formule originali",
        },
    }
    _update_config({"corner_cartellini": section})
    return section


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--primo-tempo", action="store_true", help="Tara solo la quota di gol del primo tempo")
    parser.add_argument("--corner-cartellini", action="store_true", help="Tara i modelli di corner e cartellini")
    args = parser.parse_args()
    if args.corner_cartellini:
        print(json.dumps(calibrate_counts(), indent=2, ensure_ascii=False))
        return
    if args.primo_tempo:
        print(json.dumps(calibrate_half_time(), indent=2, ensure_ascii=False))
        return
    raw = dataset.load_raw()
    xg_model = dataset.fit_shot_xg(raw)
    features = dataset.build_features(raw, xg_model)
    features = features[dataset.usable(features)]
    train = features[features["season"].isin(dataset.CALIBRATION_SEASONS)]
    holdout = features[features["season"].isin(dataset.HOLDOUT_SEASONS)]

    params, train_loss, components = select_components(train, holdout)
    legacy_train = holdout_loss(train, goal_model="legacy")
    calibrated_holdout = holdout_loss(holdout, goal_model="calibrato", goal_params=params, dixon_coles_rho=params.dixon_coles_rho)
    legacy_holdout = holdout_loss(holdout, goal_model="legacy")
    active = "calibrato" if calibrated_holdout < legacy_holdout else "legacy"

    sections = {
        "modello_attivo": active,
        "parametri": asdict(params),
        "taratura": {
            "data": date.today().isoformat(),
            "fonte": "football-data.co.uk",
            "campionati": list(dataset.LEAGUES),
            "stagioni_taratura": list(dataset.CALIBRATION_SEASONS),
            "stagioni_fuori_campione": list(dataset.HOLDOUT_SEASONS),
            "stagioni_riscaldamento_elo": list(dataset.WARMUP_SEASONS),
            "partite_taratura": int(len(train)),
            "partite_fuori_campione": int(len(holdout)),
            "obiettivo": "log-loss 1X2 + log-loss Over/Under 2.5",
            "elo": f"calcolato dai risultati stile ClubElo (K={dataset.ELO_K:g}, vantaggio casa {dataset.ELO_HFA:g})",
            "xg": f"proxy dai tiri: {xg_model.on_target:.4f}·tiri in porta + {xg_model.off_target:.4f}·tiri fuori",
            "medie_mobili": f"ultime {dataset.WINDOW} gare di campionato, minimo {dataset.MIN_HISTORY}",
        },
        "componenti": components,
        "metriche": {
            "taratura": {"calibrato": round(train_loss, 5), "legacy": round(legacy_train, 5)},
            "fuori_campione": {"calibrato": round(calibrated_holdout, 5), "legacy": round(legacy_holdout, 5)},
        },
    }
    _update_config(sections)
    print(json.dumps(sections, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
