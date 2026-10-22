"""Misura del motore su partite storiche reali contro le quote di chiusura.

Calcola Brier, log-loss e calibrazione (ECE) per 1X2, Over 2.5 e GG, e
l'errore medio assoluto sulla media di corner e cartellini. Le probabilità del
modello vengono dalle funzioni del motore (``expected_goals`` e
``dixon_coles_matrix``, senza rumore Monte Carlo); quelle del mercato dalle
quote medie di chiusura senza margine.

Con ``--ancorato`` le quote di chiusura entrano anche come input del motore
(ancoraggio al mercato); ``--tara-ancoraggio`` sceglie peso del mercato e metodo
di rimozione del margine e li salva in ``config/goal_model.json``.

Uso::

    python -m tools.baseline --label "PRIMA" --output docs/BASELINE.md
    python -m tools.baseline --goal-model calibrato --label "DOPO" --output docs/BASELINE.md
    python -m tools.baseline --tara-ancoraggio --output docs/BASELINE.md
    python -m tools.baseline --ancorato --label "DOPO ancoraggio" --output docs/BASELINE.md
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, fields, replace
from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

import engine
from tools import dataset


EVALUATION_SETS = {
    "taratura 2024-25/2025-26": dataset.CALIBRATION_SEASONS,
    "fuori campione 2026-27": dataset.HOLDOUT_SEASONS,
}
FAVORITE_THRESHOLD = 0.70
SIGNS = ("1", "X", "2")
ANCHOR_WEIGHTS = (0.5, 0.6, 0.7, 0.8, 0.9)


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


def closing_odds(row: Mapping[str, Any]) -> dict[str, float]:
    """Quote medie di chiusura con le chiavi evento del motore."""
    columns = {
        "1": "close_home", "X": "close_draw", "2": "close_away",
        "Over 2.5 gol": "close_over25", "Under 2.5 gol": "close_under25",
    }
    return {key: float(row[column]) for key, column in columns.items() if np.isfinite(row[column])}


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


def predict(features: pd.DataFrame, *, anchored: bool = False, **overrides: Any) -> pd.DataFrame:
    """Probabilità analitiche del motore per ogni partita.

    Con ``anchored`` le quote di chiusura sono passate al motore, che usa i gol
    attesi finali (modello ancorato al mercato) come nella simulazione.
    """
    rows = []
    for row in features.to_dict("records"):
        config = config_for_row(row, **({"odds": closing_odds(row)} if anchored else {}), **overrides)
        lambda_, mu, _ = engine.final_goal_rates(config)
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

def value_returns(probabilities: np.ndarray, odds: np.ndarray, outcomes: np.ndarray,
                  no_value: Sequence[str] = ()) -> dict[str, dict[str, float]]:
    """Segnali VALORE 1X2 (EV > 0 alla quota data) e rendimento puntando 1 su ognuno."""
    value = probabilities * odds - 1.0 > 0.0
    for index, sign in enumerate(SIGNS):
        if sign in no_value:
            value[:, index] = False
    won = np.eye(3, dtype=bool)[outcomes]
    profit = np.where(won, odds - 1.0, -1.0)
    report = {
        sign: {"n": int(value[:, index].sum()),
               "roi": float(profit[value[:, index], index].mean()) if value[:, index].any() else float("nan")}
        for index, sign in enumerate(SIGNS)
    }
    report["totale"] = {"n": int(value.sum()), "roi": float(profit[value].mean()) if value.any() else float("nan")}
    return report


def evaluate(features: pd.DataFrame, predictions: pd.DataFrame, no_value: Sequence[str] = ()) -> dict[str, Any]:
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

    odds_1x2 = data[["close_home", "close_draw", "close_away"]].to_numpy(float)
    returns = value_returns(model_1x2, odds_1x2, outcome_1x2, no_value)

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
        "valore_1x2": {
            "segnali_per_partita": returns["totale"]["n"] / len(data),
            "per_esito": {sign: returns[sign]["n"] for sign in SIGNS},
            "roi": returns["totale"]["roi"],
            "esclusi": list(no_value),
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
            f"- Segnali VALORE 1X2 alle quote di chiusura: {_fmt(result['valore_1x2']['segnali_per_partita'], 2)} "
            f"per partita (1: {result['valore_1x2']['per_esito']['1']}, X: {result['valore_1x2']['per_esito']['X']}, "
            f"2: {result['valore_1x2']['per_esito']['2']}); rendimento medio puntando 1 su ciascuno: "
            f"{_fmt(result['valore_1x2']['roi'] * 100, 1)}%"
            + (f" (VALORE non segnalato su: {', '.join(result['valore_1x2']['esclusi'])})." if result['valore_1x2']['esclusi'] else "."),
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


def load_usable_features() -> pd.DataFrame:
    features = dataset.load_features()
    return features[dataset.usable(features)]


def run(overrides: Mapping[str, Any] | None = None, *, anchored: bool = False) -> dict[str, dict[str, Any]]:
    features = load_usable_features()
    predictions = predict(features, anchored=anchored, **(overrides or {}))
    no_value = engine.DEFAULT_MARKET_ANCHOR.no_value_markets if anchored else ()
    return {
        name: evaluate(
            features[features["season"].isin(seasons)], predictions[features["season"].isin(seasons)], no_value
        )
        for name, seasons in EVALUATION_SETS.items()
    }


def tune_market_anchor(features: pd.DataFrame) -> dict[str, Any]:
    """Prova i pesi ``ANCHOR_WEIGHTS`` per ogni metodo di margine sulle stagioni di taratura.

    Sceglie la combinazione con il log-loss (1X2 + Over/Under 2.5) più basso e
    la attiva solo se migliora anche il fuori campione rispetto al solo modello.
    """
    from tools.calibrate import market_probabilities, outcomes, score_matrices

    has_odds = features[["close_home", "close_draw", "close_away", "close_over25", "close_under25"]].gt(1.0).all(axis=1)
    evaluated = features["season"].isin([season for seasons in EVALUATION_SETS.values() for season in seasons])
    features = features[has_odds & evaluated]
    rows = features.to_dict("records")
    rho = engine.MatchConfig(
        home=config_for_row(rows[0]).home, away=config_for_row(rows[0]).away,
        referee_yellow_avg=4.5, referee_fouls_avg=24.0,
    ).dixon_coles_rho
    model = np.array([engine.expected_goals(config_for_row(row))[:2] for row in rows])
    splits = {name: features["season"].isin(seasons).to_numpy() for name, seasons in EVALUATION_SETS.items()}
    result_1x2, over = outcomes(features)

    def losses(lambda_, mu) -> dict[str, float]:
        probabilities = market_probabilities(score_matrices(np.asarray(lambda_), np.asarray(mu), rho))
        return {
            name: log_loss(probabilities["1x2"][mask], result_1x2[mask])
            + log_loss(binary(probabilities["over25"][mask]), over[mask])
            for name, mask in splits.items()
        }

    grid = [{"metodo": "—", "peso_mercato": 0.0, "descrizione": "solo modello", **losses(model[:, 0], model[:, 1])}]
    for method in engine.DEVIG_METHODS:
        market = np.array([
            [fit["lambda"], fit["mu"]]
            for fit in (engine.market_goal_rates(closing_odds(row), method, rho) for row in rows)
        ])
        for weight in (*ANCHOR_WEIGHTS, 1.0):
            params = replace(engine.MarketAnchorParams(), market_weight=weight, devig_method=method)
            lambda_, mu, *_ = engine.anchor_goal_rates(model[:, 0], model[:, 1], market[:, 0], market[:, 1], params)
            description = "solo mercato" if weight == 1.0 else "ancorato"
            grid.append({"metodo": method, "peso_mercato": weight, "descrizione": description, **losses(lambda_, mu)})

    calibration_set, holdout_set = EVALUATION_SETS
    candidates = [row for row in grid if row["peso_mercato"] in ANCHOR_WEIGHTS]
    best = min(candidates, key=lambda row: row[calibration_set])
    active = best[holdout_set] < grid[0][holdout_set]
    params = replace(
        engine.MarketAnchorParams(), active=bool(active),
        market_weight=best["peso_mercato"], devig_method=best["metodo"],
    )
    return {"params": params, "grid": grid, "best": best, "n": len(features)}


def save_market_anchor(tuning: Mapping[str, Any]) -> None:
    data = json.loads(engine.GOAL_MODEL_PATH.read_text(encoding="utf-8"))
    data["ancoraggio_mercato"] = {
        "parametri": asdict(tuning["params"]),
        "taratura": {
            "data": date.today().isoformat(),
            "quote": "medie di chiusura football-data.co.uk (1X2 e Over/Under 2.5)",
            "obiettivo": "log-loss 1X2 + log-loss Over/Under 2.5 sulle stagioni di taratura",
            "pesi_provati": list(ANCHOR_WEIGHTS),
            "griglia": [
                {key: (round(value, 5) if isinstance(value, float) else value) for key, value in row.items()}
                for row in tuning["grid"]
            ],
        },
    }
    engine.GOAL_MODEL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_tuning(tuning: Mapping[str, Any]) -> str:
    calibration_set, holdout_set = EVALUATION_SETS
    params = tuning["params"]
    lines = [
        "## Taratura dell'ancoraggio al mercato", "",
        f"Generato il {date.today():%d/%m/%Y} con `python -m tools.baseline --tara-ancoraggio` "
        f"({tuning['n']} partite con quote di chiusura). Log-loss 1X2 + Over/Under 2.5, più basso è meglio.", "",
        f"| Metodo margine | Peso mercato | Tipo | {calibration_set} | {holdout_set} |", "|---|---|---|---|---|",
    ]
    for row in tuning["grid"]:
        lines.append(
            f"| {row['metodo']} | {row['peso_mercato']:.1f} | {row['descrizione']} | "
            f"{row[calibration_set]:.4f} | {row[holdout_set]:.4f} |"
        )
    lines += [
        "",
        f"Scelta: metodo **{params.devig_method}**, peso mercato **{params.market_weight:g}**, "
        f"correzione del modello limitata a [{params.correction_min:g}, {params.correction_max:g}]; "
        f"ancoraggio {'attivo' if params.active else 'disattivato (non migliora il fuori campione)'}.",
        "",
    ]
    return "\n".join(lines)


def draw_analysis(features: pd.DataFrame) -> str:
    """Confronta i metodi di margine per esito (1, X, 2) e il rendimento dei VALORE 1X2."""
    from tools.calibrate import market_probabilities, outcomes, score_matrices

    has_odds = features[["close_home", "close_draw", "close_away", "close_over25", "close_under25"]].gt(1.0).all(axis=1)
    evaluated = features["season"].isin([season for seasons in EVALUATION_SETS.values() for season in seasons])
    features = features[has_odds & evaluated]
    rows = features.to_dict("records")
    rho = engine.DEFAULT_GOAL_PARAMS.dixon_coles_rho
    odds = features[["close_home", "close_draw", "close_away"]].to_numpy(float)
    result, _ = outcomes(features)
    model = np.array([engine.expected_goals(config_for_row(row))[:2] for row in rows])
    weight = engine.DEFAULT_MARKET_ANCHOR.market_weight

    sources: dict[str, np.ndarray] = {}
    for method in engine.DEVIG_METHODS:
        sources[f"quote senza margine · {method}"] = np.array([engine.remove_margin(row, method) for row in odds])
    for method in engine.DEVIG_METHODS:
        market = np.array([
            [fit["lambda"], fit["mu"]]
            for fit in (engine.market_goal_rates(closing_odds(row), method, rho) for row in rows)
        ])
        sources[f"Dixon-Coles adattato al mercato · {method}"] = market_probabilities(
            score_matrices(market[:, 0], market[:, 1], rho))["1x2"]
        params = replace(engine.MarketAnchorParams(), market_weight=weight, devig_method=method)
        lambda_, mu, *_ = engine.anchor_goal_rates(model[:, 0], model[:, 1], market[:, 0], market[:, 1], params)
        sources[f"finale (peso {weight:g}) · {method}"] = market_probabilities(score_matrices(lambda_, mu, rho))["1x2"]

    final_name = f"finale (peso {weight:g}) · shin"
    scenarios = {
        f"PRIMA: finale shin, VALORE su 1, X e 2": (sources[final_name], ()),
        f"alternativa: finale proporzionale": (sources[f"finale (peso {weight:g}) · proporzionale"], ()),
        f"DOPO: finale shin, nessun VALORE sul pareggio": (sources[final_name], ("X",)),
    }
    lines = [
        "## Analisi del pareggio (1, X, 2 separati)", "",
        f"Generato il {date.today():%d/%m/%Y} con `python -m tools.baseline --analisi-pareggio`. "
        "Probabilità media prevista contro frequenza osservata; i VALORE sono calcolati alle quote "
        "di chiusura (con margine) puntando 1 su ciascun segnale.", "",
    ]
    for set_name, seasons in EVALUATION_SETS.items():
        mask = features["season"].isin(seasons).to_numpy()
        observed = np.eye(3)[result[mask]].mean(axis=0)
        lines += [
            f"### {set_name} ({int(mask.sum())} partite; osservato 1 {observed[0]:.1%}, X {observed[1]:.1%}, 2 {observed[2]:.1%})", "",
            "| Fonte | 1 prevista | X prevista | 2 prevista | Scarto X (punti) | Log-loss 1X2 |", "|---|---|---|---|---|---|",
        ]
        for name, probabilities in sources.items():
            mean = probabilities[mask].mean(axis=0)
            lines.append(
                f"| {name} | {mean[0]:.1%} | {mean[1]:.1%} | {mean[2]:.1%} | "
                f"{(mean[1] - observed[1]) * 100:+.2f} | {log_loss(probabilities[mask], result[mask]):.4f} |"
            )
        lines += ["", "| Scenario VALORE | 1: n / rend. | X: n / rend. | 2: n / rend. | Totale: n / rend. |", "|---|---|---|---|---|"]
        for name, (probabilities, no_value) in scenarios.items():
            returns = value_returns(probabilities[mask], odds[mask], result[mask], no_value)
            cells = [
                f"{returns[key]['n']} / " + ("—" if returns[key]["n"] == 0 else f"{returns[key]['roi'] * 100:.1f}%")
                for key in (*SIGNS, "totale")
            ]
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


# --- Mercati secondari ----------------------------------------------------------

MATCH_MULTIGOL = ((1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (2, 5), (2, 6), (3, 5))
TEAM_MULTIGOL = ((1, 2), (1, 3), (2, 3), (2, 4))
GOAL_SUM_CLASSES = ("0", "1", "2", "3", "4", "5+")
FIRST_HALF_MARKETS = ("1X2 1T", "Over 0.5 1T", "Over 1.5 1T", "GG 1T")
SECONDARY_GAP = 0.005


def secondary_markets(lambda_, mu, rho: float, half: "engine.HalfTimeParams", share_factor=None) -> dict[str, np.ndarray]:
    """Probabilità analitiche dei mercati gol da un'unica matrice dei punteggi per partita.

    La matrice del primo tempo deriva da quella finale assegnando ogni gol al
    primo tempo con la quota di ``half``, come nella simulazione.
    """
    from scipy.stats import binom

    from tools.calibrate import score_matrices

    lambda_, mu = np.asarray(lambda_, dtype=float), np.asarray(mu, dtype=float)
    matrix = score_matrices(lambda_, mu, rho)
    goals = np.arange(matrix.shape[1])
    home_share, away_share = engine.first_half_shares(lambda_, mu, half)
    factor = 1.0 if share_factor is None else np.asarray(share_factor, dtype=float)
    home_share = np.clip(np.broadcast_to(home_share * factor, lambda_.shape), 0.05, 0.95)
    away_share = np.clip(np.broadcast_to(away_share * factor, lambda_.shape), 0.05, 0.95)
    thin_home = binom.pmf(goals[None, None, :], goals[None, :, None], home_share[:, None, None])
    thin_away = binom.pmf(goals[None, None, :], goals[None, :, None], away_share[:, None, None])
    first_half = np.einsum("ngk,ngh,nhl->nkl", thin_home, matrix, thin_away)

    home, away = np.indices(matrix.shape[1:])
    total = home + away
    markets: dict[str, np.ndarray] = {}
    for low, high in MATCH_MULTIGOL:
        markets[f"Multigol {low}-{high}"] = matrix[:, (total >= low) & (total <= high)].sum(axis=1)
    home_goals, away_goals = matrix.sum(axis=2), matrix.sum(axis=1)
    for low, high in TEAM_MULTIGOL:
        markets[f"Multigol Casa {low}-{high}"] = home_goals[:, low:high + 1].sum(axis=1)
        markets[f"Multigol Ospite {low}-{high}"] = away_goals[:, low:high + 1].sum(axis=1)
    markets["Somma gol"] = np.stack(
        [matrix[:, total == value].sum(axis=1) for value in range(5)] + [matrix[:, total >= 5].sum(axis=1)], axis=1
    )
    markets["1X2 1T"] = np.stack([
        first_half[:, home > away].sum(axis=1), first_half[:, home == away].sum(axis=1),
        first_half[:, home < away].sum(axis=1),
    ], axis=1)
    markets["Over 0.5 1T"] = first_half[:, total >= 1].sum(axis=1)
    markets["Over 1.5 1T"] = first_half[:, total >= 2].sum(axis=1)
    markets["GG 1T"] = first_half[:, 1:, 1:].sum(axis=(1, 2))
    return markets


def secondary_outcomes(features: pd.DataFrame) -> dict[str, np.ndarray]:
    home = features["home_goals"].to_numpy(int)
    away = features["away_goals"].to_numpy(int)
    home_ht = features["home_ht_goals"].to_numpy(int)
    away_ht = features["away_ht_goals"].to_numpy(int)
    total = home + away
    observed: dict[str, np.ndarray] = {}
    for low, high in MATCH_MULTIGOL:
        observed[f"Multigol {low}-{high}"] = ((total >= low) & (total <= high)).astype(int)
    for low, high in TEAM_MULTIGOL:
        observed[f"Multigol Casa {low}-{high}"] = ((home >= low) & (home <= high)).astype(int)
        observed[f"Multigol Ospite {low}-{high}"] = ((away >= low) & (away <= high)).astype(int)
    observed["Somma gol"] = np.minimum(total, 5)
    observed["1X2 1T"] = np.select([home_ht > away_ht, home_ht == away_ht], [0, 1], 2)
    observed["Over 0.5 1T"] = (home_ht + away_ht >= 1).astype(int)
    observed["Over 1.5 1T"] = (home_ht + away_ht >= 2).astype(int)
    observed["GG 1T"] = ((home_ht > 0) & (away_ht > 0)).astype(int)
    return observed


def secondary_scores(markets: Mapping[str, np.ndarray], observed: Mapping[str, np.ndarray], mask: np.ndarray) -> dict[str, dict]:
    scores = {}
    for name, probability in markets.items():
        probabilities = probability[mask] if probability.ndim == 2 else binary(probability[mask])
        scores[name] = summarize(probabilities, observed[name][mask])
    return scores


def secondary_rates(features: pd.DataFrame) -> dict[str, np.ndarray]:
    """Gol attesi finali (ancorati alle quote di chiusura) e solo-mercato per ogni partita."""
    final, market, model = [], [], []
    for row in features.to_dict("records"):
        config = config_for_row(row, odds=closing_odds(row))
        lambda_, mu, details = engine.final_goal_rates(config)
        anchoring = details["anchoring"]
        final.append((lambda_, mu))
        market.append((anchoring["market_lambda"], anchoring["market_mu"]))
        model.append((anchoring["model_lambda"], anchoring["model_mu"]))
    final, market, model = np.array(final), np.array(market), np.array(model)
    return {
        "final_lambda": final[:, 0], "final_mu": final[:, 1],
        "market_lambda": market[:, 0], "market_mu": market[:, 1],
        "model_lambda": model[:, 0], "model_mu": model[:, 1],
    }


def secondary_features(features: pd.DataFrame) -> pd.DataFrame:
    has_odds = features[["close_home", "close_draw", "close_away", "close_over25", "close_under25"]].gt(1.0).all(axis=1)
    evaluated = features["season"].isin([season for seasons in EVALUATION_SETS.values() for season in seasons])
    has_half = features[["home_ht_goals", "away_ht_goals"]].notna().all(axis=1)
    return features[has_odds & evaluated & has_half]


def secondary_analysis(features: pd.DataFrame, before: "engine.HalfTimeParams", after: "engine.HalfTimeParams") -> str:
    """Tabella prima/dopo per ogni mercato secondario, con il mercato derivato come riferimento."""
    features = secondary_features(features)
    rates = secondary_rates(features)
    rho = engine.MatchConfig(
        home=config_for_row(features.iloc[0]).home, away=config_for_row(features.iloc[0]).away,
        referee_yellow_avg=4.5, referee_fouls_avg=24.0,
    ).dixon_coles_rho
    variants = {
        "prima": secondary_markets(rates["final_lambda"], rates["final_mu"], rho, before),
        "dopo": secondary_markets(rates["final_lambda"], rates["final_mu"], rho, after),
        "mercato": secondary_markets(rates["market_lambda"], rates["market_mu"], rho, after),
        "modello": secondary_markets(rates["model_lambda"], rates["model_mu"], rho, after),
    }
    observed = secondary_outcomes(features)
    lines = [
        "## Mercati secondari (prima/dopo la taratura del primo tempo)", "",
        f"Generato il {date.today():%d/%m/%Y} con `python -m tools.baseline --mercati-secondari`. "
        "Tutti i mercati escono dalla matrice dei punteggi dei gol attesi finali (ancorati alle quote di "
        "chiusura 1X2 e O/U 2.5). Prima: primo tempo al 50% dei gol; dopo: quote del primo tempo tarate "
        f"({after.home_share:.3f} casa, {after.away_share:.3f} ospite, pendenza {after.total_slope:+.3f}). "
        "football-data non pubblica quote per questi mercati: il riferimento «mercato» è derivato dalla "
        "matrice di λ e μ che riproducono le quote di chiusura 1X2 e O/U 2.5. "
        "«Solo modello» usa i gol attesi dei soli dati squadra, senza quote. "
        f"⚠️ = log-loss peggiore del mercato derivato di oltre {SECONDARY_GAP} (finale / solo modello).", "",
    ]
    for set_name, seasons in EVALUATION_SETS.items():
        mask = features["season"].isin(seasons).to_numpy()
        scores = {name: secondary_scores(markets, observed, mask) for name, markets in variants.items()}
        lines += [
            f"### {set_name} ({int(mask.sum())} partite)", "",
            "| Mercato | Log-loss prima | Log-loss dopo | Log-loss mercato | Log-loss solo modello "
            "| Brier prima | Brier dopo | ECE prima | ECE dopo | Finale | Solo modello |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for name in variants["dopo"]:
            before_score, after_score, market_score, model_score = (
                scores[key][name] for key in ("prima", "dopo", "mercato", "modello")
            )

            def flag(score: Mapping[str, float]) -> str:
                gap = score["log_loss"] - market_score["log_loss"]
                return f"⚠️ +{gap:.3f}" if gap > SECONDARY_GAP else ""

            lines.append(
                f"| {name} | {before_score['log_loss']:.4f} | {after_score['log_loss']:.4f} | "
                f"{market_score['log_loss']:.4f} | {model_score['log_loss']:.4f} | "
                f"{before_score['brier']:.4f} | {after_score['brier']:.4f} | "
                f"{before_score['ece']:.4f} | {after_score['ece']:.4f} | {flag(after_score)} | {flag(model_score)} |"
            )
        lines.append("")
    return "\n".join(lines)


# --- Corner e cartellini ---------------------------------------------------------------

def count_predictions(features: pd.DataFrame, params: "engine.CountModelParams") -> pd.DataFrame:
    """Medie di corner e gialli calcolate dalle funzioni del motore per ogni partita."""
    rows = []
    for row in features.to_dict("records"):
        config = config_for_row(row, count_model=params)
        home, away = engine.corner_signals(config)
        rows.append({"corner_home": home, "corner_away": away, "cards": engine.card_total_mean(config)})
    return pd.DataFrame(rows, index=features.index)


def count_analysis(features: pd.DataFrame, before: "engine.CountModelParams", after: "engine.CountModelParams") -> str:
    from tools.calibrate import CARD_LINES, CORNER_LINES, count_data, count_logpmf, count_sf

    data = count_data(features)
    data = data[data["season"].isin([season for seasons in EVALUATION_SETS.values() for season in seasons])]
    variants = {"prima": before, "dopo": after}
    predictions = {name: count_predictions(data, params) for name, params in variants.items()}
    corners = (data["home_corners"] + data["away_corners"]).to_numpy(int)
    cards = (data["home_yellows"] + data["away_yellows"]).to_numpy(int)
    lines = [
        "## Corner e cartellini (prima/dopo la taratura sui dati reali)", "",
        f"Generato il {date.today():%d/%m/%Y} con `python -m tools.baseline --corner-cartellini`. Medie calcolate "
        "dalle funzioni del motore (`corner_signals`, `card_total_mean`); distribuzione Poisson o binomiale negativa "
        f"come nella simulazione. Dopo: dispersione corner {after.corner_dispersion:g}, gialli "
        f"{after.card_dispersion:g} (0 = Poisson), peso gialli arbitro {after.card_referee_yellow_weight:.3f}, "
        f"peso falli arbitro {after.card_referee_fouls_weight:.3f}. football-data non ha quote su corner e "
        "cartellini: nessun confronto con il mercato.", "",
    ]
    for set_name, seasons in EVALUATION_SETS.items():
        mask = data["season"].isin(seasons).to_numpy()
        lines += [f"### {set_name} ({int(mask.sum())} partite)", "",
                  "| Mercato | Misura | Prima | Dopo |", "|---|---|---|---|"]
        for label, observed, key, lines_set, dispersion in (
            ("Corner totali", corners, "corner", CORNER_LINES, "corner_dispersion"),
            ("Gialli totali", cards, "cards", CARD_LINES, "card_dispersion"),
        ):
            means = {name: (prediction["corner_home"] + prediction["corner_away"]).to_numpy() if key == "corner"
                     else prediction["cards"].to_numpy() for name, prediction in predictions.items()}
            shape = {name: (getattr(params, dispersion) if params.active else 0.0) for name, params in variants.items()}
            mae = {name: float(np.mean(np.abs(means[name][mask] - observed[mask]))) for name in variants}
            nll = {name: float(-np.mean(count_logpmf(observed[mask], means[name][mask], shape[name]))) for name in variants}
            lines.append(f"| {label} | errore medio assoluto | {mae['prima']:.3f} | {mae['dopo']:.3f} |")
            lines.append(f"| {label} | log-verosimiglianza negativa | {nll['prima']:.4f} | {nll['dopo']:.4f} |")
            for threshold in lines_set:
                outcome = (observed[mask] > threshold).astype(int)
                scores = {name: summarize(binary(count_sf(threshold, means[name][mask], shape[name])), outcome) for name in variants}
                lines.append(
                    f"| {label} Over {threshold:g} | log-loss / Brier / ECE | "
                    f"{scores['prima']['log_loss']:.4f} / {scores['prima']['brier']:.4f} / {scores['prima']['ece']:.4f} | "
                    f"{scores['dopo']['log_loss']:.4f} / {scores['dopo']['brier']:.4f} / {scores['dopo']['ece']:.4f} |"
                )
        lines.append("")
    return "\n".join(lines)


def card_points_analysis(features: pd.DataFrame, before: "engine.CountModelParams", after: "engine.CountModelParams",
                         rule: "engine.CardRule") -> str:
    """Punti cartellini (regola del bookmaker) prima/dopo, sulle stesse partite di valutazione."""
    from tools.calibrate import POINT_LINES, SECOND_YELLOW_EXCLUDED, count_means, observed_points, points_data, points_nll, points_sf

    data = points_data(features)
    data = data[data["season"].isin([season for seasons in EVALUATION_SETS.values() for season in seasons])]
    variants = {"prima": before, "dopo": after}
    lines = [
        "## Punti cartellini (regola del bookmaker, prima/dopo)", "",
        f"Generato il {date.today():%d/%m/%Y} con `python -m tools.baseline --cartellini-punti`. Regola: {rule.describe()}. "
        "Prima = modello dei soli gialli usato come previsione dei punti; dopo = gialli più rossi "
        f"({after.card_red_ratio:.4f} rossi per giallo atteso), dispersione gialli {before.card_dispersion:g} → "
        f"{after.card_dispersion:g}. Punti reali da gialli e rossi di football-data.co.uk: esatti nelle leghe europee; "
        "in Premier League la doppia ammonizione vale 2 invece di 3 (il primo giallo non è nei dati).", "",
    ]
    for set_name, seasons in EVALUATION_SETS.items():
        subset = data[data["season"].isin(seasons)]
        observed = observed_points(subset, rule)
        exact = ~subset["league"].isin(SECOND_YELLOW_EXCLUDED).to_numpy()
        lines += [f"### {set_name} ({len(subset)} partite, di cui {int(exact.sum())} con conteggio esatto)", "",
                  "| Misura | Prima | Dopo |", "|---|---|---|"]
        means, results = {}, {}
        for name, params in variants.items():
            yellow = count_means(params, subset)["cards"]
            shape = params.card_dispersion if params.active else 0.0
            red = yellow * params.card_red_ratio
            means[name] = yellow * (rule.yellow_weight + rule.red_weight * params.card_red_ratio)
            results[name] = (yellow, shape, red)
        lines.append(f"| Punti medi reali / previsti | {observed.mean():.3f} / {means['prima'].mean():.3f} | "
                     f"{observed.mean():.3f} / {means['dopo'].mean():.3f} |")
        mae = {name: float(np.mean(np.abs(means[name] - observed))) for name in variants}
        lines.append(f"| Errore medio assoluto | {mae['prima']:.3f} | {mae['dopo']:.3f} |")
        nll = {name: points_nll(*results[name], rule, observed) for name in variants}
        lines.append(f"| Log-verosimiglianza negativa | {nll['prima']:.4f} | {nll['dopo']:.4f} |")
        nll_exact = {name: points_nll(results[name][0][exact], results[name][1], results[name][2][exact], rule, observed[exact])
                     for name in variants}
        lines.append(f"| Log-verosimiglianza negativa (solo leghe esatte) | {nll_exact['prima']:.4f} | {nll_exact['dopo']:.4f} |")
        for threshold in POINT_LINES:
            outcome = (observed > threshold).astype(int)
            scores = {name: summarize(binary(points_sf(threshold, *results[name], rule)), outcome) for name in variants}
            lines.append(
                f"| Over {threshold:g} punti: log-loss / Brier / ECE | "
                f"{scores['prima']['log_loss']:.4f} / {scores['prima']['brier']:.4f} / {scores['prima']['ece']:.4f} | "
                f"{scores['dopo']['log_loss']:.4f} / {scores['dopo']['brier']:.4f} / {scores['dopo']['ece']:.4f} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", help="Titolo della sezione, es. PRIMA o DOPO")
    parser.add_argument("--goal-model", help="Valore di MatchConfig.goal_model (se supportato)")
    parser.add_argument("--ancorato", action="store_true", help="Passa le quote di chiusura al motore")
    parser.add_argument("--tara-ancoraggio", action="store_true", help="Tara peso del mercato e metodo di margine")
    parser.add_argument("--corner-cartellini", action="store_true", help="Corner e gialli prima/dopo la taratura")
    parser.add_argument("--cartellini-punti", action="store_true", help="Punti cartellini (gialli e rossi) prima/dopo")
    parser.add_argument("--mercati-secondari", action="store_true", help="Multigol, somma gol e primo tempo prima/dopo")
    parser.add_argument("--analisi-pareggio", action="store_true", help="Confronta Shin e proporzionale per 1, X e 2")
    parser.add_argument("--output", type=Path, help="File markdown a cui aggiungere la sezione")
    args = parser.parse_args()
    if args.corner_cartellini:
        markdown = count_analysis(load_usable_features(), engine.CountModelParams(), engine.DEFAULT_COUNT_MODEL)
    elif args.cartellini_punti:
        tuning = json.loads(engine.GOAL_MODEL_PATH.read_text(encoding="utf-8"))["corner_cartellini"]["taratura_punti"]
        before = replace(engine.DEFAULT_COUNT_MODEL, card_red_ratio=0.0, card_dispersion=tuning["dispersione_gialli"]["prima"])
        markdown = card_points_analysis(load_usable_features(), before, engine.DEFAULT_COUNT_MODEL, engine.DEFAULT_CARD_RULE)
    elif args.mercati_secondari:
        markdown = secondary_analysis(load_usable_features(), engine.HalfTimeParams(), engine.DEFAULT_HALF_TIME)
    elif args.analisi_pareggio:
        markdown = draw_analysis(load_usable_features())
    elif args.tara_ancoraggio:
        tuning = tune_market_anchor(load_usable_features())
        save_market_anchor(tuning)
        markdown = render_tuning(tuning)
    else:
        if not args.label:
            parser.error("--label è obbligatorio per la misura")
        overrides = {"goal_model": args.goal_model} if args.goal_model else {}
        results = run(overrides, anchored=args.ancorato)
        command = " ".join(
            part for part in (
                "python -m tools.baseline",
                f"--goal-model {args.goal_model}" if args.goal_model else "",
                "--ancorato" if args.ancorato else "",
            ) if part
        )
        description = (
            f"Generato il {date.today():%d/%m/%Y} con `{command}`. "
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
