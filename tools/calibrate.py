"""Taratura dei parametri del modello gol su partite storiche reali.

Minimizza log-loss 1X2 + log-loss Over/Under 2.5 sulle stagioni di taratura,
usando la stessa ``engine.goal_rates`` dell'app. Il modello tarato diventa
attivo solo se migliora la formula originale sulla stagione fuori campione;
altrimenti il file lo salva ma lascia ``modello_attivo = "legacy"``.

Uso: ``python -m tools.calibrate`` (scrive ``config/goal_model.json``).
"""

from __future__ import annotations

from dataclasses import asdict, fields
from datetime import date
import json

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


def main() -> None:
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

    payload = {
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
    engine.GOAL_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine.GOAL_MODEL_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
