"""Fase Q, punto 7: verifica fuori campione dei nuovi mercati (6b) dove i dati ci sono.

Stagioni 2019-24 e 2026-27 (football-data.co.uk, fuori dal periodo di taratura). Probabilità esatte, come nel
motore: punteggi Dixon-Coles con i gol attesi ancorati alle quote di chiusura (``engine.final_goal_rates``), gol
del primo tempo per assottigliamento binomiale con le quote tarate (``engine.first_half_shares``); corner totali
binomiale negativa del modello dei conteggi con ripartizione binomiale casa/ospite; gialli totali binomiale
negativa (le fasce dell'app sono in punti del bookmaker: qui si misurano sui gialli, i rossi sono rari).
Per famiglia: log-loss binaria media, ECE media e scarto massimo tra probabilità media e frequenza.
Non verificabili (nessun dato per tempo nei CSV): corner e cartellini per tempo, 1X2 corner/cartellini 1T.
Uso: ``python -m tools.new_markets [--output docs/BASELINE.md]``.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binom, nbinom, poisson

import engine
from market_catalog import (
    CARD_TOTAL_BANDS, CORNER_TEAM_BANDS, CORNER_TOTAL_BANDS, MULTIGOL_1T_RANGES, MULTIGOL_2T_RANGES, OPEN,
    TEAM_PAIR_RANGES, range_label,
)
from tools import baseline, dataset

MAX_GOALS = 10
MAX_COUNT = 40
SIGNS = ("1", "X", "2", "1X", "X2")
NOT_VERIFIABLE = ("Corner per tempo (Over/Under 1T e 2T, 1X2 corner 1T)",
                  "Cartellini per tempo (Over/Under 1T e 2T, 1X2 cartellini 1T)",
                  "Fasce cartellini per squadra (divisione verificata nella fase T solo per le linee)")


def _between(values: np.ndarray, low: int, high: int) -> np.ndarray:
    return (values >= low) & (values <= (high if high != OPEN else 10 ** 6))


def goal_markets(lambda_: float, mu: float, rho: float) -> dict[str, float]:
    matrix = engine.dixon_coles_matrix(lambda_, mu, rho, max_goals=MAX_GOALS)
    matrix = matrix / matrix.sum()
    share_home, share_away = engine.first_half_shares(lambda_, mu, engine.DEFAULT_HALF_TIME)
    goals = np.arange(MAX_GOALS + 1)
    first_home = binom.pmf(goals[None, :], goals[:, None], float(share_home))   # [finale, primo tempo]
    first_away = binom.pmf(goals[None, :], goals[:, None], float(share_away))
    # joint[h, a, i, j]: finale h-a, primo tempo i-j
    joint = matrix[:, :, None, None] * first_home[:, None, :, None] * first_away[None, :, None, :]
    h, a, i, j = np.indices(joint.shape)
    first, second = i + j, (h - i) + (a - j)
    home, away = np.indices(matrix.shape)
    total = home + away
    out = {}
    for low, high in MULTIGOL_1T_RANGES:
        out[f"Multigol 1T {range_label(low, high)}"] = float(joint[_between(first, low, high)].sum())
    for low, high in MULTIGOL_2T_RANGES:
        out[f"Multigol 2T {range_label(low, high)}"] = float(joint[_between(second, low, high) & (second >= 0)].sum())
    for line in (4.5, 5.5, 6.5):
        out[f"Over {line} gol"] = float(matrix[total > line].sum())
    both = (home > 0) & (away > 0)
    signs = {"1": home > away, "X": home == away, "2": home < away}
    signs |= {"1X": signs["1"] | signs["X"], "X2": signs["X"] | signs["2"]}
    for line in (2.5, 3.5, 4.5):
        for name, mask in (("Goal", both), ("No Goal", ~both)):
            out[f"{name} + Over {line}"] = float(matrix[mask & (total > line)].sum())
            out[f"{name} + Under {line}"] = float(matrix[mask & (total < line)].sum())
    for line in (1.5, 2.5, 3.5, 4.5):
        for sign in SIGNS:
            out[f"{sign} + Over {line}"] = float(matrix[signs[sign] & (total > line)].sum())
            out[f"{sign} + Under {line}"] = float(matrix[signs[sign] & (total < line)].sum())
    for home_range in TEAM_PAIR_RANGES:
        for away_range in TEAM_PAIR_RANGES:
            key = f"Multigol Casa {range_label(*home_range)} + Ospite {range_label(*away_range)}"
            out[key] = float(matrix[_between(home, *home_range) & _between(away, *away_range)].sum())
    return out


def goal_outcomes(row) -> dict[str, bool]:
    home, away, first_home, first_away = (int(row.home_goals), int(row.away_goals), int(row.home_ht_goals),
                                          int(row.away_ht_goals))
    total, first = home + away, first_home + first_away
    second = total - first
    out = {}
    for low, high in MULTIGOL_1T_RANGES:
        out[f"Multigol 1T {range_label(low, high)}"] = bool(_between(np.array(first), low, high))
    for low, high in MULTIGOL_2T_RANGES:
        out[f"Multigol 2T {range_label(low, high)}"] = bool(_between(np.array(second), low, high))
    for line in (4.5, 5.5, 6.5):
        out[f"Over {line} gol"] = total > line
    both = home > 0 and away > 0
    signs = {"1": home > away, "X": home == away, "2": home < away}
    signs |= {"1X": signs["1"] or signs["X"], "X2": signs["X"] or signs["2"]}
    for line in (2.5, 3.5, 4.5):
        for name, flag in (("Goal", both), ("No Goal", not both)):
            out[f"{name} + Over {line}"] = flag and total > line
            out[f"{name} + Under {line}"] = flag and total < line
    for line in (1.5, 2.5, 3.5, 4.5):
        for sign in SIGNS:
            out[f"{sign} + Over {line}"] = signs[sign] and total > line
            out[f"{sign} + Under {line}"] = signs[sign] and total < line
    for home_range in TEAM_PAIR_RANGES:
        for away_range in TEAM_PAIR_RANGES:
            out[f"Multigol Casa {range_label(*home_range)} + Ospite {range_label(*away_range)}"] = bool(
                _between(np.array(home), *home_range) and _between(np.array(away), *away_range))
    return out


def _nb(mean: float, dispersion: float) -> np.ndarray:
    counts = np.arange(MAX_COUNT + 1)
    pmf = nbinom.pmf(counts, dispersion, dispersion / (dispersion + mean)) if dispersion > 0 else poisson.pmf(counts, mean)
    return pmf / pmf.sum()


def count_markets(corner_home: float, corner_away: float, cards: float, model) -> dict[str, float]:
    corner_shape = model.corner_dispersion if model.active else 0.0
    card_shape = model.card_dispersion if model.active else 0.0
    corners = _nb(corner_home + corner_away, corner_shape)
    counts = np.arange(MAX_COUNT + 1)
    share = corner_home / (corner_home + corner_away)
    home = corners @ binom.pmf(counts[None, :], counts[:, None], share)  # [totale, corner della squadra]
    away = corners @ binom.pmf(counts[None, :], counts[:, None], 1.0 - share)
    yellows = _nb(cards, card_shape)
    out = {}
    for low, high in CORNER_TOTAL_BANDS:
        out[f"Corner totali {range_label(low, high)}"] = float(corners[_between(counts, low, high)].sum())
    for low, high in CORNER_TEAM_BANDS:
        out[f"Corner casa {range_label(low, high)}"] = float(home[_between(counts, low, high)].sum())
        out[f"Corner ospite {range_label(low, high)}"] = float(away[_between(counts, low, high)].sum())
    for low, high in CARD_TOTAL_BANDS:
        out[f"Cartellini totali {range_label(low, high)}"] = float(yellows[_between(counts, low, high)].sum())
    return out


def count_outcomes(row) -> dict[str, bool]:
    corners, home, away = int(row.home_corners + row.away_corners), int(row.home_corners), int(row.away_corners)
    yellows = int(row.home_yellows + row.away_yellows)
    out = {}
    for low, high in CORNER_TOTAL_BANDS:
        out[f"Corner totali {range_label(low, high)}"] = bool(_between(np.array(corners), low, high))
    for low, high in CORNER_TEAM_BANDS:
        out[f"Corner casa {range_label(low, high)}"] = bool(_between(np.array(home), low, high))
        out[f"Corner ospite {range_label(low, high)}"] = bool(_between(np.array(away), low, high))
    for low, high in CARD_TOTAL_BANDS:
        out[f"Cartellini totali {range_label(low, high)}"] = bool(_between(np.array(yellows), low, high))
    return out


FAMILIES = {
    "Multigol 1T": lambda key: key.startswith("Multigol 1T"),
    "Multigol 2T": lambda key: key.startswith("Multigol 2T"),
    "Over 4.5-6.5 gol": lambda key: key.startswith("Over") and key.endswith("gol"),
    "Goal/No Goal + U/O": lambda key: key.startswith(("Goal +", "No Goal +")),
    "Segno + U/O": lambda key: key.split(" + ")[0] in SIGNS and " + " in key,
    "Multigol casa+ospite": lambda key: key.startswith("Multigol Casa"),
    "Fasce corner totali": lambda key: key.startswith("Corner totali"),
    "Fasce corner per squadra": lambda key: key.startswith(("Corner casa", "Corner ospite")),
    "Fasce cartellini totali (gialli)": lambda key: key.startswith("Cartellini totali"),
}


def run(limit: int | None = None) -> pd.DataFrame:
    from tools.calibrate import count_means
    from tools.goleade import rates

    features = baseline.load_usable_features()
    features = features[~features["season"].isin(dataset.CALIBRATION_SEASONS)].dropna(
        subset=["close_home", "close_draw", "close_away", "home_ht_goals", "away_ht_goals", "home_corners", "away_corners",
                "home_yellows", "away_yellows", "referee_yellow_avg", "referee_fouls_avg"])
    if limit:
        features = features.tail(limit)
    features = features.reset_index(drop=True)
    goal_rates = rates(features)
    model = engine.DEFAULT_COUNT_MODEL
    means = count_means(model, features)
    predicted, observed = [], []
    for index, row in enumerate(features.itertuples()):
        probabilities = goal_markets(goal_rates.at[index, "lambda"], goal_rates.at[index, "mu"], goal_rates.at[index, "rho"])
        probabilities |= count_markets(means["corner_home"][index], means["corner_away"][index], means["cards"][index], model)
        predicted.append(probabilities)
        observed.append(goal_outcomes(row) | count_outcomes(row))
    return pd.DataFrame(predicted), pd.DataFrame(observed).astype(int)


def report(predicted: pd.DataFrame, observed: pd.DataFrame) -> str:
    lines = ["## Nuovi mercati: verifica fuori campione (fase Q, punto 7)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.new_markets`. {len(predicted)} partite 2019-24 e "
             "2026-27 (fuori dal periodo di taratura), gol ancorati alle quote di chiusura, primo tempo con le quote "
             "tarate, corner e gialli dal modello dei conteggi. Per ogni famiglia: media sui mercati della log-loss "
             "binaria e dell'ECE, scarto massimo tra probabilità media e frequenza osservata.", "",
             "| Famiglia | Mercati | Log-loss media | ECE media | Scarto massimo (mercato: previsto / reale) |",
             "|---|---|---|---|---|"]
    for family, belongs in FAMILIES.items():
        keys = [key for key in predicted if belongs(key) and observed[key].sum() > 0]
        if not keys:
            continue
        stats = [baseline.summarize(baseline.binary(predicted[key].to_numpy()), observed[key].to_numpy()) for key in keys]
        gaps = {key: predicted[key].mean() - observed[key].mean() for key in keys}
        worst = max(gaps, key=lambda key: abs(gaps[key]))
        lines.append(f"| {family} | {len(keys)} | {np.mean([s['log_loss'] for s in stats]):.4f} | "
                     f"{np.mean([s['ece'] for s in stats]):.4f} | {worst}: {predicted[worst].mean():.1%} / "
                     f"{observed[worst].mean():.1%} |")
    lines += ["", "Non verificabili con i dati storici disponibili: " + "; ".join(NOT_VERIFIABLE) + ". Le quote dei "
              "tempi per corner (0,493) e cartellini (0,386) vengono dai pesi dei blocchi stimati su StatsBomb Open Data "
              "2015/16 (fase O) e restano dichiarate come non verificate.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    markdown = report(*run(args.limit))
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")


if __name__ == "__main__":
    main()
