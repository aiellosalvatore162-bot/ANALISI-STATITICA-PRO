"""Fase AN: controllo rapido, il dato importato migliora davvero?

Motore attuale con e senza i dati importati (forma reale dello stile; 1 stagione, 3 campionati): log-loss ed errore di
calibrazione (ECE) per mercato, con differenza appaiata. Riguarda solo le partite in cui almeno una squadra ha un dato
importato precedente alla partita. Uso: ``python -m tools.confronto_dati [--tipo stile] [--stagione 2425] [--campionati E0 I1 D1]``.
"""

from __future__ import annotations

import argparse

import numpy as np

import data_import
from tools import backtest_wf as bw

OPTION = {"forma_reale": True, "phi": "walkforward"}


def compare(campionati, stagioni) -> str:
    results = {}
    for enabled in (False, True):
        data_import.ENABLED = enabled
        features, _ = bw.prepare(campionati, stagioni, refresh=True)
        results[enabled] = (features, bw.market_table(features, bw.predict(features, OPTION)))
    data_import.ENABLED = True
    features = results[True][0]
    test = features["season"].isin(stagioni).to_numpy()
    covered = np.array([bool(data_import.style_row(row["home_team"], row["date"]) or data_import.style_row(row["away_team"], row["date"]))
                        for row in features.to_dict("records")]) & test
    lines = [f"Confronto dati importati ({', '.join(campionati)}, {', '.join(stagioni)}): {int(covered.sum())} partite coperte su {int(test.sum())}.",
             "", "| Mercato | Casi | Log-loss senza | con | Differenza (± 2 e.s.) | ECE senza | con |", "|---|---|---|---|---|---|---|"]
    if not covered.any():
        return lines[0] + "\nNessuna partita del campione ha dati importati prima della data: nulla da confrontare."
    before, after = bw.metrics(results[False][1], covered), bw.metrics(results[True][1], covered)
    for market in before:
        a, outcome, mask = results[False][1][market]
        b = results[True][1][market][0]
        ok = covered & mask
        if ok.sum() < 30:
            continue
        delta = bw._losses(b[ok], outcome[ok]) - bw._losses(a[ok], outcome[ok])
        lines.append(f"| {market} | {int(ok.sum())} | {before[market]['log_loss']:.4f} | {after[market]['log_loss']:.4f} | "
                     f"{delta.mean():+.5f} ± {2 * delta.std(ddof=1) / np.sqrt(len(delta)):.5f} | {before[market]['ece']:.4f} | {after[market]['ece']:.4f} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tipo", default="stile", help="solo «stile» entra oggi nel motore")
    parser.add_argument("--stagione", default="2425")
    parser.add_argument("--campionati", nargs="+", default=["E0", "I1", "D1"])
    args = parser.parse_args()
    if args.tipo != "stile":
        print("Oggi solo i dati di stile modificano il motore: per gli altri tipi non c'è nulla da confrontare.")
        return
    bw.CACHE = bw.CACHE.parent / "confronto_dati"
    bw.CACHE.mkdir(parents=True, exist_ok=True)
    print(compare(args.campionati, [args.stagione]))


if __name__ == "__main__":
    main()
