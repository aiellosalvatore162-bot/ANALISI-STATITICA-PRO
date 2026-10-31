"""Fase AP, punto 1: effetto degli incroci di stile (AK) su corner e cartellini, con e senza, nel «Simulatore reale – completo».

Campione: un sesto stratificato (le partite di posizione pari del terzo della fase AO). La variante «senza incroci» è quella già
calcolata dalla AO (stesso seme, stessi ingressi: ``data/cache/ao_check/parziali.jsonl``); qui si calcola solo «con incroci».
Regola (fissata prima): un incrocio resta acceso per il suo gruppo se la log-loss scende di oltre 2 errori standard appaiati ED
ECE non peggiora. Parziali riprendibili in ``data/cache/ap_check/parziali.jsonl``.

    nohup python -m tools.ap_check [--processi 2] > data/cache/ap_check/log.txt &
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from multiprocessing import Pool
from pathlib import Path
import time

import numpy as np

import engine
import event_engine
from tools import ao_check, baseline, event_check as ec, libero_check

ROOT = Path(__file__).resolve().parents[1]
PARTIAL = ROOT / "data" / "cache" / "ap_check"
OUTPUT = ROOT / "docs" / "backtest" / "AP_incroci.md"
CROSSINGS = {"possesso_contro_pressing": "cartellini", "cross_contro_blocco_basso": "corner"}


def evaluate(args: tuple[int, dict]) -> dict:
    position, row = args
    if not ao_check._STATE:
        ao_check._init()
    config = replace(baseline.config_for_row(row, odds=baseline.closing_odds(row)), league=row["league"],
                     simulations=ao_check.SIMS, seed=position, keep_samples=True)
    inputs, _ = ao_check.inputs_for(row)
    data = json.loads(event_engine.PATH.read_text(encoding="utf-8"))
    crossings = tuple(dict(data["incroci"][name]) for name in CROSSINGS)
    variant = replace(config, event_engine=replace(config.event_engine, active=True, free=True, crossings=crossings),
                      event_inputs=inputs)
    started = time.perf_counter()
    result = engine.simulate_match(variant)
    probs = {**ec.probabilities(result), **libero_check.goal_probabilities(result)}
    return {"i": position, "p": {k: np.asarray(v).tolist() for k, v in probs.items()}, "s": round(time.perf_counter() - started, 2)}


def load_partial() -> dict[int, dict]:
    path = PARTIAL / "parziali.jsonl"
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                done[item["i"]] = item
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def summarize(frame, base: dict[int, dict], new: dict[int, dict]) -> dict:
    positions = sorted(i for i in new if i in base)
    seen = ao_check.observed(frame.iloc[positions].reset_index(drop=True))
    keys = [k for k in new[positions[0]]["p"] if k in seen]
    losses = {}
    for key in keys:
        for name, source in (("senza", lambda i: base[i]["reale_dati"]["p"][key]), ("con", lambda i: new[i]["p"][key])):
            probs = np.clip(np.vstack([source(i) for i in positions]), 1e-6, 1)
            probs = probs / probs.sum(axis=1, keepdims=True)
            losses[name, key] = (-np.log(probs[np.arange(len(probs)), seen[key]]), baseline.expected_calibration_error(probs, seen[key]))
    groups = {}
    for group in ("corner", "cartellini", "combo", "tempi"):
        members = [k for k in [*ec.BINARY.get(group, ()), *ec.MULTI.get(group, {})] if k in keys]
        if not members:
            continue
        diff = np.mean([losses["con", k][0] - losses["senza", k][0] for k in members], axis=0)
        groups[group] = {"mercati": len(members), "diff": float(diff.mean()),
                         "e2": float(2 * diff.std(ddof=1) / np.sqrt(len(diff))),
                         "ece": (float(np.mean([losses["senza", k][1] for k in members])),
                                 float(np.mean([losses["con", k][1] for k in members])))}
    for group, item in groups.items():
        item["tieni"] = item["diff"] < -item["e2"] and item["ece"][1] <= item["ece"][0] and group in ("corner", "cartellini")
    return {"partite": len(positions), "gruppi": groups}


def render(result: dict) -> str:
    lines = ["# Fase AP – incroci di stile su corner e cartellini", "",
             f"{result['partite']} partite (un sesto stratificato per campionato e stagione: errore statistico più grande del terzo "
             "della AO, dichiarato nelle colonne ± 2 e.s.). Incroci accesi: possesso contro pressing (falli → cartellini) e cross "
             "contro blocco basso (corner da cross). Differenza = con − senza (negativa = meglio).", "",
             "| Gruppo | Mercati | Differenza log-loss (± 2 e.s.) | ECE senza | ECE con | Incrocio tenuto |", "|---|---|---|---|---|---|"]
    for group, item in result["gruppi"].items():
        lines.append(f"| {group} | {item['mercati']} | {item['diff']:+.5f} ± {item['e2']:.5f} | {item['ece'][0]:.4f} | "
                     f"{item['ece'][1]:.4f} | {'sì' if item['tieni'] else 'no'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processi", type=int, default=2)
    parser.add_argument("--massimo", type=int, default=None)
    parser.add_argument("--solo-report", action="store_true")
    args = parser.parse_args()
    PARTIAL.mkdir(parents=True, exist_ok=True)
    frame = ao_check.rows()
    records = frame.to_dict("records")
    base = ao_check.load_partial()
    new = load_partial()
    todo = [(i, records[i]) for i in range(0, len(records), 2) if i not in new and i in base][: args.massimo]
    if todo and not args.solo_report:
        with Pool(args.processi) as pool, (PARTIAL / "parziali.jsonl").open("a", encoding="utf-8") as handle:
            for count, out in enumerate(pool.imap_unordered(evaluate, todo, chunksize=1), start=1):
                new[out["i"]] = out
                handle.write(json.dumps(out) + "\n")
                handle.flush()
                if count % 10 == 0:
                    print(f"{len(new)}/{(len(records) + 1) // 2}", flush=True)
    result = summarize(frame, base, new)
    OUTPUT.write_text(render(result), encoding="utf-8")
    (PARTIAL / "riepilogo.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(render(result))


if __name__ == "__main__":
    main()
