"""Fase P, punti 4 e 0b: ricalibrazione finale per mercato, fuori campione.

Probabilità finali come nell'app (gol ancorati alle quote di chiusura, Dixon-Coles, primo tempo con le quote
tarate; corner e punti cartellini dal modello dei conteggi senza quote corner/cartellini, che nello storico
non ci sono) per i mercati principali, le combo, i gruppi di risultati esatti e le goleade. Per ogni mercato
si stimano sul 2024-26 una mappa di Platt (logit q = a + b·logit p) e una isotonica (con riavvicinamento
all'identità); si sceglie sul 2024-26 quella con log-loss più bassa e resta accesa solo con la regola severa
fuori campione (2019-24 e 2026-27). Uso: ``python -m tools.recalibration_check [--salva] [--output ...]``.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import engine
from tools import baseline, v2common

EXACT_GROUPS = ("1-0/2-0/2-1", "0-1/0-2/1-2", "0-0/1-1", "1-1/2-2", "2-1/3-1/3-2", "1-0/0-1/0-0")
CORNER_LINES = (8.5, 9.5, 10.5)
CARD_LINES = (3.5, 4.5, 5.5)
GOLEADE = ("Favorita 4+ gol", "Favorita vince di 3+", "Totale 5+ gol")
MAX_GOALS = 10
EPS = 1e-6


def _logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


# --- Tabella delle probabilità --------------------------------------------------------------------------

def match_probabilities(lambda_: float, mu: float, rho: float) -> tuple[dict[str, float], np.ndarray, np.ndarray]:
    from scipy.stats import binom

    matrix = engine.dixon_coles_matrix(lambda_, mu, rho, max_goals=MAX_GOALS)
    matrix = matrix / matrix.sum()
    home, away = np.indices(matrix.shape)
    total = home + away
    signs = {"1": home > away, "X": home == away, "2": home < away}
    signs |= {"1X": signs["1"] | signs["X"], "X2": signs["X"] | signs["2"], "12": signs["1"] | signs["2"]}
    out = {key: float(matrix[mask].sum()) for key, mask in signs.items()}
    for line in (1.5, 2.5, 3.5):
        out[f"Over {line} gol"] = float(matrix[total > line].sum())
    out["Goal"] = float(matrix[(home > 0) & (away > 0)].sum())
    for low, high in ((1, 3), (2, 4), (2, 5), (1, 2)):
        out[f"Multigol {low}-{high}"] = float(matrix[(total >= low) & (total <= high)].sum())
    for sign in ("1", "X", "2"):
        for line in (1.5, 2.5, 3.5):
            out[f"{sign} + Over {line}"] = float(matrix[signs[sign] & (total > line)].sum())
    for line in (2.5, 3.5):
        out[f"Goal + Over {line}"] = float(matrix[(home > 0) & (away > 0) & (total > line)].sum())
    for group in EXACT_GROUPS:
        mask = np.zeros_like(matrix, dtype=bool)
        for score in group.split("/"):
            h, a = (int(part) for part in score.split("-"))
            mask[h, a] = True
        out[f"Esatti {group}"] = float(matrix[mask].sum())
    favourite_home = lambda_ >= mu
    favourite, other = (home, away) if favourite_home else (away, home)
    out["Favorita 4+ gol"] = float(matrix[favourite >= 4].sum())
    out["Favorita vince di 3+"] = float(matrix[favourite - other >= 3].sum())
    out["Totale 5+ gol"] = float(matrix[total >= 5].sum())
    # Primo tempo: assottigliamento binomiale dei gol con le quote tarate.
    share_home, share_away = engine.first_half_shares(lambda_, mu, engine.DEFAULT_HALF_TIME)
    goals = np.arange(MAX_GOALS + 1)
    first_home = matrix.sum(axis=1) @ binom.pmf(goals[None, :], goals[:, None], float(share_home))
    first_away = matrix.sum(axis=0) @ binom.pmf(goals[None, :], goals[:, None], float(share_away))
    # Gol del primo tempo per squadra: con Dixon-Coles quasi indipendenti; si usa il prodotto delle marginali.
    first = np.outer(first_home, first_away)
    fh, fa = np.indices(first.shape)
    out["1 1T"], out["X 1T"], out["2 1T"] = (float(first[fh > fa].sum()), float(np.trace(first)), float(first[fh < fa].sum()))
    out["Over 0.5 gol 1T"] = float(first[fh + fa > 0.5].sum())
    out["Over 1.5 gol 1T"] = float(first[fh + fa > 1.5].sum())
    return out, matrix, first


def outcome_row(row) -> dict[str, int]:
    home, away = int(row.home_goals), int(row.away_goals)
    total = home + away
    signs = {"1": home > away, "X": home == away, "2": home < away}
    signs |= {"1X": signs["1"] or signs["X"], "X2": signs["X"] or signs["2"], "12": signs["1"] or signs["2"]}
    out = dict(signs)
    for line in (1.5, 2.5, 3.5):
        out[f"Over {line} gol"] = total > line
    out["Goal"] = home > 0 and away > 0
    for low, high in ((1, 3), (2, 4), (2, 5), (1, 2)):
        out[f"Multigol {low}-{high}"] = low <= total <= high
    for sign in ("1", "X", "2"):
        for line in (1.5, 2.5, 3.5):
            out[f"{sign} + Over {line}"] = signs[sign] and total > line
    for line in (2.5, 3.5):
        out[f"Goal + Over {line}"] = home > 0 and away > 0 and total > line
    for group in EXACT_GROUPS:
        out[f"Esatti {group}"] = f"{home}-{away}" in group.split("/")
    favourite_home = row.final_lambda >= row.final_mu
    favourite, other = (home, away) if favourite_home else (away, home)
    out["Favorita 4+ gol"] = favourite >= 4
    out["Favorita vince di 3+"] = favourite - other >= 3
    out["Totale 5+ gol"] = total >= 5
    first_home, first_away = int(row.home_ht_goals), int(row.away_ht_goals)
    out["1 1T"], out["X 1T"], out["2 1T"] = first_home > first_away, first_home == first_away, first_home < first_away
    out["Over 0.5 gol 1T"] = first_home + first_away > 0
    out["Over 1.5 gol 1T"] = first_home + first_away > 1
    return {key: int(value) for key, value in out.items()}


def table(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(probabilità, esiti, partite) con cache in ``data/cache/fase_p``."""
    from tools.calibrate import count_means, count_sf, observed_points, points_sf

    path = v2common.CACHE / "mercati.pkl"
    if path.exists() and not refresh:
        return pd.read_pickle(path)
    data = v2common.frame().dropna(subset=["home_ht_goals", "away_ht_goals"]).reset_index(drop=True)
    predicted, observed = [], []
    for row in data.itertuples():
        probabilities, _, _ = match_probabilities(row.final_lambda, row.final_mu, row.rho)
        predicted.append(probabilities)
        observed.append(outcome_row(row))
    predicted, observed = pd.DataFrame(predicted), pd.DataFrame(observed)
    counts = data.dropna(subset=["home_corners", "away_corners", "home_yellows", "away_yellows", "home_reds", "away_reds",
                                 "referee_yellow_avg", "referee_fouls_avg"]).index
    model = engine.DEFAULT_COUNT_MODEL
    means = count_means(model, data.loc[counts])
    corners = (data.loc[counts, "home_corners"] + data.loc[counts, "away_corners"]).to_numpy(int)
    points = observed_points(data.loc[counts], engine.DEFAULT_CARD_RULE)
    for line in CORNER_LINES:
        key = f"Over {line} corner"
        predicted[key], observed[key] = np.nan, np.nan
        predicted.loc[counts, key] = count_sf(line, means["corner_home"] + means["corner_away"], model.corner_dispersion)
        observed.loc[counts, key] = (corners > line).astype(int)
    for line in CARD_LINES:
        key = f"Over {line} cartellini"
        predicted[key], observed[key] = np.nan, np.nan
        predicted.loc[counts, key] = points_sf(line, means["cards"], model.card_dispersion,
                                               means["cards"] * model.card_red_ratio, engine.DEFAULT_CARD_RULE)
        observed.loc[counts, key] = (points > line).astype(int)
    result = (predicted, observed, data)
    pd.to_pickle(result, path)
    return result


# --- Mappe ---------------------------------------------------------------------------------------------

def fit_platt(p: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    x = _logit(p)

    def loss(theta):
        q = 1 / (1 + np.exp(-(theta[0] + theta[1] * x)))
        q = np.clip(q, EPS, 1 - EPS)
        return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))

    fitted = minimize(loss, np.array([0.0, 1.0]), method="L-BFGS-B", bounds=[(-2, 2), (0.3, 3.0)])
    return float(fitted.x[0]), float(fitted.x[1])


def apply_platt(p: np.ndarray, a: float, b: float) -> np.ndarray:
    return 1 / (1 + np.exp(-(a + b * _logit(p))))


def fit_isotonic(p: np.ndarray, y: np.ndarray, prior: float = 50.0) -> tuple[list[float], list[float]]:
    """Isotonica (pool adjacent violators) su 20 classi di probabilità, ogni classe riavvicinata alla propria
    media prevista con ``prior`` partite fittizie; restituisce i nodi (x, y) per l'interpolazione."""
    order = np.argsort(p)
    bins = np.array_split(order, 20)
    xs = np.array([p[index].mean() for index in bins])
    ys = np.array([(y[index].sum() + prior * p[index].mean()) / (len(index) + prior) for index in bins])
    weights = np.array([len(index) + prior for index in bins], dtype=float)
    values, sizes, blocks = list(ys), list(weights), [[i] for i in range(len(ys))]
    i = 0
    while i < len(values) - 1:
        if values[i] > values[i + 1]:
            merged = (values[i] * sizes[i] + values[i + 1] * sizes[i + 1]) / (sizes[i] + sizes[i + 1])
            values[i:i + 2], sizes[i:i + 2], blocks[i:i + 2] = [merged], [sizes[i] + sizes[i + 1]], [blocks[i] + blocks[i + 1]]
            i = max(i - 1, 0)
        else:
            i += 1
    fitted = np.empty(len(ys))
    for value, block in zip(values, blocks):
        fitted[block] = value
    return [float(value) for value in xs], [float(value) for value in fitted]


def apply_isotonic(p: np.ndarray, xs, ys) -> np.ndarray:
    return np.clip(np.interp(p, xs, ys), EPS, 1 - EPS)


def binary_loss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _fit(method: str, p: np.ndarray, y: np.ndarray):
    if method == "platt":
        a, b = fit_platt(p, y)
        return {"a": a, "b": b}, lambda values: apply_platt(values, a, b)
    xs, ys = fit_isotonic(p, y)
    return {"xs": xs, "ys": ys}, lambda values: apply_isotonic(values, xs, ys)


def holm(results: dict) -> None:
    """Correzione di Holm per i confronti multipli (un test per mercato, unilaterale al 5%): un mercato resta
    acceso solo se supera anche la soglia corretta, oltre alla regola severa."""
    from scipy.stats import norm

    tested = sorted(((row["z"], key) for key, row in results.items() if row.get("stimabile")), reverse=False)
    count = len(tested)
    still = True
    for rank, (z, key) in enumerate(tested):
        threshold = -norm.ppf(1 - 0.05 / (count - rank))
        still = still and z < threshold
        results[key]["holm"] = still
        results[key]["tenuta"] = bool(results[key]["regola_severa"] and still)


def run() -> dict:
    predicted, observed, data = table()
    train = v2common.is_train(data)
    seasons = data["season"].to_numpy()
    first_train = train & (seasons == min(seasons[train]))
    second_train = train & ~first_train
    results = {}
    for key in predicted.columns:
        valid = predicted[key].notna().to_numpy() & observed[key].notna().to_numpy()
        p, y = predicted[key].to_numpy(float), observed[key].to_numpy(float)
        fit_mask, test_mask = valid & train, valid & ~train
        if fit_mask.sum() < 300 or y[fit_mask].sum() < 20:
            results[key] = {"stimabile": False}
            continue
        # Metodo scelto in validazione incrociata dentro il 2024-26 (una stagione stima, l'altra misura).
        cv = {}
        for method in ("platt", "isotonica"):
            losses = []
            for fit_part, check_part in ((first_train, second_train), (second_train, first_train)):
                _, mapper = _fit(method, p[valid & fit_part], y[valid & fit_part])
                losses.append(binary_loss(mapper(p[valid & check_part]), y[valid & check_part]).mean())
            cv[method] = float(np.mean(losses))
        method = min(cv, key=cv.get)
        parameters, mapper = _fit(method, p[fit_mask], y[fit_mask])
        after_p = mapper(p[test_mask])
        before = (binary_loss(p[test_mask], y[test_mask]),
                  baseline.expected_calibration_error(baseline.binary(p[test_mask]), y[test_mask].astype(int)))
        after = (binary_loss(after_p, y[test_mask]),
                 baseline.expected_calibration_error(baseline.binary(after_p), y[test_mask].astype(int)))
        verdict = v2common.strict(before, after)
        verdict |= {"stimabile": True, "metodo": method, **parameters, "regola_severa": verdict["tenuta"],
                    "z": verdict["differenza"] / (verdict["due_es"] / 2) if verdict["due_es"] > 0 else 0.0,
                    "prevista_prima": float(p[test_mask].mean()), "prevista_dopo": float(after_p.mean()),
                    "reale": float(y[test_mask].mean())}
        if key in GOLEADE:
            # 0b: il quinto più squilibrato (|λ − μ|), dove la fase Q aveva visto la sovrastima.
            imbalance = (data["final_lambda"] - data["final_mu"]).abs().to_numpy()
            top = test_mask & (imbalance >= np.quantile(imbalance[test_mask], 0.8))
            verdict["squilibrate"] = {"partite": int(top.sum()), "prima": float(p[top].mean()),
                                      "dopo": float(mapper(p[top]).mean()), "reale": float(y[top].mean())}
        results[key] = verdict
    holm(results)
    return results


def render(results: dict) -> str:
    kept = [key for key, row in results.items() if row.get("tenuta")]
    lines = ["## Ricalibrazione finale per mercato (fase P, punti 4 e 0b)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.recalibration_check`. Mappa (Platt o isotonica, "
             "scelta in validazione incrociata tra 2024-25 e 2025-26) stimata sul 2024-26, verificata sul 2019-24 e "
             "2026-27 per mercato con la regola severa e, poiché i mercati sono tanti, con la correzione di Holm per i "
             f"confronti multipli. Accese: {len(kept)} su {sum(row.get('stimabile', False) for row in results.values())}"
             + (f" ({', '.join(kept)})" if kept else "") + ".", "",
             "| Mercato | Metodo | Partite | Log-loss prima | dopo | Differenza (± 2 e.s.) | ECE prima → dopo | "
             "Prevista prima / dopo / reale | Esito |", "|---|---|---|---|---|---|---|---|---|"]
    for key, row in results.items():
        if not row.get("stimabile"):
            lines.append(f"| {key} | — | — | — | — | — | — | — | non stimabile |")
            continue
        lines.append(f"| {key} | {row['metodo']} | {row['partite']} | {row['prima']:.4f} | {row['dopo']:.4f} | "
                     f"{row['differenza']:+.5f} ± {row['due_es']:.5f} | {row['ece_prima']:.4f} → {row['ece_dopo']:.4f} | "
                     f"{row['prevista_prima']:.1%} / {row['prevista_dopo']:.1%} / {row['reale']:.1%} | "
                     f"**{'accesa' if row['tenuta'] else ('spenta (Holm)' if row['regola_severa'] else 'spenta')}** |")
    lines += ["", "Goleade nel quinto di partite più squilibrate (|λ − μ|), fuori campione (0b):", "",
              "| Mercato | Partite | Prevista prima | Prevista dopo | Reale |", "|---|---|---|---|---|"]
    for key in GOLEADE:
        top = results.get(key, {}).get("squilibrate")
        if top:
            lines.append(f"| {key} | {top['partite']} | {top['prima']:.1%} | {top['dopo']:.1%} | {top['reale']:.1%} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = run()
    markdown = render(results)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva:
        from tools.calibrate import _update_config

        maps = {key: ({"metodo": "platt", "a": round(row["a"], 5), "b": round(row["b"], 5)} if row["metodo"] == "platt"
                      else {"metodo": "isotonica", "x": [round(v, 5) for v in row["xs"]], "y": [round(v, 5) for v in row["ys"]]})
                for key, row in results.items() if row.get("tenuta")}
        _update_config({"ricalibrazione": {"data": date.today().isoformat(), "attiva": bool(maps), "mappe": maps,
                                           "verificati": sorted(key for key, row in results.items() if row.get("stimabile")),
                                           "nota": "solo i mercati che migliorano fuori campione (regola severa)"}})


if __name__ == "__main__":
    main()
