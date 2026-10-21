"""Misura del motore su partite storiche reali contro le quote di chiusura.

Calcola Brier, log-loss e calibrazione (ECE) per 1X2, Over 2.5 e GG, e
l'errore medio assoluto sulla media di corner e cartellini. Le probabilità del
modello vengono dalle funzioni del motore (``expected_goals`` e
``dixon_coles_matrix``, senza rumore Monte Carlo); quelle del mercato dalle
quote medie di chiusura senza margine.

Uso::

    python -m tools.baseline --label "PRIMA" --output docs/BASELINE.md
    python -m tools.baseline --goal-model calibrato --label "DOPO" --output docs/BASELINE.md
"""

from __future__ import annotations

import argparse
from dataclasses import fields
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

import engine
from tools import dataset


EVALUATION_SETS = {
    "taratura 2024-25/2025-26": dataset.CALIBRATION_SEASONS,
    "fuori campione 2026-27": dataset.HOLDOUT_SEASONS,
}
FAVORITE_THRESHOLD = 0.70


# --- Metriche -----------------------------------------------------------------

def log_loss(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    """Log-loss medio; ``probabilities`` (N, K) e ``outcomes`` indici di classe."""
    chosen = np.clip(probabilities[np.arange(len(outcomes)), outcomes], 1e-12, 1.0)
    return float(-np.mean(np.log(chosen)))


def brier(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    """Brier multiclasse: somma degli scarti quadratici su tutte le classi."""
    observed = np.eye(probabilities.shape[1])[outcomes]
    return float(np.mean(np.sum((probabilities - observed) ** 2, axis=1)))


def calibration_table(probabilities: np.ndarray, outcomes: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Tabella di affidabilità su tutte le classi, a fasce di probabilità uguali."""
    observed = np.eye(probabilities.shape[1])[outcomes].ravel()
    predicted = probabilities.ravel()
    index = np.minimum((predicted * bins).astype(int), bins - 1)
    rows = []
    for bucket in range(bins):
        mask = index == bucket
        if mask.any():
            rows.append({
                "fascia": f"{bucket / bins:.0%}-{(bucket + 1) / bins:.0%}",
                "n": int(mask.sum()),
                "prevista": float(predicted[mask].mean()),
                "osservata": float(observed[mask].mean()),
            })
    return pd.DataFrame(rows)


def expected_calibration_error(probabilities: np.ndarray, outcomes: np.ndarray, bins: int = 10) -> float:
    table = calibration_table(probabilities, outcomes, bins)
    if table.empty:
        return float("nan")
    return float(np.sum(table["n"] * (table["prevista"] - table["osservata"]).abs()) / table["n"].sum())


def binary(probability: np.ndarray) -> np.ndarray:
    probability = np.asarray(probability, dtype=float)
    return np.column_stack([1.0 - probability, probability])


def de_vig(*odds: np.ndarray) -> np.ndarray:
    """Probabilità implicite normalizzate (margine rimosso in proporzione)."""
    implied = np.column_stack([1.0 / np.asarray(value, dtype=float) for value in odds])
    return implied / implied.sum(axis=1, keepdims=True)


def summarize(probabilities: np.ndarray, outcomes: np.ndarray) -> dict[str, float]:
    return {
        "log_loss": log_loss(probabilities, outcomes),
        "brier": brier(probabilities, outcomes),
        "ece": expected_calibration_error(probabilities, outcomes),
    }


# --- Previsioni del motore ----------------------------------------------------

_CONFIG_FIELDS = {item.name for item in fields(engine.MatchConfig)}


def config_for_row(row: Mapping[str, Any], **overrides: Any) -> engine.MatchConfig:
    """Costruisce la stessa ``MatchConfig`` che l'utente otterrebbe dal parser."""

    def team(side: str) -> engine.TeamParams:
        return engine.TeamParams(
            name=row[f"{side}_team"],
            attack=float(np.clip(row[f"{side}_attack"], 0.2, 3.0)),
            defense=float(np.clip(row[f"{side}_defense"], 0.2, 3.0)),
            elo=float(row[f"{side}_elo"]),
            form=row[f"{side}_form"],
            xg_for=float(row[f"{side}_xg_for"]),
            xg_against=float(row[f"{side}_xg_against"]),
            corners_for=float(row[f"{side}_corners_for"]),
            corners_against=float(row[f"{side}_corners_against"]),
            cards_for=float(row[f"{side}_cards_for"]),
        )

    unknown = set(overrides) - _CONFIG_FIELDS
    if unknown:
        raise ValueError(f"Parametri MatchConfig sconosciuti: {sorted(unknown)}")
    return engine.MatchConfig(
        home=team("home"),
        away=team("away"),
        referee_yellow_avg=float(row["referee_yellow_avg"]),
        referee_fouls_avg=float(row["referee_fouls_avg"]),
        **overrides,
    )


def predict(features: pd.DataFrame, **overrides: Any) -> pd.DataFrame:
    """Probabilità analitiche del motore per ogni partita."""
    rows = []
    for row in features.to_dict("records"):
        config = config_for_row(row, **overrides)
        lambda_, mu, _ = engine.expected_goals(config)
        matrix = engine.dixon_coles_matrix(lambda_, mu, config.dixon_coles_rho, max_goals=12)
        home_goals, away_goals = np.indices(matrix.shape)
        corners_home, corners_away = engine.corner_signals(config)
        rows.append({
            "lambda": lambda_,
            "mu": mu,
            "p_home": float(matrix[home_goals > away_goals].sum()),
            "p_draw": float(np.trace(matrix)),
            "p_away": float(matrix[home_goals < away_goals].sum()),
            "p_over25": float(matrix[home_goals + away_goals > 2].sum()),
            "p_btts": float(matrix[1:, 1:].sum()),
            "corner_mean": corners_home + corners_away,
            "card_mean": engine.card_total_mean(config),
        })
    return pd.DataFrame(rows, index=features.index)


# --- Valutazione --------------------------------------------------------------

def evaluate(features: pd.DataFrame, predictions: pd.DataFrame) -> dict[str, Any]:
    has_odds = features[["close_home", "close_draw", "close_away", "close_over25", "close_under25"]].gt(1.0).all(axis=1)
    data, model = features[has_odds], predictions[has_odds]
    outcome_1x2 = np.select(
        [data["home_goals"] > data["away_goals"], data["home_goals"] == data["away_goals"]], [0, 1], 2
    )
    over25 = ((data["home_goals"] + data["away_goals"]) > 2).to_numpy().astype(int)
    btts = ((data["home_goals"] > 0) & (data["away_goals"] > 0)).to_numpy().astype(int)

    model_1x2 = model[["p_home", "p_draw", "p_away"]].to_numpy()
    market_1x2 = de_vig(data["close_home"], data["close_draw"], data["close_away"])
    model_over = binary(model["p_over25"])
    market_over = de_vig(data["close_under25"], data["close_over25"])

    favorite = market_1x2.max(axis=1) >= FAVORITE_THRESHOLD
    favorite_index = market_1x2.argmax(axis=1)
    rows = np.arange(len(data))

    actual_corners = (data["home_corners"] + data["away_corners"]).to_numpy()
    actual_cards = (data["home_yellows"] + data["away_yellows"]).to_numpy()
    corner_mask, card_mask = np.isfinite(actual_corners), np.isfinite(actual_cards)
    return {
        "n": int(len(data)),
        "1x2": {"modello": summarize(model_1x2, outcome_1x2), "mercato": summarize(market_1x2, outcome_1x2)},
        "over25": {"modello": summarize(model_over, over25), "mercato": summarize(market_over, over25)},
        "gg": {"modello": summarize(binary(model["p_btts"]), btts), "mercato": None},
        "favorite": {
            "n": int(favorite.sum()),
            "mercato": float(market_1x2[rows, favorite_index][favorite].mean()) if favorite.any() else float("nan"),
            "modello": float(model_1x2[rows, favorite_index][favorite].mean()) if favorite.any() else float("nan"),
        },
        "corner_mae": float(np.mean(np.abs(model["corner_mean"].to_numpy() - actual_corners)[corner_mask])),
        "cartellini_mae": float(np.mean(np.abs(model["card_mean"].to_numpy() - actual_cards)[card_mask])),
        "calibrazione_1x2": calibration_table(model_1x2, outcome_1x2),
    }


def _fmt(value: float | None, digits: int = 4) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.{digits}f}"


def render_markdown(label: str, description: str, results: Mapping[str, dict[str, Any]]) -> str:
    lines = [f"## {label}", "", description, ""]
    for set_name, result in results.items():
        lines += [
            f"### {set_name} ({result['n']} partite)", "",
            "| Mercato | Log-loss modello | Log-loss mercato | Brier modello | Brier mercato | ECE modello | ECE mercato |",
            "|---|---|---|---|---|---|---|",
        ]
        for key, name in (("1x2", "1X2"), ("over25", "Over 2.5"), ("gg", "GG")):
            model, market = result[key]["modello"], result[key]["mercato"] or {}
            lines.append(
                f"| {name} | {_fmt(model['log_loss'])} | {_fmt(market.get('log_loss'))} | "
                f"{_fmt(model['brier'])} | {_fmt(market.get('brier'))} | "
                f"{_fmt(model['ece'])} | {_fmt(market.get('ece'))} |"
            )
        favorite = result["favorite"]
        lines += [
            "",
            f"- Favorite nette (mercato ≥ {FAVORITE_THRESHOLD:.0%}, {favorite['n']} partite): "
            f"probabilità media mercato {_fmt(favorite['mercato'] * 100, 1)}%, "
            f"modello {_fmt(favorite['modello'] * 100, 1)}%.",
            f"- Errore medio assoluto sulla media corner: {_fmt(result['corner_mae'], 2)}; "
            f"cartellini gialli: {_fmt(result['cartellini_mae'], 2)}.",
            "",
            "Calibrazione 1X2 del modello (tutte le classi):", "",
            "| Fascia | n | Prevista | Osservata |", "|---|---|---|---|",
        ]
        for row in result["calibrazione_1x2"].itertuples(index=False):
            lines.append(f"| {row.fascia} | {row.n} | {row.prevista:.3f} | {row.osservata:.3f} |")
        lines.append("")
    return "\n".join(lines)


def run(overrides: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    features = dataset.load_features()
    features = features[dataset.usable(features)]
    predictions = predict(features, **(overrides or {}))
    return {
        name: evaluate(features[features["season"].isin(seasons)], predictions[features["season"].isin(seasons)])
        for name, seasons in EVALUATION_SETS.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="Titolo della sezione, es. PRIMA o DOPO")
    parser.add_argument("--goal-model", help="Valore di MatchConfig.goal_model (se supportato)")
    parser.add_argument("--output", type=Path, help="File markdown a cui aggiungere la sezione")
    args = parser.parse_args()
    overrides = {"goal_model": args.goal_model} if args.goal_model else {}
    results = run(overrides)
    description = (
        f"Generato il {date.today():%d/%m/%Y} con `python -m tools.baseline"
        f"{' --goal-model ' + args.goal_model if args.goal_model else ''}`. "
        "Campionati: Serie A, Premier League, Liga, Bundesliga (football-data.co.uk)."
    )
    markdown = render_markdown(args.label, description, results)
    print(markdown)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")


if __name__ == "__main__":
    main()
