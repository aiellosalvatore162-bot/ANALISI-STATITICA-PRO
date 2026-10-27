"""Fase P: base comune delle verifiche del motore v2.

``frame()`` costruisce una volta (cache in ``data/cache/fase_p/``) la tabella delle partite con quote di chiusura:
gol attesi del modello attuale, del mercato (Shin) e finali ancorati come nell'app, esiti. ``strict`` applica la
regola severa usata in tutto il progetto: log-loss appaiata giù di oltre 2 errori standard ED ECE non peggiore
(tolleranza 0.0005), sempre sulle stagioni fuori campione (2019-24 e 2026-27; taratura = 2024-26).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import engine
from tools import baseline, dataset

CACHE = Path(__file__).resolve().parents[1] / "data" / "cache" / "fase_p"
ECE_TOLERANCE = 0.0005


def is_train(frame: pd.DataFrame) -> np.ndarray:
    return frame["season"].isin(dataset.CALIBRATION_SEASONS).to_numpy()


def frame(refresh: bool = False) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "partite.pkl"
    if path.exists() and not refresh:
        return pd.read_pickle(path)
    features = baseline.load_usable_features()
    features = features[features[["close_home", "close_draw", "close_away", "close_over25", "close_under25"]]
                        .gt(1.0).all(axis=1)].reset_index(drop=True)
    rows = []
    for row in features.to_dict("records"):
        config = baseline.config_for_row(row, odds=baseline.closing_odds(row))
        model_lambda, model_mu, _ = engine.expected_goals(config)
        market = engine.market_goal_rates(baseline.closing_odds(row), config.market_anchor.devig_method, config.dixon_coles_rho)
        final_lambda, final_mu, _ = engine.final_goal_rates(config)
        rows.append({"model_lambda": model_lambda, "model_mu": model_mu,
                     "market_lambda": market["lambda"] if market else np.nan, "market_mu": market["mu"] if market else np.nan,
                     "final_lambda": final_lambda, "final_mu": final_mu, "rho": config.dixon_coles_rho})
    result = pd.concat([features, pd.DataFrame(rows)], axis=1)
    result.to_pickle(path)
    return result


def goal_probabilities(lambda_: np.ndarray, mu: np.ndarray, rho: float, max_goals: int = 10) -> dict[str, np.ndarray]:
    from tools.calibrate import market_probabilities, score_matrices

    probabilities = market_probabilities(score_matrices(np.asarray(lambda_, float), np.asarray(mu, float), rho, max_goals))
    return {"1x2": probabilities["1x2"], "over25": probabilities["over25"]}


def outcomes(data: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    from tools.calibrate import outcomes as base_outcomes

    return base_outcomes(data)


def goal_losses(data: pd.DataFrame, lambda_: np.ndarray, mu: np.ndarray) -> tuple[np.ndarray, float]:
    """Log-loss per partita (1X2 + Over/Under 2.5, come la taratura) ed ECE media dei due mercati."""
    result, over = outcomes(data)
    probabilities = goal_probabilities(lambda_, mu, float(data["rho"].iloc[0]))
    one_x_two = probabilities["1x2"]
    loss = (-np.log(np.clip(one_x_two[np.arange(len(result)), result], 1e-12, 1))
            - np.log(np.clip(np.where(over == 1, probabilities["over25"], 1 - probabilities["over25"]), 1e-12, 1)))
    ece = (baseline.expected_calibration_error(one_x_two, result)
           + baseline.expected_calibration_error(baseline.binary(probabilities["over25"]), over)) / 2
    return loss, ece


def anchored(data: pd.DataFrame, model_lambda: np.ndarray, model_mu: np.ndarray,
             weight: float | np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Ancoraggio al mercato come nell'app (peso del mercato della configurazione o quello dato)."""
    from dataclasses import replace

    params = engine.DEFAULT_MARKET_ANCHOR
    if weight is not None:
        params = replace(params, market_weight=np.asarray(weight, float))  # anche un peso per partita
    lambda_, mu, *_ = engine.anchor_goal_rates(np.asarray(model_lambda, float), np.asarray(model_mu, float),
                                               data["market_lambda"].to_numpy(), data["market_mu"].to_numpy(), params)
    return np.asarray(lambda_, float), np.asarray(mu, float)


def strict(before: tuple[np.ndarray, float], after: tuple[np.ndarray, float]) -> dict:
    """Confronto appaiato: ``before``/``after`` = (perdita per partita, ECE)."""
    difference = after[0] - before[0]
    standard_error = float(difference.std(ddof=1) / np.sqrt(len(difference))) if len(difference) > 1 else float("nan")
    keep = bool(difference.mean() < -2 * standard_error and after[1] <= before[1] + ECE_TOLERANCE)
    return {"prima": float(before[0].mean()), "dopo": float(after[0].mean()), "differenza": float(difference.mean()),
            "due_es": 2 * standard_error, "ece_prima": float(before[1]), "ece_dopo": float(after[1]), "tenuta": keep,
            "partite": int(len(difference))}


def row_text(name: str, result: dict) -> str:
    return (f"| {name} | {result['partite']} | {result['prima']:.4f} | {result['dopo']:.4f} | "
            f"{result['differenza']:+.5f} ± {result['due_es']:.5f} | {result['ece_prima']:.4f} → {result['ece_dopo']:.4f} | "
            f"**{'accesa' if result['tenuta'] else 'spenta'}** |")


TABLE_HEADER = ["| Variante | Partite | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE | Esito |",
                "|---|---|---|---|---|---|---|"]
