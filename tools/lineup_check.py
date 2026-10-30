"""Verifica e stime della fase AL sullo storico delle formazioni (Understat, banco della fase AD).

Per ogni partita con rosa Understat, la formazione effettiva (come sarebbe nota poco prima del fischio) entra in
``lineup.team_lineup`` con minuti attesi, tassi e fattori calcolati SOLO con le gare precedenti. Si confrontano i gol attesi
del modello senza fattori (= XI tipo) con quelli moltiplicati per il fattore attacco (e, se stimato, difesa) su 1X2 e
Over/Under gol; differenza di log-loss appaiata con errore standard. Stime (solo sul periodo di taratura, fino al 31/12/2025,
verifica dal 01/01/2026):

- intervallo storico del fattore attacco (1° e 99° percentile): unico limite, contro i valori esorbitanti;
- pesi per ruolo della difesa: regressione di Poisson dei gol subiti (offset = gol attesi del modello) sulla quota di minuti di
  ruolo dell'XI tipo che mancano, con penalità ridge; applicati solo se positivi e con z ≥ 2, altrimenti solo etichetta;
- k dello shrinkage di «sta performando»: regressione senza intercetta della differenza gol−npxG nella seconda metà delle
  gare su quella della prima (β), k = x̄·(1−β)/β.

Lo storico dei giocatori copre solo il 2025/26 e il 2026/27 (cache ``tools.player_data``): le prime giornate del 2025/26
hanno poco passato e usano i tassi di ruolo (avviso dichiarato in ``docs/backtest/AL_giocatori.md``).

    python -m tools.lineup_check [--campionati I1 E0 D1 SP1] [--stagioni 2526 2627] [--salva]
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import lineup
import players as pl
from datasources.names import canonical_key
from tools import backtest_wf, baseline

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "backtest" / "AL_giocatori.md"
CACHE = ROOT / "data" / "cache" / "ad"
SPLIT = pd.Timestamp("2026-01-01")
RIDGE = 5.0
MARKETS = ("1X2", "Over 1.5 gol", "Over 2.5 gol", "Over 3.5 gol", "GG", "Casa Over 0.5 gol", "Ospite Over 0.5 gol",
           "Casa Over 1.5 gol", "Ospite Over 1.5 gol")


def _match_ids(table: pd.DataFrame) -> dict[tuple, str]:
    home = table[table["venue"] == "home"].drop_duplicates("match_id")
    return {(row.date, row.key): row.match_id for row in home.itertuples()}


def _starters(table: pd.DataFrame) -> dict[tuple[str, str], list[str]]:
    started = table[table["starter"]]
    return {(match_id, team): list(group["player"]) for (match_id, team), group in started.groupby(["match_id", "team"])}


def compute_columns(features: pd.DataFrame, store: pl.PlayerStore, seasons: Sequence[str], refresh: bool = False) -> pd.DataFrame:
    """Fattori della formazione effettiva per ogni partita di prova con rosa Understat (cache su disco)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"formazioni_{backtest_wf._slug(sorted(features['league'].unique()), sorted(seasons), len(features))}.pkl"
    if path.exists() and not refresh:
        return pd.read_pickle(path)
    table = store.table
    ids, starters = _match_ids(table), _starters(table)
    rows = []
    test = features[features["season"].isin(seasons) & features["league"].isin(pl.UNDERSTAT_LEAGUES)]
    for row in test.itertuples():
        when = pd.Timestamp(row.date).normalize()
        match_id = None
        for shift in (0, -1, 1):
            match_id = ids.get((when + pd.Timedelta(days=shift), canonical_key(row.home_team)))
            if match_id:
                break
        if not match_id:
            continue
        sides = {}
        for side, team in (("home", row.home_team), ("away", row.away_team)):
            key = canonical_key(team)
            names = starters.get((match_id, table.loc[(table["match_id"] == match_id) & (table["key"] == key), "team"].iloc[0]), []) \
                if ((table["match_id"] == match_id) & (table["key"] == key)).any() else []
            data = lineup.team_lineup(store, row.league, key, when, confirmed=names or None, light=True)
            if not data.get("disponibile"):
                break
            sides[side] = data
        if len(sides) < 2:
            continue
        record = {"index": row.Index}
        for side, data in sides.items():
            record[f"{side}_lu_attack"] = data["fattore_attacco"]["valore"]
            record[f"{side}_games"] = data["fattore_attacco"]["campione"]
            for role, value in data["fattore_difesa"]["quota_minuti_mancanti"].items():
                record[f"{side}_miss_{role}"] = value
        rows.append(record)
    result = pd.DataFrame(rows).set_index("index")
    result.to_pickle(path)
    return result


def _poisson_fit(x: np.ndarray, goals: np.ndarray, rate: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """β della regressione di Poisson con offset log(rate) e penalità ridge; errori standard dalla matrice d'informazione."""
    def loss(beta):
        eta = x @ beta
        return float(np.sum(rate * np.exp(eta) - goals * eta) + RIDGE * np.sum(beta ** 2))

    fit = minimize(loss, np.zeros(x.shape[1]), method="BFGS")
    mu = rate * np.exp(x @ fit.x)
    information = x.T @ (x * mu[:, None]) + 2 * RIDGE * np.eye(x.shape[1])
    return fit.x, np.sqrt(np.diag(np.linalg.inv(information)))


def estimate_defense(frame: pd.DataFrame, lam: np.ndarray, mu: np.ndarray) -> dict[str, Any]:
    """Pesi per ruolo: gol subiti dalla squadra sulla quota di minuti di ruolo mancanti, offset = gol attesi."""
    roles = ("POR", "DIF", "CEN")
    # la squadra di casa subisce i gol «away» (mu), l'ospite subisce quelli «home» (lam)
    x = np.vstack([frame[[f"home_miss_{r}" for r in roles]].to_numpy(), frame[[f"away_miss_{r}" for r in roles]].to_numpy()])
    goals = np.concatenate([frame["away_goals"].to_numpy(float), frame["home_goals"].to_numpy(float)])
    rate = np.concatenate([mu, lam])
    beta, se = _poisson_fit(x, goals, rate)
    weights = {role: (float(b) if b > 0 and b / s >= 2.0 else 0.0) for role, b, s in zip(roles, beta, se)}
    return {"beta": dict(zip(roles, map(float, beta))), "se": dict(zip(roles, map(float, se))),
            "z": dict(zip(roles, map(float, beta / se))), "pesi_applicati": weights, "partite_squadra": int(len(goals))}


def estimate_performing(store: pl.PlayerStore, min_matches: int = 15) -> dict[str, Any]:
    """β e k dello shrinkage: differenza gol−npxG della seconda metà delle gare spiegata da quella della prima."""
    table = store.table
    out = {}
    for label, group_cols, min_n in (("giocatore", ["player_id"], min_matches), ("squadra", ["league", "key"], 10)):
        first, second, mass = [], [], []
        for _, group in table[table["minutes"] > 0].groupby(group_cols):
            group = group.sort_values(["date", "match_id"])
            if group["match_id"].nunique() < min_n * 2:
                continue
            ids = list(dict.fromkeys(group["match_id"]))
            half = len(ids) // 2
            a, b = group[group["match_id"].isin(ids[:half])], group[group["match_id"].isin(ids[half:])]
            first.append(float((a["goals"] - a["pen_goals"] - a["npxg"]).sum()))
            second.append(float((b["goals"] - b["pen_goals"] - b["npxg"]).sum()))
            mass.append(float(a["npxg"].sum()))
        first, second, mass = np.array(first), np.array(second), np.array(mass)
        beta = float(np.sum(first * second) / np.sum(first ** 2)) if len(first) and np.sum(first ** 2) > 0 else 0.0
        k = float(np.mean(mass) * (1 - beta) / beta) if beta > 0.02 else 1000.0
        out[label] = {"unita": int(len(first)), "beta": round(beta, 4), "x_medio": round(float(np.mean(mass)), 2) if len(mass) else None,
                      "k": round(min(k, 1000.0), 2)}
    return out


def evaluate(frame: pd.DataFrame, sub: pd.DataFrame, base: dict, after: dict) -> pd.DataFrame:
    tables = {"prima": backtest_wf.market_table(sub, base), "dopo": backtest_wf.market_table(sub, after)}
    rows = []
    for scope_name, scope in (("taratura (fino al 31/12/2025)", (sub["date"] < SPLIT).to_numpy()),
                              ("verifica (dal 01/01/2026)", (sub["date"] >= SPLIT).to_numpy()), ("tutte", np.ones(len(sub), bool))):
        for market in MARKETS:
            probability_a, outcome, mask = tables["prima"][market]
            probability_b = tables["dopo"][market][0]
            ok = scope & mask
            if ok.sum() < 30:
                continue
            delta = backtest_wf._losses(probability_b[ok], outcome[ok]) - backtest_wf._losses(probability_a[ok], outcome[ok])
            rows.append({"ambito": scope_name, "mercato": market, "n": int(ok.sum()),
                         "log_loss_prima": baseline.summarize(probability_a[ok], outcome[ok])["log_loss"],
                         "log_loss_dopo": baseline.summarize(probability_b[ok], outcome[ok])["log_loss"],
                         "ece_prima": baseline.summarize(probability_a[ok], outcome[ok])["ece"],
                         "ece_dopo": baseline.summarize(probability_b[ok], outcome[ok])["ece"],
                         "differenza": float(delta.mean()), "errore_standard": float(delta.std(ddof=1) / np.sqrt(len(delta)))})
    return pd.DataFrame(rows)


def run(campionati: Sequence[str] = ("I1", "E0", "D1", "SP1"), stagioni: Sequence[str] = ("2526", "2627"),
        refresh: bool = False) -> dict[str, Any]:
    features, _ = backtest_wf.prepare(campionati, stagioni, refresh)
    store = pl.PlayerStore(pl.load_table(campionati, (2025, 2026)))
    columns = compute_columns(features, store, stagioni, refresh)
    sub = features.loc[columns.index].join(columns)
    base = backtest_wf.predict(sub, backtest_wf.ATTUALE)
    lam, mu = base["lambda"], base["mu"]
    training = (sub["date"] < SPLIT).to_numpy()
    percentiles = (float(np.percentile(np.concatenate([sub.loc[training, "home_lu_attack"], sub.loc[training, "away_lu_attack"]]), 1)),
                   float(np.percentile(np.concatenate([sub.loc[training, "home_lu_attack"], sub.loc[training, "away_lu_attack"]]), 99)))
    attack_home = np.clip(sub["home_lu_attack"].to_numpy(), *percentiles)
    attack_away = np.clip(sub["away_lu_attack"].to_numpy(), *percentiles)
    # esponente: log λ = log λ0 + γ·log f  (regressione di Poisson sul periodo di taratura, penalità ridge)
    x_all = np.concatenate([np.log(attack_home), np.log(attack_away)])[:, None]
    goals_all = np.concatenate([sub["home_goals"].to_numpy(float), sub["away_goals"].to_numpy(float)])
    rate_all = np.concatenate([lam, mu])
    train_all = np.concatenate([training, training])
    gamma_fit, gamma_se = _poisson_fit(x_all[train_all], goals_all[train_all], rate_all[train_all])
    gamma = float(max(gamma_fit[0], 0.0))
    full_factor = evaluate(sub, sub, base, dict(base, **{"lambda": np.clip(lam * attack_home, 0.05, 5.0),
                                                         "mu": np.clip(mu * attack_away, 0.05, 5.0)}))      # γ = 1, non usato
    attack_home, attack_away = attack_home ** gamma, attack_away ** gamma
    after_attack = dict(base, **{"lambda": np.clip(lam * attack_home, 0.05, 5.0), "mu": np.clip(mu * attack_away, 0.05, 5.0)})
    attack_only = evaluate(sub, sub, base, after_attack)
    # difesa: pesi stimati sul periodo di taratura (gol attesi già con il fattore attacco), verifica dopo
    after_for_fit = (lam * attack_home, mu * attack_away)
    defense = estimate_defense(sub[training], after_for_fit[0][training], after_for_fit[1][training])
    weights = defense["pesi_applicati"]
    roles = ("POR", "DIF", "CEN")
    defense_home = np.exp(sum(weights[r] * sub[f"home_miss_{r}"].to_numpy() for r in roles))     # su mu (gol dell'ospite)
    defense_away = np.exp(sum(weights[r] * sub[f"away_miss_{r}"].to_numpy() for r in roles))     # su lam
    after_full = dict(base, **{"lambda": np.clip(lam * attack_home * defense_away, 0.05, 5.0),
                               "mu": np.clip(mu * attack_away * defense_home, 0.05, 5.0)})
    full = evaluate(sub, sub, base, after_full)
    performing = estimate_performing(store)
    return {"partite": len(sub), "campionati": list(campionati), "stagioni": list(stagioni), "limiti_attacco": percentiles, "esponente": {"valore": gamma, "grezzo": float(gamma_fit[0]), "se": float(gamma_se[0])},
            "solo_attacco": attack_only, "fattore_pieno": full_factor, "completo": full, "difesa": defense, "performando": performing,
            "distribuzione": sub[["home_lu_attack", "away_lu_attack"]].stack().describe(percentiles=[0.01, 0.05, 0.5, 0.95, 0.99]).round(4).to_dict(),
            "inizio_dati": str(store.table["date"].min().date())}


def render(result: dict[str, Any]) -> str:
    def table(frame: pd.DataFrame) -> list[str]:
        lines = ["| Ambito | Mercato | N | Log-loss prima → dopo | ECE prima → dopo | Differenza ± e.s. |", "|---|---|---|---|---|---|"]
        for r in frame.itertuples():
            lines.append(f"| {r.ambito} | {r.mercato} | {r.n} | {r.log_loss_prima:.4f} → {r.log_loss_dopo:.4f} | "
                         f"{r.ece_prima:.4f} → {r.ece_dopo:.4f} | {r.differenza:+.5f} ± {r.errore_standard:.5f} |")
        return lines

    defense = result["difesa"]
    lines = [f"# Formazioni e giocatori (fase AL): verifica sullo storico", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.lineup_check`. Campionati {', '.join(result['campionati'])}, "
             f"stagioni {', '.join(result['stagioni'])}, {result['partite']} partite con rosa Understat. Storico giocatori disponibile "
             f"dal {result['inizio_dati']} (cache `tools.player_data`: 2025/26 e 2026/27): le prime giornate del 2025/26 hanno poco passato "
             "e usano i tassi di ruolo.", "",
             "**Cosa si confronta.** Gol attesi del modello senza fattori (= XI tipo) contro gli stessi moltiplicati per il fattore della "
             "FORMAZIONE EFFETTIVA (come sarebbe nota poco prima del fischio d'inizio; minuti attesi e tassi solo dal passato). "
             "Non è una previsione a più giorni: vale solo se la formazione è nota al momento della giocata. Previsioni del solo modello "
             "(non ancorato); differenza = dopo − prima (negativa = migliora).", "",
             f"Intervallo storico del fattore attacco (1°-99° percentile, periodo di taratura): "
             f"{result['limiti_attacco'][0]:.3f}-{result['limiti_attacco'][1]:.3f}.",
             f"Esponente del fattore attacco (elasticità dei gol attesi alla produzione npxG+xA, stimato nel periodo di taratura): "
             f"γ = {result['esponente']['grezzo']:.3f} ± {result['esponente']['se']:.3f} (usato: {result['esponente']['valore']:.3f}; "
             "l'1 vorrebbe dire che i gol seguono la produzione 1 a 1, ma npxG+xA conta due volte ogni occasione).", "",
             "## Solo fattore attacco (con l'esponente stimato)", ""] + table(result["solo_attacco"]) + [
             "", "## Per confronto: fattore PIENO (γ = 1), non usato", "",
             "Se i gol seguissero la produzione 1 a 1 (come nelle assenze della Fase P), questo sarebbe l'effetto sul modello senza ancoraggio:", ""] \
        + table(result["fattore_pieno"][result["fattore_pieno"]["ambito"] == "tutte"]) + [
             "", "## Attacco + difesa per ruolo", ""] + table(result["completo"]) + [
             "", "## Pesi della difesa per ruolo (stimati nel periodo di taratura)", "",
             "| Ruolo | β | e.s. | z | Peso applicato |", "|---|---|---|---|---|"]
    for role in ("POR", "DIF", "CEN"):
        lines.append(f"| {role} | {defense['beta'][role]:+.4f} | {defense['se'][role]:.4f} | {defense['z'][role]:+.2f} | "
                     f"{defense['pesi_applicati'][role]:.4f} |")
    lines += ["", "Regola: peso applicato solo se β > 0 e z ≥ 2; altrimenti la difesa è SOLO ETICHETTA (dichiarato in scheda).", "",
              "## «Sta performando»: shrinkage di gol−npxG", "", "| Unità | N | β (2ª metà su 1ª) | npxG medio 1ª metà | k stimato |", "|---|---|---|---|---|"]
    for label, item in result["performando"].items():
        lines.append(f"| {label} | {item['unita']} | {item['beta']} | {item['x_medio']} | {item['k']} |")
    lines += ["", "β piccolo = la fortuna in finalizzazione quasi non si ripete: lo shrinkage è forte (k grande)."]
    return "\n".join(lines) + "\n"


def save(result: dict[str, Any], path: Path = ROOT / "config" / "giocatori.json") -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    stamp = {"data": date.today().isoformat(), "partite": result["partite"], "campionati": result["campionati"]}
    data["fattore_attacco"]["limiti"] = [round(value, 4) for value in result["limiti_attacco"]]
    data["fattore_attacco"]["esponente"] = round(result["esponente"]["valore"], 4)
    data["fattore_attacco"]["stimato"] = {**stamp, "esponente_grezzo": round(result["esponente"]["grezzo"], 4),
                                           "errore_standard": round(result["esponente"]["se"], 4)}
    defense = result["difesa"]
    data["difesa"]["pesi_ruolo"] = {role: round(defense["pesi_applicati"][role], 5) for role in ("POR", "DIF", "CEN")}
    data["difesa"]["stimato"] = {**stamp, "z": {r: round(v, 2) for r, v in defense["z"].items()}}
    data["performando"]["k_xg"] = result["performando"]["giocatore"]["k"]
    data["performando"]["k_xg_squadra"] = result["performando"]["squadra"]["k"]
    data["performando"]["stimato"] = {**stamp, "beta": {k: v["beta"] for k, v in result["performando"].items()}}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--campionati", nargs="+", default=["I1", "E0", "D1", "SP1"])
    parser.add_argument("--stagioni", nargs="+", default=["2526", "2627"])
    parser.add_argument("--salva", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", default=str(OUT))
    args = parser.parse_args()
    result = run(args.campionati, args.stagioni, args.refresh)
    Path(args.output).write_text(render(result), encoding="utf-8")
    if args.salva:
        save(result)
    print(render(result))


if __name__ == "__main__":
    main()
