"""Fase AO, stadio 2: effetto di formazione e assenti sui TIRI e sulla QUALITÀ dei tiri (npxG per tiro), per il motore a eventi.

Per ogni squadra-partita con rosa Understat, la formazione effettiva entra in ``lineup.team_lineup`` (solo gare precedenti) e
dà il rapporto XI atteso / XI tipo dei tiri (r_t) e dell'npxG per tiro (r_q) e la quota di minuti di ruolo mancanti (POR, DIF,
CEN) rispetto all'XI tipo. Stime (quasi-Poisson con offset, errori robusti raggruppati per partita):

- tiri:    log E[tiri]  = offset_t + a + b·casa + γ_t·log r_t + Σ δ_t,ruolo · mancanti_avversario,ruolo
- qualità: log E[npxG] = log tiri + offset_q + a + b·casa + γ_q·log r_q + Σ δ_q,ruolo · mancanti_avversario,ruolo

offset_t = log(tiri dell'XI tipo) + log(tiri concessi dall'avversario / media del campionato), offset_q = log(npxG/tiro
dell'XI tipo) + log(npxG/tiro concesso dall'avversario / media), tutto con le sole gare precedenti. Nessun limite sui
coefficienti: si scrivono i valori stimati con l'intervallo al 95% (``config/giocatori.json`` → ``motore_eventi``).

    nohup python -m tools.ao_giocatori [--salva] > data/cache/ao/giocatori.log &
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import lineup
import players as pl

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "ao"
OUT = ROOT / "docs" / "backtest" / "AO_giocatori.md"
ROLES = ("POR", "DIF", "CEN")
LEAGUES = ("I1", "E0", "D1", "SP1", "F1")
MIN_GAMES = 5


def team_matches(table: pd.DataFrame) -> pd.DataFrame:
    """Una riga per squadra e partita: tiri, npxG, avversario e concessioni medie precedenti (dell'avversario)."""
    agg = (table.groupby(["league", "match_id", "date", "key", "team", "venue"], as_index=False)[["shots", "npxg"]].sum())
    opp = agg[["match_id", "key", "shots", "npxg"]].rename(columns={"key": "opp_key", "shots": "opp_shots", "npxg": "opp_npxg"})
    agg = agg.merge(opp, on="match_id")
    agg = agg[agg["key"] != agg["opp_key"]].sort_values(["date", "match_id"]).reset_index(drop=True)
    # concessioni dell'avversario PRIMA della partita: tiri e npxG fatti contro di lui nelle gare precedenti; media di campionato
    grouped = agg.groupby(["league", "opp_key"])
    agg["c_n"] = grouped.cumcount()
    agg["c_shots_mean"] = grouped["shots"].transform(lambda s: s.shift().expanding().mean())
    agg["c_npxg_mean"] = grouped["npxg"].transform(lambda s: s.shift().expanding().mean())
    league = agg.groupby("league")
    agg["l_shots"] = league["shots"].transform(lambda s: s.shift().expanding().mean())
    agg["l_npxg"] = league["npxg"].transform(lambda s: s.shift().expanding().mean())
    return agg


def compute(store: pl.PlayerStore, refresh: bool = False) -> pd.DataFrame:
    """Rapporti della formazione per squadra-partita (parziali su disco ogni 200 partite, ripresa automatica)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "giocatori_colonne.pkl"
    done = pd.read_pickle(path) if path.exists() and not refresh else pd.DataFrame()
    seen = set(zip(done["match_id"], done["key"])) if len(done) else set()
    table = store.table
    starters = {(m, k): list(g["player"]) for (m, k), g in table[table["starter"]].groupby(["match_id", "key"])}
    keys = table[["league", "match_id", "date", "key"]].drop_duplicates()
    rows, pending = [], 0
    for item in keys.itertuples(index=False):
        if (item.match_id, item.key) in seen:
            continue
        names = starters.get((item.match_id, item.key))
        if not names or len(store.team_rows(item.league, item.key, item.date)["match_id"].unique()) < MIN_GAMES:
            rows.append({"match_id": item.match_id, "key": item.key, "ok": False})
        else:
            data = lineup.team_lineup(store, item.league, item.key, pd.Timestamp(item.date), confirmed=names, light=True)
            if data.get("disponibile"):
                ev = data["eventi"]
                rows.append({"match_id": item.match_id, "key": item.key, "ok": True, "r_shots": ev["rapporto_tiri"],
                             "r_quality": ev["rapporto_qualita"], "base_shots": ev["tiri_xi"] / max(ev["rapporto_tiri"], 1e-9),
                             "base_npxg": data["fattore_attacco"]["npxg_tipo"],
                             **{f"miss_{r}": ev["quota_minuti_mancanti"][r] for r in ROLES}})
            else:
                rows.append({"match_id": item.match_id, "key": item.key, "ok": False})
        pending += 1
        if pending % 200 == 0:
            done = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
            done.to_pickle(path)
            rows = []
            print(f"{len(done)} squadre-partita", flush=True)
    done = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
    done.to_pickle(path)
    return done


def quasi_poisson(x: np.ndarray, y: np.ndarray, offset: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """β per log E[y] = offset + Xβ (equazioni di stima di Poisson, y anche continuo); errori robusti per gruppo."""
    def loss(beta):
        eta = offset + x @ beta
        return float(np.sum(np.exp(eta) - y * eta))

    def grad(beta):
        return x.T @ (np.exp(offset + x @ beta) - y)

    fit = minimize(loss, np.zeros(x.shape[1]), jac=grad, method="BFGS")
    mu = np.exp(offset + x @ fit.x)
    bread = np.linalg.inv(x.T @ (x * mu[:, None]))
    scores = pd.DataFrame(x * (y - mu)[:, None]).groupby(groups).sum().to_numpy()
    meat = scores.T @ scores
    return fit.x, np.sqrt(np.diag(bread @ meat @ bread))


def estimate(frame: pd.DataFrame) -> dict[str, Any]:
    data = frame[frame["ok"] & (frame["c_n"] >= MIN_GAMES) & (frame["base_shots"] > 0) & (frame["base_npxg"] > 0)
                 & (frame["shots"] > 0) & frame["opp_ok"]].copy()
    home = (data["venue"] == "home").to_numpy(float)
    groups = data["match_id"].to_numpy()
    miss_opp = data[[f"opp_miss_{r}" for r in ROLES]].to_numpy(float)
    names = ["intercetta", "casa", "attacco", *(f"difesa_{r}" for r in ROLES)]
    # tiri
    x = np.column_stack([np.ones(len(data)), home, np.log(data["r_shots"].clip(0.2, 5.0)), miss_opp])
    offset = np.log(data["base_shots"]) + np.log(data["c_shots_mean"] / data["l_shots"])
    beta_t, se_t = quasi_poisson(x, data["shots"].to_numpy(float), offset.to_numpy(), groups)
    # qualità (npxG per tiro, dato il numero di tiri)
    x = np.column_stack([np.ones(len(data)), home, np.log(data["r_quality"].clip(0.2, 5.0)), miss_opp])
    base_quality = data["base_npxg"] / data["base_shots"]
    conceded_quality = (data["c_npxg_mean"] / data["c_shots_mean"]) / (data["l_npxg"] / data["l_shots"])
    offset = np.log(data["shots"]) + np.log(base_quality) + np.log(conceded_quality)
    beta_q, se_q = quasi_poisson(x, data["npxg"].to_numpy(float), offset.to_numpy(), groups)

    def block(beta, se):
        return {name: {"stima": round(float(b), 4), "se": round(float(s), 4),
                       "ic95": [round(float(b - 1.96 * s), 4), round(float(b + 1.96 * s), 4)]} for name, b, s in zip(names, beta, se)}

    means = {r: round(float(data[f"opp_miss_{r}"].mean()), 4) for r in ROLES}
    spread = {column: data[column].describe(percentiles=[0.05, 0.5, 0.95]).round(3).to_dict()
              for column in ("r_shots", "r_quality", *(f"opp_miss_{r}" for r in ROLES))}
    return {"squadre_partita": int(len(data)), "partite": int(len(set(groups))), "campionati": sorted(data["league"].unique()),
            "dal": str(pd.Timestamp(data["date"].min()).date()), "al": str(pd.Timestamp(data["date"].max()).date()),
            "tiri": block(beta_t, se_t), "qualita": block(beta_q, se_q), "distribuzione": spread, "media_mancanti": means}


def run(refresh: bool = False) -> dict[str, Any]:
    store = pl.PlayerStore(pl.load_table(LEAGUES, (2025, 2026)))
    columns = compute(store, refresh)
    matches = team_matches(store.table)
    frame = matches.merge(columns, on=["match_id", "key"], how="left")
    frame["ok"] = frame["ok"].fillna(False).astype(bool)
    opp = columns[["match_id", "key", "ok", *(f"miss_{r}" for r in ROLES)]].rename(
        columns={"key": "opp_key", "ok": "opp_ok", **{f"miss_{r}": f"opp_miss_{r}" for r in ROLES}})
    frame = frame.merge(opp, on=["match_id", "opp_key"], how="left")
    frame["opp_ok"] = frame["opp_ok"].fillna(False).astype(bool)
    return estimate(frame)


def render(result: dict[str, Any]) -> str:
    lines = ["# Fase AO – giocatori e formazione nel motore a eventi", "",
             f"Understat, {result['squadre_partita']} squadre-partita ({result['partite']} partite, {', '.join(result['campionati'])}), "
             f"dal {result['dal']} al {result['al']}; solo gare precedenti per tassi, XI tipo e concessioni. Quasi-Poisson con offset, "
             "errori robusti per partita.", ""]
    for title, key in (("Tiri (fase offensiva e difensiva)", "tiri"), ("Qualità: npxG per tiro", "qualita")):
        lines += [f"## {title}", "", "| termine | stima | e.s. | IC 95% |", "|---|---|---|---|"]
        for name, item in result[key].items():
            lines.append(f"| {name} | {item['stima']:+.4f} | {item['se']:.4f} | {item['ic95'][0]:+.4f} … {item['ic95'][1]:+.4f} |")
        lines.append("")
    lines += ["«attacco» = esponente del rapporto XI atteso / XI tipo (tiri o npxG per tiro); «difesa_RUOLO» = effetto sul "
              "logaritmo per quota di minuti di ruolo mancanti nell'AVVERSARIO (1 = tutto il reparto dell'XI tipo assente).",
              "Nel motore entrano i valori stimati così come sono (anche se vicini a zero), con l'intervallo nella scheda.", ""]
    return "\n".join(lines)


def save(result: dict[str, Any], path: Path = ROOT / "config" / "giocatori.json") -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["motore_eventi"] = {
        "nota": "Fase AO: tiri = rapporto_tiri^attacco · exp(Σ difesa_RUOLO·(mancanti avversario − media)); qualità (npxG/tiro) "
                "uguale. "
                "Stimati con python -m tools.ao_giocatori --salva; valori usati come stimati, intervallo nella scheda.",
        "data": date.today().isoformat(), "partite": result["partite"], "campionati": result["campionati"],
        "media_mancanti": result["media_mancanti"],
        **{key: {name: result[key][name] for name in ("attacco", *(f"difesa_{r}" for r in ROLES))} for key in ("tiri", "qualita")},
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    parser.add_argument("--ricomincia", action="store_true")
    args = parser.parse_args()
    result = run(args.ricomincia)
    OUT.write_text(render(result), encoding="utf-8")
    print(render(result))
    if args.salva:
        save(result)


if __name__ == "__main__":
    main()
