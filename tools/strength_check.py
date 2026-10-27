"""Fase P, punto 1: forza corretta per il calendario (``ratings.py``), scelta e verifica fuori campione.

Per ogni campionato e settimana di gioco le forze si stimano con le sole partite precedenti (finestra di 730
giorni). Griglia: decadimento ξ ∈ ``DECAYS`` (per giorno) × peso dei gol ∈ ``GOAL_WEIGHTS`` (il resto xG
Understat). Due modi d'uso: «diretto» (gol attesi del modello = quelli Dixon-Coles) e «ingressi» (attacco e
difesa del blocco = forze Dixon-Coles, pesi del modello gol ristimati sul 2024-26). La combinazione si sceglie
sul 2024-26 con i gol ancorati al mercato come nell'app; resta accesa solo con la regola severa fuori
campione. Uso: ``python -m tools.strength_check [--salva] [--output docs/BASELINE.md]``.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

import engine
import ratings
from tools import dataset, v2common

DECAYS = (0.0005, 0.001, 0.002, 0.004)
GOAL_WEIGHTS = (1.0, 0.5, 0.0)
UNDERSTAT_CODES = {"I1": "Serie_A", "E0": "EPL", "SP1": "La_liga", "D1": "Bundesliga"}


def history_with_xg() -> pd.DataFrame:
    """Partite football-data con gli xG Understat della partita (dove ci sono)."""
    from datasources.cache import SourceCache
    from datasources.names import match_team
    from datasources.sources import Understat

    raw = dataset.load_raw().copy()
    raw["home_xg"] = raw["away_xg"] = np.nan
    understat = Understat(SourceCache())
    for league, code in UNDERSTAT_CODES.items():
        frames = [understat.league(code, year, timedelta(days=365 if year < 2026 else 1)).data for year in range(2019, 2027)]
        rows = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True)
        if rows.empty:
            continue
        rows = rows[rows["venue"] == "home"]
        names = {team: match_team(team, list(rows["team"].unique())) for team in raw.loc[raw["league"] == league, "home_team"].unique()}
        lookup = {(team, day): (xg_for, xg_against) for team, day, xg_for, xg_against in
                  rows[["team", "date", "xg_for", "xg_against"]].itertuples(index=False)}
        mask = raw["league"] == league
        for index, team, day in raw.loc[mask, ["home_team", "date"]].itertuples():
            found = lookup.get((names.get(team), pd.Timestamp(day).normalize()))
            if found:
                raw.at[index, "home_xg"], raw.at[index, "away_xg"] = found
    return raw


def strengths_table(history: pd.DataFrame, data: pd.DataFrame, params: ratings.StrengthParams) -> pd.DataFrame:
    """Gol attesi e rapporti attacco/difesa Dixon-Coles per ogni partita di ``data`` (nan senza stima)."""
    out = pd.DataFrame(index=data.index, columns=["dc_lambda", "dc_mu", "home_att", "home_def", "away_att", "away_def"],
                       dtype=float)
    week = data["date"].dt.to_period("W")
    for (league, _), group in data.groupby([data["league"], week]):
        fitted = ratings.fit(history[history["league"] == league], group["date"].min(), params)
        if fitted is None:
            continue
        for index, home, away in group[["home_team", "away_team"]].itertuples():
            out.loc[index, ["dc_lambda", "dc_mu"]] = fitted.rates(home, away)
            out.loc[index, ["home_att", "home_def"]] = fitted.ratios(home)
            out.loc[index, ["away_att", "away_def"]] = fitted.ratios(away)
    return out


def direct(data: pd.DataFrame, table: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    lambda_ = table["dc_lambda"].fillna(data["model_lambda"]).to_numpy(float)
    mu = table["dc_mu"].fillna(data["model_mu"]).to_numpy(float)
    return lambda_, mu


def inputs_mode(data: pd.DataFrame, table: pd.DataFrame, train: np.ndarray) -> tuple[np.ndarray, np.ndarray, engine.GoalModelParams]:
    from tools.calibrate import fit, model_inputs

    features = data.copy()
    for side in ("home", "away"):
        features[f"{side}_attack"] = table[f"{side}_att"].fillna(features[f"{side}_attack"]).clip(0.2, 3.0)
        features[f"{side}_defense"] = table[f"{side}_def"].fillna(features[f"{side}_defense"]).clip(0.2, 3.0)
    params, _ = fit(features[train])
    lambda_, mu, _ = engine.goal_rates(params, **model_inputs(features))
    return np.asarray(lambda_, float), np.asarray(mu, float), params


def run() -> dict:
    data = v2common.frame()
    train = v2common.is_train(data)
    history = history_with_xg()
    before_final = v2common.anchored(data, data["model_lambda"], data["model_mu"])
    base_train = v2common.goal_losses(data[train], before_final[0][train], before_final[1][train])
    grid = []
    tables = {}
    for decay, goal_weight in product(DECAYS, GOAL_WEIGHTS):
        params = ratings.StrengthParams(decay_per_day=decay, goal_weight=goal_weight)
        table = strengths_table(history, data, params)
        tables[(decay, goal_weight)] = table
        lambda_, mu = v2common.anchored(data, *direct(data, table))
        loss, ece = v2common.goal_losses(data[train], lambda_[train], mu[train])
        grid.append({"modo": "diretto", "decadimento": decay, "peso_gol": goal_weight, "taratura": float(loss.mean()),
                     "ece": ece})
        print(grid[-1], flush=True)
    best_direct = min(grid, key=lambda row: row["taratura"])
    # «ingressi» solo con la combinazione migliore del modo diretto (ristimare il modello per ogni cella è lento).
    table = tables[(best_direct["decadimento"], best_direct["peso_gol"])]
    in_lambda, in_mu, goal_params = inputs_mode(data, table, train)
    in_final = v2common.anchored(data, in_lambda, in_mu)
    in_train = v2common.goal_losses(data[train], in_final[0][train], in_final[1][train])
    candidates = {"diretto": v2common.anchored(data, *direct(data, table)), "ingressi": in_final}
    train_losses = {"diretto": best_direct["taratura"], "ingressi": float(in_train[0].mean())}
    mode = min(train_losses, key=train_losses.get)
    test = ~train
    before = v2common.goal_losses(data[test], before_final[0][test], before_final[1][test])
    results = {}
    for name, (lambda_, mu) in candidates.items():
        results[name] = v2common.strict(before, v2common.goal_losses(data[test], lambda_[test], mu[test]))
    model_only = {
        "attuale": v2common.goal_losses(data[test], data["model_lambda"].to_numpy()[test], data["model_mu"].to_numpy()[test]),
        "diretto": v2common.goal_losses(data[test], *[value[test] for value in direct(data, table)]),
        "ingressi": v2common.goal_losses(data[test], in_lambda[test], in_mu[test]),
    }
    return {"griglia": grid, "migliore": best_direct, "modo": mode, "taratura": train_losses,
            "taratura_attuale": float(base_train[0].mean()), "risultati": results,
            "solo_modello": {name: v2common.strict(model_only["attuale"], value) for name, value in model_only.items()},
            "parametri_gol": goal_params, "xg_coperti": float(history["home_xg"].notna().mean())}


def render(result: dict) -> str:
    best = result["migliore"]
    chosen = result["risultati"][result["modo"]]
    lines = ["## Forza corretta per il calendario (fase P, punto 1)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.strength_check`. Forze Dixon-Coles di tutte le "
             "squadre stimate insieme, solo con le partite precedenti (730 giorni, settimana per settimana), risposta = "
             f"peso·gol + (1 − peso)·xG Understat (xG presenti nel {result['xg_coperti']:.0%} delle partite storiche). "
             f"Griglia scelta sul 2024-26 con i gol ancorati al mercato: migliore ξ = {best['decadimento']}/giorno, "
             f"peso dei gol {best['peso_gol']}; modo scelto sul 2024-26: **{result['modo']}** (taratura: attuale "
             f"{result['taratura_attuale']:.4f}, diretto {result['taratura']['diretto']:.4f}, ingressi "
             f"{result['taratura']['ingressi']:.4f}).", "",
             "Fuori campione (2019-24 e 2026-27), log-loss 1X2 + Over/Under 2.5 per partita:", "",
             *v2common.TABLE_HEADER]
    for name, row in result["risultati"].items():
        lines.append(v2common.row_text(f"finale ancorato, {name}", row))
    for name, row in result["solo_modello"].items():
        if name != "attuale":
            text = v2common.row_text(f"solo modello, {name} (informativo)", row)
            verdict = "migliora" if row["tenuta"] else "non migliora"
            lines.append(text.replace("**accesa**", f"*{verdict}*").replace("**spenta**", f"*{verdict}*"))
    lines += ["", "Griglia (taratura 2024-26, modo diretto):", "", "| ξ/giorno | Peso gol | Log-loss | ECE |", "|---|---|---|---|"]
    lines += [f"| {row['decadimento']} | {row['peso_gol']} | {row['taratura']:.4f} | {row['ece']:.4f} |" for row in result["griglia"]]
    lines += ["", f"Esito: **{'accesa' if chosen['tenuta'] else 'spenta'}** (modo {result['modo']}).", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    markdown = render(result)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva:
        from tools.calibrate import _update_config

        best = result["migliore"]
        chosen = result["risultati"][result["modo"]]
        section = {"data": date.today().isoformat(), "attiva": chosen["tenuta"],
                   "parametri": {"decay_per_day": best["decadimento"], "goal_weight": best["peso_gol"], "mode": result["modo"],
                                 "window_days": 730, "prior_matches": 3.0},
                   "verifica": {name: {key: round(value, 6) if isinstance(value, float) else value for key, value in row.items()}
                                for name, row in result["risultati"].items()}}
        if result["modo"] == "ingressi":
            from dataclasses import asdict

            section["pesi_modello_gol"] = asdict(result["parametri_gol"])
        _update_config({"forza_calendario": section})


if __name__ == "__main__":
    main()
