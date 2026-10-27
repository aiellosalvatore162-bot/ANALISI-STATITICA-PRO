"""Fase P, punti 3, 5 e 6: incertezza dei parametri, peso del mercato per campionato e tipo, riposo.

Tutti sul campione comune (``tools.v2common``): scelta sul 2024-26, regola severa fuori campione.

- ``--incertezza``: gol attesi (e medie di corner e cartellini) moltiplicati in ogni simulazione per
  exp(σ·Z − σ²/2), Z normale; probabilità calcolate esattamente con la quadratura di Gauss-Hermite.
- ``--peso-mercato``: ancoraggio separato per totale (media geometrica di λ e μ) e supremazia (λ/μ), un peso per
  campionato e tipo stimato sul 2024-26 e riavvicinato a 0,9 con ``SHRINK_MATCHES`` partite fittizie.
- ``--contesto``: giorni di riposo dalla partita di campionato precedente (corti = 3 giorni o meno); le coppe
  non sono nei dati storici e restano escluse (non verificabili).
Uso: ``python -m tools.model_v2 --incertezza|--peso-mercato|--contesto [--salva] [--output ...]``.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import engine
from tools import baseline, dataset, v2common

SIGMAS = (0.0, 0.05, 0.1, 0.15, 0.2, 0.25)
WEIGHTS = tuple(round(value, 2) for value in np.arange(0.5, 1.0001, 0.05))
SHRINK_MATCHES = 1000.0
NODES = 7


def _hermite(nodes: int = NODES) -> tuple[np.ndarray, np.ndarray]:
    x, w = np.polynomial.hermite_e.hermegauss(nodes)
    return x, w / w.sum()


# --- 3. Incertezza ---------------------------------------------------------------------------------------

def goal_mixture_losses(data: pd.DataFrame, sigma: float) -> tuple[np.ndarray, float]:
    lambda_, mu = data["final_lambda"].to_numpy(), data["final_mu"].to_numpy()
    if sigma == 0:
        return v2common.goal_losses(data, lambda_, mu)
    x, w = _hermite()
    rho = float(data["rho"].iloc[0])
    one_x_two, over = np.zeros((len(data), 3)), np.zeros(len(data))
    for xi, wi in zip(x, w):
        for xj, wj in zip(x, w):
            factor_h, factor_a = np.exp(sigma * xi - sigma ** 2 / 2), np.exp(sigma * xj - sigma ** 2 / 2)
            probabilities = v2common.goal_probabilities(lambda_ * factor_h, mu * factor_a, rho)
            one_x_two += wi * wj * probabilities["1x2"]
            over += wi * wj * probabilities["over25"]
    result, observed_over = v2common.outcomes(data)
    loss = (-np.log(np.clip(one_x_two[np.arange(len(result)), result], 1e-12, 1))
            - np.log(np.clip(np.where(observed_over == 1, over, 1 - over), 1e-12, 1)))
    ece = (baseline.expected_calibration_error(one_x_two, result)
           + baseline.expected_calibration_error(baseline.binary(over), observed_over)) / 2
    return loss, ece


def count_mixture_losses(data: pd.DataFrame, sigma: float, kind: str) -> tuple[np.ndarray, float]:
    from tools.calibrate import count_means, count_sf, observed_points, points_sf

    model = engine.DEFAULT_COUNT_MODEL
    means = count_means(model, data)
    x, w = _hermite(9)
    lines = (8.5, 9.5, 10.5) if kind == "corner" else (3.5, 4.5, 5.5)
    if kind == "corner":
        mean = means["corner_home"] + means["corner_away"]
        observed = (data["home_corners"] + data["away_corners"]).to_numpy(int)
    else:
        mean = means["cards"]
        observed = observed_points(data, engine.DEFAULT_CARD_RULE)
    losses, eces = np.zeros(len(data)), []
    for line in lines:
        probability = np.zeros(len(data))
        for xi, wi in zip(x, w) if sigma > 0 else ((0.0, 1.0),):
            factor = np.exp(sigma * xi - sigma ** 2 / 2)
            probability += wi * (count_sf(line, mean * factor, model.corner_dispersion) if kind == "corner" else
                                 points_sf(line, mean * factor, model.card_dispersion, mean * factor * model.card_red_ratio,
                                           engine.DEFAULT_CARD_RULE))
        outcome = (observed > line).astype(int)
        probability = np.clip(probability, 1e-9, 1 - 1e-9)
        losses += -(outcome * np.log(probability) + (1 - outcome) * np.log(1 - probability)) / len(lines)
        eces.append(baseline.expected_calibration_error(baseline.binary(probability), outcome))
    return losses, float(np.mean(eces))


def uncertainty() -> dict:
    data = v2common.frame()
    train = v2common.is_train(data)
    counts = data.dropna(subset=["home_corners", "away_corners", "home_yellows", "away_yellows", "home_reds",
                                 "away_reds", "referee_yellow_avg", "referee_fouls_avg"])
    count_train = v2common.is_train(counts)
    out = {}
    for name, losses, frame, mask in (("gol", goal_mixture_losses, data, train),
                                      ("corner", lambda d, s: count_mixture_losses(d, s, "corner"), counts, count_train),
                                      ("cartellini", lambda d, s: count_mixture_losses(d, s, "cartellini"), counts, count_train)):
        grid = {sigma: float(losses(frame[mask], sigma)[0].mean()) for sigma in SIGMAS}
        best = min(grid, key=grid.get)
        test = frame[~mask]
        reference = losses(test, 0.0)
        verdict = v2common.strict(reference, losses(test, best)) if best > 0 else \
            {**v2common.strict(reference, reference), "tenuta": False}
        # Per confronto: σ = 0.1 imposto, anche quando la taratura sceglie 0.
        forced = v2common.strict(reference, losses(test, 0.1))
        out[name] = {"griglia": grid, "sigma": best, **verdict, "imposto": forced}
    return out


def render_uncertainty(result: dict) -> str:
    lines = ["## Incertezza dei parametri (fase P, punto 3)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.model_v2 --incertezza`. In ogni simulazione "
             "la media (gol di ciascuna squadra; corner totali; gialli e rossi) è moltiplicata per exp(σZ − σ²/2): stessa "
             "media, più dispersione. σ scelto sul 2024-26 (griglia " + ", ".join(f"{s:g}" for s in SIGMAS) + "), verifica "
             "fuori campione con la regola severa (gol: 1X2 + Over/Under 2.5; corner: Over 8.5-10.5; cartellini in punti: "
             "Over 3.5-5.5).", "", *v2common.TABLE_HEADER]
    for name, row in result.items():
        lines.append(v2common.row_text(f"{name}, σ scelto = {row['sigma']:g}", row))
        lines.append(v2common.row_text(f"{name}, σ = 0.1 imposto (confronto)", {**row["imposto"], "tenuta": False}))
    lines += ["", "Log-loss sul 2024-26 per σ:", "", "| Mercati | " + " | ".join(f"σ = {s:g}" for s in SIGMAS) + " |",
              "|---|" + "---|" * len(SIGMAS)]
    for name, row in result.items():
        lines.append(f"| {name} | " + " | ".join(f"{row['griglia'][s]:.4f}" for s in SIGMAS) + " |")
    lines.append("")
    return "\n".join(lines)


# --- 5. Peso del mercato per campionato e tipo -----------------------------------------------------------

def split_anchor(data: pd.DataFrame, weight_total, weight_supremacy) -> tuple[np.ndarray, np.ndarray]:
    lambda_, mu, *_ = engine.anchor_goal_rates_split(
        data["model_lambda"].to_numpy(), data["model_mu"].to_numpy(), data["market_lambda"].to_numpy(),
        data["market_mu"].to_numpy(), engine.DEFAULT_MARKET_ANCHOR, np.asarray(weight_total, float),
        np.asarray(weight_supremacy, float))
    return np.asarray(lambda_, float), np.asarray(mu, float)


def market_weights() -> dict:
    data = v2common.frame()
    train = v2common.is_train(data)
    base_weight = engine.DEFAULT_MARKET_ANCHOR.market_weight
    weights = {}
    for league in sorted(data["league"].unique()):
        subset = data[train & (data["league"] == league)]
        best, best_loss = (base_weight, base_weight), np.inf
        for total in WEIGHTS:
            for supremacy in WEIGHTS:
                loss = v2common.goal_losses(subset, *split_anchor(subset, total, supremacy))[0].mean()
                if loss < best_loss:
                    best, best_loss = (total, supremacy), loss
        n = len(subset)
        shrunk = tuple(round((n * value + SHRINK_MATCHES * base_weight) / (n + SHRINK_MATCHES), 3) for value in best)
        weights[league] = {"totale": shrunk[0], "supremazia": shrunk[1], "stima_totale": best[0],
                           "stima_supremazia": best[1], "partite": n}
    test = data[~train]
    total = test["league"].map(lambda league: weights[league]["totale"]).to_numpy()
    supremacy = test["league"].map(lambda league: weights[league]["supremazia"]).to_numpy()
    before = v2common.goal_losses(test, *v2common.anchored(test, test["model_lambda"], test["model_mu"]))
    after = v2common.goal_losses(test, *split_anchor(test, total, supremacy))
    return {"pesi": weights, **v2common.strict(before, after)}


def render_market_weights(result: dict) -> str:
    lines = ["## Peso del mercato per campionato e tipo (fase P, punto 5)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.model_v2 --peso-mercato`. Ancoraggio separato del "
             "totale gol (media geometrica di λ e μ) e della supremazia (λ/μ); peso per campionato stimato sul 2024-26 "
             f"(griglia 0,50-1,00) e riavvicinato a {engine.DEFAULT_MARKET_ANCHOR.market_weight} con "
             f"{SHRINK_MATCHES:g} partite fittizie. Corner e cartellini: nessuna quota storica, peso non stimabile "
             "(resta 0,8 dichiarato).", "",
             "| Campionato | Partite 2024-26 | Totale: stima → usato | Supremazia: stima → usato |", "|---|---|---|---|"]
    for league, row in result["pesi"].items():
        lines.append(f"| {league} | {row['partite']} | {row['stima_totale']} → {row['totale']} | "
                     f"{row['stima_supremazia']} → {row['supremazia']} |")
    lines += ["", *v2common.TABLE_HEADER, v2common.row_text("pesi per campionato e tipo", result), ""]
    return "\n".join(lines)


# --- 6. Riposo ------------------------------------------------------------------------------------------

def rest_days(data: pd.DataFrame) -> pd.DataFrame:
    """Giorni dalla partita di campionato precedente di ciascuna squadra (nan alla prima della serie)."""
    raw = dataset.load_raw()
    long = pd.concat([raw[["league", "date", "home_team"]].rename(columns={"home_team": "team"}),
                      raw[["league", "date", "away_team"]].rename(columns={"away_team": "team"})]).drop_duplicates()
    long = long.sort_values(["league", "team", "date"])
    long["rest"] = long.groupby(["league", "team"])["date"].diff().dt.days
    lookup = long.set_index(["league", "team", "date"])["rest"]
    out = pd.DataFrame(index=data.index)
    for side in ("home", "away"):
        keys = list(zip(data["league"], data[f"{side}_team"], data["date"]))
        out[side] = lookup.reindex(keys).to_numpy()
    return out


def rest_factors(rest: pd.DataFrame, theta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """θ = (effetto per giorno di riposo in più, fino a 7; effetto del riposo corto ≤ 3 giorni)."""
    home = np.clip(rest["home"].fillna(7).to_numpy(), 2, 7)
    away = np.clip(rest["away"].fillna(7).to_numpy(), 2, 7)
    short_home, short_away = (home <= 3).astype(float), (away <= 3).astype(float)
    difference = (home - away) / 7.0
    factor_home = np.exp(theta[0] * difference + theta[1] * (short_away - short_home))
    return factor_home, 1.0 / factor_home


def context() -> dict:
    data = v2common.frame()
    train = v2common.is_train(data)
    rest = rest_days(data)

    def loss(theta, mask):
        factor_home, factor_away = rest_factors(rest[mask], theta)
        subset = data[mask]
        return v2common.goal_losses(subset, subset["final_lambda"].to_numpy() * factor_home,
                                    subset["final_mu"].to_numpy() * factor_away)

    fitted = minimize(lambda theta: loss(theta, train)[0].mean(), np.zeros(2), method="L-BFGS-B",
                      bounds=[(-0.3, 0.3), (-0.3, 0.3)])
    theta = fitted.x
    verdict = v2common.strict(loss(np.zeros(2), ~train), loss(theta, ~train))
    short = ((rest["home"] <= 3) | (rest["away"] <= 3)).mean()
    return {"theta": [float(value) for value in theta], "riposo_corto": float(short), **verdict}


def render_context(result: dict) -> str:
    return "\n".join([
        "## Contesto: giorni di riposo (fase P, punto 6)", "",
        f"Generato il {date.today():%d/%m/%Y} con `python -m tools.model_v2 --contesto`. Riposo dalla partita di "
        "campionato precedente (2-7 giorni), effetto dopo l'ancoraggio al mercato: gol attesi casa × exp(a·(riposo casa − "
        f"riposo ospite)/7 + b·(corto ospite − corto casa)). Stima sul 2024-26: a = {result['theta'][0]:+.3f}, "
        f"b = {result['theta'][1]:+.3f}; partite con almeno una squadra a riposo corto: {result['riposo_corto']:.1%}. "
        "Le partite di coppa nei 4 giorni precedenti non sono nei dati storici (football-data.co.uk ha solo il "
        "campionato): non verificabili, escluse.", "",
        *v2common.TABLE_HEADER, v2common.row_text("riposo", result), ""])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--incertezza", action="store_true")
    parser.add_argument("--peso-mercato", action="store_true")
    parser.add_argument("--contesto", action="store_true")
    parser.add_argument("--salva", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    from tools.calibrate import _update_config

    sections, texts = {}, []
    if args.incertezza:
        result = uncertainty()
        texts.append(render_uncertainty(result))
        sections["incertezza_parametri"] = {
            "data": date.today().isoformat(),
            "attiva": any(row["tenuta"] for row in result.values()),
            "sigma": {name: (row["sigma"] if row["tenuta"] else 0.0) for name, row in result.items()},
            "verifica": {name: {key: round(value, 6) if isinstance(value, float) else value
                                for key, value in row.items() if key not in ("griglia", "imposto")} for name, row in result.items()}}
    if args.peso_mercato:
        result = market_weights()
        texts.append(render_market_weights(result))
        sections["peso_mercato_campionato"] = {
            "data": date.today().isoformat(), "attiva": result["tenuta"], "pesi": result["pesi"],
            "verifica": {key: round(value, 6) if isinstance(value, float) else value for key, value in result.items()
                         if key != "pesi"}}
    if args.contesto:
        result = context()
        texts.append(render_context(result))
        sections["contesto_riposo"] = {
            "data": date.today().isoformat(), "attiva": result["tenuta"],
            "parametri": {"per_giorno": round(result["theta"][0], 5), "riposo_corto": round(result["theta"][1], 5)},
            "verifica": {key: round(value, 6) if isinstance(value, float) else value for key, value in result.items()
                         if key != "theta"}}
    markdown = "\n".join(texts)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva and sections:
        _update_config(sections)


if __name__ == "__main__":
    main()
