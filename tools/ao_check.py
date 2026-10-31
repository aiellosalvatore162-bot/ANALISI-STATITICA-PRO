"""Fase AO, stadio 6: verifica su un terzo stratificato (campionato × stagione) del «Simulatore reale – completo» CON tutti i
dati della partita (formazione e assenti, corsie dai titolari, stile misurato) contro il calcolo attuale.

Partite 2025/26 e 2026/27 (E0, SP1, I1, D1) con rosa Understat; per ogni partita, solo informazioni note prima del fischio:
titolari ufficiali (come nella fase AL), tassi e XI tipo con le sole gare precedenti, stile con le gare precedenti. Stessa
``MatchConfig`` dell'app (quote di chiusura 1X2 e Over/Under 2.5, medie di corner e cartellini, arbitro), stesso seme.
Misure come ``tools.event_check`` (gruppi tempi, corner, cartellini, combo) più i mercati di gol: log-loss appaiata ± 2 e.s.
ed ECE. L'arbitro dei falli del motore a eventi non entra (nel dataset storico manca il nome dell'arbitro): dichiarato.

Parziali in ``data/cache/ao_check/parziali.jsonl`` (ripresa automatica).

    nohup python -m tools.ao_check [--processi 2] > data/cache/ao_check/log.txt &
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from multiprocessing import Pool
from pathlib import Path
import time

import numpy as np
import pandas as pd

import engine
import event_inputs
import formation
import lineup
import players as pl
import style_profile
from datasources.names import canonical_key
from tools import backtest_wf, baseline, event_check as ec, libero_check, lineup_check

ROOT = Path(__file__).resolve().parents[1]
PARTIAL = ROOT / "data" / "cache" / "ao_check"
OUTPUT = ROOT / "docs" / "backtest" / "AO_verifica.md"
LEAGUES = ("E0", "SP1", "I1", "D1")
SEASONS = ("2526", "2627")
SIMS = 10_000
VARIANTS = ("attuale", "reale_dati")
_STATE: dict = {}


def rows() -> pd.DataFrame:
    features, _ = backtest_wf.prepare(LEAGUES, SEASONS)
    features = features[features["season"].isin(SEASONS)].dropna(
        subset=["home_ht_goals", "away_ht_goals", "home_corners", "away_corners", "home_yellows", "away_yellows",
                "home_reds", "away_reds", "close_home", "close_draw", "close_away"])
    features = features.sort_values("date").reset_index(drop=True)
    rank = features.groupby(["league", "season"]).cumcount().to_numpy()
    return features[rank % 3 == 0].reset_index(drop=True)       # un terzo, stratificato per campionato e stagione


def _init() -> None:
    _, store = backtest_wf.prepare(LEAGUES, SEASONS)
    players = pl.PlayerStore(pl.load_table(LEAGUES, (2025, 2026)))
    table = players.table
    _STATE.update(style=store, players=players, ids=lineup_check._match_ids(table),
                  starters={(m, k): g for (m, k), g in table[table["starter"]].groupby(["match_id", "key"])})


def inputs_for(row: dict) -> tuple[dict | None, list[str]]:
    """Ingressi del motore a eventi per una partita storica (solo dati precedenti, titolari ufficiali)."""
    when = pd.Timestamp(row["date"]).normalize()
    match_id = next((_STATE["ids"].get((when + pd.Timedelta(days=d), canonical_key(row["home_team"]))) for d in (0, -1, 1)
                     if _STATE["ids"].get((when + pd.Timedelta(days=d), canonical_key(row["home_team"])))), None)
    notes = []
    report, wides = {}, {}
    for side, label, team in (("home", "casa", row["home_team"]), ("away", "ospite", row["away_team"])):
        group = _STATE["starters"].get((match_id, canonical_key(team))) if match_id else None
        if group is None or len(group) < 11:
            notes.append(f"{label}: titolari non trovati")
            continue
        report[label] = {"formazione": list(group["player"]), "fonte": "Understat (titolari ufficiali)"}
        wides[side] = formation.wide_from_understat(list(group["position"]))
    data = lineup.get_lineup_params(row["home_team"], row["away_team"], when, _STATE["players"], league=row["league"],
                                    report=report or None) if len(report) == 2 else None
    styles = {}
    try:
        _, profiles, _ = style_profile.match_style(_STATE["style"], row["home_team"], row["away_team"], when, row["league"])
        styles = dict(zip(("home", "away"), profiles))
    except Exception as exc:  # stile mancante: neutro, dichiarato
        notes.append(f"stile non disponibile ({type(exc).__name__})")
    cuts = event_inputs.league_cuts(_STATE["style"], row["league"], when)
    out = event_inputs.build(lineup=data, styles=styles, cuts=cuts, wides=wides if len(wides) == 2 else None)
    return out, notes


def evaluate(args: tuple[int, dict]) -> dict:
    position, row = args
    if not _STATE:
        _init()
    config = replace(baseline.config_for_row(row, odds=baseline.closing_odds(row)), league=row["league"], simulations=SIMS,
                     seed=position, keep_samples=True)
    inputs, notes = inputs_for(row)
    out = {"i": position, "key": ec.row_key(row), "note": notes,
           "scale": {side: {k: inputs[side].get(k) for k in ("shot_scale", "quality_scale", "corner_cross_scale")}
                     for side in ("home", "away")} if inputs else None,
           "profili": {side: inputs[side].get("profile") for side in ("home", "away")} if inputs else None}
    for name in VARIANTS:
        free = name != "attuale"
        variant = replace(config, event_engine=replace(config.event_engine, active=free, free=free),
                          event_inputs=inputs if free else None)
        started = time.perf_counter()
        result = engine.simulate_match(variant)
        probs = {**ec.probabilities(result), **libero_check.goal_probabilities(result)}
        out[name] = {"p": {k: np.asarray(v).tolist() for k, v in probs.items()}, "s": round(time.perf_counter() - started, 2)}
    return out


def load_partial() -> dict[int, dict]:
    path = PARTIAL / "parziali.jsonl"
    if not path.exists():
        return {}
    done = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            done[item["i"]] = item
        except (json.JSONDecodeError, KeyError):
            continue
    return done


def observed(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    out = ec.observed_events(frame)
    gh, ga = frame["home_goals"].to_numpy(int), frame["away_goals"].to_numpy(int)
    out["1X2"] = np.select([gh > ga, gh == ga], [0, 1], 2)
    for key, mask in (("Over 2.5 gol", gh + ga > 2), ("Over 1.5 gol", gh + ga > 1), ("Over 3.5 gol", gh + ga > 3),
                      ("Goal", (gh > 0) & (ga > 0))):
        out[key] = mask.astype(int)
    return out


GROUP_KEYS = {"gol": ("1X2", "Over 1.5 gol", "Over 2.5 gol", "Over 3.5 gol", "Goal"), **{g: None for g in ec.GROUPS}}


def summarize(frame: pd.DataFrame, done: dict[int, dict]) -> dict:
    positions = [i for i in range(len(frame)) if i in done]
    sub = frame.iloc[positions].reset_index(drop=True)
    seen = observed(sub)
    keys = [k for k in done[positions[0]]["attuale"]["p"] if k in seen]
    per_key, per_group = {}, {}
    losses = {name: {} for name in VARIANTS}
    for key in keys:
        for name in VARIANTS:
            probs = np.clip(np.vstack([done[i][name]["p"][key] for i in positions]), 1e-6, 1)
            probs = probs / probs.sum(axis=1, keepdims=True)
            losses[name][key] = (-np.log(probs[np.arange(len(probs)), seen[key]]),
                                 baseline.expected_calibration_error(probs, seen[key]))
        diff = losses["reale_dati"][key][0] - losses["attuale"][key][0]
        per_key[key] = {"attuale": float(losses["attuale"][key][0].mean()), "reale": float(losses["reale_dati"][key][0].mean()),
                        "diff": float(diff.mean()), "e2": float(2 * diff.std(ddof=1) / np.sqrt(len(diff))),
                        "ece": (losses["attuale"][key][1], losses["reale_dati"][key][1])}
    for group, members in GROUP_KEYS.items():
        members = [k for k in (members or [*ec.BINARY.get(group, ()), *ec.MULTI.get(group, {})]) if k in per_key]
        if not members:
            continue
        diff = np.mean([losses["reale_dati"][k][0] - losses["attuale"][k][0] for k in members], axis=0)
        per_group[group] = {"mercati": len(members), "diff": float(diff.mean()), "e2": float(2 * diff.std(ddof=1) / np.sqrt(len(diff))),
                            "ece": (float(np.mean([per_key[k]["ece"][0] for k in members])),
                                    float(np.mean([per_key[k]["ece"][1] for k in members])))}
    counts = sub.groupby(["league", "season"]).size().to_dict()
    seconds = float(np.mean([done[i]["reale_dati"]["s"] for i in positions]))
    with_lineup = sum(1 for i in positions if done[i].get("scale") and done[i]["scale"]["home"].get("shot_scale") is not None)
    with_lanes = sum(1 for i in positions if done[i].get("scale") and done[i]["scale"]["home"].get("corner_cross_scale") is not None)
    return {"partite": len(positions), "conteggi": {f"{l} {s}": n for (l, s), n in counts.items()}, "gruppi": per_group,
            "mercati": per_key, "secondi": seconds, "con_formazione": with_lineup, "con_corsie": with_lanes}


def render(result: dict, total: int) -> str:
    lines = ["# Fase AO – verifica del Simulatore reale con tutti i dati", "",
             f"Generato con `python -m tools.ao_check`. {result['partite']} partite su {total} del terzo stratificato "
             f"({', '.join(f'{k}: {v}' for k, v in result['conteggi'].items())}); {SIMS:,} simulazioni, stesso seme. "
             f"Formazione nel motore in {result['con_formazione']} partite, corsie dai titolari in {result['con_corsie']}. "
             "Calcolo attuale contro «Simulatore reale – completo» (modo libero + ripesatura Dixon-Coles) con formazione, assenti, "
             "corsie e stile. Differenza di log-loss appaiata (reale − attuale; negativa = meglio) ± 2 errori standard. "
             "Arbitro nei falli non verificabile qui (manca il nome nel dataset storico). Partite 2025/26 nel periodo di taratura "
             "dei parametri base (2024-26): i gruppi gol e corner/cartellini partono dalle stesse medie in entrambe le varianti.", "",
             "| Gruppo | Mercati | Differenza log-loss (± 2 e.s.) | ECE attuale | ECE reale |", "|---|---|---|---|---|"]
    for group, item in result["gruppi"].items():
        lines.append(f"| {group} | {item['mercati']} | {item['diff']:+.5f} ± {item['e2']:.5f} | {item['ece'][0]:.4f} | {item['ece'][1]:.4f} |")
    lines += ["", "| Mercato | Log-loss attuale | Log-loss reale | Differenza (± 2 e.s.) | ECE attuale | ECE reale |", "|---|---|---|---|---|---|"]
    for key, item in result["mercati"].items():
        lines.append(f"| {key} | {item['attuale']:.4f} | {item['reale']:.4f} | {item['diff']:+.5f} ± {item['e2']:.5f} | "
                     f"{item['ece'][0]:.4f} | {item['ece'][1]:.4f} |")
    lines += ["", f"Tempo medio per partita (Simulatore reale con dati): {result['secondi']:.1f} s."]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processi", type=int, default=2)
    parser.add_argument("--massimo", type=int, default=None, help="al più N partite (prova)")
    parser.add_argument("--solo-report", action="store_true")
    args = parser.parse_args()
    PARTIAL.mkdir(parents=True, exist_ok=True)
    frame = rows()
    records = frame.to_dict("records")
    done = load_partial()
    todo = [(i, records[i]) for i in range(len(records)) if i not in done][: args.massimo]
    if todo and not args.solo_report:
        with Pool(args.processi) as pool, (PARTIAL / "parziali.jsonl").open("a", encoding="utf-8") as handle:
            for count, out in enumerate(pool.imap_unordered(evaluate, todo, chunksize=1), start=1):
                done[out["i"]] = out
                handle.write(json.dumps(out) + "\n")
                handle.flush()
                if count % 10 == 0:
                    print(f"{len(done)}/{len(records)}", flush=True)
    result = summarize(frame, done)
    OUTPUT.write_text(render(result, len(records)), encoding="utf-8")
    (PARTIAL / "riepilogo.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(render(result, len(records)))


if __name__ == "__main__":
    main()
