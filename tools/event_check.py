"""Fase AK, stadio 14: verifica fuori campione del motore a eventi contro il motore attuale.

Partite di football-data.co.uk (``tools.dataset``) delle stagioni 2020/21, 2021/22 e 2022/23 (campione per campionato e
stagione) più tutte quelle del 2026/27: fuori dalla taratura di corner, cartellini e primo tempo (2024-26) e dalla stima del
motore a eventi (StatsBomb 2015/16). Campionati: Premier, Liga, Serie A, Bundesliga (la Ligue 1 non ha righe complete nel
dataset). Per ogni partita la STESSA ``MatchConfig`` dell'app (quote di chiusura 1X2 e Over/Under 2.5, medie di corner e
cartellini, arbitro) va in ``engine.simulate_match`` due volte: motore attuale e motore a eventi (stesso seme, quindi
stessi punteggi Dixon-Coles). Mercati: primo e secondo tempo, corner e cartellini (totali, per squadra, 1X2) e combo.
Corner e cartellini del primo tempo non sono nei dati: non verificabili.

Regola (come le fasi O e P): il motore a eventi si accende solo se la log-loss media scende di più di due errori standard
appaiati (partita per partita), l'ECE media non sale (tolleranza ``TOLERANCE_ECE``) e nessun gruppo peggiora di più di due
errori standard. Uso: ``python -m tools.event_check [--per-stagione 100] [--processi 2] [--salva] [--ricomincia]``.

Risultati parziali: una riga JSON per partita in ``data/cache/event_check/<campionato>.jsonl``, scritta appena la partita è
calcolata; un nuovo avvio salta le partite già fatte (``--ricomincia`` cancella i parziali). Avanzamento in
``data/cache/event_check/avanzamento.txt``.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
import json
from multiprocessing import get_context
from pathlib import Path
import time

import numpy as np
import pandas as pd

import engine
from tools import baseline

SIMULATIONS = 20_000
SEASONS = ("2021", "2122", "2223")
HOLDOUT = ("2627",)
LEAGUES = ("E0", "SP1", "I1", "D1")
TOLERANCE_ECE = 0.0005
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "backtest" / "AK_motore_eventi.md"
PARTIAL = Path(__file__).resolve().parents[1] / "data" / "cache" / "event_check"

MULTI = {"tempi": {"1X2 1T": ("1 1T", "X 1T", "2 1T"), "1X2 2T": ("1 2T", "X 2T", "2 2T")},
         "corner": {"1X2 corner": ("1 corner", "X corner", "2 corner")},
         "cartellini": {"1X2 cartellini": ("1 cartellini", "X cartellini", "2 cartellini")}}
BINARY = {
    "tempi": ("Over 0.5 gol 1T", "Over 1.5 gol 1T", "Over 0.5 gol 2T", "Over 1.5 gol 2T", "Goal 1T", "Multigol 1T 1-2",
              "Multigol 2T 1-3"),
    "corner": ("Over 8.5 corner", "Over 9.5 corner", "Over 10.5 corner", "Casa Over 4.5 corner", "Casa Over 5.5 corner",
               "Ospite Over 3.5 corner", "Ospite Over 4.5 corner"),
    "cartellini": ("Over 3.5 cartellini", "Over 4.5 cartellini", "Over 5.5 cartellini", "Casa Over 1.5 cartellini",
                   "Casa Over 2.5 cartellini", "Ospite Over 1.5 cartellini", "Ospite Over 2.5 cartellini"),
    "combo": ("Over 2.5 gol & Over 9.5 corner", "Over 2.5 gol & Over 4.5 cartellini", "Goal & Over 9.5 corner",
              "1 & Casa Over 4.5 corner", "2 & Ospite Over 3.5 corner", "1 & Over 4.5 cartellini", "X & Over 4.5 cartellini",
              "Over 9.5 corner & Over 4.5 cartellini", "Over 0.5 gol 1T & Over 9.5 corner",
              "Over 1.5 gol 2T & Over 4.5 cartellini", "X 1T & Over 4.5 cartellini", "Under 2.5 gol & Under 9.5 corner",
              "1 & 2 corner", "2 & 1 corner"),
}
GROUPS = tuple(BINARY)
VARIANTS = ("motore attuale", "motore a eventi")


def evaluation_rows(per_season: int, seed: int = 11) -> pd.DataFrame:
    features = baseline.load_usable_features()
    features = features.dropna(subset=["home_ht_goals", "away_ht_goals", "home_corners", "away_corners", "home_yellows",
                                       "away_yellows", "home_reds", "away_reds", "close_home", "close_draw", "close_away"])
    features = features[features["league"].isin(LEAGUES)]
    early = features[features["season"].isin(SEASONS)]
    early = early.groupby(["league", "season"], group_keys=False).apply(
        lambda frame: frame.sample(min(per_season, len(frame)), random_state=seed))
    late = features[features["season"].isin(HOLDOUT)]
    return pd.concat([early, late]).sort_values("date").reset_index(drop=True)


def _mask(result: dict, key: str) -> np.ndarray:
    size = result["sample_size"]
    mask = np.ones(size, dtype=bool)
    for leg in key.split(" & "):
        mask &= np.unpackbits(result["event_samples"][leg])[:size].astype(bool)
    return mask


def probabilities(result: dict) -> dict[str, np.ndarray]:
    out = {}
    for group in GROUPS:
        for name, keys in MULTI.get(group, {}).items():
            values = np.array([_mask(result, key).mean() for key in keys])
            out[name] = values / values.sum()
        for key in BINARY[group]:
            p = _mask(result, key).mean()
            out[key] = np.array([1.0 - p, p])
    return out


def residual_draw(result: dict, rng: np.random.Generator) -> dict[str, float] | None:
    """Una partita estratta dal campione del motore a eventi (per le correlazioni dei residui)."""
    sample = result.get("event_engine_sample")
    if not sample:
        return None
    index = int(rng.integers(len(sample["goals_home"])))
    return {key: float(sample[name][index]) for key, name in (
        ("gh", "goals_home"), ("ga", "goals_away"), ("ch", "corners_home"), ("ca", "corners_away"),
        ("yh", "yellows_home"), ("ya", "yellows_away"), ("rh", "reds_home"), ("ra", "reds_away"))}


def evaluate_row(args: tuple[int, dict]) -> dict:
    position, row = args
    config = replace(baseline.config_for_row(row, odds=baseline.closing_odds(row)), league=row["league"],
                     simulations=SIMULATIONS, seed=position, keep_samples=True)
    out = {"position": position}
    for variant, active in zip(VARIANTS, (False, True)):
        variant_config = replace(config, event_engine=replace(config.event_engine, active=active))
        started = time.perf_counter()
        result = engine.simulate_match(variant_config)
        out[variant] = {"probabilita": probabilities(result), "secondi": time.perf_counter() - started,
                        "simulazioni": result["sample_size"],
                        "medie": (result["markets"]["corners"]["mean"], result["markets"]["cards"]["mean"])}
        if active:
            out["estrazione"] = residual_draw(result, np.random.default_rng([position, 99]))
            out["avvisi"] = result["event_engine"]["warnings"]
    return out


def observed_events(rows: pd.DataFrame) -> dict[str, np.ndarray]:
    rule = engine.DEFAULT_CARD_RULE
    gh, ga = rows["home_goals"].to_numpy(int), rows["away_goals"].to_numpy(int)
    fh, fa = rows["home_ht_goals"].to_numpy(int), rows["away_ht_goals"].to_numpy(int)
    sh, sa = gh - fh, ga - fa
    ch, ca = rows["home_corners"].to_numpy(int), rows["away_corners"].to_numpy(int)
    ph = engine.card_points(rows["home_yellows"].to_numpy(int), rows["home_reds"].to_numpy(int), rule)
    pa = engine.card_points(rows["away_yellows"].to_numpy(int), rows["away_reds"].to_numpy(int), rule)
    first, second, total, corners, points = fh + fa, sh + sa, gh + ga, ch + ca, ph + pa
    events = {
        "1": gh > ga, "X": gh == ga, "2": gh < ga, "Goal": (gh > 0) & (ga > 0), "Over 2.5 gol": total > 2.5,
        "Under 2.5 gol": total < 2.5,
        "1 1T": fh > fa, "X 1T": fh == fa, "2 1T": fh < fa, "1 2T": sh > sa, "X 2T": sh == sa, "2 2T": sh < sa,
        "Over 0.5 gol 1T": first > 0.5, "Over 1.5 gol 1T": first > 1.5, "Over 0.5 gol 2T": second > 0.5,
        "Over 1.5 gol 2T": second > 1.5, "Goal 1T": (fh > 0) & (fa > 0), "Multigol 1T 1-2": (first >= 1) & (first <= 2),
        "Multigol 2T 1-3": (second >= 1) & (second <= 3),
        "1 corner": ch > ca, "X corner": ch == ca, "2 corner": ch < ca,
        "1 cartellini": ph > pa, "X cartellini": ph == pa, "2 cartellini": ph < pa,
    }
    for line in (8.5, 9.5, 10.5):
        events[f"Over {line:g} corner"] = corners > line
    events["Under 9.5 corner"] = corners < 9.5
    for line in (3.5, 4.5, 5.5):
        events[f"Over {line:g} cartellini"] = points > line
    for label, values in (("Casa", ch), ("Ospite", ca)):
        for line in (3.5, 4.5, 5.5):
            events[f"{label} Over {line:g} corner"] = values > line
    for label, values in (("Casa", ph), ("Ospite", pa)):
        for line in (1.5, 2.5):
            events[f"{label} Over {line:g} cartellini"] = values > line
    out = {}
    for group in GROUPS:
        for name, keys in MULTI.get(group, {}).items():
            out[name] = np.select([events[keys[0]], events[keys[1]]], [0, 1], 2)
        for key in BINARY[group]:
            mask = np.ones(len(rows), dtype=bool)
            for leg in key.split(" & "):
                mask &= events[leg]
            out[key] = mask.astype(int)
    return out


def _market_keys(group: str) -> list[str]:
    return [*MULTI.get(group, {}), *BINARY[group]]


def score(collected: dict[str, list[np.ndarray]], observed: dict[str, np.ndarray]) -> dict:
    result = {}
    for group in GROUPS:
        for key in _market_keys(group):
            probs = np.clip(np.vstack(collected[key]), 1e-6, 1.0)
            probs = probs / probs.sum(axis=1, keepdims=True)
            loss = -np.log(probs[np.arange(len(probs)), observed[key]])
            result[key] = {**baseline.summarize(probs, observed[key]), "gruppo": group, "_per_partita": loss}
    for group in (*GROUPS, None):
        keys = [key for key, value in result.items() if not key.startswith("media") and (group is None or value["gruppo"] == group)]
        name = f"media {group}" if group else "media"
        result[name] = {metric: float(np.mean([result[key][metric] for key in keys])) for metric in ("log_loss", "ece", "brier")}
        result[name]["_per_partita"] = np.mean([result[key]["_per_partita"] for key in keys], axis=0)
    return result


def paired(before: dict, after: dict, key: str) -> tuple[float, float]:
    difference = after[key]["_per_partita"] - before[key]["_per_partita"]
    return float(difference.mean()), float(difference.std(ddof=1) / np.sqrt(len(difference)))


def residual_correlations(rows: pd.DataFrame, draws: list[dict | None]) -> dict[str, tuple[float, float]]:
    """Correlazioni dei residui (a parità di quote, medie di corner/cartellini, arbitro e campionato): reali e del motore a
    eventi (una partita simulata per riga, stessi regressori)."""
    inv = 1.0 / rows[["close_home", "close_draw", "close_away"]].to_numpy(float)
    inv /= inv.sum(axis=1, keepdims=True)
    over = rows["close_over25"].fillna(rows["close_over25"].median()).to_numpy(float)
    X = np.column_stack([np.ones(len(rows)), inv[:, 0] - inv[:, 2], 1.0 / over,
                         rows[["home_corners_for", "home_corners_against", "away_corners_for", "away_corners_against",
                               "home_cards_for", "away_cards_for"]].to_numpy(float),
                         rows["referee_yellow_avg"].fillna(rows["referee_yellow_avg"].mean()).to_numpy(float),
                         pd.get_dummies(rows["league"]).to_numpy(float)[:, 1:]])

    def residual(values):
        beta, *_ = np.linalg.lstsq(X, values, rcond=None)
        return values - X @ beta

    def measures(gh, ga, ch, ca, yellows, reds):
        res_yellows = residual(yellows)
        return {"diff. gol / diff. corner": np.corrcoef(residual(gh - ga), residual(ch - ca))[0, 1],
                "gol totali / corner totali": np.corrcoef(residual(gh + ga), residual(ch + ca))[0, 1],
                "|diff. gol| / gialli": np.corrcoef(residual(np.abs(gh - ga)), res_yellows)[0, 1],
                "gialli in più con un rosso (residuo)": float(res_yellows[reds > 0].mean() - res_yellows[reds == 0].mean())}

    real = measures(rows["home_goals"].to_numpy(float), rows["away_goals"].to_numpy(float), rows["home_corners"].to_numpy(float),
                    rows["away_corners"].to_numpy(float), (rows["home_yellows"] + rows["away_yellows"]).to_numpy(float),
                    (rows["home_reds"] + rows["away_reds"]).to_numpy(float))
    sim = pd.DataFrame([draw for draw in draws])
    model = measures(sim["gh"].to_numpy(), sim["ga"].to_numpy(), sim["ch"].to_numpy(), sim["ca"].to_numpy(),
                     (sim["yh"] + sim["ya"]).to_numpy(), (sim["rh"] + sim["ra"]).to_numpy())
    return {key: (float(real[key]), float(model[key])) for key in real}


def row_key(row: dict) -> str:
    return f"{pd.Timestamp(row['date']):%Y-%m-%d}|{row['home_team']}|{row['away_team']}"


def _to_json(output: dict, key: str) -> str:
    data = {"key": key, "position": output["position"], "estrazione": output.get("estrazione"), "avvisi": output.get("avvisi")}
    for variant in VARIANTS:
        value = output[variant]
        data[variant] = {"probabilita": {name: [float(x) for x in probs] for name, probs in value["probabilita"].items()},
                         "secondi": value["secondi"], "simulazioni": int(value["simulazioni"]),
                         "medie": [float(x) for x in value["medie"]]}
    return json.dumps(data, ensure_ascii=False)


def _from_json(line: str) -> dict:
    data = json.loads(line)
    for variant in VARIANTS:
        data[variant]["probabilita"] = {name: np.asarray(probs) for name, probs in data[variant]["probabilita"].items()}
        data[variant]["medie"] = tuple(data[variant]["medie"])
    return data


def load_partial(league: str, folder: Path = PARTIAL) -> dict[str, dict]:
    """Partite già calcolate di un campionato (chiave data|casa|ospite); righe troncate ignorate."""
    path = folder / f"{league}.jsonl"
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = _from_json(line)
            except (json.JSONDecodeError, KeyError):
                continue
            done[item["key"]] = item
    return done


def _write_progress(counts: dict[str, list[int]], started: float, folder: Path = PARTIAL) -> None:
    done, total = sum(c[0] for c in counts.values()), sum(c[1] for c in counts.values())
    elapsed = time.time() - started
    lines = [f"{date.today():%d/%m/%Y} {time.strftime('%H:%M:%S')} — {done}/{total} partite "
             f"({done / max(total, 1):.0%}), {elapsed / 60:.1f} minuti in questa esecuzione"]
    lines += [f"{league}: {c[0]}/{c[1]}" for league, c in counts.items()]
    (folder / "avanzamento.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(per_season: int = 100, processes: int = 2, folder: Path = PARTIAL) -> dict:
    rows = evaluation_rows(per_season)
    records = rows.to_dict("records")
    folder.mkdir(parents=True, exist_ok=True)
    started = time.time()
    by_key: dict[str, dict] = {}
    counts = {}
    for league in LEAGUES:
        done = load_partial(league, folder)
        keys = [row_key(record) for record in records if record["league"] == league]
        by_key.update({key: done[key] for key in keys if key in done})
        counts[league] = [sum(key in done for key in keys), len(keys)]
    _write_progress(counts, started, folder)
    with get_context("fork").Pool(processes) as pool:
        for league in LEAGUES:
            pending = [(position, record) for position, record in enumerate(records)
                       if record["league"] == league and row_key(record) not in by_key]
            if not pending:
                continue
            keys = {position: row_key(record) for position, record in pending}
            with (folder / f"{league}.jsonl").open("a", encoding="utf-8") as handle:
                for output in pool.imap_unordered(evaluate_row, pending):
                    key = keys[output["position"]]
                    handle.write(_to_json(output, key) + "\n")
                    handle.flush()
                    by_key[key] = _from_json(_to_json(output, key))
                    counts[league][0] += 1
                    _write_progress(counts, started, folder)
    outputs = []
    for position, record in enumerate(records):
        item = dict(by_key[row_key(record)])
        item["position"] = position
        outputs.append(item)
    observed = observed_events(rows)
    results = {}
    for variant in VARIANTS:
        collected: dict[str, list] = {}
        for output in outputs:
            for key, value in output[variant]["probabilita"].items():
                collected.setdefault(key, []).append(value)
        results[variant] = score(collected, observed)
    before, after = results[VARIANTS[0]], results[VARIANTS[1]]
    groups = {}
    for group in (*GROUPS, None):
        key = f"media {group}" if group else "media"
        mean, error = paired(before, after, key)
        groups[group or "tutti"] = {"differenza": mean, "errore_standard": error,
                                    "ece_prima": before[key]["ece"], "ece_dopo": after[key]["ece"],
                                    "log_loss_prima": before[key]["log_loss"], "log_loss_dopo": after[key]["log_loss"]}
    overall = groups["tutti"]
    improves = overall["differenza"] < -2.0 * overall["errore_standard"]
    calibrated = overall["ece_dopo"] <= overall["ece_prima"] + TOLERANCE_ECE
    worse = [group for group in GROUPS if groups[group]["differenza"] > 2.0 * groups[group]["errore_standard"]]
    decision = {"accendere": bool(improves and calibrated and not worse), "migliora": bool(improves),
                "ece_non_peggiore": bool(calibrated), "gruppi_peggiori": worse}
    timing = {variant: (float(np.mean([o[variant]["secondi"] for o in outputs])),
                        float(np.mean([o[variant]["simulazioni"] for o in outputs]))) for variant in VARIANTS}
    means = {variant: tuple(float(np.mean([o[variant]["medie"][index] for o in outputs])) for index in range(2))
             for variant in VARIANTS}
    correlations = residual_correlations(rows, [output["estrazione"] for output in outputs])
    warnings = sorted({warning for output in outputs for warning in output.get("avvisi") or []})
    return {"rows": rows, "results": results, "groups": groups, "decision": decision, "timing": timing, "means": means,
            "correlations": correlations, "warnings": warnings,
            "real_means": (float((rows["home_corners"] + rows["away_corners"]).mean()),
                           float(np.mean(engine.card_points((rows["home_yellows"] + rows["away_yellows"]).to_numpy(int),
                                                            (rows["home_reds"] + rows["away_reds"]).to_numpy(int),
                                                            engine.DEFAULT_CARD_RULE))))}


def report(run_result: dict) -> str:
    rows, results, groups, decision = run_result["rows"], run_result["results"], run_result["groups"], run_result["decision"]
    before, after = results[VARIANTS[0]], results[VARIANTS[1]]
    counts = rows.groupby(["league", "season"]).size()
    power = engine._event_params(None).state_power
    lines = ["# Motore a eventi: verifica fuori campione (fase AK, stadio 14)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.event_check`. {len(rows)} partite di football-data.co.uk "
             f"({', '.join(f'{league} {season}: {n}' for (league, season), n in counts.items())}). Stessa `MatchConfig` "
             f"dell'app (quote di chiusura 1X2 e Over/Under 2.5), `engine.simulate_match` con {SIMULATIONS:,} simulazioni al "
             "massimo, motore attuale contro motore a eventi (stesso seme: stessi punteggi Dixon-Coles; arresto adattivo "
             f"acceso nel motore a eventi; esponente di attenuazione degli stati {power:g}). Corner e cartellini del primo "
             "tempo non sono nei dati: non verificabili.".replace(",", "."), "",
             "## Decisione", "",
             f"- Log-loss media su tutti i mercati: {groups['tutti']['log_loss_prima']:.5f} → {groups['tutti']['log_loss_dopo']:.5f} "
             f"(differenza appaiata {groups['tutti']['differenza']:+.5f} ± {2 * groups['tutti']['errore_standard']:.5f}, 2 e.s.).",
             f"- ECE media: {groups['tutti']['ece_prima']:.5f} → {groups['tutti']['ece_dopo']:.5f} (tolleranza {TOLERANCE_ECE}).",
             f"- Gruppi peggiori di oltre 2 e.s.: {', '.join(decision['gruppi_peggiori']) or 'nessuno'}.",
             f"- **Esito: motore a eventi {'ACCESO' if decision['accendere'] else 'SPENTO'}** (regola: log-loss giù di oltre 2 "
             "e.s. appaiati, ECE non peggiore, nessun gruppo peggiore).", "",
             "## Per gruppo", "",
             "| Gruppo | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE prima | ECE dopo |", "|---|---|---|---|---|---|"]
    for group, value in groups.items():
        lines.append(f"| {group} | {value['log_loss_prima']:.5f} | {value['log_loss_dopo']:.5f} | {value['differenza']:+.5f} ± "
                     f"{2 * value['errore_standard']:.5f} | {value['ece_prima']:.5f} | {value['ece_dopo']:.5f} |")
    lines += ["", "## Per mercato", "", "| Mercato | Gruppo | Log-loss prima | Log-loss dopo | Differenza (± 2 e.s.) | ECE prima | ECE dopo |",
              "|---|---|---|---|---|---|---|"]
    for key, value in before.items():
        if key.startswith("media"):
            continue
        mean, error = paired(before, after, key)
        lines.append(f"| {key} | {value['gruppo']} | {value['log_loss']:.4f} | {after[key]['log_loss']:.4f} | {mean:+.5f} ± "
                     f"{2 * error:.5f} | {value['ece']:.4f} | {after[key]['ece']:.4f} |")
    timing, means, real = run_result["timing"], run_result["means"], run_result["real_means"]
    lines += ["", "## Medie, tempi e correlazioni", "",
              f"- Corner medi previsti {means[VARIANTS[0]][0]:.2f} (attuale) / {means[VARIANTS[1]][0]:.2f} (eventi), reali {real[0]:.2f}; "
              f"punti cartellino {means[VARIANTS[0]][1]:.2f} / {means[VARIANTS[1]][1]:.2f}, reali {real[1]:.2f}.",
              f"- Tempo medio per partita: {timing[VARIANTS[0]][0]:.2f} s ({timing[VARIANTS[0]][1]:,.0f} simulazioni) contro "
              f"{timing[VARIANTS[1]][0]:.2f} s ({timing[VARIANTS[1]][1]:,.0f} simulazioni con l'arresto adattivo).".replace(",", "."),
              "", "| Correlazione dei residui | Reale | Motore a eventi |", "|---|---|---|"]
    for key, (real_value, model_value) in run_result["correlations"].items():
        lines.append(f"| {key} | {real_value:+.3f} | {model_value:+.3f} |")
    lines += ["", "Nel motore attuale le prime tre sono circa 0 per costruzione (corner e cartellini indipendenti dai gol).",
              "Residui = scarti da una regressione lineare su quote 1X2 e Over 2.5, medie di corner e cartellini, arbitro e "
              "campionato; per il motore a eventi una partita simulata per riga, stessi regressori."]
    if run_result["warnings"]:
        lines += ["", "Avvisi del motore a eventi: " + "; ".join(run_result["warnings"])]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-stagione", type=int, default=100, help="Partite per campionato e stagione (2020-23)")
    parser.add_argument("--processi", type=int, default=2)
    parser.add_argument("--salva", action="store_true", help="Scrive l'esito in config/goal_model.json (motore_eventi)")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--ricomincia", action="store_true", help="Cancella i risultati parziali e riparte da zero")
    args = parser.parse_args()
    if args.ricomincia:
        for path in PARTIAL.glob("*.jsonl"):
            path.unlink()
    run_result = run(args.per_stagione, args.processi)
    markdown = report(run_result)
    print(markdown)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    if args.salva:
        from tools.calibrate import _update_config

        section = json.loads(engine.GOAL_MODEL_PATH.read_text(encoding="utf-8")).get("motore_eventi", {})
        groups = {name: {key: round(value, 5) for key, value in values.items()} for name, values in run_result["groups"].items()}
        _update_config({"motore_eventi": {
            **section, "attivo": run_result["decision"]["accendere"],
            "verifica": {"data": date.today().isoformat(), "partite": len(run_result["rows"]), "gruppi": groups,
                         "decisione": run_result["decision"], "report": "docs/backtest/AK_motore_eventi.md"},
        }})


if __name__ == "__main__":
    main()
