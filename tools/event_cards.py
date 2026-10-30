"""Fase AK: legame tra rossi, gialli e stato della partita nel motore a eventi, stimato per inferenza indiretta.

Il banco dello stadio 14 ha trovato il legame troppo debole: gialli in più nelle partite con un rosso +0,96 reali contro +0,11
del motore, correlazione |diff. reti| / gialli −0,18 contro −0,07. La causa principale (uomo in meno: gialli ×0,39 con
l'effetto fisso) è corretta in ``tools.stima_motore`` (stima tra partite, ×0,87). Qui si stimano i due parametri restanti:

- ``esponente_stato_gialli`` a: moltiplicatori di stato dei gialli (StatsBomb, grezzi) elevati ad a, al posto
  dell'esponente comune di attenuazione (stimato sui tiri, non sui cartellini);
- ``esponente_calore_rossi`` g: la partita «calda» (moltiplicatore gamma dei gialli del vincolo di coerenza) elevata a g su
  rossi diretti e seconde gialle (media riportata a 1).

Momenti osservati sui CSV football-data 2024/25 e 2025/26 (le stagioni di taratura del motore attuale; MAI quelle dei banchi
di verifica), residui a parità di quote, medie di corner e cartellini, arbitro e campionato (``event_check.regressors``):
pendenza dei gialli sul |diff. reti| e gialli in più con almeno un rosso. Gli stessi momenti dal motore a eventi
(``engine.simulate_match`` acceso sulla stessa ``MatchConfig`` di ogni partita, ``PERCORSI`` partite simulate per riga, gialli
nella convenzione dei dati: in Inghilterra e Scozia senza il primo giallo dell'espulso). I due parametri interagiscono
(più stato sui gialli = meno gialli dopo un rosso, che di solito arriva a punteggio sbilanciato): stima alternata, griglia di
a con g = 1, griglia di g con l'a trovato, di nuovo a (a ± 0,5) con il g trovato. Valore = interpolazione lineare della curva
sul momento osservato; errore standard = bootstrap per partita del momento osservato diviso la pendenza della curva.

Uso: ``python -m tools.event_cards [--per-stagione 50] [--processi 2] [--salva]`` → ``docs/backtest/AK_cartellini.md`` e,
con ``--salva``, ``stato_partita.legame_cartellini`` di ``config/motore_eventi.json``. Punti della griglia in cache in
``data/cache/event_cards/``.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
import json
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd

import engine
import event_engine
from tools import baseline
from tools.event_check import LEAGUES, regressors

SEASONS = ("2425", "2526")
GRID_A = (1.0, 2.0, 3.0)
GRID_G = (1.0, 2.0, 3.0, 4.0)
STEP = 0.25                     # arrotondamento delle stime intermedie (riuso dei punti in cache)
PERCORSI = 10
SIMULATIONS = 4_000
BOOTSTRAP = 500
CACHE = Path(__file__).resolve().parents[1] / "data" / "cache" / "event_cards"
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "backtest" / "AK_cartellini.md"
COLUMNS = ["home_yellows", "away_yellows", "home_reds", "away_reds", "close_home", "close_draw", "close_away"]


def calibration_rows(per_season: int | None = None, seed: int = 5) -> pd.DataFrame:
    """Partite delle stagioni di taratura (tutte, o ``per_season`` per campionato e stagione)."""
    features = baseline.load_usable_features().dropna(subset=COLUMNS)
    features = features[features["league"].isin(LEAGUES) & features["season"].isin(SEASONS)]
    if per_season:
        features = pd.concat([frame.sample(min(per_season, len(frame)), random_state=seed)
                              for _, frame in features.groupby(["league", "season"])])
    return features.sort_values("date").reset_index(drop=True)


def moments(X: np.ndarray, goal_diff: np.ndarray, yellows: np.ndarray, reds: np.ndarray,
            weights: np.ndarray | None = None) -> dict[str, float]:
    """Pendenza dei gialli sul |diff. reti|, correlazione e gialli in più con un rosso, sui residui della regressione."""
    w = np.ones(len(yellows)) if weights is None else weights
    sw = np.sqrt(w)

    def residual(values):
        beta, *_ = np.linalg.lstsq(X * sw[:, None], values * sw, rcond=None)
        return values - X @ beta

    rg, ry = residual(np.abs(goal_diff).astype(float)), residual(yellows.astype(float))
    red = reds > 0
    return {"pendenza_gd": float((w * rg * ry).sum() / (w * rg ** 2).sum()),
            "correlazione_gd": float((w * rg * ry).sum() / np.sqrt((w * rg ** 2).sum() * (w * ry ** 2).sum())),
            "gialli_con_rosso": float(np.average(ry[red], weights=w[red]) - np.average(ry[~red], weights=w[~red]))}


def observed(rows: pd.DataFrame, bootstrap: int = BOOTSTRAP, seed: int = 7) -> dict:
    X = regressors(rows)
    args = ((rows["home_goals"] - rows["away_goals"]).to_numpy(), (rows["home_yellows"] + rows["away_yellows"]).to_numpy(),
            (rows["home_reds"] + rows["away_reds"]).to_numpy())
    point = moments(X, *args)
    rng = np.random.default_rng(seed)
    draws = [moments(X, *args, weights=np.bincount(rng.integers(0, len(rows), len(rows)), minlength=len(rows)).astype(float))
             for _ in range(bootstrap)]
    return {key: {"valore": value, "es": float(np.std([draw[key] for draw in draws], ddof=1))} for key, value in point.items()}


_PARAMS: dict = {}


def _params(league, a, g):
    key = (league, a, g)
    if key not in _PARAMS:
        _PARAMS[key] = event_engine.load(league, attenuate=True).with_card_link(a, g)
    return _PARAMS[key]


def simulate_row(args: tuple[int, dict, float | None, float]) -> dict:
    position, row, a, g = args
    engine._event_params = lambda league: _params(league, a, g)
    config = replace(baseline.config_for_row(row, odds=baseline.closing_odds(row)), league=row["league"],
                     simulations=SIMULATIONS, seed=position, keep_samples=True)
    config = replace(config, event_engine=replace(config.event_engine, active=True, pilot=SIMULATIONS, minimum=SIMULATIONS,
                                                  batch=SIMULATIONS))
    sample = engine.simulate_match(config)["event_engine_sample"]
    take = slice(0, PERCORSI)
    yellows = sample["yellows_home"][take] + sample["yellows_away"][take]
    if row["league"] in engine.SECOND_YELLOW_EXCLUDED_LEAGUES:
        yellows = yellows - sample["double_yellows_home"][take] - sample["double_yellows_away"][take]
    return {"position": position, "gd": (sample["goals_home"][take] - sample["goals_away"][take]).tolist(),
            "yellows": yellows.tolist(), "reds": (sample["reds_home"][take] + sample["reds_away"][take]).tolist()}


def model_moments(rows: pd.DataFrame, a: float | None, g: float, processes: int, folder: Path = CACHE) -> dict[str, float]:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"a{a}_g{g}_n{len(rows)}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    records = rows.to_dict("records")
    with get_context("fork").Pool(processes) as pool:
        outputs = sorted(pool.map(simulate_row, [(i, record, a, g) for i, record in enumerate(records)]),
                         key=lambda item: item["position"])
    X = np.repeat(regressors(rows), PERCORSI, axis=0)
    result = moments(X, np.concatenate([o["gd"] for o in outputs]), np.concatenate([o["yellows"] for o in outputs]),
                     np.concatenate([o["reds"] for o in outputs]))
    path.write_text(json.dumps(result), encoding="utf-8")
    return result


def _solve(grid: tuple[float, ...], curve: list[float], target: float, error: float) -> tuple[float, float, bool]:
    """Valore della griglia che riproduce il momento (interpolazione lineare), errore standard e se è dentro la griglia."""
    values = np.asarray(curve)
    order = np.argsort(values)
    inside = bool(values.min() <= target <= values.max())
    estimate = float(np.interp(target, values[order], np.asarray(grid)[order]))
    slope = abs(np.polyfit(grid, values, 1)[0])
    return estimate, float(error / slope) if slope > 0 else float("inf"), inside


def run(per_season: int = 50, processes: int = 2) -> dict:
    real = observed(calibration_rows())
    rows = calibration_rows(per_season)
    base = event_engine.load(None)

    def rounded(value):
        return round(round(value / STEP) * STEP, 2)

    def solve_a(grid, g):
        curve = {a: model_moments(rows, a, g, processes) for a in grid}
        a, error, inside = _solve(tuple(curve), [m["pendenza_gd"] for m in curve.values()], real["pendenza_gd"]["valore"],
                                  real["pendenza_gd"]["es"])
        return curve, max(a, 0.0), error, inside

    start = {"a": base.state_power, "g": 1.0, **model_moments(rows, None, 1.0, processes)}
    curve_a, first_a, _, _ = solve_a(GRID_A, 1.0)
    curve_g = {g: model_moments(rows, rounded(first_a), g, processes) for g in GRID_G}
    g, g_error, g_inside = _solve(GRID_G, [m["gialli_con_rosso"] for m in curve_g.values()], real["gialli_con_rosso"]["valore"],
                                  real["gialli_con_rosso"]["es"])
    g = rounded(max(g, 0.0))
    around = rounded(first_a)
    curve_a2, a, a_error, a_inside = solve_a(tuple(sorted({max(around - 0.5, 0.0), around, around + 0.5})), g)
    a = round(a, 2)
    final = model_moments(rows, a, g, processes)
    return {"reale": real, "partite_reali": int(len(calibration_rows())), "partite_motore": int(len(rows)),
            "partenza": start, "curva_a": curve_a, "a_intermedio": rounded(first_a), "curva_g": curve_g,
            "curva_a2": curve_a2, "a": a, "a_es": round(a_error, 3), "a_dentro": a_inside, "g": g, "g_es": round(g_error, 3),
            "g_dentro": g_inside, "finale": final}


def section(result: dict) -> dict:
    return {
        "esponente_stato_gialli": result["a"], "es_stato_gialli": result["a_es"],
        "esponente_calore_rossi": result["g"], "es_calore_rossi": result["g_es"],
        "momenti_reali": {key: round(value["valore"], 4) for key, value in result["reale"].items()},
        "momenti_motore": {key: round(value, 4) for key, value in result["finale"].items()},
        "partite": {"reali": result["partite_reali"], "motore": result["partite_motore"], "percorsi_per_partita": PERCORSI},
        "data": date.today().isoformat(),
        "metodo": "inferenza indiretta sui CSV football-data 2024/25-2025/26 (stagioni di taratura): pendenza dei gialli sul "
                  "|diff. reti| → esponente di stato dei gialli; gialli in più con un rosso → esponente della partita calda sui "
                  "rossi. Report docs/backtest/AK_cartellini.md (python -m tools.event_cards)",
    }


def report(result: dict) -> str:
    real = result["reale"]
    lines = ["# Motore a eventi: legame tra rossi, gialli e stato della partita (fase AK)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.event_cards`. Momenti reali su {result['partite_reali']} "
             f"partite football-data 2024/25-2025/26 (stagioni di taratura, nessuna partita dei banchi di verifica); motore su "
             f"{result['partite_motore']} partite delle stesse stagioni × {PERCORSI} percorsi (`simulate_match` acceso, "
             f"{SIMULATIONS:,} simulazioni). Residui a parità di quote, medie, arbitro e campionato.".replace(",", "."), "",
             "## Stima", "",
             f"- Esponente di stato dei gialli: **{result['a']:g}** (± {2 * result['a_es']:.2f}, 2 e.s.; era l'esponente comune "
             f"{result['partenza']['a']:g}){'' if result['a_dentro'] else ' — FUORI dalla griglia: valore al bordo'}.",
             f"- Esponente della partita calda sui rossi: **{result['g']:g}** (± {2 * result['g_es']:.2f}){'' if result['g_dentro'] else ' — FUORI dalla griglia: valore al bordo'}.",
             "", "| Momento | Reale (± 2 e.s.) | Motore prima | Motore dopo |", "|---|---|---|---|"]
    for key, label in (("pendenza_gd", "pendenza gialli / |diff. reti|"), ("correlazione_gd", "correlazione |diff. reti| / gialli"),
                       ("gialli_con_rosso", "gialli in più con un rosso")):
        lines.append(f"| {label} | {real[key]['valore']:+.3f} ± {2 * real[key]['es']:.3f} | {result['partenza'][key]:+.3f} | "
                     f"{result['finale'][key]:+.3f} |")
    lines += ["", "«Motore prima» = uomo in meno già stimato tra partite (gialli ×0,87), esponente comune, partita calda con "
              "esponente 1. Con l'uomo in meno stimato con l'effetto fisso (×0,39) il banco dava +0,11 gialli con un rosso.", "",
              "## Curve", "", "| a (g = 1) | pendenza | correlazione | gialli con rosso |", "|---|---|---|---|"]
    for a, value in result["curva_a"].items():
        lines.append(f"| {a:g} | {value['pendenza_gd']:+.3f} | {value['correlazione_gd']:+.3f} | {value['gialli_con_rosso']:+.3f} |")
    lines += ["", f"| g (a = {result['a_intermedio']:g}) | pendenza | correlazione | gialli con rosso |", "|---|---|---|---|"]
    for g, value in result["curva_g"].items():
        lines.append(f"| {g:g} | {value['pendenza_gd']:+.3f} | {value['correlazione_gd']:+.3f} | {value['gialli_con_rosso']:+.3f} |")
    lines += ["", f"| a (g = {result['g']:g}) | pendenza | correlazione | gialli con rosso |", "|---|---|---|---|"]
    for a, value in result["curva_a2"].items():
        lines.append(f"| {a:g} | {value['pendenza_gd']:+.3f} | {value['correlazione_gd']:+.3f} | {value['gialli_con_rosso']:+.3f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-stagione", type=int, default=50)
    parser.add_argument("--processi", type=int, default=2)
    parser.add_argument("--salva", action="store_true", help="Scrive stato_partita.legame_cartellini in config/motore_eventi.json")
    args = parser.parse_args()
    result = run(args.per_stagione, args.processi)
    markdown = report(result)
    print(markdown)
    OUTPUT.write_text(markdown, encoding="utf-8")
    if args.salva:
        data = json.loads(event_engine.PATH.read_text(encoding="utf-8"))
        data["stato_partita"]["legame_cartellini"] = section(result)
        event_engine.PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
