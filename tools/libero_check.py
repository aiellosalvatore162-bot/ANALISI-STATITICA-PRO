"""Fase AN: prova rapida del «Simulatore reale – completo» (modo libero + ripesatura Dixon-Coles) contro il motore attuale.

1 stagione (2023/24), 3 campionati (E0, I1, D1), ``--partite`` per campionato, stesse partite e stesso seme. Misura log-loss
ed ECE per gruppo (tempi, corner, cartellini, combo, come ``tools/event_check``) e, in più, sui mercati di gol. Risultati
parziali in ``data/cache/libero_check/`` (riprende se interrotto). Uso: ``python -m tools.libero_check [--partite 80]``.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

import engine
from tools import baseline, event_check as ec

PARTIAL = Path(__file__).resolve().parents[1] / "data" / "cache" / "libero_check"
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "backtest" / "AN_libero.md"
SIMS = 10_000
GOAL_BINARY = ("1", "X", "2", "Over 2.5 gol", "Over 1.5 gol", "Over 3.5 gol", "Goal")


def goal_probabilities(result: dict) -> dict[str, np.ndarray]:
    out = {}
    one = np.array([ec._mask(result, key).mean() for key in ("1", "X", "2")])
    out["1X2"] = one / one.sum()
    for key in GOAL_BINARY[3:]:
        p = ec._mask(result, key).mean()
        out[key] = np.array([1 - p, p])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--partite", type=int, default=80)
    parser.add_argument("--terzo", action="store_true", help="un terzo delle partite, stratificato per campionato (riusa i parziali)")
    args = parser.parse_args()
    PARTIAL.mkdir(parents=True, exist_ok=True)
    features = ec._usable()
    features = features[features["season"].eq("2324") & features["league"].isin(["E0", "I1", "D1"])]
    rows = ec.pd.concat([f.sample(min(args.partite, len(f)), random_state=5) for _, f in features.groupby("league")])
    rows = rows.sort_values("date").reset_index(drop=True)
    positions = list(range(len(rows)))
    if args.terzo:
        rank = rows.groupby("league").cumcount().to_numpy()
        positions = [p for p in positions if rank[p] % 3 == 0]
    store = PARTIAL / "parziali.jsonl"
    done = {json.loads(line)["i"]: json.loads(line) for line in store.read_text().splitlines()} if store.exists() else {}
    records = rows.to_dict("records")
    for position in positions:
        row = records[position]
        if position in done:
            continue
        config = replace(baseline.config_for_row(row, odds=baseline.closing_odds(row)), league=row["league"], simulations=SIMS,
                         seed=position, keep_samples=True)
        out = {"i": position}
        for name, free in (("attuale", False), ("libero", True)):
            event = replace(config.event_engine, active=free, free=free)
            started = time.perf_counter()
            result = engine.simulate_match(replace(config, event_engine=event))
            out[name] = {"p": {k: v.tolist() for k, v in {**ec.probabilities(result), **goal_probabilities(result)}.items()},
                         "s": time.perf_counter() - started}
        done[position] = out
        with store.open("a") as handle:
            handle.write(json.dumps(out) + "\n")
    rows = rows.iloc[positions].reset_index(drop=True)
    observed = ec.observed_events(rows)
    gh, ga = rows["home_goals"].to_numpy(int), rows["away_goals"].to_numpy(int)
    observed["1X2"] = np.select([gh > ga, gh == ga], [0, 1], 2)
    for key, mask in (("Over 2.5 gol", gh + ga > 2), ("Over 1.5 gol", gh + ga > 1), ("Over 3.5 gol", gh + ga > 3), ("Goal", (gh > 0) & (ga > 0))):
        observed[key] = mask.astype(int)
    lines = [f"# Simulatore reale – completo: prova rapida (fase AN)", "",
             f"Generato con `python -m tools.libero_check`. {len(rows)} partite 2023/24 (E0, I1, D1), {SIMS} simulazioni, "
             "quote di chiusura 1X2 e Over/Under 2.5, motore attuale contro modo libero con ripesatura Dixon-Coles. "
             f"{'Un terzo del campione (stratificato per campionato): gli errori statistici sono circa √3 volte più grandi che con tutto il campione. ' if args.terzo else ''}"
             "Campione piccolo: serve a vedere se il modo libero è plausibile, non a accenderlo come verificato.", "",
             "| Mercato | Log-loss attuale | Log-loss libero | Differenza (± 2 e.s.) | ECE attuale | ECE libero |", "|---|---|---|---|---|---|"]
    keys = [k for k in done[positions[0]]["attuale"]["p"] if k in observed]
    for key in keys:
        cells = {}
        for name in ("attuale", "libero"):
            probs = np.clip(np.vstack([done[i][name]["p"][key] for i in positions]), 1e-6, 1)
            probs = probs / probs.sum(axis=1, keepdims=True)
            cells[name] = (-np.log(probs[np.arange(len(probs)), observed[key]]), baseline.expected_calibration_error(probs if probs.shape[1] > 2 else probs, observed[key]))
        diff = cells["libero"][0] - cells["attuale"][0]
        lines.append(f"| {key} | {cells['attuale'][0].mean():.4f} | {cells['libero'][0].mean():.4f} | {diff.mean():+.5f} ± "
                     f"{2 * diff.std(ddof=1) / np.sqrt(len(diff)):.5f} | {cells['attuale'][1]:.4f} | {cells['libero'][1]:.4f} |")
    seconds = np.mean([done[i]["libero"]["s"] for i in positions])
    lines += ["", f"Tempo medio per partita (libero): {seconds:.1f} s."]
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
