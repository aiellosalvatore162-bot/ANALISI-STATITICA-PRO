"""Fase P, punto 7: soglia di valore per mercato = errore tipico del modello su quel mercato.

Errore tipico (punti di EV) = media, pesata per partite, dello scarto relativo |frequenza reale − probabilità
media| / probabilità media nelle 10 classi di probabilità (classi con almeno ``MIN_BIN`` partite), sulle stagioni
fuori campione e per ogni lato del mercato (es. Over e Under). Se la probabilità sbaglia in media del 6% relativo,
anche l'EV calcolato sbaglia di circa 6 punti: un EV sotto questa soglia non è distinguibile da zero.
Verifica: sulle quote di chiusura storiche (solo 1X2 senza pareggio e Over/Under 2.5) rendimento delle giocate
sopra soglia con le soglie stimate e con quelle attuali di ``config/oggi.json``; le stimate restano accese solo se
il rendimento non peggiora. Uso: ``python -m tools.value_thresholds [--salva] [--output ...]``.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools import v2common
from tools.recalibration_check import table

MIN_BIN = 50
MIN_BETS = 100
GROUPS = {
    "1X2": ("1", "X", "2"), "Doppia chance": ("1X", "X2", "12"), "DNB": ("1", "2"),
    "Gol": ("Over 1.5 gol", "Over 2.5 gol", "Over 3.5 gol", "Goal", "Multigol 1-3", "Multigol 2-4", "Multigol 2-5"),
    "Primo tempo": ("1 1T", "X 1T", "2 1T", "Over 0.5 gol 1T", "Over 1.5 gol 1T"),
    "Corner": ("Over 8.5 corner", "Over 9.5 corner", "Over 10.5 corner"),
    "Cartellini": ("Over 3.5 cartellini", "Over 4.5 cartellini", "Over 5.5 cartellini"),
    "Combo": ("1 + Over 1.5", "1 + Over 2.5", "2 + Over 1.5", "2 + Over 2.5", "Goal + Over 2.5", "Goal + Over 3.5"),
    "Risultati esatti": ("Esatti 1-0/2-0/2-1", "Esatti 0-1/0-2/1-2", "Esatti 0-0/1-1", "Esatti 1-1/2-2",
                         "Esatti 2-1/3-1/3-2"),
}
# Mercati a due lati: si misura anche il complemento (Under, No Goal, …); 1X2 e gruppi hanno già tutti i lati.
TWO_SIDED = ("Over", "Goal", "Multigol")
OGGI_PATH = Path(__file__).resolve().parents[1] / "config" / "oggi.json"


def relative_error(p: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    order = np.argsort(p)
    total, weight = 0.0, 0
    for index in np.array_split(order, 10):
        if len(index) < MIN_BIN:
            continue
        mean = p[index].mean()
        total += len(index) * abs(y[index].mean() - mean) / mean
        weight += len(index)
    return (total / weight if weight else float("nan")), weight


def estimate() -> dict[str, float]:
    predicted, observed, data = table()
    test = ~v2common.is_train(data)
    thresholds = {}
    for group, keys in GROUPS.items():
        errors, weights = [], []
        for key in keys:
            valid = test & predicted[key].notna().to_numpy()
            p, y = predicted[key].to_numpy(float)[valid], observed[key].to_numpy(float)[valid]
            sides = [(p, y)] + ([(1 - p, 1 - y)] if key.startswith(TWO_SIDED) else [])
            for side_p, side_y in sides:
                error, weight = relative_error(side_p, side_y)
                if np.isfinite(error):
                    errors.append(error)
                    weights.append(weight)
        thresholds[group] = round(100 * float(np.average(errors, weights=weights)), 1)
    return thresholds


def backtest(thresholds: dict[str, float]) -> dict:
    """Giocate sopra soglia sulle quote di chiusura (1 e 2; Over/Under 2.5), fuori campione."""
    data = v2common.frame()
    data = data[~v2common.is_train(data)]
    probabilities = v2common.goal_probabilities(data["final_lambda"].to_numpy(), data["final_mu"].to_numpy(),
                                                float(data["rho"].iloc[0]))
    result, over = v2common.outcomes(data)
    bets = []
    for column, index, group, won in (("close_home", 0, "1X2", result == 0), ("close_away", 2, "1X2", result == 2)):
        bets.append((probabilities["1x2"][:, index], data[column].to_numpy(), group, won))
    bets.append((probabilities["over25"], data["close_over25"].to_numpy(), "Gol", over == 1))
    bets.append((1 - probabilities["over25"], data["close_under25"].to_numpy(), "Gol", over == 0))
    profits = []
    for probability, odds, group, won in bets:
        ev = 100 * (probability * odds - 1)
        chosen = ev >= thresholds[group]
        profits.append(np.where(won[chosen], odds[chosen] - 1, -1.0))
    profit = np.concatenate(profits)
    return {"giocate": int(len(profit)), "rendimento": float(profit.mean()) if len(profit) else 0.0,
            "errore_standard": float(profit.std(ddof=1) / np.sqrt(len(profit))) if len(profit) > 1 else float("nan")}


def run() -> dict:
    estimated = estimate()
    current = json.loads(OGGI_PATH.read_text(encoding="utf-8"))["soglie_ev"]
    before, after = backtest(current), backtest(estimated)
    verifiable = min(before["giocate"], after["giocate"]) >= MIN_BETS
    keep = verifiable and after["rendimento"] >= before["rendimento"]
    return {"stimate": estimated, "attuali": current, "prima": before, "dopo": after, "tenuta": keep,
            "verificabile": verifiable}


def render(result: dict) -> str:
    lines = ["## Soglia di valore per mercato (fase P, punto 7)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.value_thresholds`. Soglia = errore relativo tipico "
             "della probabilità finale fuori campione (2019-24 e 2026-27), in punti di EV.", "",
             "| Mercato | Soglia attuale (oggi.json) | Errore tipico stimato |", "|---|---|---|"]
    for group, value in result["stimate"].items():
        lines.append(f"| {group} | {result['attuali'].get(group, '—')} | {value:g} |")
    before, after = result["prima"], result["dopo"]
    lines += ["", "Verifica sulle quote di chiusura (1 e 2, Over/Under 2.5; il pareggio resta escluso come sempre):", "",
              "| Soglie | Giocate | Rendimento medio (± e.s.) |", "|---|---|---|",
              f"| attuali | {before['giocate']} | {before['rendimento']:+.2%} ± {before['errore_standard']:.2%} |",
              f"| stimate | {after['giocate']} | {after['rendimento']:+.2%} ± {after['errore_standard']:.2%} |", "",
              f"Esito: **{'accese le soglie stimate' if result['tenuta'] else 'restano le soglie attuali'}**"
              + ("" if result["verificabile"] else
                 f" (meno di {MIN_BETS} giocate: le probabilità finali sono ancorate alle stesse quote di chiusura, "
                 "quindi l'EV sulla chiusura supera di rado la soglia e il rendimento non è misurabile; le soglie "
                 "stimate restano disponibili in configurazione)") + ".", ""]
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

        _update_config({"soglie_valore": {"data": date.today().isoformat(), "attiva": result["tenuta"],
                                          "soglie_ev": result["stimate"], "verifica": {"prima": result["prima"],
                                                                                       "dopo": result["dopo"]}}})


if __name__ == "__main__":
    main()
