"""Fase O: verifica fuori campione del motore minuto per minuto contro il motore attuale.

Partite di football-data.co.uk (``tools.dataset``) non usate né per stimare le regole (Understat 2023/24
e 2024/25 = stagioni 2324 e 2425) né per tarare gli altri parametri (2024-26): campione casuale delle
stagioni 2019-23 più tutte le 2026-27. Ingressi come nell'app con le quote di chiusura (gol ancorati
al mercato), stesse medie di corner e cartellini (fasi M e T). Per ogni partita e variante
``SIMULATIONS`` simulazioni; log-loss ed ECE su 1X2, Over/Under, primo e secondo tempo, corner,
cartellini e combinazioni (Combo Builder).

Le componenti si provano in ordine (``gol_stato``, ``espulsioni``, ``corner_pressione``,
``cartellini_tempo``): una resta accesa solo se la log-loss media su tutti i mercati scende di più di due
errori standard (confronto appaiato partita per partita, così il rumore Monte Carlo non accende nulla) e
l'ECE media non sale. Uso: ``python -m tools.minute_check [--partite 1500] [--salva] [--output docs/BASELINE.md]``.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd

import engine
import timeline
from tools import baseline, dataset

SIMULATIONS = 20_000
EXCLUDED = ("2324", "2425", "2526")
TOLERANCE_ECE = 0.0005

BINARY = {
    "gol": ("Over 1.5", "Over 2.5", "Over 3.5", "Goal"),
    "tempi": ("1T Over 0.5", "1T Over 1.5", "2T Over 0.5", "2T Over 1.5", "Multigol 1T 0-1", "Multigol 1T 1-2",
              "Multigol 2T 0-1", "Multigol 2T 1-3", "Primo tempo con più gol"),
    "corner": ("Corner Over 8.5", "Corner Over 9.5", "Corner Over 10.5"),
    "cartellini": ("Cartellini Over 3.5", "Cartellini Over 4.5", "Cartellini Over 5.5"),
    "combo": ("Over 2.5 & Corner Over 9.5", "Over 2.5 & Cartellini Over 4.5", "Goal & Corner Over 9.5",
              "1 & Over 2.5", "X & Under 2.5", "Corner Over 9.5 & Cartellini Over 4.5", "X & Cartellini Over 4.5",
              "1T Over 0.5 & Over 2.5", "Under 2.5 & Corner Under 9.5", "1T Over 0.5 & Corner Over 9.5",
              "2T Over 1.5 & Cartellini Over 4.5", "1X2 1T pari & Cartellini Over 4.5"),
}
MULTI = {"gol": ("1X2",), "tempi": ("1X2 1T", "1X2 2T")}
# Gruppi su cui si decide (i mercati gol finali restano identici con le varianti a punteggi Dixon-Coles fissi).
SELECTION_GROUPS = ("tempi", "corner", "cartellini", "combo")


def evaluation_rows(limit: int, seed: int = 11) -> pd.DataFrame:
    features = baseline.load_usable_features()
    features = features.dropna(subset=["home_ht_goals", "away_ht_goals", "home_corners", "away_corners",
                                       "home_yellows", "away_yellows", "home_reds", "away_reds",
                                       "close_home", "close_draw", "close_away"])
    early = features[features["season"].isin(dataset.WARMUP_SEASONS) & ~features["season"].isin(EXCLUDED)]
    late = features[features["season"].isin(dataset.HOLDOUT_SEASONS)]
    early = early.sample(min(limit, len(early)), random_state=seed)
    return pd.concat([early, late]).sort_values("date")


def match_inputs(row: dict) -> dict:
    """Ingressi del motore per una partita: gol finali ancorati, quote primo tempo, medie di corner e cartellini."""
    config = baseline.config_for_row(row, odds=baseline.closing_odds(row))
    lambda_, mu, _ = engine.final_goal_rates(config)
    matrix = engine.dixon_coles_matrix(lambda_, mu, config.dixon_coles_rho, max_goals=12)
    home, away = np.indices(matrix.shape)
    underdog = float(matrix[home < away].sum() - matrix[home > away].sum())
    yellow_mean = engine.card_total_mean(config)
    share, _ = engine.card_split_share(config, underdog, yellow_mean)
    first_home, first_away = engine.first_half_shares(lambda_, mu, config.half_time)
    corner_home, corner_away = engine.corner_signals(config)
    count = config.count_model
    return {"config": config, "lambda": lambda_, "mu": mu, "matrix": matrix, "first_home": first_home,
            "first_away": first_away, "corner_home": corner_home, "corner_away": corner_away,
            "corner_dispersion": count.corner_dispersion if count.active else 0.0, "yellow_mean": yellow_mean,
            "card_dispersion": count.card_dispersion if count.active else 0.0,
            "red_mean": count.card_red_ratio * yellow_mean, "card_share": share}


def simulate(inputs: dict, params: timeline.TimelineParams | None, seed: int) -> dict[str, np.ndarray]:
    """Motore attuale (``params`` None) o minuto per minuto: gol per tempo, corner, punti cartellini totali."""
    rng = np.random.default_rng(seed)
    matrix = inputs["matrix"]
    index = rng.choice(matrix.size, size=SIMULATIONS, p=(matrix / matrix.sum()).ravel())
    goals_home, goals_away = np.unravel_index(index, matrix.shape)
    rule = inputs["config"].card_rule
    if params is None:
        first_home = rng.binomial(goals_home, inputs["first_home"])
        first_away = rng.binomial(goals_away, inputs["first_away"])
        corners = timeline._nb(rng, np.full(SIMULATIONS, inputs["corner_home"] + inputs["corner_away"]), inputs["corner_dispersion"])
        yellows = timeline._nb(rng, np.full(SIMULATIONS, inputs["yellow_mean"]), inputs["card_dispersion"])
        reds = rng.poisson(inputs["red_mean"], SIMULATIONS)
        return {"gh": goals_home, "ga": goals_away, "fh": first_home, "fa": first_away, "corners": corners,
                "points": engine.card_points(yellows, reds, rule)}
    out = timeline.sample(rng, SIMULATIONS, lambda_=inputs["lambda"], mu=inputs["mu"], first_share_home=inputs["first_home"],
                          first_share_away=inputs["first_away"], corner_home=inputs["corner_home"],
                          corner_away=inputs["corner_away"], corner_dispersion=inputs["corner_dispersion"],
                          yellow_mean=inputs["yellow_mean"], card_dispersion=inputs["card_dispersion"],
                          red_mean=inputs["red_mean"], card_share=inputs["card_share"], params=params,
                          scores=(goals_home, goals_away))
    reds = (out["reds_home"] + out["reds_away"]) if out["reds_home"] is not None else rng.poisson(inputs["red_mean"], SIMULATIONS)
    return {"gh": out["goals_home"], "ga": out["goals_away"], "fh": out["first_home"], "fa": out["first_away"],
            "corners": out["corners_home"] + out["corners_away"], "points": engine.card_points(out["yellows"], reds, rule)}


def events(sample: dict) -> dict[str, np.ndarray]:
    """Eventi booleani (o classe 0/1/2 per i 1X2) da un campione o dai risultati reali."""
    gh, ga, fh, fa = sample["gh"], sample["ga"], sample["fh"], sample["fa"]
    total, first = gh + ga, fh + fa
    second = total - first
    corners, points = sample["corners"], sample["points"]
    found = {
        "1X2": np.where(gh > ga, 0, np.where(gh == ga, 1, 2)), "1X2 1T": np.where(fh > fa, 0, np.where(fh == fa, 1, 2)),
        "1X2 2T": np.where(gh - fh > ga - fa, 0, np.where(gh - fh == ga - fa, 1, 2)),
        "Multigol 1T 0-1": first <= 1, "Multigol 1T 1-2": (first >= 1) & (first <= 2),
        "Multigol 2T 0-1": second <= 1, "Multigol 2T 1-3": (second >= 1) & (second <= 3),
        "Primo tempo con più gol": first > second,
        "Over 1.5": total > 1.5, "Over 2.5": total > 2.5, "Over 3.5": total > 3.5, "Goal": (gh > 0) & (ga > 0),
        "1T Over 0.5": first > 0.5, "1T Over 1.5": first > 1.5, "2T Over 0.5": second > 0.5, "2T Over 1.5": second > 1.5,
        "Corner Over 8.5": corners > 8.5, "Corner Over 9.5": corners > 9.5, "Corner Over 10.5": corners > 10.5,
        "Cartellini Over 3.5": points > 3.5, "Cartellini Over 4.5": points > 4.5, "Cartellini Over 5.5": points > 5.5,
    }
    found.update({
        "Over 2.5 & Corner Over 9.5": found["Over 2.5"] & found["Corner Over 9.5"],
        "Over 2.5 & Cartellini Over 4.5": found["Over 2.5"] & found["Cartellini Over 4.5"],
        "Goal & Corner Over 9.5": found["Goal"] & found["Corner Over 9.5"],
        "1 & Over 2.5": (gh > ga) & found["Over 2.5"], "X & Under 2.5": (gh == ga) & ~found["Over 2.5"],
        "Corner Over 9.5 & Cartellini Over 4.5": found["Corner Over 9.5"] & found["Cartellini Over 4.5"],
        "X & Cartellini Over 4.5": (gh == ga) & found["Cartellini Over 4.5"],
        "1T Over 0.5 & Over 2.5": found["1T Over 0.5"] & found["Over 2.5"],
        "Under 2.5 & Corner Under 9.5": ~found["Over 2.5"] & ~found["Corner Over 9.5"],
        "1T Over 0.5 & Corner Over 9.5": found["1T Over 0.5"] & found["Corner Over 9.5"],
        "2T Over 1.5 & Cartellini Over 4.5": found["2T Over 1.5"] & found["Cartellini Over 4.5"],
        "1X2 1T pari & Cartellini Over 4.5": (fh == fa) & found["Cartellini Over 4.5"],
    })
    return found


def probabilities(sample: dict) -> dict[str, np.ndarray]:
    found = events(sample)
    result = {}
    for key, value in found.items():
        if key in ("1X2", "1X2 1T", "1X2 2T"):
            result[key] = np.bincount(value, minlength=3) / len(value)
        else:
            result[key] = np.array([1 - value.mean(), value.mean()])
    return result


def outcomes(rows: pd.DataFrame) -> dict[str, np.ndarray]:
    rule = engine.DEFAULT_CARD_RULE
    real = {"gh": rows["home_goals"].to_numpy(int), "ga": rows["away_goals"].to_numpy(int),
            "fh": rows["home_ht_goals"].to_numpy(int), "fa": rows["away_ht_goals"].to_numpy(int),
            "corners": (rows["home_corners"] + rows["away_corners"]).to_numpy(int),
            "points": engine.card_points((rows["home_yellows"] + rows["away_yellows"]).to_numpy(int),
                                         (rows["home_reds"] + rows["away_reds"]).to_numpy(int), rule)}
    return {key: np.asarray(value).astype(int) for key, value in events(real).items()}


def per_match_loss(predictions: dict[str, list[np.ndarray]], observed: dict[str, np.ndarray]) -> np.ndarray:
    """Log-loss media sui mercati, partita per partita (per il confronto appaiato tra varianti)."""
    losses = []
    groups = SELECTION_GROUPS
    for key in (*(key for group in groups for key in MULTI.get(group, ())), *(key for group in groups for key in BINARY[group])):
        probs = np.clip(np.vstack(predictions[key]), 1e-6, 1)
        probs = probs / probs.sum(axis=1, keepdims=True)
        losses.append(-np.log(probs[np.arange(len(probs)), observed[key]]))
    return np.mean(losses, axis=0)


def score(predictions: dict[str, list[np.ndarray]], observed: dict[str, np.ndarray]) -> dict[str, dict]:
    result = {}
    for group, keys in {**{g: v for g, v in BINARY.items()}}.items():
        for key in (*MULTI.get(group, ()), *keys):
            probs = np.clip(np.vstack(predictions[key]), 1e-6, 1)
            probs = probs / probs.sum(axis=1, keepdims=True)
            result[key] = {**baseline.summarize(probs, observed[key]), "gruppo": group}
    for group in BINARY:
        keys = [key for key, value in result.items() if value.get("gruppo") == group]
        result[f"media {group}"] = {metric: float(np.mean([result[key][metric] for key in keys])) for metric in ("log_loss", "ece", "brier")}
    keys = [key for key in result if not key.startswith("media") and result[key]["gruppo"] in SELECTION_GROUPS]
    result["media"] = {metric: float(np.mean([result[key][metric] for key in keys])) for metric in ("log_loss", "ece", "brier")}
    return result


def run(limit: int, components: tuple[str, ...] = timeline.HYBRID_COMPONENTS + ("corner_pressione", "cartellini_tempo")
        ) -> tuple[dict, dict, pd.DataFrame]:
    rows = evaluation_rows(limit)
    observed = outcomes(rows)
    base_params = timeline.load(engine.GOAL_MODEL_PATH)
    inputs = [match_inputs(row) for row in rows.to_dict("records")]
    variants: dict[str, timeline.TimelineParams | None] = {"motore attuale": None}
    chosen: list[str] = []
    results = {}

    def evaluate(params):
        collected: dict[str, list] = {}
        for position, item in enumerate(inputs):
            for key, value in probabilities(simulate(item, params, seed=position)).items():
                collected.setdefault(key, []).append(value)
        scored = score(collected, observed)
        scored["_per_partita"] = per_match_loss(collected, observed)
        return scored

    results["motore attuale"] = evaluate(None)
    current = results["motore attuale"]
    steps = [{"passo": "motore attuale", "tenuta": True, "log_loss": current["media"]["log_loss"], "ece": current["media"]["ece"],
              "differenza": 0.0, "errore_standard": 0.0}]
    for component in components:
        candidate = base_params.with_components((*chosen, component))
        label = " + ".join((*chosen, component))
        results[label] = evaluate(candidate)
        mean = results[label]["media"]
        difference = results[label]["_per_partita"] - current["_per_partita"]
        standard_error = float(difference.std(ddof=1) / np.sqrt(len(difference)))
        keep = float(difference.mean()) < -2.0 * standard_error and mean["ece"] <= current["media"]["ece"] + TOLERANCE_ECE
        steps.append({"passo": label, "tenuta": keep, "log_loss": mean["log_loss"], "ece": mean["ece"],
                      "differenza": float(difference.mean()), "errore_standard": standard_error})
        if keep:
            chosen.append(component)
            current = results[label]
    return {"componenti": chosen, "passi": steps}, results, rows


def report(selection: dict, results: dict, rows: pd.DataFrame) -> str:
    final_label = " + ".join(selection["componenti"]) if selection["componenti"] else "motore attuale"
    before, after = results["motore attuale"], results[final_label]
    seasons = rows["season"].value_counts().sort_index()
    lines = ["## Motore minuto per minuto: verifica fuori campione (fase O)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.minute_check`. {len(rows)} partite di "
             f"football-data.co.uk ({', '.join(f'{season}: {count}' for season, count in seasons.items())}), escluse le "
             f"stagioni usate per stimare le regole o tarare gli altri parametri ({', '.join(EXCLUDED)}). Gol ancorati "
             f"alle quote di chiusura come nell'app; {SIMULATIONS:,} simulazioni per partita e variante. Una componente "
             "resta accesa solo se la log-loss media scende di più di due errori standard (confronto appaiato partita "
             f"per partita) e l'ECE media non sale (tolleranza {TOLERANCE_ECE}).".replace(",", "."), "",
             "### Componenti provate, nell'ordine", "",
             "| Passo | Log-loss media | ECE media | Differenza appaiata (± 2 e.s.) | Tenuta |", "|---|---|---|---|---|"]
    for step in selection["passi"]:
        lines.append(f"| {step['passo']} | {step['log_loss']:.5f} | {step['ece']:.5f} | "
                     f"{step['differenza']:+.5f} ± {2 * step['errore_standard']:.5f} | {'sì' if step['tenuta'] else 'no'} |")
    lines += ["", f"### Per mercato: motore attuale → scelta finale ({final_label})", "",
              "| Mercato | Gruppo | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |", "|---|---|---|---|---|---|"]
    for key, value in before.items():
        if key.startswith(("media", "_")):
            continue
        lines.append(f"| {key} | {value['gruppo']} | {value['log_loss']:.4f} | {after[key]['log_loss']:.4f} | "
                     f"{value['ece']:.4f} | {after[key]['ece']:.4f} |")
    lines += ["", "| Media per gruppo | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |", "|---|---|---|---|---|"]
    for key in [*(f"media {group}" for group in BINARY), "media"]:
        lines.append(f"| {key} | {before[key]['log_loss']:.4f} | {after[key]['log_loss']:.4f} | {before[key]['ece']:.4f} | {after[key]['ece']:.4f} |")
    lines += ["", "### Tutte le varianti (log-loss / ECE medie per gruppo)", "",
              "| Variante | " + " | ".join(BINARY) + " | media |", "|---|" + "---|" * (len(BINARY) + 1)]
    for label, value in results.items():
        cells = [f"{value[f'media {group}']['log_loss']:.4f} / {value[f'media {group}']['ece']:.4f}" for group in BINARY]
        lines.append(f"| {label} | " + " | ".join(cells) + f" | {value['media']['log_loss']:.4f} / {value['media']['ece']:.4f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--partite", type=int, default=1500, help="Partite del 2019-23 da campionare")
    parser.add_argument("--salva", action="store_true", help="Scrive componenti e attivazione in config/goal_model.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    selection, results, rows = run(args.partite)
    markdown = report(selection, results, rows)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva:
        from tools.calibrate import _update_config

        section = json.loads(engine.GOAL_MODEL_PATH.read_text(encoding="utf-8")).get("minuto_per_minuto", {})
        _update_config({"minuto_per_minuto": {
            **section, "attivo": bool(selection["componenti"]),
            "componenti": {component: component in selection["componenti"] for component in timeline.ALL_COMPONENTS},
            "verifica": {"data": date.today().isoformat(), "partite": len(rows),
                         "passi": [{key: (round(value, 5) if isinstance(value, float) else value) for key, value in step.items()}
                                   for step in selection["passi"]]},
        }})


if __name__ == "__main__":
    main()
