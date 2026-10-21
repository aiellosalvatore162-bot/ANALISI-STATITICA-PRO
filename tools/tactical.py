"""Validazione della correzione «avversari simili» su stagioni intere.

Per ogni partita delle stagioni di taratura (2024-25, 2025-26) e di quella in
corso (2026-27) cerca le partite di entrambe le squadre contro avversari simili
(profilo al momento della partita + Elo), calcola i fattori con shrinkage e
misura 1X2, Over/Under 2.5, Multigol, primo tempo, corner e cartellini con e
senza correzione. Lo shrinkage τ è scelto sulle stagioni di taratura; una
correzione resta attiva solo se migliora sia sulle stagioni di taratura sia su
quella in corso. Risultati in ``docs/STILI.md`` e interruttori nella sezione
``scenario_tattico`` di ``config/goal_model.json``.

Uso: ``python -m tools.tactical``
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import json
from pathlib import Path

import numpy as np
import pandas as pd

import engine
from datasources.cache import SourceCache
from datasources.similar import FEATURES, correction_factors, match_factors, match_history, similar_matches
from datasources.sources import Understat
from tools import baseline, dataset
from tools.calibrate import CARD_LINES, CORNER_LINES, count_logpmf, count_means, count_sf, market_probabilities, score_matrices

UNDERSTAT_CODES = {"I1": "Serie_A", "E0": "EPL", "SP1": "La_liga", "D1": "Bundesliga"}
HISTORY_SEASONS = ("2223", "2324", "2425", "2526", "2627")
TAU_GRID = (5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0)
FAMILIES = ("goals", "goals_supremacy", "first_half", "corners", "cards")
DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "STILI.md"
SETTINGS = {"k": 10, "window_days": 730, "half_life_days": 365.0}


def load_histories(cache: SourceCache) -> dict[str, pd.DataFrame]:
    raw = dataset.load_raw()
    elos = dataset.match_elos(raw)
    understat = Understat(cache)
    histories = {}
    for league, code in UNDERSTAT_CODES.items():
        subset = raw[(raw["league"] == league) & raw["season"].isin(HISTORY_SEASONS)]
        frames = []
        for season in HISTORY_SEASONS:
            year = 2000 + int(season[:2])
            frame = understat.league(code, year, timedelta(days=1) if season == HISTORY_SEASONS[-1] else timedelta(days=60))
            if not frame.data.empty:
                frames.append(frame.data)
        histories[league] = match_history(subset, pd.concat(frames, ignore_index=True) if frames else None, elos.loc[subset.index])
    return histories


def _profile(row: pd.Series) -> dict[str, float]:
    return {key: float(row[f"z_{key}"]) for key in FEATURES if f"z_{key}" in row and pd.notna(row[f"z_{key}"])}


def find_neighbours(features: pd.DataFrame, histories: dict[str, pd.DataFrame]) -> list[dict]:
    """Partite simili per casa e ospite di ogni partita valutata."""
    neighbours = []
    for row in features.itertuples(index=False):
        history = histories[row.league]
        day = history[history["date"] == row.date]
        home = day[(day["team"] == row.home_team) & (day["venue"] == "home")]
        away = day[(day["team"] == row.away_team) & (day["venue"] == "away")]
        item = {"home": None, "away": None, "home_features": [], "away_features": []}
        if not home.empty and not away.empty and pd.notna(home.iloc[0]["history_matches"]) and pd.notna(away.iloc[0]["history_matches"]):
            for side, team_row, other_row in (("home", home.iloc[0], away.iloc[0]), ("away", away.iloc[0], home.iloc[0])):
                selected, used = similar_matches(history, team_row["team"], _profile(other_row), float(other_row["team_elo"]),
                                                 row.date, **SETTINGS)
                item[side], item[f"{side}_features"] = selected, used
        neighbours.append(item)
    return neighbours


def factor_arrays(neighbours: list[dict], tau: dict[str, float]) -> dict[str, np.ndarray]:
    keys = ("lambda", "mu", "first_half", "corners_home", "corners_away", "cards")
    result = {key: np.ones(len(neighbours)) for key in keys}
    result["matches"] = np.zeros(len(neighbours))
    for index, item in enumerate(neighbours):
        if item["home"] is None:
            continue
        sides = {}
        for side in ("home", "away"):
            ratio = len(FEATURES) / max(len(item[f"{side}_features"]), 1)
            sides[side], _, _ = correction_factors(item[side], tau=tau, feature_ratio=ratio)
        for key, value in match_factors(sides["home"], sides["away"]).items():
            result[key][index] = value
        result["matches"][index] = min(len(item["home"]), len(item["away"]))
    return result


def evaluate(features: pd.DataFrame, rates: dict[str, np.ndarray], factors: dict[str, np.ndarray],
             enabled: set[str], *, anchored: bool) -> dict[str, float]:
    """Log-loss medi per gruppo di mercati con le correzioni ``enabled``."""
    rho = engine.DEFAULT_GOAL_PARAMS.dixon_coles_rho
    lam, mu = rates["model_lambda"].copy(), rates["model_mu"].copy()
    if "goals" in enabled:
        lam, mu = lam * factors["lambda"], mu * factors["mu"]
    elif "goals_supremacy" in enabled:
        shift = np.sqrt(factors["lambda"] / factors["mu"])
        lam, mu = lam * shift, mu / shift
    if anchored:
        lam, mu, *_ = engine.anchor_goal_rates(lam, mu, rates["market_lambda"], rates["market_mu"], engine.DEFAULT_MARKET_ANCHOR)
    share = factors["first_half"] if "first_half" in enabled else None
    matrix_markets = market_probabilities(score_matrices(lam, mu, rho))
    secondary = baseline.secondary_markets(lam, mu, rho, engine.DEFAULT_HALF_TIME, share_factor=share)
    observed = baseline.secondary_outcomes(features)
    result_1x2 = np.select([features["home_goals"] > features["away_goals"], features["home_goals"] == features["away_goals"]], [0, 1], 2)
    over = ((features["home_goals"] + features["away_goals"]) > 2).to_numpy().astype(int)

    def mean_loss(names) -> float:
        return float(np.mean([baseline.log_loss(secondary[name] if secondary[name].ndim == 2 else baseline.binary(secondary[name]),
                                                observed[name]) for name in names]))

    count_model = engine.DEFAULT_COUNT_MODEL
    means = count_means(count_model, features)
    corner_home, corner_away, cards = means["corner_home"], means["corner_away"], means["cards"]
    if "corners" in enabled:
        corner_home, corner_away = corner_home * factors["corners_home"], corner_away * factors["corners_away"]
    if "cards" in enabled:
        cards = cards * factors["cards"]
    corner_total = (features["home_corners"] + features["away_corners"]).to_numpy(int)
    card_total = (features["home_yellows"] + features["away_yellows"]).to_numpy(int)
    corner_shape = count_model.corner_dispersion if count_model.active else 0.0
    card_shape = count_model.card_dispersion if count_model.active else 0.0

    def count_loss(totals, mean, shape, lines) -> float:
        nll = float(-np.mean(count_logpmf(totals, mean, shape)))
        lines_loss = np.mean([baseline.log_loss(baseline.binary(count_sf(line, mean, shape)), (totals > line).astype(int)) for line in lines])
        return nll + float(lines_loss)

    return {
        "1X2": baseline.log_loss(matrix_markets["1x2"], result_1x2),
        "Over/Under 2.5": baseline.log_loss(baseline.binary(matrix_markets["over25"]), over),
        "Multigol": mean_loss([f"Multigol {low}-{high}" for low, high in baseline.MATCH_MULTIGOL]),
        "Primo tempo": mean_loss(baseline.FIRST_HALF_MARKETS),
        "Corner": count_loss(corner_total, corner_home + corner_away, corner_shape, CORNER_LINES),
        "Cartellini": count_loss(card_total, cards, card_shape, CARD_LINES),
    }


FAMILY_MARKETS = {
    "goals": ("1X2", "Over/Under 2.5", "Multigol"),
    "goals_supremacy": ("1X2", "Over/Under 2.5", "Multigol"),
    "first_half": ("Primo tempo",),
    "corners": ("Corner",),
    "cards": ("Cartellini",),
}


def run(cache: SourceCache | None = None) -> dict:
    cache = cache or SourceCache()
    histories = load_histories(cache)
    features = baseline.secondary_features(baseline.load_usable_features())
    features = features[features["league"].isin(UNDERSTAT_CODES)].dropna(
        subset=["home_corners", "away_corners", "home_yellows", "away_yellows"]).reset_index(drop=True)
    rates = baseline.secondary_rates(features)
    neighbours = find_neighbours(features, histories)
    sets = {name: features["season"].isin(seasons).to_numpy() for name, seasons in baseline.EVALUATION_SETS.items()}
    calibration_set, holdout_set = baseline.EVALUATION_SETS

    def subset(mask):
        return features[mask].reset_index(drop=True), {key: value[mask] for key, value in rates.items()}

    chosen_tau, decisions, tables = {}, {}, {}
    for family in FAMILIES:
        scores = {}
        for tau in TAU_GRID:
            factors = factor_arrays(neighbours, {key: tau for key in ("goals", "first_half", "corners", "cards")})
            data, data_rates = subset(sets[calibration_set])
            loss = evaluate(data, data_rates, {key: value[sets[calibration_set]] for key, value in factors.items()}, {family}, anchored=False)
            scores[tau] = sum(loss[market] for market in FAMILY_MARKETS[family])
        chosen_tau[family] = min(scores, key=scores.get)

    # La variante «solo rapporto di forza» usa gli stessi fattori dei gol con il proprio τ.
    factors = factor_arrays(neighbours, {key: chosen_tau[key] for key in ("goals", "first_half", "corners", "cards")})
    supremacy = factor_arrays(neighbours, {**{key: chosen_tau[key] for key in ("first_half", "corners", "cards")},
                                           "goals": chosen_tau["goals_supremacy"]})
    factors["lambda_supremacy"], factors["mu_supremacy"] = supremacy["lambda"], supremacy["mu"]
    for set_name, mask in sets.items():
        data, data_rates = subset(mask)
        set_factors = {key: value[mask] for key, value in factors.items()}
        for anchored in (False, True):
            label = f"{set_name} · {'ancorato al mercato' if anchored else 'solo modello'}"
            base = evaluate(data, data_rates, set_factors, set(), anchored=anchored)
            tables[label] = {"senza": base}
            for family in FAMILIES:
                family_factors = set_factors if family != "goals_supremacy" else {
                    **set_factors, "lambda": set_factors["lambda_supremacy"], "mu": set_factors["mu_supremacy"]}
                tables[label][family] = evaluate(data, data_rates, family_factors, {family}, anchored=anchored)
    for family in FAMILIES:
        improvements = {}
        for label, table in tables.items():
            for market in FAMILY_MARKETS[family]:
                improvements[(label, market)] = table["senza"][market] - table[family][market]
        decisions[family] = {
            "attivo": all(value > 0 for value in improvements.values()),
            "miglioramenti": {f"{label} · {market}": round(value, 5) for (label, market), value in improvements.items()},
        }
    coverage = {
        "partite_valutate": int(len(features)),
        "partite_con_simili": int((factors["matches"] > 0).sum()),
        "simili_medie_per_squadra": round(float(factors["matches"][factors["matches"] > 0].mean()), 2),
    }
    return {"tau": chosen_tau, "decisions": decisions, "tables": tables, "coverage": coverage,
            "factor_spread": {key: [round(float(np.percentile(factors[key], q)), 3) for q in (5, 50, 95)]
                              for key in ("lambda", "mu", "lambda_supremacy", "mu_supremacy", "first_half",
                                          "corners_home", "corners_away", "cards")}}


def render(result: dict) -> str:
    names = {"goals": "Gol (λ, μ)", "goals_supremacy": "Gol, solo rapporto di forza", "first_half": "Quota primo tempo",
             "corners": "Corner", "cards": "Cartellini"}
    lines = [
        "# Analisi avversari simili: validazione", "",
        f"Generato il {date.today():%d/%m/%Y} con `python -m tools.tactical`. Serie A, Premier League, Liga e "
        "Bundesliga (Understat + football-data.co.uk). Per ogni partita: le 10 partite di ciascuna squadra negli "
        "ultimi 2 anni contro gli avversari più simili all'avversario di oggi (profilo al momento della partita su "
        f"{len(FEATURES)} metriche + Elo; emivita 1 anno), rendimento rispetto alla media delle 20 gare precedenti, "
        "shrinkage verso 1 con forza τ, limiti 0.85-1.15 (gol, primo tempo) e 0.80-1.20 (corner, cartellini).", "",
        f"Partite valutate: {result['coverage']['partite_valutate']}; con partite simili: "
        f"{result['coverage']['partite_con_simili']} (in media {result['coverage']['simili_medie_per_squadra']} per squadra).", "",
        "## τ scelto sulle stagioni di taratura e decisione", "",
        "| Correzione | τ | Fattori (5°/50°/95° percentile) | Attiva |", "|---|---|---|---|",
    ]
    spread = result["factor_spread"]
    spread_keys = {"goals": ("lambda", "mu"), "goals_supremacy": ("lambda_supremacy", "mu_supremacy"),
                   "first_half": ("first_half",), "corners": ("corners_home", "corners_away"), "cards": ("cards",)}
    for family in FAMILIES:
        values = "; ".join(f"{key} {spread[key][0]:.3f}/{spread[key][1]:.3f}/{spread[key][2]:.3f}" for key in spread_keys[family])
        lines.append(f"| {names[family]} | {result['tau'][family]:g} | {values} | "
                     f"{'**sì**' if result['decisions'][family]['attivo'] else 'no'} |")
    lines += ["", "Regola: attiva solo se riduce il log-loss su tutti i mercati del gruppo, sia nelle stagioni di "
              "taratura sia in quella in corso, sia con il solo modello sia con l'ancoraggio al mercato.", ""]
    at_edge = [names[family] for family in FAMILIES if result["tau"][family] == max(TAU_GRID)]
    if at_edge:
        lines += [f"Lettura: per {', '.join(at_edge)} τ è al massimo della griglia ({max(TAU_GRID):g}): i fattori sono "
                  "quasi uguali a 1 e i dati preferiscono nessuna correzione.", ""]
    for label, table in result["tables"].items():
        lines += [f"## {label}", "", "| Mercato | Senza correzione | Gol | Gol, solo rapporto di forza | Primo tempo | Corner | Cartellini |",
                  "|---|---|---|---|---|---|---|"]
        for market in table["senza"]:
            cells = [f"{table[family][market]:.5f}" + (" ✓" if table[family][market] < table["senza"][market] - 1e-9 else "")
                     for family in FAMILIES]
            lines.append(f"| {market} | {table['senza'][market]:.5f} | " + " | ".join(cells) + " |")
        lines += ["", "Log-loss medio (corner e cartellini: log-verosimiglianza negativa del totale + log-loss medio "
                  "delle linee Over/Under). ✓ = migliore che senza correzione.", ""]
    return "\n".join(lines)


def save(result: dict) -> None:
    path = engine.GOAL_MODEL_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scenario_tattico"] = {
        "attivo": {family: result["decisions"][family]["attivo"] for family in FAMILIES},
        "parametri": {"tau": result["tau"], **SETTINGS},
        "validazione": {"data": date.today().isoformat(), "copertura": result["coverage"],
                        "decisioni": result["decisions"], "documento": "docs/STILI.md"},
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    result = run()
    save(result)
    DOC_PATH.write_text(render(result) + "\n", encoding="utf-8")
    print(render(result))


if __name__ == "__main__":
    main()
