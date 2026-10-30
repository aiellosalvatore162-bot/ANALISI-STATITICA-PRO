"""Fase AM: calibrazione per mercato (previsto contro uscito), walk-forward.

Probabilità finali dello storico come nell'app (cache ``data/cache/fase_p/mercati.pkl`` più i mercati aggiunti qui:
Over 4.5, secondo tempo, gol per squadra). Per ogni mercato:

* tabella di affidabilità per fascia di probabilità dichiarata (grezza);
* ricalibrazione walk-forward a blocchi di stagione: la mappa che corregge la stagione S è stimata solo sulle stagioni
  precedenti (isotonica se i casi bastano, altrimenti Platt con riavvicinamento all'identità; tutti i campionati insieme);
* una sola mappa per mercato: resta la nuova solo se migliora o pareggia log-loss ed ECE; se la ricalibrazione
  precedente (fase P) dello stesso mercato è migliore, resta quella;
* la mappa finale è stimata su tutto lo storico; le etichette vengono dalle celle walk-forward.

Scrive ``config/taratura.json``. Uso: ``python -m tools.taratura_check [--salva] [--rapido] [--output docs/BASELINE.md]``.
``--rapido`` = una stagione di verifica e 3 campionati, senza scrivere.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import binom

import engine
from taratura import DERIVED, TRIOS
from tools import baseline, recalibration_check as rc, v2common

CONFIG = Path(__file__).resolve().parents[1] / "config" / "taratura.json"
EXTRA_CACHE = v2common.CACHE / "taratura_extra.pkl"
DEFAULTS = {"minimo_casi_taratura": 400, "minimo_positivi": 30, "soglia_isotonica_casi": 3000, "shrinkage_platt": 200.0,
            "prior_isotonica": 50.0, "limite_correzione_pp": 15.0, "tolleranza_ece": 0.0005,
            "min_casi_fascia": 150, "min_casi_oltre80": 300, "scarto_piccolo": 0.03, "scarto_grande": 0.06}


def settings() -> dict:
    stored = json.loads(CONFIG.read_text(encoding="utf-8")).get("parametri", {}) if CONFIG.exists() else {}
    return DEFAULTS | stored


# --- Mercati aggiunti ---------------------------------------------------------------------------------------

def extras(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    if EXTRA_CACHE.exists() and not refresh:
        return pd.read_pickle(EXTRA_CACHE)
    _, _, data = rc.table()
    goals = np.arange(rc.MAX_GOALS + 1)
    predicted, observed = [], []
    for row in data.itertuples():
        _, matrix, _ = rc.match_probabilities(row.final_lambda, row.final_mu, row.rho)
        share_home, share_away = engine.first_half_shares(row.final_lambda, row.final_mu, engine.DEFAULT_HALF_TIME)
        second_home = matrix.sum(axis=1) @ binom.pmf(goals[None, :], goals[:, None], 1 - float(share_home))
        second_away = matrix.sum(axis=0) @ binom.pmf(goals[None, :], goals[:, None], 1 - float(share_away))
        second = np.outer(second_home, second_away)
        sh, sa = np.indices(second.shape)
        home, away = np.indices(matrix.shape)
        marginal_home, marginal_away = matrix.sum(axis=1), matrix.sum(axis=0)
        predicted.append({
            "Over 4.5 gol": float(matrix[home + away > 4].sum()),
            "1 secondo tempo": float(second[sh > sa].sum()), "X secondo tempo": float(np.trace(second)),
            "2 secondo tempo": float(second[sh < sa].sum()),
            "Over 0.5 gol 2T": float(second[sh + sa > 0].sum()), "Over 1.5 gol 2T": float(second[sh + sa > 1].sum()),
            "Casa Over 0.5 gol": float(marginal_home[1:].sum()), "Casa Over 1.5 gol": float(marginal_home[2:].sum()),
            "Ospite Over 0.5 gol": float(marginal_away[1:].sum()), "Ospite Over 1.5 gol": float(marginal_away[2:].sum()),
        })
        h, a = int(row.home_goals), int(row.away_goals)
        h2, a2 = h - int(row.home_ht_goals), a - int(row.away_ht_goals)
        observed.append({
            "Over 4.5 gol": h + a > 4, "1 secondo tempo": h2 > a2, "X secondo tempo": h2 == a2, "2 secondo tempo": h2 < a2,
            "Over 0.5 gol 2T": h2 + a2 > 0, "Over 1.5 gol 2T": h2 + a2 > 1,
            "Casa Over 0.5 gol": h > 0, "Casa Over 1.5 gol": h > 1, "Ospite Over 0.5 gol": a > 0, "Ospite Over 1.5 gol": a > 1})
    result = (pd.DataFrame(predicted), pd.DataFrame(observed).astype(int))
    pd.to_pickle(result, EXTRA_CACHE)
    return result


def full_table(refresh: bool = False):
    predicted, observed, data = rc.table(refresh)
    more_p, more_o = extras(refresh)
    return pd.concat([predicted, more_p], axis=1), pd.concat([observed, more_o], axis=1), data


def group_of(key: str) -> str:
    if key in ("1", "X", "2", "1X", "X2", "12"):
        return "1X2"
    if "corner" in key:
        return "corner"
    if "cartellini" in key:
        return "cartellini"
    if key.startswith(("Casa Over", "Ospite Over")):
        return "per squadra"
    if key.endswith(("1T",)) and " + " not in key:
        return "primo tempo"
    if key.endswith(("2T", "secondo tempo")):
        return "secondo tempo"
    if key.startswith("Multigol"):
        return "multigol"
    if key == "Goal":
        return "GG/NG"
    if key.startswith("Over") and "gol" in key:
        return "over/under gol"
    return "combo e gruppi"   # combinazioni, risultati esatti, goleade


# --- Mappe ----------------------------------------------------------------------------------------------------

def fit_platt_shrunk(p: np.ndarray, y: np.ndarray, shrink: float) -> tuple[float, float]:
    x = rc._logit(p)
    weight = shrink / (len(p) + shrink)

    def loss(theta):
        q = np.clip(1 / (1 + np.exp(-(theta[0] + theta[1] * x))), rc.EPS, 1 - rc.EPS)
        return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)) + 0.5 * weight * (theta[0] ** 2 + (theta[1] - 1) ** 2)

    fitted = minimize(loss, np.array([0.0, 1.0]), method="L-BFGS-B", bounds=[(-2, 2), (0.3, 3.0)])
    return float(fitted.x[0]), float(fitted.x[1])


def fit_map(p: np.ndarray, y: np.ndarray, cfg: dict) -> dict | None:
    """Mappa nel formato di ``engine.recalibrate`` o None se i casi non bastano."""
    if len(p) < cfg["minimo_casi_taratura"] or y.sum() < cfg["minimo_positivi"] or (len(y) - y.sum()) < cfg["minimo_positivi"]:
        return None
    if len(p) >= cfg["soglia_isotonica_casi"]:
        xs, ys = rc.fit_isotonic(p, y, cfg["prior_isotonica"])
        return {"metodo": "isotonica", "x": [round(v, 5) for v in xs], "y": [round(v, 5) for v in ys]}
    a, b = fit_platt_shrunk(p, y, cfg["shrinkage_platt"])
    return {"metodo": "platt", "a": round(a, 5), "b": round(b, 5)}


def apply_map(p: np.ndarray, mapping: dict, limit_pp: float) -> np.ndarray:
    q = np.array([engine.recalibrate(100.0 * v, mapping) / 100.0 for v in p])
    return np.clip(q, p - limit_pp / 100.0, p + limit_pp / 100.0)


# --- Misure ---------------------------------------------------------------------------------------------------

BANDS = ((0.0, 0.5, "sotto 50"), (0.5, 0.55, "50-55"), (0.55, 0.6, "55-60"), (0.6, 0.7, "60-70"), (0.7, 0.8, "70-80"),
         (0.8, 1.01, "oltre 80"))


def reliability(p: np.ndarray, y: np.ndarray) -> list[dict]:
    rows = []
    for low, high, label in BANDS:
        mask = (p >= low) & (p < high)
        rows.append({"fascia": label, "n": int(mask.sum()), "dichiarato": round(float(p[mask].mean()), 4) if mask.any() else None,
                     "uscito": round(float(y[mask].mean()), 4) if mask.any() else None})
    return rows


def ece(p: np.ndarray, y: np.ndarray) -> float:
    return baseline.expected_calibration_error(baseline.binary(p), y.astype(int))


def walk_forward(p: np.ndarray, y: np.ndarray, seasons: np.ndarray, cfg: dict, only_after: str | None = None):
    """Probabilità corrette stagione per stagione solo con le precedenti; restituisce (corrette, righe verificabili)."""
    order = sorted(set(seasons))
    corrected, checked = p.copy(), np.zeros(len(p), bool)
    for season in order[1:]:
        if only_after and season < only_after:
            continue
        mask = seasons == season
        past = np.isin(seasons, [s for s in order if s < season])
        mapping = fit_map(p[past], y[past], cfg)
        if mapping is None or not mask.any():
            continue
        corrected[mask] = apply_map(p[mask], mapping, cfg["limite_correzione_pp"])
        checked |= mask
    return corrected, checked


def label_cells(cells: list[dict], cfg: dict) -> list[dict]:
    out = []
    for cell in cells:
        n, gap = cell["n"], None
        if n:
            gap = abs(cell["dichiarato"] - cell["uscito"])
        minimum = cfg["min_casi_oltre80"] if cell["fascia"] == "oltre 80" else cfg["min_casi_fascia"]
        if n == 0:
            label = None
        elif n < minimum:
            label = "poco verificata"
        elif gap > cfg["scarto_grande"]:
            label = "non affidabile"
        elif gap > cfg["scarto_piccolo"]:
            label = "poco verificata"
        else:
            label = "verificata"
        out.append(cell | {"scarto": None if gap is None else round(gap, 4), "etichetta": label})
    return out


def run(quick: bool = False, refresh: bool = False) -> dict:
    cfg = settings()
    predicted, observed, data = full_table(refresh)
    seasons = data["season"].astype(str).to_numpy()
    keep = np.ones(len(data), bool)
    if quick:
        keep = data["league"].isin(["E0", "I1", "D1"]).to_numpy() & np.isin(seasons, ["2425", "2526", "2324"])
    old = (json.loads((Path(__file__).resolve().parents[1] / "config" / "goal_model.json").read_text(encoding="utf-8"))
           .get("ricalibrazione", {}).get("mappe", {}))
    only_after = "2526" if quick else None
    results = {}
    trio_keys = {key for trio in TRIOS for key in trio}
    for key in predicted.columns:
        if key in DERIVED:
            results[key] = {"gruppo": group_of(key), "n_totale": 0, "stato": "derivato"}
            continue
        if key in trio_keys:
            continue
        valid = predicted[key].notna().to_numpy() & observed[key].notna().to_numpy() & keep
        p, y, s = (predicted[key].to_numpy(float)[valid], observed[key].to_numpy(float)[valid], seasons[valid])
        entry = {"gruppo": group_of(key), "n_totale": int(valid.sum())}
        if valid.sum() < cfg["minimo_casi_taratura"]:
            results[key] = entry | {"stato": "non tarato", "motivo": "casi insufficienti", "fasce_grezze": reliability(p, y)}
            continue
        corrected, checked = walk_forward(p, y, s, cfg, only_after)
        if not checked.any():
            results[key] = entry | {"stato": "non tarato", "motivo": "casi insufficienti per la verifica",
                                    "fasce_grezze": reliability(p, y)}
            continue
        p0, y0, q0 = p[checked], y[checked], corrected[checked]
        loss0, loss1 = rc.binary_loss(p0, y0), rc.binary_loss(q0, y0)
        ece0, ece1 = ece(p0, y0), ece(q0, y0)
        entry |= {"n": int(checked.sum()), "scarto_prima": round(ece0, 4), "scarto_dopo": round(ece1, 4),
                  "logloss_prima": round(float(loss0.mean()), 5), "logloss_dopo": round(float(loss1.mean()), 5),
                  "fasce_grezze": reliability(p0, y0)}
        better = loss1.mean() <= loss0.mean() and ece1 <= ece0 + cfg["tolleranza_ece"]
        mapping, origin = (fit_map(p, y, cfg), "nuova") if better else (None, None)
        chosen_q = q0
        if key in old:
            old_q = np.array([engine.recalibrate(100.0 * v, old[key]) / 100.0 for v in p0])
            loss_old = rc.binary_loss(old_q, y0).mean()
            if loss_old < (loss1.mean() if better else loss0.mean()):
                mapping, origin, chosen_q = old[key], "precedente (fase P)", old_q
                entry |= {"logloss_dopo": round(float(loss_old), 5), "scarto_dopo": round(ece(old_q, y0), 4)}
        if mapping is None:
            entry |= {"stato": "non tarato", "motivo": "la correzione non migliora log-loss ed ECE nel walk-forward",
                      "fasce": label_cells(reliability(p0, y0), cfg)}
        else:
            entry |= {"stato": "tarato", "metodo": mapping["metodo"], "origine": origin, "mappa": mapping,
                      "fasce": label_cells(reliability(chosen_q, y0), cfg)}
        results[key] = entry
    for trio in TRIOS:
        results.update(_trio(trio, predicted, observed, seasons, keep, cfg, only_after))
    return results


def _trio(trio, predicted, observed, seasons, keep, cfg, only_after) -> dict:
    """Terna 1/X/2 tarata come un'unità: mappe per esito, poi normalizzazione a 1; vale se migliora la log-loss multiclasse
    e l'ECE medio, altrimenti nessuna delle tre."""
    valid = keep.copy()
    for key in trio:
        valid &= predicted[key].notna().to_numpy()
    p = np.column_stack([predicted[key].to_numpy(float)[valid] for key in trio])
    y = np.column_stack([observed[key].to_numpy(float)[valid] for key in trio])
    s = seasons[valid]
    entries = {key: {"gruppo": group_of(key), "n_totale": int(valid.sum())} for key in trio}
    walked = [walk_forward(p[:, i], y[:, i], s, cfg, only_after) for i in range(3)]
    checked = walked[0][1]
    for _, other in walked[1:]:
        checked &= other
    if not checked.any():
        return {key: entries[key] | {"stato": "non tarato", "motivo": "casi insufficienti", "fasce_grezze": reliability(p[:, i], y[:, i])}
                for i, key in enumerate(trio)}
    q = np.column_stack([w[0] for w in walked])[checked]
    q = q / q.sum(axis=1, keepdims=True)
    p0, y0 = p[checked], y[checked]
    loss0 = -(y0 * np.log(np.clip(p0, rc.EPS, 1))).sum(axis=1)
    loss1 = -(y0 * np.log(np.clip(q, rc.EPS, 1))).sum(axis=1)
    ece0 = [ece(p0[:, i], y0[:, i]) for i in range(3)]
    ece1 = [ece(q[:, i], y0[:, i]) for i in range(3)]
    good = loss1.mean() <= loss0.mean() and np.mean(ece1) <= np.mean(ece0) + cfg["tolleranza_ece"]
    maps = [fit_map(p[:, i], y[:, i], cfg) for i in range(3)] if good else [None] * 3
    good = good and all(maps)
    out = {}
    for i, key in enumerate(trio):
        entry = entries[key] | {"n": int(checked.sum()), "scarto_prima": round(ece0[i], 4), "scarto_dopo": round(ece1[i], 4),
                                "logloss_prima": round(float(loss0.mean()), 5), "logloss_dopo": round(float(loss1.mean()), 5),
                                "fasce_grezze": reliability(p0[:, i], y0[:, i])}
        if good:
            entry |= {"stato": "tarato", "metodo": maps[i]["metodo"], "origine": "nuova (terna normalizzata)", "mappa": maps[i],
                      "fasce": label_cells(reliability(q[:, i], y0[:, i]), cfg)}
        else:
            entry |= {"stato": "non tarato", "motivo": "la correzione della terna non migliora log-loss ed ECE",
                      "fasce": label_cells(reliability(p0[:, i], y0[:, i]), cfg)}
        out[key] = entry
    return out


def render(results: dict, quick: bool) -> str:
    lines = [f"## Calibrazione per mercato (fase AM{', rapida' if quick else ''})", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.taratura_check`. Walk-forward: ogni stagione è corretta "
             "solo con le precedenti. Scarto = ECE (media pesata |dichiarato − uscito|).", "",
             "| Gruppo | Mercato | Casi | Scarto prima | Scarto dopo | Log-loss prima → dopo | Stato |", "|---|---|---|---|---|---|---|"]
    for key, row in results.items():
        if row.get("stato") == "derivato":
            lines.append(f"| {row['gruppo']} | {key} | — | — | — | — | derivato dalla base |")
            continue
        if "n" not in row:
            lines.append(f"| {row['gruppo']} | {key} | {row['n_totale']} | — | — | — | non tarato ({row['motivo']}) |")
            continue
        state = f"tarato ({row['metodo']}, {row['origine']})" if row["stato"] == "tarato" else "non tarato"
        lines.append(f"| {row['gruppo']} | {key} | {row['n']} | {row['scarto_prima']:.4f} | {row['scarto_dopo']:.4f} | "
                     f"{row['logloss_prima']:.5f} → {row['logloss_dopo']:.5f} | {state} |")
    lines += ["", "### Dichiarato contro uscito (grezzo, fasce 50+)", "",
              "| Mercato | Fascia | Dichiarato | Uscito | Casi |", "|---|---|---|---|---|"]
    for key, row in results.items():
        for cell in row.get("fasce_grezze", []):
            if cell["fascia"] != "sotto 50" and cell["n"]:
                lines.append(f"| {key} | {cell['fascia']} | {cell['dichiarato']:.1%} | {cell['uscito']:.1%} | {cell['n']} |")
    return "\n".join(lines) + "\n"


def save(results: dict) -> None:
    cfg = settings()
    markets = {}
    for key, row in results.items():
        item = {"gruppo": row["gruppo"], "stato": row["stato"], "casi": row.get("n", row["n_totale"])}
        if row["stato"] == "derivato":
            markets[key] = item
            continue
        for name in ("metodo", "origine", "mappa", "scarto_prima", "scarto_dopo", "logloss_prima", "logloss_dopo", "fasce", "motivo"):
            if name in row:
                item[name] = row[name]
        if "fasce" not in item and "fasce_grezze" in row:
            item["fasce"] = label_cells(row["fasce_grezze"], cfg)
        markets[key] = item
    payload = {"versione": 1, "data": date.today().isoformat(), "attiva": True, "parametri": cfg,
               "nota": "una sola mappa per mercato; sostituisce la ricalibrazione della fase P dello stesso mercato; "
                       "etichette dalle celle walk-forward (nessun dato dal futuro)",
               "mercati": markets}
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    parser.add_argument("--rapido", action="store_true")
    parser.add_argument("--ricalcola", action="store_true", help="rigenera le tabelle in cache")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = run(args.rapido, args.ricalcola)
    markdown = render(results, args.rapido)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva and not args.rapido:
        save(results)


if __name__ == "__main__":
    main()
