"""Fase Q, punto 6c: goleade. Calibrazione fuori campione di «favorita 4+ gol», «favorita vince con 3+ di
scarto» e «totale 5+ gol» per fascia di squilibrio (|λ − μ|), e prova di una correzione della coda.

Gol attesi come nell'app (ancorati alle quote di chiusura, ``engine.final_goal_rates``), punteggi
Dixon-Coles. Correzione candidata: marginali binomiali negative (stesse medie λ e μ, coda più pesante,
dispersione k) con la stessa correzione Dixon-Coles sui punteggi bassi; k tarato sul 2024-26 per massima
verosimiglianza dei punteggi esatti. Resta accesa solo con la regola severa della fase O: log-loss media
dei tre mercati giù di oltre 2 errori standard (confronto appaiato) e ECE media non peggiore, senza
peggiorare 1X2 e Over/Under 2.5 oltre il rumore. Uso: ``python -m tools.goleade [--salva] [--output ...]``.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import nbinom

import engine
from tools import baseline, dataset

MAX_GOALS = 12
MARKETS = ("Favorita 4+ gol", "Favorita vince di 3+", "Totale 5+ gol")
UPPER_DISPERSION = 500.0


def rates(features: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in features.to_dict("records"):
        config = baseline.config_for_row(row, odds=baseline.closing_odds(row))
        lambda_, mu, _ = engine.final_goal_rates(config)
        rows.append({"lambda": lambda_, "mu": mu, "rho": config.dixon_coles_rho})
    return pd.DataFrame(rows, index=features.index)


def score_matrix(lambda_: float, mu: float, rho: float, dispersion: float = 0.0) -> np.ndarray:
    """Dixon-Coles con marginali Poisson (dispersion 0) o binomiali negative di uguale media."""
    if dispersion <= 0:
        return engine.dixon_coles_matrix(lambda_, mu, rho, max_goals=MAX_GOALS)
    goals = np.arange(MAX_GOALS + 1)
    home = nbinom.pmf(goals, dispersion, dispersion / (dispersion + lambda_))
    away = nbinom.pmf(goals, dispersion, dispersion / (dispersion + mu))
    matrix = np.outer(home, away)
    tau = np.ones_like(matrix)
    tau[0, 0] = 1 - lambda_ * mu * rho
    tau[0, 1] = 1 + lambda_ * rho
    tau[1, 0] = 1 + mu * rho
    tau[1, 1] = 1 - rho
    matrix = matrix * np.maximum(tau, 0)
    return matrix / matrix.sum()


def event_probabilities(matrix: np.ndarray, home_favourite: bool) -> dict[str, float]:
    home, away = np.indices(matrix.shape)
    favourite, other = (home, away) if home_favourite else (away, home)
    return {"Favorita 4+ gol": float(matrix[favourite >= 4].sum()),
            "Favorita vince di 3+": float(matrix[favourite - other >= 3].sum()),
            "Totale 5+ gol": float(matrix[home + away >= 5].sum()),
            "1": float(matrix[home > away].sum()), "X": float(np.trace(matrix)), "2": float(matrix[home < away].sum()),
            "Over 2.5": float(matrix[home + away > 2.5].sum())}


def predictions(data: pd.DataFrame, dispersion: float) -> pd.DataFrame:
    rows = []
    for row in data.itertuples():
        matrix = score_matrix(row.lambda_, row.mu, row.rho, dispersion)
        rows.append(event_probabilities(matrix, row.lambda_ >= row.mu))
    return pd.DataFrame(rows, index=data.index)


def outcomes(data: pd.DataFrame) -> pd.DataFrame:
    home, away = data["home_goals"].to_numpy(), data["away_goals"].to_numpy()
    favourite_home = data["lambda_"].to_numpy() >= data["mu"].to_numpy()
    favourite = np.where(favourite_home, home, away)
    other = np.where(favourite_home, away, home)
    return pd.DataFrame({"Favorita 4+ gol": favourite >= 4, "Favorita vince di 3+": favourite - other >= 3,
                         "Totale 5+ gol": home + away >= 5,
                         "1X2": np.where(home > away, 0, np.where(home == away, 1, 2)), "Over 2.5": home + away > 2.5},
                        index=data.index)


def exact_nll(data: pd.DataFrame, dispersion: float) -> float:
    total = 0.0
    for row in data.itertuples():
        matrix = score_matrix(row.lambda_, row.mu, row.rho, dispersion)
        total -= np.log(max(matrix[min(int(row.home_goals), MAX_GOALS), min(int(row.away_goals), MAX_GOALS)], 1e-12))
    return total / len(data)


def per_match_loss(pred: pd.DataFrame, out: pd.DataFrame) -> np.ndarray:
    losses = [-np.log(np.clip(np.where(out[key], pred[key], 1 - pred[key]), 1e-9, 1)) for key in MARKETS]
    return np.mean(losses, axis=0)


def summary_rows(pred: pd.DataFrame, out: pd.DataFrame) -> dict[str, dict]:
    result = {}
    for key in MARKETS:
        result[key] = baseline.summarize(baseline.binary(pred[key].to_numpy()), out[key].to_numpy().astype(int))
    result["1X2"] = baseline.summarize(pred[["1", "X", "2"]].to_numpy(), out["1X2"].to_numpy())
    result["Over 2.5"] = baseline.summarize(baseline.binary(pred["Over 2.5"].to_numpy()), out["Over 2.5"].to_numpy().astype(int))
    result["media goleade"] = {metric: float(np.mean([result[key][metric] for key in MARKETS])) for metric in ("log_loss", "ece", "brier")}
    return result


def band_table(data: pd.DataFrame, before: pd.DataFrame, after: pd.DataFrame, out: pd.DataFrame, bands: int = 5) -> list[str]:
    imbalance = (data["lambda_"] - data["mu"]).abs()
    groups = pd.qcut(imbalance, bands, duplicates="drop")
    lines = ["| Fascia |λ − μ| | Partite | " + " | ".join(f"{key}: prima / dopo / reale" for key in MARKETS) + " |",
             "|---|---|" + "---|" * len(MARKETS)]
    for band, index in data.groupby(groups, observed=True).groups.items():
        cells = [f"{before.loc[index, key].mean():.1%} / {after.loc[index, key].mean():.1%} / {out.loc[index, key].mean():.1%}"
                 for key in MARKETS]
        lines.append(f"| {band.left:.2f}–{band.right:.2f} | {len(index)} | " + " | ".join(cells) + " |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    features = baseline.load_usable_features().dropna(subset=["close_home", "close_draw", "close_away"])
    data = features.join(rates(features)).rename(columns={"lambda": "lambda_"})
    train = data[data["season"].isin(dataset.CALIBRATION_SEASONS)]
    outside = data[~data["season"].isin(dataset.CALIBRATION_SEASONS)]
    fitted = minimize_scalar(lambda log_k: exact_nll(train, float(np.exp(log_k))), bounds=(np.log(2.0), np.log(UPPER_DISPERSION)),
                             method="bounded")
    dispersion = float(np.exp(fitted.x))
    out = outcomes(outside)
    before, after = predictions(outside, 0.0), predictions(outside, dispersion)
    first, second = summary_rows(before, out), summary_rows(after, out)
    difference = per_match_loss(after, out) - per_match_loss(before, out)
    standard_error = float(difference.std(ddof=1) / np.sqrt(len(difference)))
    other_ok = (second["1X2"]["log_loss"] <= first["1X2"]["log_loss"] + 1e-4
                and second["Over 2.5"]["log_loss"] <= first["Over 2.5"]["log_loss"] + 1e-4)
    # Una dispersione al limite superiore vuol dire «niente coda più pesante» (≈ Poisson): non è una correzione.
    at_bound = dispersion > 0.9 * UPPER_DISPERSION
    keep = (not at_bound and float(difference.mean()) < -2 * standard_error
            and second["media goleade"]["ece"] <= first["media goleade"]["ece"] + 0.0005 and other_ok)
    lines = ["## Goleade: calibrazione fuori campione e correzione della coda (fase Q, 6c)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.goleade`. {len(outside)} partite fuori campione "
             f"(2019-24 e 2026-27), gol attesi ancorati alle quote di chiusura, punteggi Dixon-Coles. Correzione provata: "
             f"marginali binomiali negative con dispersione k = {dispersion:.1f} tarata sul 2024-26 ({len(train)} partite, "
             f"verosimiglianza dei punteggi esatti). Differenza appaiata della log-loss media dei tre mercati "
             f"{difference.mean():+.5f} ± {2 * standard_error:.5f} (2 e.s.): **{'tenuta' if keep else 'spenta'}**"
             + (" (dispersione al limite superiore: i dati non chiedono una coda più pesante, il modello Poisson "
                "non sottostima le goleade)" if at_bound else "") + ".", "",
             "| Mercato | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |", "|---|---|---|---|---|"]
    for key in (*MARKETS, "media goleade", "1X2", "Over 2.5"):
        lines.append(f"| {key} | {first[key]['log_loss']:.4f} | {second[key]['log_loss']:.4f} | {first[key]['ece']:.4f} | {second[key]['ece']:.4f} |")
    lines += ["", "Per fascia di squilibrio (media prevista prima / dopo / frequenza reale):", "",
              *band_table(outside, before, after, out), ""]
    markdown = "\n".join(lines)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva:
        from tools.calibrate import _update_config

        _update_config({"goleade": {"data": date.today().isoformat(), "attiva": keep, "dispersione_gol": round(dispersion, 3),
                                    "differenza_log_loss": round(float(difference.mean()), 6),
                                    "due_errori_standard": round(2 * standard_error, 6)}})


if __name__ == "__main__":
    main()
