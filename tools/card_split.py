"""Fase T: divisione dei cartellini tra le squadre (1X2 cartellini, linee per squadra), verifica e taratura.

Il totale dei gialli resta quello della fase M (``engine.card_total_mean``, binomiale negativa). Qui si
modella solo la quota della squadra di casa ``p`` con cui il totale si divide (e i rossi con la stessa
quota): logit p = casa + peso_ritmo·log(c_casa/c_ospite) + peso_provocati·log(prov_ospite/prov_casa)
+ peso_sfavorita·u + peso_arbitro·log(gialli arbitro/4.5)·log(c_casa/c_ospite), con eventuale
beta-binomiale (concentrazione φ, divisione più dispersa) o binomiale moltiplicativa di Altham
(bilanciamento θ: con log θ > 0 le divisioni equilibrate sono più probabili, come quando l'arbitro
«compensa»). Il fattore comune gamma c'è già: totale binomiale negativa diviso in modo binomiale = due
binomiali negative con lo stesso fattore. Prima = divisione attuale del motore
(p = c_casa/(c_casa + c_ospite)).

Componenti provate in ordine (a ritmo e provocati con shrinkage, b sfavorita, c casa, d fattore comune,
e arbitro): ognuna resta accesa solo se migliora fuori campione sia la log-loss media sia l'ECE media di
1X2 cartellini e linee per squadra 0.5/1.5/2.5 (punti Eurobet). Taratura sul 2024-26 (come la fase M),
fuori campione = 2019-24 e 2026-27. Uso: ``python -m tools.card_split [--output docs/BASELINE.md]``.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, replace
from datetime import date
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import betaln, gammaln
from scipy.stats import nbinom, poisson

import engine
from tools import baseline, dataset
from tools.calibrate import count_means


MAX_YELLOWS = 16
MAX_REDS = 3
TEAM_LINES = (0.5, 1.5, 2.5)
SHRINK_MATCHES = 5.0
SETS_OUT = {"2019-24": dataset.WARMUP_SEASONS, "2026-27": dataset.HOLDOUT_SEASONS}


@dataclass(frozen=True)
class SplitParams:
    home: float = 0.0
    rate_weight: float = 1.0
    provoked_weight: float = 0.0
    underdog_weight: float = 0.0
    referee_weight: float = 0.0
    concentration: float = 0.0      # 0 = binomiale (nessun fattore comune aggiuntivo)
    balance: float = 0.0            # log θ della binomiale moltiplicativa (0 = binomiale)
    shrink: bool = False            # ritmo e provocati con shrinkage verso la media di lega
    underdog: str = "elo"           # elo | mercato


# --- Dati ---------------------------------------------------------------------------------------

def with_provoked(features: pd.DataFrame, window: int = dataset.WINDOW) -> pd.DataFrame:
    """Aggiunge, solo da partite precedenti, i gialli «provocati» (presi dagli avversari) e i ritmi con shrinkage."""
    data = features.sort_values("date").copy()
    provoked: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
    received: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
    league: dict[str, deque] = defaultdict(lambda: deque(maxlen=window * 20))
    columns = {key: [] for key in ("home_provoked", "away_provoked", "home_rate_shrunk", "away_rate_shrunk", "league_team_yellows")}
    for day, group in data.groupby("date", sort=True):
        for match in group.itertuples(index=False):
            mean = float(np.mean(league[match.league])) if league[match.league] else np.nan
            columns["league_team_yellows"].append(mean)
            for side, team in (("home", match.home_team), ("away", match.away_team)):
                for name, store in (("provoked", provoked), ("rate_shrunk", received)):
                    values = list(store[team])
                    if values and np.isfinite(mean):
                        shrunk = (sum(values) + SHRINK_MATCHES * mean) / (len(values) + SHRINK_MATCHES)
                    else:
                        shrunk = np.nan
                    columns[f"{side}_{name}"].append(shrunk)
        for match in group.itertuples(index=False):
            if np.isfinite(match.home_yellows) and np.isfinite(match.away_yellows):
                provoked[match.home_team].append(match.away_yellows)
                provoked[match.away_team].append(match.home_yellows)
                received[match.home_team].append(match.home_yellows)
                received[match.away_team].append(match.away_yellows)
                league[match.league].extend([match.home_yellows, match.away_yellows])
    for key, values in columns.items():
        data[key] = values
    return data.sort_index()


def split_data(features: pd.DataFrame) -> pd.DataFrame:
    from tools.calibrate import points_data

    data = with_provoked(features)
    data = points_data(data[dataset.usable(data)])
    data = data.dropna(subset=["home_provoked", "away_provoked", "home_rate_shrunk", "away_rate_shrunk",
                               "close_home", "close_draw", "close_away"])
    market = baseline.de_vig(data["close_home"], data["close_draw"], data["close_away"])
    data = data.assign(market_home=market[:, 0], market_away=market[:, 2])
    means = count_means(engine.DEFAULT_COUNT_MODEL, data)
    return data.assign(yellow_mean=means["cards"])


# --- Modello della divisione ------------------------------------------------------------------------

def logit_share(params: SplitParams, data: pd.DataFrame) -> np.ndarray:
    def column(name: str) -> np.ndarray:
        return np.maximum(data[name].to_numpy(float), 0.05)

    home_rate, away_rate = ((column("home_rate_shrunk"), column("away_rate_shrunk")) if params.shrink
                            else (column("home_cards_for"), column("away_cards_for")))
    rate = np.log(home_rate / away_rate)
    value = params.home + params.rate_weight * rate
    if params.provoked_weight:
        value = value + params.provoked_weight * np.log(column("away_provoked") / column("home_provoked"))
    if params.underdog_weight:
        if params.underdog == "mercato":
            underdog = data["market_away"].to_numpy(float) - data["market_home"].to_numpy(float)
        else:
            underdog = (data["away_elo"].to_numpy(float) - data["home_elo"].to_numpy(float)) / 100.0
        value = value + params.underdog_weight * underdog
    if params.referee_weight:
        value = value + params.referee_weight * np.log(column("referee_yellow_avg") / 4.5) * rate
    return value


def share(params: SplitParams, data: pd.DataFrame) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-logit_share(params, data)))


def split_nll(params: SplitParams, data: pd.DataFrame) -> float:
    """Log-verosimiglianza negativa della divisione dei gialli, dato il totale (binomiale, beta-binomiale o Altham)."""
    home = data["home_yellows"].to_numpy(int)
    total = home + data["away_yellows"].to_numpy(int)
    p = np.clip(share(params, data), 1e-6, 1 - 1e-6)
    combinations = gammaln(total + 1) - gammaln(home + 1) - gammaln(total - home + 1)
    if params.balance:
        keep = total <= MAX_YELLOWS
        log_pmf = engine.split_log_pmf(total[keep], p[keep], params.balance)
        return float(-np.mean(log_pmf[np.arange(int(keep.sum())), home[keep]]))
    if params.concentration > 0:
        alpha, beta = params.concentration * p, params.concentration * (1 - p)
        log_lik = combinations + betaln(home + alpha, total - home + beta) - betaln(alpha, beta)
    else:
        log_lik = combinations + home * np.log(p) + (total - home) * np.log(1 - p)
    return float(-np.mean(log_lik))


FREE = {
    "a": ("rate_weight", "provoked_weight"),
    "b": ("underdog_weight",),
    "c": ("home",),
    "d": ("concentration",),
    "d2": ("balance",),
    "e": ("referee_weight",),
}


def fit(params: SplitParams, names: tuple[str, ...], data: pd.DataFrame) -> SplitParams:
    def unpack(vector: np.ndarray) -> SplitParams:
        values = dict(zip(names, vector))
        if "concentration" in values:
            values["concentration"] = float(math.exp(values["concentration"]))
        return replace(params, **values)

    start = [math.log(max(getattr(params, name), 20.0)) if name == "concentration" else getattr(params, name) for name in names]
    result = minimize(lambda vector: split_nll(unpack(vector), data), np.asarray(start, float), method="Nelder-Mead",
                      options={"xatol": 1e-4, "fatol": 1e-7, "maxiter": 4000})
    return unpack(result.x)


# --- Distribuzione dei punti per squadra -----------------------------------------------------------

def points_joint(params: SplitParams, data: pd.DataFrame, count: engine.CountModelParams = engine.DEFAULT_COUNT_MODEL,
                 rule: engine.CardRule = engine.DEFAULT_CARD_RULE) -> np.ndarray:
    """P[n, punti casa, punti ospite] con le stesse funzioni della simulazione (``engine.card_points_joint``)."""
    return engine.card_points_joint(data["yellow_mean"].to_numpy(float), np.clip(share(params, data), 1e-6, 1 - 1e-6),
                                    count, rule, balance=params.balance, concentration=params.concentration)


def observed(data: pd.DataFrame, rule: engine.CardRule = engine.DEFAULT_CARD_RULE) -> tuple[np.ndarray, np.ndarray]:
    home = engine.card_points(data["home_yellows"].to_numpy(int), data["home_reds"].to_numpy(int), rule)
    away = engine.card_points(data["away_yellows"].to_numpy(int), data["away_reds"].to_numpy(int), rule)
    return np.asarray(home, int), np.asarray(away, int)


def market_probabilities(points: np.ndarray) -> dict[str, np.ndarray]:
    """1X2 cartellini e linee per squadra dalla distribuzione congiunta dei punti."""
    width = points.shape[1]
    index = np.arange(width)
    home_wins = (index[:, None] > index[None, :])
    draws = (index[:, None] == index[None, :])
    one = (points * home_wins).sum(axis=(1, 2))
    draw = (points * draws).sum(axis=(1, 2))
    total = points.sum(axis=(1, 2))
    result = {"1x2": np.column_stack([one, draw, total - one - draw]) / total[:, None]}
    home_marginal, away_marginal = points.sum(axis=2), points.sum(axis=1)
    for line in TEAM_LINES:
        result[f"Casa Over {line:g}"] = home_marginal[:, int(line) + 1:].sum(axis=1) / total
        result[f"Ospite Over {line:g}"] = away_marginal[:, int(line) + 1:].sum(axis=1) / total
    return result


def scores(params: SplitParams, data: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Log-loss ed ECE di 1X2 cartellini e delle sei linee per squadra; ``media`` = media sulle sette voci."""
    probabilities = market_probabilities(points_joint(params, data))
    home, away = observed(data)
    outcome = np.where(home > away, 0, np.where(home == away, 1, 2))
    result = {"1X2 cartellini": baseline.summarize(probabilities["1x2"], outcome)}
    for line in TEAM_LINES:
        for side, values in (("Casa", home), ("Ospite", away)):
            key = f"{side} Over {line:g}"
            result[key] = baseline.summarize(baseline.binary(probabilities[key]), (values > line).astype(int))
    result["media"] = {metric: float(np.mean([result[key][metric] for key in result])) for metric in ("log_loss", "ece", "brier")}
    return result


def calibration_rows(params: SplitParams, data: pd.DataFrame, bins: int = 5) -> list[dict]:
    """Previsto/reale per fascia (quantili) di 1, X, 2 cartellini e delle linee per squadra."""
    probabilities = market_probabilities(points_joint(params, data))
    home, away = observed(data)
    targets = {"1 cartellini": (probabilities["1x2"][:, 0], home > away),
               "X cartellini": (probabilities["1x2"][:, 1], home == away),
               "2 cartellini": (probabilities["1x2"][:, 2], home < away)}
    for line in TEAM_LINES:
        targets[f"Casa Over {line:g}"] = (probabilities[f"Casa Over {line:g}"], home > line)
        targets[f"Ospite Over {line:g}"] = (probabilities[f"Ospite Over {line:g}"], away > line)
    rows = []
    for market, (predicted, outcome) in targets.items():
        frame = pd.DataFrame({"p": predicted, "y": outcome.astype(float)})
        for band, group in frame.groupby(pd.qcut(frame["p"].rank(method="first"), bins, labels=False), observed=True):
            rows.append({"mercato": market, "fascia": int(band) + 1, "partite": len(group),
                         "prevista": float(group["p"].mean()), "reale": float(group["y"].mean())})
    return rows


# --- Selezione delle componenti ------------------------------------------------------------------------

def select(data: pd.DataFrame) -> tuple[SplitParams, list[dict]]:
    """Prova a)–e) in ordine sul 2024-26, tiene ciò che migliora log-loss ed ECE medie fuori campione (unione)."""
    train = data[data["season"].isin(dataset.CALIBRATION_SEASONS)]
    outside = data[~data["season"].isin(dataset.CALIBRATION_SEASONS)]
    current = SplitParams()
    current_score = scores(current, outside)["media"]
    steps = [{"passo": "prima (divisione attuale)", "tenuta": True, **_brief(current_score), "parametri": asdict(current)}]
    candidates = [
        ("a) ritmo + provocati, con shrinkage", "a", {"shrink": True}),
        ("b) sfavorita (differenza Elo)", "b", {"underdog": "elo"}),
        ("b) sfavorita (1X2 di mercato senza margine)", "b", {"underdog": "mercato"}),
        ("c) casa/trasferta", "c", {}),
        ("d) fattore comune: divisione più dispersa (beta-binomiale)", "d", {}),
        ("d) fattore comune: bilanciamento (binomiale moltiplicativa)", "d2", {"balance": 0.01}),
        ("e) arbitro sulla divisione", "e", {}),
    ]
    taken = set()
    for label, component, extra in candidates:
        if component in taken or {component, "d", "d2"} <= taken | {component} and taken & {"d", "d2"}:
            continue
        free = tuple(name for key in sorted(taken | {component}) for name in FREE[key])
        candidate = fit(replace(current, **extra), free, train)
        score = scores(candidate, outside)["media"]
        keep = score["log_loss"] < current_score["log_loss"] - 1e-5 and score["ece"] <= current_score["ece"] + 1e-5
        steps.append({"passo": label, "tenuta": keep, **_brief(score), "parametri": asdict(candidate)})
        if keep:
            current, current_score = candidate, score
            taken.add(component)
    return current, steps


def _brief(score: dict) -> dict:
    return {"log_loss": round(score["log_loss"], 5), "ece": round(score["ece"], 5), "brier": round(score["brier"], 5)}


def report(data: pd.DataFrame, chosen: SplitParams, steps: list[dict]) -> str:
    before = SplitParams()
    lines = ["## Cartellini per squadra: divisione tra casa e ospite (fase T)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.card_split`. Totale gialli invariato (fase M); "
             "si modella solo la quota della squadra di casa. Punti Eurobet (giallo 1, rosso 2). Taratura sul 2024-26, "
             "fuori campione 2019-24 e 2026-27 (stesso schema della fase M). Una componente resta accesa solo se "
             "migliora sia la log-loss media sia l'ECE media fuori campione (unione dei due insiemi).", "",
             "### Componenti provate, nell'ordine", "",
             "| Passo | Log-loss media | ECE media | Brier media | Tenuta |", "|---|---|---|---|---|"]
    for step in steps:
        lines.append(f"| {step['passo']} | {step['log_loss']:.5f} | {step['ece']:.5f} | {step['brier']:.5f} | "
                     f"{'sì' if step['tenuta'] else 'no'} |")
    lines += ["", f"Parametri scelti: {json.dumps(asdict(chosen), ensure_ascii=False)}", ""]
    for name, seasons in SETS_OUT.items():
        subset = data[data["season"].isin(seasons)]
        first, after = scores(before, subset), scores(chosen, subset)
        lines += [f"### {name} ({len(subset)} partite): prima / dopo", "",
                  "| Mercato | Log-loss prima | Log-loss dopo | ECE prima | ECE dopo |", "|---|---|---|---|---|"]
        for key in first:
            lines.append(f"| {key} | {first[key]['log_loss']:.4f} | {after[key]['log_loss']:.4f} | "
                         f"{first[key]['ece']:.4f} | {after[key]['ece']:.4f} |")
        lines.append("")
    outside = data[~data["season"].isin(dataset.CALIBRATION_SEASONS)]
    lines += ["### Previsto / reale per fascia (fuori campione, 5 fasce uguali): prima → dopo", "",
              "| Mercato | Fascia | Partite | Prevista prima | Prevista dopo | Reale |", "|---|---|---|---|---|---|"]
    first_rows, after_rows = calibration_rows(before, outside), calibration_rows(chosen, outside)
    for row_before, row_after in zip(first_rows, after_rows):
        lines.append(f"| {row_before['mercato']} | {row_before['fascia']} | {row_before['partite']} | "
                     f"{row_before['prevista']:.1%} | {row_after['prevista']:.1%} | {row_before['reale']:.1%} |")
    return "\n".join(lines) + "\n"


def summary(data: pd.DataFrame, chosen: SplitParams, steps: list[dict]) -> dict:
    outside = data[~data["season"].isin(dataset.CALIBRATION_SEASONS)]
    after = scores(chosen, outside)
    parameters = {key: value for key, value in asdict(chosen).items() if key not in ("shrink", "underdog")}
    return {
        "data": date.today().isoformat(),
        "attiva": chosen != SplitParams(),
        "peso_mercato": 0.8,
        "nota": ("Sfavorita = P(2) − P(1): nello storico dalle quote 1X2 di chiusura senza margine, nell'app dai gol "
                 "simulati (ancorati alle quote quando ci sono). Ritmo e provocati con shrinkage verso la media di "
                 f"lega ({SHRINK_MATCHES:g} partite) nello storico; nell'app i valori del blocco. Peso mercato 0.8 "
                 "dichiarato: nessuna quota cartellini nello storico."),
        "parametri": parameters,
        "scelta_sfavorita": chosen.underdog,
        "passi": [{key: step[key] for key in ("passo", "tenuta", "log_loss", "ece")} for step in steps],
        "ece_fuori_campione": {key: round(value["ece"], 4) for key, value in after.items()},
        "log_loss_fuori_campione": {key: round(value["log_loss"], 4) for key, value in after.items()},
        "partite_fuori_campione": int(len(outside)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, help="File markdown a cui aggiungere la sezione")
    parser.add_argument("--salva", action="store_true", help="Scrive la sezione «divisione_cartellini» in config/goal_model.json")
    args = parser.parse_args()
    data = split_data(dataset.load_features())
    chosen, steps = select(data)
    markdown = report(data, chosen, steps)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva:
        from tools.calibrate import _update_config

        _update_config({"divisione_cartellini": summary(data, chosen, steps)})


if __name__ == "__main__":
    main()
