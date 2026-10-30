"""Formazione attesa, minuti e contributo dei giocatori (fase AL), come INPUT per il motore.

- XI atteso: formazione del report dell'Analista (o inserita a mano) se c'è; altrimenti l'XI tipo = i migliori 11 per minuti
  negli ultimi ``xi_tipo_partite`` undici (1 portiere + 10 di movimento). Assenti/squalificati con fonte: chi manca nell'XI
  tipo è sostituito, ruolo per ruolo, dal miglior disponibile per minuti pesati.
- Minuti attesi: titolare = minuti medi da titolare; panchina = quota dei minuti liberati dai cambi, ripartita tra i
  disponibili in proporzione a (entrate × minuti medi da subentrato).
- Fattore attacco = Σ (minuti attesi/90 × (npxG + xA per 90)) dell'XI atteso / la stessa somma dell'XI tipo. Gli assenti sono
  PESATI (quota persa singola), non contati. Sostituisce l'«assenze pesate» della Fase P (stessa grandezza, niente doppia
  conta); non contiene la forma recente della AD (che è xG−xGA delle ultime gare, non la formazione).
- Difesa: quota dei minuti di ruolo dell'XI tipo che mancano × peso per ruolo (``difesa.pesi_ruolo``, stimato da
  ``tools.lineup_check``); peso 0 = solo etichetta, dichiarato.
- Rigorista: battitore più frequente; se manca, il sostituto con shrinkage verso la conversione media del campionato.
- «Sta performando»: gol (senza rigori) − npxG con shrinkage forte ``x/(x+k)``: la fortuna in finalizzazione si
  ridimensiona verso la media. Va ai marcatori e all'etichetta, NON ai gol attesi della squadra (l'attacco del modello è già solo xG).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

import players as pl
from datasources.names import canonical_key, match_team

DEFAULT_START_MINUTES = {"POR": 90.0, "DIF": 88.0, "CEN": 82.0, "ATT": 78.0}
DEFAULT_SUB_MINUTES = 25.0
PENALTY_SHARE_MIN = 1


def _squad_index(squad: pd.DataFrame) -> dict[str, dict]:
    return {row["player_id"]: row for row in squad.to_dict("records")}


def _start_minutes(row: Mapping) -> float:
    value = row.get("minuti_da_titolare")
    return float(value) if value is not None and np.isfinite(value) else DEFAULT_START_MINUTES[row["role"]]


def typical_xi(store: pl.PlayerStore, league: str, key: str, when: pd.Timestamp, squad: pd.DataFrame) -> list[str]:
    """Gli 11 con più minuti negli ultimi ``xi_tipo_partite`` undici (un portiere e dieci di movimento)."""
    rows = store.team_rows(league, key, when)
    if rows.empty:
        return []
    recent_ids = list(dict.fromkeys(rows.sort_values(["date", "match_id"])["match_id"]))[-int(store.config["xi_tipo_partite"]):]
    recent = rows[rows["match_id"].isin(recent_ids)]
    minutes = recent.groupby("player_id")["minutes"].sum()
    roles = squad.set_index("player_id")["role"].to_dict()
    ordered = [pid for pid in minutes.sort_values(ascending=False).index if pid in roles]
    keepers = [pid for pid in ordered if roles[pid] == "POR"][:1]
    outfield = [pid for pid in ordered if roles[pid] != "POR"][:10]
    return keepers + outfield


def fill_xi(index: Mapping[str, Mapping], base: Sequence[str], unavailable: set[str]) -> list[str]:
    """Toglie gli indisponibili e li sostituisce con il miglior disponibile dello stesso ruolo (minuti pesati)."""
    xi = [pid for pid in base if pid not in unavailable]
    for pid in base:
        if pid not in unavailable:
            continue
        role = index[pid]["role"]
        pool = sorted((row for row in index.values() if row["player_id"] not in unavailable and row["player_id"] not in xi
                       and row["role"] == role), key=lambda row: -row["minuti_pesati"])
        if not pool:   # nessuno dello stesso ruolo: il migliore di movimento (mai un portiere per un giocatore di movimento)
            pool = sorted((row for row in index.values() if row["player_id"] not in unavailable and row["player_id"] not in xi
                           and (row["role"] == "POR") == (role == "POR")), key=lambda row: -row["minuti_pesati"])
        if pool:
            xi.append(pool[0]["player_id"])
    return xi


def expected_minutes(index: Mapping[str, Mapping], xi: Sequence[str], unavailable: set[str]) -> dict[str, tuple[float, str]]:
    """Minuti attesi per giocatore e origine («titolare» / «panchina»)."""
    minutes = {pid: (_start_minutes(index[pid]), "titolare") for pid in xi}
    freed = max(0.0, 11 * 90.0 - sum(value for value, _ in minutes.values()))
    bench = [row for row in index.values() if row["player_id"] not in minutes and row["player_id"] not in unavailable]
    weights = {}
    for row in bench:
        sub = row.get("minuti_da_subentrato")
        sub = float(sub) if sub is not None and np.isfinite(sub) else DEFAULT_SUB_MINUTES
        weights[row["player_id"]] = max(float(row.get("entrate", 0)), 0.5) * sub if row.get("entrate", 0) else 0.0
    total = sum(weights.values())
    if total > 0:
        for pid, weight in weights.items():
            if weight > 0:
                minutes[pid] = (freed * weight / total, "panchina")
    return minutes


def production(index: Mapping[str, Mapping], minutes: Mapping[str, tuple[float, str]]) -> dict[str, float]:
    npxg = sum(value / 90.0 * index[pid]["npxg90"] for pid, (value, _) in minutes.items())
    xa = sum(value / 90.0 * index[pid]["xa90"] for pid, (value, _) in minutes.items())
    return {"npxg": npxg, "xa": xa, "totale": npxg + xa}


def _match_names(names: Iterable[str], index: Mapping[str, Mapping]) -> tuple[list[str], list[str]]:
    by_name = {row["player"]: pid for pid, row in index.items()}
    found, missing = [], []
    for name in names:
        hit = match_team(name, list(by_name)) if by_name else None
        (found if hit else missing).append(by_name[hit] if hit else name)
    return found, missing


def team_lineup(store: pl.PlayerStore, league: str, key: str, when: pd.Timestamp, *, confirmed: Sequence[str] | None = None,
                absent: Sequence[Mapping[str, str]] = (), source: str = "", light: bool = False) -> dict[str, Any]:
    """Tutto ciò che serve del lato di una squadra: XI, minuti, assenti pesati, fattori, rigorista, performando."""
    squad = pl.squad_stats(store, league, key, when)
    cfg = store.config
    if squad.empty:
        return {"disponibile": False, "avvisi": ["Nessun dato giocatore per la squadra: formazione non calcolabile."]}
    index = _squad_index(squad)
    warnings: list[str] = []
    for row in index.values():
        warnings += [f"{row['player']}: {item}" for item in row["avvisi"]]
    typical = typical_xi(store, league, key, when, squad)
    if not typical:
        return {"disponibile": False, "avvisi": ["Nessuna gara recente: XI tipo non calcolabile."]}
    absent_ids: dict[str, Mapping[str, str]] = {}
    for item in absent:
        found, missing = _match_names([item["nome"]], index)
        if found:
            absent_ids[found[0]] = item
        else:
            warnings.append(f"Assente «{item['nome']}» non trovato nella rosa Understat: ignorato.")
    unavailable = set(absent_ids)
    if confirmed:
        found, missing = _match_names(confirmed, index)
        warnings += [f"Titolare «{name}» non trovato nella rosa: sostituito dal miglior disponibile." for name in missing]
        xi = fill_xi(index, found + [pid for pid in typical if pid not in found], unavailable)[:11] if len(found) < 11 else \
            [pid for pid in found if pid not in unavailable][:11]
        origin = f"formazione indicata ({source or 'report'})"
    else:
        xi = fill_xi(index, typical, unavailable)
        origin = ("XI tipo (ultimi %d undici per minuti)" % cfg["xi_tipo_partite"]
                  + (f", meno {len(unavailable)} assenti con fonte" if unavailable else ""))
    typical_minutes = expected_minutes(index, typical, set())
    scenario_minutes = expected_minutes(index, xi, unavailable)
    base = production(index, typical_minutes)
    now = production(index, scenario_minutes)
    factor = now["totale"] / base["totale"] if base["totale"] > 0 else 1.0
    limits = cfg["fattore_attacco"].get("limiti")
    attack_warning = None
    if limits and not (limits[0] <= factor <= limits[1]):
        clipped = min(max(factor, limits[0]), limits[1])
        attack_warning = f"fattore {factor:.3f} fuori dall'intervallo storico {limits[0]:.2f}-{limits[1]:.2f}: riportato a {clipped:.3f}"
        factor = clipped
    components = cfg["componenti"]
    if not components.get("attacco", True):
        factor, attack_warning = 1.0, "componente attacco spenta in config/giocatori.json"
    # assenti pesati: quota persa se mancasse solo lui
    weighted = []
    for pid, item in absent_ids.items():
        alone = production(index, expected_minutes(index, fill_xi(index, typical, {pid}), {pid}))["totale"]
        share = 1.0 - alone / base["totale"] if base["totale"] > 0 else 0.0
        weighted.append({"giocatore": index[pid]["player"], "ruolo": index[pid]["role"], "motivo": item.get("motivo", "assente"),
                         "fonte": item.get("fonte", ""), "quota_persa": round(share, 4),
                         "in_xi_tipo": pid in typical})
    # difesa: quota dei minuti di ruolo dell'XI tipo che manca nell'XI atteso
    missing_share = {}
    for role in ("POR", "DIF", "CEN"):
        typical_role = [pid for pid in typical if index[pid]["role"] == role]
        total = sum(_start_minutes(index[pid]) for pid in typical_role)
        lost = sum(_start_minutes(index[pid]) for pid in typical_role if pid not in xi)
        missing_share[role] = lost / total if total else 0.0
    weights = cfg["difesa"]["pesi_ruolo"]
    defense = float(np.exp(sum(weights[role] * missing_share[role] for role in weights))) if components.get("difesa", True) else 1.0
    defense_label = ("pesi per ruolo stimati dal backtest" if any(weights.values()) and cfg["difesa"].get("stimato")
                     else "solo etichetta: pesi per ruolo non stimabili dal backtest (dichiarato)")
    total_minutes = {pid: value for pid, (value, _) in scenario_minutes.items()}
    sum_npxg = sum(total_minutes[pid] / 90.0 * index[pid]["npxg90"] for pid in total_minutes) or 1.0
    sum_xa = sum(total_minutes[pid] / 90.0 * index[pid]["xa90"] for pid in total_minutes) or 1.0
    on_field = []
    for pid, (minutes, how) in sorted(scenario_minutes.items(), key=lambda item: (-(item[1][1] == "titolare"), -item[1][0])):
        row = index[pid]
        on_field.append({"giocatore": row["player"], "ruolo": row["role"], "ruolo_stimato": row["ruolo_stimato"], "come": how,
                         "minuti_attesi": round(minutes, 1), "npxg90": round(row["npxg90"], 3), "xa90": round(row["xa90"], 3),
                         "tiri90": round(row["shots90"], 2), "quota_npxg": round(minutes / 90.0 * row["npxg90"] / sum_npxg, 4),
                         "quota_xa": round(minutes / 90.0 * row["xa90"] / sum_xa, 4), "minuti_campione": round(row["minuti_pesati"]),
                         "origine": origin if how == "titolare" else "panchina: entrate × minuti da subentrato"})
    penalty = {} if light else penalty_params(store, league, key, when, index, xi, unavailable, components.get("rigorista", True))
    performing = {} if light else performing_params(store, league, key, when, index, components.get("performando", True))
    return {"disponibile": True, "origine_formazione": origin, "xi": [row for row in on_field if row["come"] == "titolare"],
            "panchina": [row for row in on_field if row["come"] == "panchina"], "assenti": weighted,
            "fattore_attacco": {"valore": round(factor, 4), "campione": int(squad["partite"].sum()),
                                "fonte": "Σ minuti attesi/90 × (npxG+xA)/90 dell'XI atteso ÷ XI tipo (Understat, ultime 2 stagioni)",
                                "avviso": attack_warning, "npxg_xi": round(now["npxg"], 3), "npxg_tipo": round(base["npxg"], 3)},
            "fattore_difesa": {"valore": round(defense, 4), "quota_minuti_mancanti": {r: round(v, 3) for r, v in missing_share.items()},
                               "fonte": defense_label},
            "rigorista": penalty, "performando": performing, "avvisi": warnings}


def penalty_params(store, league, key, when, index, xi, unavailable, enabled: bool = True) -> dict[str, Any]:
    stats = pl.penalty_stats(store, league, key, when)
    cfg = store.config["rigori"]
    league_conv = stats["lega"]["conversione"]
    k = float(cfg["k_conversione"])
    base = {"xg_rigore": round(stats["lega"]["xg_per_rigore"], 3) if np.isfinite(stats["lega"]["xg_per_rigore"]) else None,
            "rigori_per_partita": round(stats["squadra"]["rigori_per_partita"], 4),
            "fonte": f"Understat: rigori della squadra (ultime 2 stagioni) e della lega ({int(stats['lega']['rigori'])} rigori)"}
    if not enabled:
        return {**base, "rigorista": None, "stato": "componente spenta in config/giocatori.json"}
    takers = [row for row in stats["battitori"] if row["player_id"] in index and row["n"] >= PENALTY_SHARE_MIN]
    if not takers:
        return {**base, "rigorista": None, "stato": "nessun rigorista noto", "conversione": round(league_conv, 3),
                "campione": 0}
    first = takers[0]
    shrunk = lambda row: (row["goals"] + k * league_conv) / (row["n"] + k)       # noqa: E731
    if first["player_id"] in xi and first["player_id"] not in unavailable:
        return {**base, "rigorista": first["player"], "stato": "in campo", "conversione": round(shrunk(first), 3),
                "campione": int(first["n"])}
    substitute = next((row for row in takers[1:] if row["player_id"] in xi and row["player_id"] not in unavailable), None)
    if substitute is not None:
        return {**base, "rigorista": first["player"], "stato": "assente", "sostituto": substitute["player"],
                "conversione": round(shrunk(substitute), 3), "campione": int(substitute["n"])}
    return {**base, "rigorista": first["player"], "stato": "assente", "sostituto": None,
            "conversione": round(league_conv, 3), "campione": 0,
            "nota": "nessun sostituto con rigori: conversione media del campionato"}


def performing_params(store, league, key, when, index, enabled: bool = True) -> dict[str, Any]:
    """Gol (senza rigori) − npxG con shrinkage x/(x+k): la finalizzazione sopra o sotto l'attesa, ridimensionata."""
    cfg = store.config["performando"]
    if not enabled:
        return {"squadra": None, "giocatori": [], "nota": "componente spenta"}
    rows = store.team_rows(league, key, when)
    k = float(cfg["k_xg"])

    def shrunk(goals: float, xg: float) -> float:
        return (goals - xg) * xg / (xg + k) if xg > 0 else 0.0

    team_goals, team_xg = float((rows["goals"] - rows["pen_goals"]).sum()), float(rows["npxg"].sum())
    k_team = float(cfg.get("k_xg_squadra") or k)
    team = (team_goals - team_xg) * team_xg / (team_xg + k_team) if team_xg > 0 else 0.0
    players = []
    for pid, group in rows.groupby("player_id"):
        if pid not in index:
            continue
        goals, xg = float((group["goals"] - group["pen_goals"]).sum()), float(group["npxg"].sum())
        value = shrunk(goals, xg)
        label = "sopra l'xG" if value >= cfg["soglia_etichetta"] else "sotto l'xG" if value <= -cfg["soglia_etichetta"] else "in linea"
        players.append({"giocatore": index[pid]["player"], "gol_senza_rigori": goals, "npxg": round(xg, 2),
                        "differenza_grezza": round(goals - xg, 2), "differenza_ridimensionata": round(value, 2),
                        "etichetta": label, "fonte": f"Understat, shrinkage x/(x+{k:g}) verso la media"})
    players.sort(key=lambda row: -abs(row["differenza_ridimensionata"]))
    return {"squadra": {"gol_senza_rigori": team_goals, "npxg": round(team_xg, 2), "differenza_ridimensionata": round(team, 2),
                        "fonte": f"Understat, shrinkage x/(x+{k_team:g}); non entra nei gol attesi (l'attacco del modello è già solo xG)"},
            "giocatori": players[:8]}


def get_lineup_params(home: str, away: str, when, store: pl.PlayerStore, *, league: str | None = None,
                      report: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Parametri di formazione per la partita (solo gare precedenti).

    ``report``: ``{"casa": {"formazione": [nomi], "assenti": [{"nome", "fonte", "motivo"?}], "fonte": str}, "ospite": {...}}``
    dal report dell'Analista o dal blocco a mano; senza report si usa l'XI tipo. Ritorna
    ``{"casa": lato, "ospite": lato, "motore": {"home": {"attack", "defense"}, "away": {...}} | None, "avvisi": [...]}``.
    """
    when = pd.Timestamp(when).normalize()
    result: dict[str, Any] = {"data": when.date().isoformat(), "avvisi": []}
    sides = {}
    for label, team in (("casa", home), ("ospite", away)):
        key = canonical_key(team)
        leagues = [league] if league else store.team_keys(key)
        if not leagues:
            sides[label] = {"disponibile": False, "avvisi": [f"Nessun dato giocatore per {team} (solo Understat dei 5 grandi campionati)."]}
            continue
        chosen = max(leagues, key=lambda code: len(store.team_rows(code, key, when)))
        info = (report or {}).get(label) or {}
        sides[label] = team_lineup(store, chosen, key, when, confirmed=info.get("formazione"), absent=info.get("assenti") or (),
                                   source=info.get("fonte", ""))
        sides[label]["squadra"] = team
    result.update(sides)
    result["avvisi"] = [message for side in sides.values() for message in side.get("avvisi", [])]
    if all(side.get("disponibile") for side in sides.values()):
        result["motore"] = {"home": {"attack": sides["casa"]["fattore_attacco"]["valore"], "defense": sides["casa"]["fattore_difesa"]["valore"]},
                            "away": {"attack": sides["ospite"]["fattore_attacco"]["valore"], "defense": sides["ospite"]["fattore_difesa"]["valore"]}}
    else:
        result["motore"] = None
        result["avvisi"].append("Formazione non disponibile per entrambe le squadre: nessun fattore applicato al motore.")
    return result
