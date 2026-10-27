"""Fase P, punti 2 e 7b: verifica di assenze pesate e marcatori sullo storico partita per partita (Understat).

Dati: ``python -m tools.player_data 2025 2026`` (cache locale). Per ogni partita, in ordine di data, le statistiche
dei giocatori sono quelle della stagione fino alla partita precedente (niente dati futuri). Gol attesi delle
squadre: quelli finali ancorati alle quote di chiusura (``tools.v2common``), per Premier, Liga, Serie A e
Bundesliga (la Ligue 1 non ha quote nel campione e serve solo per i riferimenti di ruolo).

- Marcatori (7b): P(segna) = 1 − exp(−gol attesi della squadra · quota · minuti attesi / 90) (assottigliamento di
  Poisson), minuti attesi = minuti medi per presenza fino a quel momento, solo giocatori scesi in campo (come la
  tabella dell'app senza titolari confermati). Versione attuale (xG con rigori, quota a priori unica) contro v2
  (npxG, riferimento per ruolo, rigorista). Parametri v2 stimati sulle partite fino al 31/12/2025, verifica dal
  01/01/2026 (seconda metà 2025/26 e 2026/27). «Verificato» = v2 migliore con la regola severa ED ECE fuori
  campione ≤ ``ECE_VERIFIED``.
- Assenze (2): titolari abituali (almeno metà dei minuti della squadra, dopo 5 partite) non in distinta = assenti;
  fattore di ``absences.absence_factor`` sui gol attesi finali; regola severa su 1X2 + Over/Under 2.5.
Uso: ``python -m tools.player_check [--salva] [--output docs/BASELINE.md]``.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import absences
from tools import baseline, v2common
from tools.minute_data import LEAGUES
from tools.player_data import load

SEASONS = (2025, 2026)
CODES = {"EPL": "E0", "La_liga": "SP1", "Bundesliga": "D1", "Serie_A": "I1"}
SPLIT = pd.Timestamp("2026-01-01")
MIN_MINUTES = 90
ECE_VERIFIED = 0.015
ROLES = absences.ROLES


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def records() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    """(righe giocatore-partita per i marcatori, righe squadra-partita per le assenze, produzione per ruolo)."""
    matches = sorted((row for league in LEAGUES for season in SEASONS for row in load(league, season)),
                     key=lambda row: row["date"])
    players: dict = defaultdict(lambda: defaultdict(lambda: {"minutes": 0.0, "apps": 0, "xg": 0.0, "npxg": 0.0, "xa": 0.0,
                                                             "pen_goals": 0, "roles": Counter()}))
    teams: dict = defaultdict(lambda: {"games": 0, "xg": 0.0, "npxg": 0.0})
    scorer_rows, absence_rows = [], []
    role_minutes, role_production = Counter(), Counter()
    for match in matches:
        penalties = defaultdict(float)
        penalty_goals = Counter()
        for shot in match.get("penalties", []):
            penalties[shot["player_id"]] += _f(shot["xG"])
            penalty_goals[shot["player_id"]] += shot.get("result") == "Goal"
        sides = {"h": match["home"], "a": match["away"]}
        for side, team in sides.items():
            key = (match["league"], match["season"], team)
            squad, state = players[key], teams[key]
            lineup = [player for player in match["players"] if player["side"] == side]
            appeared = {player["player_id"] for player in lineup if _f(player["time"]) > 0}
            base = {"league": match["league"], "season": match["season"], "date": pd.Timestamp(match["date"]),
                    "team": team, "side": side, "home": match["home"], "away": match["away"], "team_games": state["games"]}
            if state["games"] >= 1:
                taker = max(squad, key=lambda pid: squad[pid]["pen_goals"], default=None)
                taker = taker if taker is not None and squad[taker]["pen_goals"] > 0 else None
                for player in lineup:
                    stats = squad.get(player["player_id"])
                    role = absences.role_of(stats["roles"].most_common(1)[0][0]) if stats and stats["roles"] else None
                    if stats is None or role is None or stats["minutes"] < MIN_MINUTES or _f(player["time"]) <= 0:
                        continue
                    scorer_rows.append({**base, "player": player["player"], "role": role, "minutes": stats["minutes"],
                                        "apps": stats["apps"], "xg": stats["xg"], "npxg": stats["npxg"],
                                        "taker": player["player_id"] == taker, "team_xg": state["xg"],
                                        "team_npxg": state["npxg"], "scored": int(_f(player["goals"]) > 0)})
            if state["games"] >= 5:
                squad_list = [absences.SquadPlayer(pid, absences.role_of(stats["roles"].most_common(1)[0][0]) if stats["roles"] else None,
                                                   stats["minutes"], stats["npxg"], stats["xa"]) for pid, stats in squad.items()]
                regulars = [pid for pid, stats in squad.items()
                            if stats["minutes"] >= 0.5 * 90 * state["games"] and absences.role_of(
                                stats["roles"].most_common(1)[0][0] if stats["roles"] else "GK")]
                missing = [pid for pid in regulars if pid not in appeared and pid not in {p["player_id"] for p in lineup}]
                factor, _ = absences.absence_factor(squad_list, missing, state["games"])
                absence_rows.append({**base, "absent": len(missing), "factor": factor})
            # Aggiornamento dopo la partita.
            for player in lineup:
                minutes = _f(player["time"])
                if minutes <= 0:
                    continue
                stats = squad[player["player_id"]]
                xg = _f(player["xG"])
                npxg = max(0.0, xg - penalties.get(player["player_id"], 0.0))
                stats["minutes"] += minutes
                stats["apps"] += 1
                stats["xg"] += xg
                stats["npxg"] += npxg
                stats["xa"] += _f(player["xA"])
                stats["pen_goals"] += penalty_goals.get(player["player_id"], 0)
                if player["position"] != "Sub":
                    stats["roles"][player["position"]] += 1
                elif not stats["roles"]:
                    stats["roles"]["Sub"] += 0
                role = absences.role_of(player["position"])
                if role:
                    role_minutes[role] += minutes
                    role_production[role] += npxg + _f(player["xA"])
                state["xg"] += xg
                state["npxg"] += npxg
            state["games"] += 1
    role_rate = {role: round(90.0 * role_production[role] / role_minutes[role], 3) for role in ROLES if role_minutes[role]}
    return pd.DataFrame(scorer_rows), pd.DataFrame(absence_rows), role_rate


def attach_rates(rows: pd.DataFrame) -> pd.DataFrame:
    """Gol attesi finali della squadra (ancorati) dal campione comune; righe senza partita corrispondente tolte."""
    from datasources.names import match_team

    frame = v2common.frame()
    rows = rows[rows["league"].isin(CODES)].copy()
    out = []
    for (league, season), group in rows.groupby(["league", "season"]):
        code, label = CODES[league], f"{str(season)[2:]}{str(season + 1)[2:]}"
        subset = frame[(frame["league"] == code) & (frame["season"] == label)]
        if subset.empty:
            continue
        names = {team: match_team(team, list(subset["home_team"].unique())) for team in set(group["home"])}
        index = {(home, day): (lam, mu) for home, day, lam, mu in
                 subset[["home_team", "date", "final_lambda", "final_mu"]].itertuples(index=False)}
        for row in group.itertuples():
            day = row.date.normalize()
            found = index.get((names.get(row.home), day)) or index.get((names.get(row.home), day - pd.Timedelta(days=1)))
            if found:
                out.append({**row._asdict(), "lambda_team": found[0] if row.side == "h" else found[1],
                            "lambda_home": found[0], "lambda_away": found[1]})
    return pd.DataFrame(out).drop(columns=["Index"], errors="ignore")


# --- Marcatori ------------------------------------------------------------------------------------------

def old_probability(rows: pd.DataFrame) -> np.ndarray:
    from scorers import PRIOR_SHARE, PRIOR_XG

    team_xg90 = rows["team_xg"] / rows["team_games"]
    share = (rows["xg"] + PRIOR_XG * PRIOR_SHARE) / (team_xg90 * rows["minutes"] / 90 + PRIOR_XG)
    minutes = np.minimum(90, rows["minutes"] / rows["apps"])
    return (1 - np.exp(-rows["lambda_team"] * share * minutes / 90)).to_numpy()


def new_probability(rows: pd.DataFrame, theta: np.ndarray) -> np.ndarray:
    role_share = dict(zip(ROLES, theta[:3]))
    prior_xg, penalty_share = theta[3], theta[4]
    team_npxg90 = rows["team_npxg"] / rows["team_games"]
    prior = rows["role"].map(role_share)
    open_play = (rows["npxg"] + prior_xg * prior) / (team_npxg90 * rows["minutes"] / 90 + prior_xg)
    share = (1 - penalty_share) * open_play + penalty_share * rows["taker"].astype(float)
    minutes = np.minimum(90, rows["minutes"] / rows["apps"])
    return (1 - np.exp(-rows["lambda_team"] * share * minutes / 90)).to_numpy()


def _loss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def scorer_check(rows: pd.DataFrame) -> dict:
    train, test = rows[rows["date"] < SPLIT], rows[rows["date"] >= SPLIT]
    y_train = train["scored"].to_numpy(float)
    start = np.array([0.03, 0.08, 0.2, 2.0, 0.1])
    fitted = minimize(lambda theta: _loss(new_probability(train, theta), y_train).mean(), start, method="L-BFGS-B",
                      bounds=[(0.005, 0.2), (0.01, 0.3), (0.05, 0.5), (0.2, 20.0), (0.0, 0.3)])
    theta = fitted.x
    y = test["scored"].to_numpy(float)
    old, new = old_probability(test), new_probability(test, theta)
    ece = lambda p: baseline.expected_calibration_error(baseline.binary(p), y.astype(int))
    verdict = v2common.strict((_loss(old, y), ece(old)), (_loss(new, y), ece(new)))
    groups = []
    minutes_band = pd.cut(test["minutes"] / test["apps"], [0, 30, 60, 91], labels=["< 30'", "30-60'", "60'+"])
    for (role, band), index in test.groupby([test["role"], minutes_band], observed=True).groups.items():
        mask = test.index.isin(index)
        groups.append({"ruolo": role, "minuti": str(band), "righe": int(mask.sum()), "attuale": float(old[mask].mean()),
                       "v2": float(new[mask].mean()), "reale": float(y[mask].mean())})
    verified = bool(verdict["tenuta"] and verdict["ece_dopo"] <= ECE_VERIFIED)
    return {"theta": [float(value) for value in theta], "verdetto": verdict, "gruppi": groups, "verificato": verified,
            "righe_taratura": len(train), "righe_verifica": len(test)}


# --- Assenze ---------------------------------------------------------------------------------------------

def absence_check(rows: pd.DataFrame) -> dict:
    data = v2common.frame()
    pairs = rows.pivot_table(index=["league", "season", "home", "away", "date"], columns="side", values="factor").dropna()
    lookup = rows.drop_duplicates(["league", "season", "home", "away", "date"]).set_index(
        ["league", "season", "home", "away", "date"])[["lambda_home", "lambda_away"]]
    joined = pairs.join(lookup, how="inner").reset_index()
    goals = []
    from datasources.names import match_team

    for row in joined.itertuples():
        subset = data[(data["league"] == CODES[row.league]) & (data["date"].between(row.date.normalize() - pd.Timedelta(days=1),
                                                                                       row.date.normalize()))]
        name = match_team(row.home, list(subset["home_team"])) if not subset.empty else None
        found = subset[subset["home_team"] == name]
        if not found.empty:
            goals.append({**found.iloc[0].to_dict(), "factor_home": row.h, "factor_away": row.a})
    frame = pd.DataFrame(goals)
    if frame.empty:
        return {"partite": 0}
    before = v2common.goal_losses(frame, frame["final_lambda"].to_numpy(), frame["final_mu"].to_numpy())
    after = v2common.goal_losses(frame, (frame["final_lambda"] * frame["factor_home"]).to_numpy(),
                                 (frame["final_mu"] * frame["factor_away"]).to_numpy())
    model_before = v2common.goal_losses(frame, frame["model_lambda"].to_numpy(), frame["model_mu"].to_numpy())
    model_after = v2common.goal_losses(frame, (frame["model_lambda"] * frame["factor_home"]).to_numpy(),
                                       (frame["model_mu"] * frame["factor_away"]).to_numpy())
    touched = ((frame["factor_home"] != 1) | (frame["factor_away"] != 1)).mean()
    return {"finale": v2common.strict(before, after), "solo_modello": v2common.strict(model_before, model_after),
            "partite": len(frame), "con_assenze": float(touched),
            "fattore_medio": float(np.concatenate([frame["factor_home"], frame["factor_away"]]).mean()),
            "fattore_minimo": float(np.concatenate([frame["factor_home"], frame["factor_away"]]).min())}


def render(scorers: dict, absent: dict, role_rate: dict) -> str:
    theta = scorers["theta"]
    lines = ["## Marcatori v2 e assenze pesate (fase P, punti 7b e 2)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.player_check`. Storico partita per partita "
             "Understat 2025/26 e 2026/27 (5 campionati, statistiche fino alla partita precedente).", "",
             "### Marcatori", "",
             f"Parametri v2 stimati fino al 31/12/2025 ({scorers['righe_taratura']} righe giocatore-partita): quota a "
             f"priori difensore {theta[0]:.3f}, centrocampista {theta[1]:.3f}, attaccante {theta[2]:.3f}; xG fittizi "
             f"{theta[3]:.2f}; quota dei gol su rigore {theta[4]:.3f}. Verifica dal 01/01/2026 "
             f"({scorers['righe_verifica']} righe).", "", *v2common.TABLE_HEADER,
             v2common.row_text("attuale → v2", scorers["verdetto"]), "",
             f"Esito: v2 **{'adottata' if scorers['verdetto']['tenuta'] else 'non adottata'}**; marcatori "
             f"**{'verificati' if scorers['verificato'] else 'non verificati: restano solo informativi, fuori da multiple e lista giocate'}**"
             f" (soglia ECE {ECE_VERIFIED}).", "",
             "| Ruolo | Minuti medi | Righe | P media attuale | P media v2 | Frequenza reale |", "|---|---|---|---|---|---|"]
    for group in scorers["gruppi"]:
        lines.append(f"| {group['ruolo']} | {group['minuti']} | {group['righe']} | {group['attuale']:.1%} | "
                     f"{group['v2']:.1%} | {group['reale']:.1%} |")
    lines += ["", "### Assenze pesate", "",
              "Produzione per 90 minuti (npxG + xA) per ruolo nei dati: " + ", ".join(f"{role} {value}" for role, value in role_rate.items()) + "."]
    if absent.get("partite"):
        lines += [f"{absent['partite']} partite con quote; almeno un'assenza pesata nel {absent['con_assenze']:.0%}; "
                  f"fattore medio {absent['fattore_medio']:.3f}, minimo {absent['fattore_minimo']:.3f}. Nessun parametro "
                  "stimato: tutte le partite sono fuori campione per il fattore.", "", *v2common.TABLE_HEADER,
                  v2common.row_text("finale ancorato × fattore assenze", absent["finale"]),
                  v2common.row_text("solo modello × fattore assenze (informativo)", absent["solo_modello"]).replace(
                      "**accesa**", "*migliora*").replace("**spenta**", "*non migliora*"), ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scorer_rows, absence_rows, role_rate = records()
    scorers = scorer_check(attach_rates(scorer_rows))
    absent = absence_check(attach_rates(absence_rows))
    markdown = render(scorers, absent, role_rate)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva:
        from tools.calibrate import _update_config

        sections = {"assenze": {"data": date.today().isoformat(),
                                "attiva": bool(absent.get("finale", {}).get("tenuta", False)),
                                "limiti": list(absences.LIMITS), "riferimento_ruolo": role_rate,
                                "verifica": {key: value for key, value in absent.items()}}}
        theta = scorers["theta"]
        if scorers["verdetto"]["tenuta"]:
            note = ("Calibrazione verificata fuori campione (python -m tools.player_check)." if scorers["verificato"] else
                    "Versione v2 migliore della precedente ma non verificata (ECE fuori campione sopra la soglia): "
                    "stima indicativa, fuori da multiple e lista delle giocate.")
            sections["marcatori"] = {"data": date.today().isoformat(), "verificato": scorers["verificato"],
                                     "quota_ruolo": dict(zip(ROLES, (round(value, 4) for value in theta[:3]))),
                                     "xg_fittizi": round(theta[3], 3), "quota_rigori": round(theta[4], 4), "nota": note,
                                     "verifica": scorers["verdetto"]}
        _update_config(sections)


if __name__ == "__main__":
    main()
