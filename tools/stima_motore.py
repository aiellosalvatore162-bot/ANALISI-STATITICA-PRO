"""Fase AK, stadio 2: stima dei parametri del motore a eventi → ``config/motore_eventi.json``.

Dati: StatsBomb Open Data 2015/16 (riassunto «dettaglio» di ``tools.minute_data --statsbomb-dettaglio``, eventi ridotti e
stili per squadra-partita della fase Q), football-data.co.uk per gli arbitri. Fonte da citare: «Data: StatsBomb Open Data».

1. Tiri per tipo (rigore, palla inattiva, transizione, fuori area, testa da cross, azione): tiri per squadra e partita,
   xG medio, gol per tiro, quota parata/respinta; per campionato e comune. Palla inattiva = punizione diretta o possesso
   nato da corner (lo schema «From Free Kick» copre tutto il possesso nato da una punizione qualsiasi e resta azione).
2. Corner per origine (tiro parato o respinto, cross, altro) e falli per zona; corner per tiro parato o respinto.
3. Stato di partita: moltiplicatori di tiri, xG, corner, falli e gialli per scarto (−2…+2) e per fascia di minuti, con
   un effetto fisso per squadra-partita (la forza resta fuori) ed errore standard bootstrap per partita.
4. Dizionario tattico: per ogni termine misurabile, scheda della squadra dai valori di stagione SENZA la partita (terzili
   come nella fase Q), regressione di Poisson del conteggio della partita sul punteggio del termine con controlli (forza
   delle due squadre, casa, concessioni dell'avversario come offset), errore robusto per partita. Il beta entra nel
   dizionario solo se l'intervallo al 95% esclude lo zero; altrimenti 0 con la stima grezza dichiarata. Termini non
   misurabili nei dati: beta null con il motivo.
5. Incroci: termine dell'attacco × termine della difesa nella stessa regressione (solo stima: l'accensione si decide
   con il banco fuori campione dello stadio 14).
6. Arbitri (``referee_stats``): varianza tra arbitri, shrinkage k stimato e verifica fuori campione.

Bundesliga: StatsBomb pubblica solo le 34 partite del Leverkusen → entra solo nelle stime comuni; per la Bundesliga
valgono i valori comuni (dichiarato nel file). Uso: ``python -m tools.stima_motore [--bootstrap 200] [--no-dizionario]``.
"""

from __future__ import annotations

import argparse
from datetime import date
import gzip
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import referee_stats
import tactical_dictionary
from tools import dataset
from tools.minute_data import CACHE, SAVED, SB_SEASONS
from tools.tactical_cross import _bins, statsbomb_rows

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "motore_eventi.json"
REPORT = ROOT / "docs" / "backtest" / "AK_stima.md"
LEAGUE_NAMES = {2: "Premier League", 11: "La Liga", 12: "Serie A", 9: "Bundesliga", 7: "Ligue 1"}
NO_OWN_EFFECTS = {"Bundesliga"}
SOURCE = "Data: StatsBomb Open Data 2015/16"
SHOT_TYPES = ("rigore", "palla_inattiva", "transizione", "fuori_area", "testa_da_cross", "azione")
SET_PIECE_PATTERNS = {"From Corner"}  # «From Free Kick» = tutto il possesso nato da una punizione qualsiasi
OPEN_PLAY = {"transizione", "fuori_area", "testa_da_cross", "azione"}
BANDS = ((0, 30, "0-30"), (30, 60, "30-60"), (60, 75, "60-75"), (75, 200, "75-90"))
STATES = (-2, -1, 0, 1, 2)
YELLOW = {"Yellow Card", "Second Yellow"}
STRAIGHT_RED = {"Red Card"}
RED = {"Red Card", "Second Yellow"}
QUANTITIES = ("tiri", "xg", "corner", "corner_gioco", "falli", "gialli")
MEN = (-1, 0, 1)


def shot_type(shot: dict) -> str:
    """Tipo di tiro del motore a eventi da un tiro del riassunto «dettaglio» (ordine di precedenza fisso)."""
    if shot.get("t") == "Penalty":
        return "rigore"
    if shot.get("t") in ("Free Kick", "Corner") or shot.get("pp") in SET_PIECE_PATTERNS:
        return "palla_inattiva"
    if shot.get("pp") == "From Counter":
        return "transizione"
    if not shot.get("area"):
        return "fuori_area"
    if shot.get("b") == "Head" and shot.get("cross"):
        return "testa_da_cross"
    return "azione"


def load_detail() -> list[dict]:
    rows = []
    for competition, season in SB_SEASONS:
        detail = json.load(gzip.open(CACHE / f"statsbomb_dettaglio_{competition}_{season}.json.gz", "rt", encoding="utf-8"))
        basic = {match["id"]: match for match in
                 json.load(gzip.open(CACHE / f"statsbomb_{competition}_{season}.json.gz", "rt", encoding="utf-8"))}
        for match in detail:
            events = basic.get(match["id"], {}).get("events", [])
            match["own_goals"] = [event for event in events if event["kind"] == "own_goal_for"]
            match["last_minute"] = {period: max([event["minute"] for event in events if event["period"] == period] or [0])
                                    for period in (1, 2)}
            match["league"], match["season_key"] = LEAGUE_NAMES[competition], f"{competition}_{season}"
            rows.append(match)
    return rows


# --- 1-2. Tiri per tipo, corner per origine, falli per zona -------------------------------------------------------------

def shot_table(matches: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"league": match["league"], "match": match["id"], "side": shot["s"], "tipo": shot_type(shot),
                          "xg": float(shot.get("xg") or 0.0), "gol": bool(shot["g"]), "parato": shot.get("o") in SAVED}
                         for match in matches for shot in match["shots"]])


def _summary_by_type(shots: pd.DataFrame, team_matches: int) -> dict:
    result = {}
    for kind in SHOT_TYPES:
        rows = shots[shots["tipo"] == kind]
        n = len(rows)
        rate = n / team_matches
        goals = rows["gol"].mean() if n else 0.0
        result[kind] = {"tiri_per_squadra_partita": rate, "quota": n / max(len(shots), 1),
                        "xg_medio": float(rows["xg"].mean()) if n else None, "gol_per_tiro": float(goals) if n else None,
                        "gol_per_tiro_es": math.sqrt(goals * (1 - goals) / n) if n else None,
                        "quota_parato_respinto": float(rows["parato"].mean()) if n else None, "n": int(n)}
    return result


def shots_section(matches: list[dict]) -> dict:
    shots = shot_table(matches)
    section = {"comune": _summary_by_type(shots, 2 * len(matches))}
    for league in sorted({match["league"] for match in matches} - NO_OWN_EFFECTS):
        own = [match for match in matches if match["league"] == league]
        section[league] = _summary_by_type(shots[shots["league"] == league], 2 * len(own))
    return section


def corners_fouls_section(matches: list[dict]) -> dict:
    def block(rows: list[dict]) -> dict:
        team_matches = 2 * len(rows)
        origins = pd.Series([corner["o"] for match in rows for corner in match["corners"]]).value_counts()
        saved = sum(shot.get("o") in SAVED for match in rows for shot in match["shots"])
        fouls = pd.DataFrame([foul for match in rows for foul in match["fouls"]])
        yellow = sum(foul.get("card") in YELLOW for match in rows for foul in match["fouls"]) + \
            sum(card.get("card") in YELLOW for match in rows for card in match["cards"])
        return {"corner_per_squadra_partita": {origin: float(origins.get(origin, 0)) / team_matches
                                               for origin in ("tiro", "cross", "altro")},
                "corner_per_tiro_parato_respinto": float(origins.get("tiro", 0)) / max(saved, 1),
                "falli_per_squadra_partita": len(fouls) / team_matches,
                "falli_per_zona": {zone: float((fouls["z"] == zone).mean()) for zone in ("difesa", "centro", "attacco")},
                "gialli_per_fallo": yellow / max(len(fouls), 1), **red_rates(rows), "partite": len(rows)}

    section = {"comune": block(matches)}
    for league in sorted({match["league"] for match in matches} - NO_OWN_EFFECTS):
        section[league] = block([match for match in matches if match["league"] == league])
    return section


def _cards(match: dict) -> list[tuple[int, float, str, str]]:
    """Cartellini della partita (tempo, minuto, squadra, tipo) in ordine: da fallo e non da fallo."""
    cards = [(event["p"], event["m"], event["s"], event["card"]) for event in match["fouls"] if event.get("card")]
    cards += [(event["p"], event["m"], event["s"], event["card"]) for event in match["cards"] if event.get("card")]
    return sorted(cards)


def red_rates(rows: list[dict]) -> dict:
    """Rossi diretti per fallo e quota di seconde gialle tra i gialli presi da chi ha già un giallo di squadra."""
    fouls = sum(len(match["fouls"]) for match in rows)
    straight = second = with_prior = 0
    for match in rows:
        booked = {"h": 0, "a": 0}
        for _, _, side, card in _cards(match):
            if card in STRAIGHT_RED:
                straight += 1
            elif card in YELLOW:
                if booked[side]:
                    with_prior += 1
                    second += card == "Second Yellow"
                booked[side] += 1
    return {"rossi_diretti_per_fallo": straight / max(fouls, 1),
            "seconda_gialla_per_giallo_con_precedente": second / max(with_prior, 1),
            "rossi_diretti": straight, "seconde_gialle": second}


# --- 3. Stato di partita ------------------------------------------------------------------------------------------------

def _band(minute: float) -> str:
    return next(name for low, high, name in BANDS if low <= minute < high)


def goal_times(match: dict) -> list[tuple[int, float, str]]:
    """(tempo, minuto, squadra che segna) ordinati: tiri a segno + autogol (squadra che ne beneficia)."""
    goals = [(shot["p"], shot["m"] + 0.5, shot["s"]) for shot in match["shots"] if shot["g"]]
    goals += [(goal["period"], goal["minute"] + 0.5, goal["h_a"]) for goal in match.get("own_goals", [])]
    return sorted(goals)


def state_cells(match: dict) -> pd.DataFrame:
    """Celle (squadra, fascia, stato) con esposizione in minuti e conteggi di tiri, xG, corner, falli e gialli."""
    goals = goal_times(match)
    reds = [(period, minute + 0.5, side) for period, minute, side, card in _cards(match) if card in RED]
    cuts = {1: [0.0, 30.0], 2: [45.0, 60.0, 75.0]}
    pieces = []
    for period in (1, 2):
        start = 0.0 if period == 1 else 45.0
        end = max(float(match["last_minute"].get(period, 0)) + 1.0, start + 45.0)
        points = sorted({start, end, *[cut for cut in cuts[period] if start < cut < end],
                         *[minute for p, minute, _ in goals + reds if p == period and start < minute < end]})
        pieces += [(period, low, high) for low, high in zip(points, points[1:])]

    def score_at(period: int, minute: float) -> tuple[int, int]:
        done = [side for p, m, side in goals if (p, m) <= (period, minute)]
        return done.count("h"), done.count("a")

    def men_at(period: int, minute: float, side: str) -> int:
        """Uomini in più (+1) o in meno (−1) della squadra: espulsi dell'avversario meno i propri."""
        done = [team for p, m, team in reds if (p, m) <= (period, minute)]
        return int(np.clip(done.count("a" if side == "h" else "h") - done.count(side), -1, 1))

    def empty() -> dict:
        return {"esposizione": 0.0, **{quantity: 0.0 for quantity in QUANTITIES}}

    cells: dict[tuple[str, str, int, int], dict] = {}
    for period, low, high in pieces:
        home, away = score_at(period, low)
        for side, diff in (("h", home - away), ("a", away - home)):
            key = (side, _band(low), int(np.clip(diff, -2, 2)), men_at(period, low, side))
            cells.setdefault(key, empty())["esposizione"] += high - low

    def add(event: dict, quantity: str, value: float = 1.0) -> None:
        minute = event["m"] + 0.25  # prima del gol dello stesso minuto: il tiro che segna conta nello stato precedente
        home, away = score_at(event["p"], minute)
        diff = home - away if event["s"] == "h" else away - home
        key = (event["s"], _band(min(minute, 199.0)), int(np.clip(diff, -2, 2)), men_at(event["p"], minute, event["s"]))
        cells.setdefault(key, empty())[quantity] += value

    for shot in match["shots"]:
        add(shot, "tiri")
        if shot.get("t") != "Penalty":
            add(shot, "xg", float(shot.get("xg") or 0.0))
    for corner in match["corners"]:
        add(corner, "corner")
        if corner["o"] != "tiro":
            add(corner, "corner_gioco")
    for foul in match["fouls"]:
        add(foul, "falli")
        if foul.get("card") in YELLOW:
            add(foul, "gialli")
    for card in match["cards"]:
        if card.get("card") in YELLOW:
            add(card, "gialli")
    return pd.DataFrame([{"match": match["id"], "side": side, "fascia": band, "stato": state, "uomini": men, **values}
                         for (side, band, state, men), values in cells.items()])


def fit_state_effects(cells: pd.DataFrame, quantity: str, weights: np.ndarray | None = None,
                      iterations: int = 200) -> tuple[dict[int, float], dict[str, float]]:
    """Poisson con effetto fisso per squadra-partita: n = b_squadra · fascia · stato · minuti (stato 0 e 0-30 = 1)."""
    team = pd.factorize(cells["match"].astype(str) + cells["side"])[0]
    state = cells["stato"].map({value: index for index, value in enumerate(STATES)}).to_numpy()
    band = cells["fascia"].map({name: index for index, (_, _, name) in enumerate(BANDS)}).to_numpy()
    count, exposure = cells[quantity].to_numpy(float), cells["esposizione"].to_numpy(float)
    weight = np.ones(len(cells)) if weights is None else weights
    s_eff, b_eff = np.ones(len(STATES)), np.ones(len(BANDS))
    team_n = np.bincount(team, weights=weight * count)
    state_n = np.bincount(state, weights=weight * count, minlength=len(STATES))
    band_n = np.bincount(band, weights=weight * count, minlength=len(BANDS))
    for _ in range(iterations):
        base = team_n / np.maximum(np.bincount(team, weights=weight * s_eff[state] * b_eff[band] * exposure), 1e-12)
        s_new = state_n / np.maximum(np.bincount(state, weights=weight * base[team] * b_eff[band] * exposure,
                                                 minlength=len(STATES)), 1e-12)
        s_new /= s_new[STATES.index(0)]
        b_new = band_n / np.maximum(np.bincount(band, weights=weight * base[team] * s_new[state] * exposure,
                                                minlength=len(BANDS)), 1e-12)
        b_new /= b_new[0]
        done = np.allclose(s_new, s_eff, rtol=1e-7) and np.allclose(b_new, b_eff, rtol=1e-7)
        s_eff, b_eff = s_new, b_new
        if done:
            break
    return ({value: float(s_eff[index]) for index, value in enumerate(STATES)},
            {name: float(b_eff[index]) for index, (_, _, name) in enumerate(BANDS)})


def state_section(matches: list[dict], bootstrap: int, seed: int = 11) -> dict:
    cells = pd.concat([state_cells(match) for match in matches], ignore_index=True)
    codes, unique = pd.factorize(cells["match"])
    rng = np.random.default_rng(seed)
    draws = [np.bincount(rng.integers(0, len(unique), len(unique)), minlength=len(unique))[codes].astype(float)
             for _ in range(bootstrap)]
    exposure = cells.groupby("stato")["esposizione"].sum() / 2  # minuti di partita (ogni minuto conta per le due squadre)
    section = {"minuti_per_stato": {str(state): float(exposure.get(state, 0.0)) for state in STATES}, "quantita": {}}
    for quantity in QUANTITIES:
        states, bands = fit_state_effects(cells, quantity)
        boot = [fit_state_effects(cells, quantity, weights, iterations=60) for weights in draws]
        section["quantita"][quantity] = {
            "stato": {str(state): {"moltiplicatore": value,
                                   "es": float(np.std([np.log(b[0][state]) for b in boot], ddof=1)) if boot else None}
                      for state, value in states.items()},
            "fascia": {band: {"moltiplicatore": value,
                              "es": float(np.std([np.log(b[1][band]) for b in boot], ddof=1)) if boot else None}
                       for band, value in bands.items()}}
    section["nota"] = ("moltiplicatori del tasso per minuto rispetto al pareggio (stato 0) e alla fascia 0-30; es = errore "
                       "standard bootstrap per partita del logaritmo; effetto fisso per squadra-partita (la forza non entra); "
                       "rigori esclusi dagli xG; espulsioni non separate qui (sezione «espulsioni»); corner_gioco = corner "
                       "non nati da un tiro (cross e altro)")
    teams = {match["id"]: (match["league"], match["home"], match["away"]) for match in matches}
    cells["league"] = cells["match"].map(lambda key: teams[key][0])
    cells["team"] = [teams[key][1 if side == "h" else 2] for key, side in zip(cells["match"], cells["side"])]
    cells["opp"] = [teams[key][2 if side == "h" else 1] for key, side in zip(cells["match"], cells["side"])]
    section["espulsioni"] = men_section(cells, draws)
    return section


def fit_men_effects(cells: pd.DataFrame, quantity: str, weights: np.ndarray | None = None,
                    iterations: int = 200) -> dict[int, float]:
    """Come ``fit_state_effects`` con un fattore in più per gli uomini in campo (−1, 0, +1; 0 = 1)."""
    team = pd.factorize(cells["match"].astype(str) + cells["side"])[0]
    factors = [cells["stato"].map({value: index for index, value in enumerate(STATES)}).to_numpy(),
               cells["fascia"].map({name: index for index, (_, _, name) in enumerate(BANDS)}).to_numpy(),
               cells["uomini"].map({value: index for index, value in enumerate(MEN)}).to_numpy()]
    references = [STATES.index(0), 0, MEN.index(0)]
    count, exposure = cells[quantity].to_numpy(float), cells["esposizione"].to_numpy(float)
    weight = np.ones(len(cells)) if weights is None else weights
    effects = [np.ones(len(STATES)), np.ones(len(BANDS)), np.ones(len(MEN))]
    team_n = np.bincount(team, weights=weight * count)
    totals = [np.bincount(index, weights=weight * count, minlength=len(effect)) for index, effect in zip(factors, effects)]
    for _ in range(iterations):
        previous = [effect.copy() for effect in effects]
        rate = effects[0][factors[0]] * effects[1][factors[1]] * effects[2][factors[2]]
        base = team_n / np.maximum(np.bincount(team, weights=weight * rate * exposure), 1e-12)
        for position, (index, effect) in enumerate(zip(factors, effects)):
            others = base[team] * exposure * np.prod([effects[j][factors[j]] for j in range(3) if j != position], axis=0)
            new = totals[position] / np.maximum(np.bincount(index, weights=weight * others, minlength=len(effect)), 1e-12)
            effects[position] = new / new[references[position]]
        if all(np.allclose(a, b, rtol=1e-7) for a, b in zip(effects, previous)):
            break
    return {value: float(effects[2][index]) for index, value in enumerate(MEN)}


# Falli e gialli: i cartellini PRECEDONO l'espulsione (fase calda, seconde gialle), quindi dentro la stessa squadra-partita
# il tratto prima del rosso è gonfiato e l'effetto fisso esagera il calo dopo (gialli ×0,39). Per queste due quantità
# l'uomo in meno/in più si misura TRA partite: conteggio osservato contro quello atteso dalla squadra e dall'avversario
# nelle ALTRE partite della stagione (stato e fascia come controlli). Su tiri e corner i due metodi coincidono.
MEN_BETWEEN = ("falli", "gialli")


def fit_men_between(cells: pd.DataFrame, quantity: str, weights: np.ndarray | None = None,
                    effects: tuple[dict[int, float], dict[str, float]] | None = None) -> dict[int, float]:
    """Uomini in campo tra partite: per ogni squadra-partita il tasso atteso = tasso della squadra nelle altre partite ×
    concessioni dell'avversario nelle altre partite / media del campionato (senza la partita), per stato e fascia
    (moltiplicatori di ``fit_state_effects``); moltiplicatore = osservato/atteso per uomini, riferito alla parità."""
    weight = np.ones(len(cells)) if weights is None else weights
    states, bands = effects if effects is not None else fit_state_effects(cells, quantity)
    frame = pd.DataFrame({"match": cells["match"].to_numpy(), "side": cells["side"].to_numpy(),
                          "team": cells["team"].to_numpy(), "opp": cells["opp"].to_numpy(),
                          "league": cells["league"].to_numpy(), "men": cells["uomini"].to_numpy(),
                          "n": cells[quantity].to_numpy(float) * weight,
                          "w": cells["stato"].map(states).to_numpy() * cells["fascia"].map(bands).to_numpy()
                          * cells["esposizione"].to_numpy(float) * weight})
    pair = frame.groupby(["match", "side"], sort=False).agg(n=("n", "sum"), w=("w", "sum"), team=("team", "first"),
                                                            opp=("opp", "first"), league=("league", "first"))

    def rest(key):
        return ((pair.groupby(key)["n"].transform("sum") - pair["n"])
                / np.maximum(pair.groupby(key)["w"].transform("sum") - pair["w"], 1e-12))

    base = rest("team") * rest("opp") / np.maximum(rest("league"), 1e-12)
    frame = frame.join(base.rename("base"), on=["match", "side"])
    frame["atteso"] = frame["base"] * frame["w"]
    frame = frame[np.isfinite(frame["atteso"])]
    ratio = frame.groupby("men")["n"].sum() / np.maximum(frame.groupby("men")["atteso"].sum(), 1e-12)
    return {men: float(ratio.get(men, np.nan) / ratio[0]) for men in MEN}


def men_section(cells: pd.DataFrame, draws: list[np.ndarray]) -> dict:
    """Effetto dell'inferiorità e della superiorità numerica (stato e fascia come controlli)."""
    exposure = cells.groupby("uomini")["esposizione"].sum() / 2
    section = {"minuti": {str(men): float(exposure.get(men, 0.0)) for men in MEN}, "quantita": {}}
    for quantity in QUANTITIES:
        fixed = fit_men_effects(cells, quantity)
        if quantity in MEN_BETWEEN:
            effects = fit_state_effects(cells, quantity)
            point = fit_men_between(cells, quantity, effects=effects)
            boot = [fit_men_between(cells, quantity, weights, effects) for weights in draws]
        else:
            point = fixed
            boot = [fit_men_effects(cells, quantity, weights, iterations=60) for weights in draws]
        section["quantita"][quantity] = {
            **{str(men): {"moltiplicatore": point[men],
                          "es": float(np.std([np.log(max(b[men], 1e-9)) for b in boot], ddof=1)) if boot else None}
               for men in MEN},
            "metodo": "tra partite" if quantity in MEN_BETWEEN else "effetto fisso",
            **({"effetto_fisso": {str(men): fixed[men] for men in MEN}} if quantity in MEN_BETWEEN else {})}
    section["nota"] = ("moltiplicatore del tasso per minuto con un uomo in meno (−1) o in più (+1) rispetto alla parità, "
                       "a parità di stato del punteggio e fascia; rossi diretti e seconde gialle insieme. Tiri, xG e corner: "
                       "effetto fisso per squadra-partita. Falli e gialli: tra partite (atteso dalle altre partite di squadra "
                       "e avversario), perché i cartellini precedono il rosso e l'effetto fisso gonfia il calo dopo "
                       "(«effetto_fisso» resta per confronto)")
    return section


# --- 4-5. Dizionario tattico e incroci ----------------------------------------------------------------------------------

def poisson_fit(y: np.ndarray, X: np.ndarray, offset: np.ndarray, groups: np.ndarray,
                iterations: int = 50) -> tuple[np.ndarray, np.ndarray]:
    """Regressione di Poisson (IRLS) con errore standard robusto per gruppo (sandwich, correzione G/(G−1)).

    La prima colonna di ``X`` è la costante."""
    beta = np.zeros(X.shape[1])
    beta[0] = math.log(max(y.mean(), 1e-9) / max(np.exp(offset).mean(), 1e-9))
    for _ in range(iterations):
        mu = np.exp(X @ beta + offset)
        step = np.linalg.solve(X.T @ (X * mu[:, None]), X.T @ (y - mu))
        beta += step
        if np.max(np.abs(step)) < 1e-9:
            break
    mu = np.exp(X @ beta + offset)
    bread = np.linalg.inv(X.T @ (X * mu[:, None]))
    codes, unique = pd.factorize(groups)
    scores = np.zeros((len(unique), X.shape[1]))
    np.add.at(scores, codes, X * (y - mu)[:, None])
    g = len(unique)
    cov = bread @ (scores.T @ scores) @ bread * g / max(g - 1, 1)
    return beta, np.sqrt(np.diag(cov))


def ols_fit(y: np.ndarray, X: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    residual = y - X @ beta
    bread = np.linalg.inv(X.T @ X)
    codes, unique = pd.factorize(groups)
    scores = np.zeros((len(unique), X.shape[1]))
    np.add.at(scores, codes, X * residual[:, None])
    g = len(unique)
    cov = bread @ (scores.T @ scores) @ bread * g / max(g - 1, 1)
    return beta, np.sqrt(np.diag(cov))


def match_counts(matches: list[dict]) -> pd.DataFrame:
    """Conteggi per squadra-partita dal dettaglio: tiri per tipo, corner per origine, falli."""
    rows = []
    for match in matches:
        for side in ("h", "a"):
            kinds = [shot_type(shot) for shot in match["shots"] if shot["s"] == side]
            corners = [corner["o"] for corner in match["corners"] if corner["s"] == side]
            rows.append({"match": match["id"], "venue": side,
                         "tiri_transizione": kinds.count("transizione"), "tiri_fuori_area": kinds.count("fuori_area"),
                         "tiri_da_cross": sum(1 for shot in match["shots"] if shot["s"] == side and shot.get("cross")),
                         "azioni_pericolose": sum(kind in OPEN_PLAY for kind in kinds),
                         "corner_fasce": corners.count("cross"), "corner_tot": len(corners),
                         "falli_fatti": sum(1 for foul in match["fouls"] if foul["s"] == side)})
    return pd.DataFrame(rows)


# (termine, tasso) → (lato del punteggio, colonna osservata della squadra in attacco, misura del termine)
#   lato «att»: punteggio della squadra della riga; «dif»: punteggio dell'avversario (la riga conta ciò che concede).
EFFECTS = {
    ("possesso", "quota_possesso"): ("att", "quota_passaggi", "pass_share"),
    ("possesso", "tiri_transizione"): ("att", "tiri_transizione", "pass_share"),
    ("possesso", "tiri_fuori_area"): ("att", "tiri_fuori_area", "pass_share"),
    ("verticalizzazione", "tiri_transizione"): ("att", "tiri_transizione", "vert"),
    ("verticalizzazione", "azioni_pericolose"): ("att", "azioni_pericolose", "vert"),
    ("altezza_linea", "tiri_transizione_concessi"): ("dif", "tiri_transizione", "height"),
    ("altezza_linea", "corner_concessi"): ("dif", "corner_tot", "height"),
    ("pressing", "falli_fatti"): ("att", "falli_fatti", "press"),
    ("transizione", "tiri_transizione"): ("att", "tiri_transizione", "vert"),
    ("fasce_cross", "cross"): ("att", "crosses", "cross_avg"),
    ("fasce_cross", "tiri_da_cross"): ("att", "tiri_da_cross", "cross_avg"),
    ("fasce_cross", "corner_fasce"): ("att", "corner_fasce", "cross_avg"),
    ("gestione_blocco_basso", "tiri_contro_blocco_basso"): ("att", "azioni_pericolose", "xg_avg"),
}
NOT_MEASURABLE = {
    "recuperi_alti": "recuperi del pallone con la posizione non salvati nel riassunto StatsBomb",
    "attenuazione_incroci": "l'adattabilità non ha un indicatore nei dati: restano i valori fissi della fase Q",
    "spinta_in_svantaggio": "nessun indicatore per squadra; effetto medio nello stato di partita (sezione stato_partita)",
    "spinta_in_vantaggio": "nessun indicatore per squadra; effetto medio nello stato di partita (sezione stato_partita)",
}
NOT_MEASURABLE_TERMS = {"marcatura": "uomo/zona non si ricava dagli eventi aperti"}
PROXY = {"pass_share": "quota di passaggi riusciti di stagione (terzili)", "vert": "progressione per passaggio (terzili; "
         "transizione: quintili)", "height": "altezza media delle azioni difensive (terzili)", "press": "pressioni per "
         "passaggio avversario (terzili)", "cross_avg": "cross per partita (terzili)", "xg_avg": "xG prodotti (terzili, "
         "proxy della qualità: la forza è tra i controlli), solo contro avversari a blocco basso"}
INTERACTIONS = (
    {"id": "verticali_contro_linea_alta", "attacco": "verticalizzazione", "difesa": "altezza_linea",
     "tasso": "tiri_transizione", "colonna": "tiri_transizione"},
    {"id": "possesso_contro_pressing", "attacco": "possesso", "difesa": "pressing", "tasso": "falli_fatti",
     "colonna": "falli_subiti"},
    {"id": "cross_contro_blocco_basso", "attacco": "fasce_cross", "difesa": "altezza_linea", "tasso": "corner_fasce",
     "colonna": "corner_fasce"},
)


def style_rows(matches: list[dict], dictionary: dict) -> pd.DataFrame:
    """Una riga per squadra in attacco contro l'avversario (suffisso _d) con punteggi dei termini e conteggi."""
    rows = statsbomb_rows()
    broken = rows.loc[(rows["passes"] == 0) | (rows["opp_passes"] == 0), "match"]  # eventi di una squadra mancanti
    rows = rows[~rows["match"].isin(broken)].copy()
    passes =rows.groupby(["season", "team"])[["passes", "opp_passes"]].transform("sum") - rows[["passes", "opp_passes"]]
    rows["pass_share"] = passes["passes"] / (passes["passes"] + passes["opp_passes"])
    rows["quota_passaggi"] = rows["passes"] / (rows["passes"] + rows["opp_passes"])
    seasons = rows.groupby("season")
    scores = {"possesso": ("pass_share", ("diretto", "misto", "palla_a_terra")),
              "verticalizzazione": ("vert", ("bassa", "media", "alta")),
              "fasce_cross": ("cross_avg", ("basso", "medio", "alto")),
              "gestione_blocco_basso": ("xg_avg", ("scarsa", "media", "buona"))}
    for term, (column, labels) in scores.items():
        rows[f"lab_{term}"] = seasons[column].transform(lambda values, labels=labels: _bins(values, labels))
    rows["lab_altezza_linea"], rows["lab_pressing"] = rows["blocco"], rows["pressing"]
    rows["lab_transizione"] = rows["transizione"].astype("Int64").astype(str)
    for term in ("possesso", "verticalizzazione", "altezza_linea", "pressing", "transizione", "fasce_cross",
                 "gestione_blocco_basso"):
        rows[f"sc_{term}"] = rows[f"lab_{term}"].map(dictionary["termini"][term]["punteggio"]).astype(float)
    rows["strength"] = rows["xg_avg"] - rows["xga_avg"]
    rows["home"] = (rows["venue"] == "h").astype(float)
    counts = match_counts(matches)
    rows = rows.merge(counts, on=["match", "venue"], how="inner")
    pairs = rows.merge(rows, left_on=["match", "opponent"], right_on=["match", "team"], suffixes=("", "_d"))
    pairs["falli_subiti"] = pairs["falli_fatti_d"]
    for column in ("tiri_transizione", "tiri_fuori_area", "tiri_da_cross", "azioni_pericolose", "corner_fasce", "corner_tot",
                   "falli_fatti", "crosses"):
        # media di stagione (senza la partita) di ciò che l'avversario concede / produce, per l'offset
        conceded = pairs.groupby(["season", "team_d"])[column].transform("sum") - pairs[column]
        produced = pairs.groupby(["season", "team"])[column].transform("sum") - pairs[column]
        games = pairs.groupby(["season", "team"])["match"].transform("count") - 1
        league = pairs.groupby("season")[column].transform("mean")
        pairs[f"conc_{column}"] = (conceded / games.replace(0, np.nan)) / league
        pairs[f"prod_{column}"] = (produced / games.replace(0, np.nan)) / league
    fouled = pairs.groupby(["season", "team_d"])["falli_subiti"].transform("sum") - pairs["falli_subiti"]
    pairs["prod_falli_subiti"] = fouled / (pairs.groupby(["season", "team_d"])["match"].transform("count") - 1) / \
        pairs.groupby("season")["falli_subiti"].transform("mean")
    pairs["conc_falli_subiti"] = (pairs.groupby(["season", "team"])["falli_subiti"].transform("sum") - pairs["falli_subiti"]) / \
        (pairs.groupby(["season", "team"])["match"].transform("count") - 1) / pairs.groupby("season")["falli_subiti"].transform("mean")
    return pairs


def _regression(pairs: pd.DataFrame, column: str, scores: list[np.ndarray], offset_column: str | None) -> dict:
    base = [np.ones(len(pairs)), pairs["strength"].to_numpy(float), pairs["strength_d"].to_numpy(float),
            pairs["home"].to_numpy(float)]
    X = np.column_stack(base + scores)  # costante in prima colonna (punto di partenza dell'IRLS)
    y = pairs[column].to_numpy(float)
    groups = pairs["match"].to_numpy()
    if column == "quota_passaggi":
        beta, se = ols_fit(np.log(y), X, groups)
    else:
        offset = np.log(pairs[offset_column].to_numpy(float)) if offset_column else np.zeros(len(pairs))
        beta, se = poisson_fit(y, X, offset, groups)
    return {"beta": [float(value) for value in beta[len(base):]], "es": [float(value) for value in se[len(base):]]}


def dictionary_section(pairs: pd.DataFrame, dictionary: dict) -> tuple[dict, dict]:
    """(stime per termine e tasso, dizionario aggiornato). Beta nel dizionario solo se l'IC 95% esclude lo zero."""
    updated = json.loads(json.dumps(dictionary))
    estimates = {}
    for term, spec in updated["termini"].items():
        for effect in spec["effetti"]:
            key = (term, effect["tasso"])
            reason = NOT_MEASURABLE_TERMS.get(term) or NOT_MEASURABLE.get(effect["tasso"])
            if key not in EFFECTS:
                effect.update(beta=None, intervallo=None, n=0, fonte=None, motivo=reason or "non misurabile nei dati")
                estimates[f"{term}|{effect['tasso']}"] = {"stimabile": False, "motivo": effect["motivo"]}
                continue
            side, column, proxy = EFFECTS[key]
            data = pairs.copy()
            if term == "gestione_blocco_basso":
                data = data[data["lab_altezza_linea_d"] == "basso"]
            score_column = f"sc_{term}" if side == "att" else f"sc_{term}_d"
            data = data.dropna(subset=[score_column, "strength", "strength_d", column])
            offset = None if column == "quota_passaggi" else (f"conc_{column}" if side == "att" else f"prod_{column}")
            if offset:
                data = data[np.isfinite(data[offset]) & (data[offset] > 0)]
            fit = _regression(data, column, [data[score_column].to_numpy(float)], offset)
            beta, se = fit["beta"][0], fit["es"][0]
            low, high = beta - 1.96 * se, beta + 1.96 * se
            significant = low > 0 or high < 0
            row = {"stimabile": True, "beta_grezzo": beta, "es": se, "intervallo": [low, high], "n": int(len(data)),
                   "significativo": significant, "segno_atteso": effect["segno"],
                   "segno_concorde": bool(np.sign(beta) == effect["segno"]), "proxy": PROXY[proxy]}
            estimates[f"{term}|{effect['tasso']}"] = row
            effect.update(beta=round(beta, 4) if significant else 0.0, intervallo=[round(low, 4), round(high, 4)],
                          n=int(len(data)), fonte=f"{SOURCE}; proxy: {PROXY[proxy]}")
            effect.pop("motivo", None)
            if not significant:
                effect["motivo"] = f"stima {beta:+.3f} ± {1.96 * se:.3f} non distinguibile da zero: beta 0"
            elif not row["segno_concorde"]:
                effect["motivo"] = f"segno opposto all'atteso ({beta:+.3f}): tenuto come stimato, da rivedere"
    updated["stima"] = {"data": date.today().isoformat(), "strumento": "python -m tools.stima_motore", "fonte": SOURCE,
                        "regola": "beta = coefficiente di Poisson (quota possesso: log-lineare) con controlli forza "
                                  "delle due squadre e casa; nel dizionario solo se l'IC 95% esclude lo zero",
                        "nota_proxy": "verticalizzazione e transizione usano lo stesso indicatore: non sommarle"}
    return estimates, updated


def interactions_section(pairs: pd.DataFrame) -> dict:
    result = {}
    for spec in INTERACTIONS:
        attack, defence = f"sc_{spec['attacco']}", f"sc_{spec['difesa']}_d"
        column = spec["colonna"]
        data = pairs.dropna(subset=[attack, defence, "strength", "strength_d", column])
        offset = f"conc_{column}"
        data = data[np.isfinite(data[offset]) & (data[offset] > 0)]
        a, d = data[attack].to_numpy(float), data[defence].to_numpy(float)
        fit = _regression(data, column, [a * d, a, d], offset)
        beta, se = fit["beta"][0], fit["es"][0]
        result[spec["id"]] = {**spec, "beta": beta, "es": se, "intervallo": [beta - 1.96 * se, beta + 1.96 * se],
                              "significativo": abs(beta) > 1.96 * se, "n": int(len(data)), "attiva": False}
    return result


# --- 6. Arbitri -----------------------------------------------------------------------------------------------------------

def referee_section(matches: list[dict]) -> dict:
    csv = dataset.load_raw(("E0", "SC0"), ("1920", "2021", "2122", "2223", "2324", "2425", "2526"))
    csv = csv.assign(fouls=csv["home_fouls"] + csv["away_fouls"], yellows=csv["home_yellows"] + csv["away_yellows"])
    names = {"E0": "Premier League", "SC0": "Scozia"}
    csv["league"] = csv["league"].map(names)
    columns = {"falli": "fouls", "gialli": "yellows"}
    section = {"football_data": referee_stats.estimate(csv, columns),
               "gialli_e_falli": {names[code]: referee_stats.cards_per_foul(csv[csv["league"] == names[code]])
                                  for code in names}}
    sb = pd.DataFrame([{"league": match["league"], "season": match["season_key"], "referee": match.get("referee"),
                        "fouls": len(match["fouls"]),
                        "yellows": sum(foul.get("card") in YELLOW for foul in match["fouls"]) +
                        sum(card.get("card") in YELLOW for card in match["cards"])}
                       for match in matches if match["league"] not in NO_OWN_EFFECTS])
    section["statsbomb_2015_16"] = referee_stats.estimate(sb, columns)
    section["nota"] = ("k = shrinkage stimato (valore arbitro = media + n/(n+k)·scarto); l'app oggi usa k=10 fisso "
                       "(datasources.stats.REFEREE_PRIOR_MATCHES): il cambio si decide con il banco dello stadio 14. "
                       "Effetti confusi con le squadre arbitrate (designazioni non casuali).")
    return section


ATTENUATION_GRID = tuple(round(0.1 * step, 1) for step in range(11))


def _fe_poisson(y: np.ndarray, X: np.ndarray, ridge: float = 1e-4, iterations: int = 60) -> np.ndarray:
    """Medie di una Poisson con effetti fissi (IRLS con una piccola cresta: le leghe sono componenti separate)."""
    beta = np.zeros(X.shape[1])
    beta[0] = math.log(max(y.mean(), 1e-9))
    for _ in range(iterations):
        mu = np.exp(X @ beta)
        step = np.linalg.solve(X.T @ (X * mu[:, None]) + ridge * np.eye(X.shape[1]), X.T @ (y - mu) - ridge * beta)
        beta += step
        if np.max(np.abs(step)) < 1e-10:
            break
    return np.exp(X @ beta)


def attenuation_section(matches: list[dict], config: dict, draws: int = 20, bootstrap: int = 200, seed: int = 3) -> dict:
    """Esponente a dei moltiplicatori di stato per inferenza indiretta (stadio 12).

    Gli effetti di stato stimati dentro la partita sono gonfiati: i minuti prima di un gol sono minuti di pressione, quelli
    dopo tornano alla media. Misura: pendenza dei tiri sbagliati (senza rigori) sui gol della stessa squadra-partita, dai
    residui di una Poisson con attacco, difesa avversaria e casa (StatsBomb 2015/16, senza la Bundesliga). Il motore a
    eventi in modo «punteggi» con moltiplicatori^a, simulato sugli stessi gol attesi, dà la stessa pendenza con l'esponente
    scelto (interpolazione lineare sulla griglia 0-1); errore standard = bootstrap per partita della pendenza osservata
    diviso la pendenza della curva del motore."""
    import event_engine

    rows = []
    for match in matches:
        if match["league"] in NO_OWN_EFFECTS:
            continue
        for side in ("h", "a"):
            shots = [shot for shot in match["shots"] if shot["s"] == side and shot_type(shot) != "rigore"]
            rows.append({"match": match["id"], "team": match["home"] if side == "h" else match["away"],
                         "opp": match["away"] if side == "h" else match["home"], "home": int(side == "h"),
                         "goals": sum(1 for shot in shots if shot["g"]), "misses": sum(1 for shot in shots if not shot["g"])})
    frame = pd.DataFrame(rows)
    X = np.column_stack([np.ones(len(frame)), frame["home"],
                         pd.get_dummies(frame["team"]).to_numpy(float)[:, 1:], pd.get_dummies(frame["opp"]).to_numpy(float)[:, 1:]])
    goal_mean = _fe_poisson(frame["goals"].to_numpy(float), X)
    miss_mean = _fe_poisson(frame["misses"].to_numpy(float), X)
    goals_res, miss_res = frame["goals"].to_numpy(float) - goal_mean, frame["misses"].to_numpy(float) - miss_mean
    observed = float((goals_res * miss_res).sum() / (goals_res ** 2).sum())
    rng = np.random.default_rng(seed)
    codes, unique = pd.factorize(frame["match"])
    boot = []
    for _ in range(bootstrap):
        weights = np.bincount(rng.choice(len(unique), len(unique)), minlength=len(unique))[codes]
        boot.append(float((weights * goals_res * miss_res).sum() / (weights * goals_res ** 2).sum()))
    error = float(np.std(boot, ddof=1))
    base = event_engine.EventParams.from_config(config, None, attenuate=False)
    pairs = frame.assign(mean=goal_mean).groupby("match", sort=False)["mean"].agg(list)
    # Partite raggruppate per gol attesi arrotondati (un'unica simulazione vettoriale per gruppo).
    keys = pd.Series([(round(values[0], 1), round(values[1], 1)) for values in pairs]).value_counts()
    curve = []
    for power in ATTENUATION_GRID:
        params = base.with_state_power(power)
        sim_rng = np.random.default_rng([seed, int(power * 10)])
        numerator = denominator = 0.0
        for (lam, mu), count in keys.items():
            lam, mu, n = max(lam, 0.05), max(mu, 0.05), int(count) * draws
            scores = (sim_rng.poisson(lam, n), sim_rng.poisson(mu, n))
            sample = event_engine.simulate(sim_rng, n, event_engine.TeamInput(lam, first_share=0.45),
                                           event_engine.TeamInput(mu, first_share=0.45), params, scores=scores)
            for side in ("home", "away"):
                penalties = sample[f"goals_by_type_{side}"][:, event_engine.PENALTY]
                goals = sample[f"goals_{side}"] - penalties
                misses = (sample[f"shots_{side}"] - sample[f"goals_by_type_{side}"]).sum(axis=1) - (
                    sample[f"shots_{side}"][:, event_engine.PENALTY] - penalties)
                goals, misses = goals - goals.mean(), misses - misses.mean()
                numerator += float((goals * misses).sum())
                denominator += float((goals ** 2).sum())
        curve.append(numerator / denominator)
    grid = np.asarray(ATTENUATION_GRID)
    order = np.argsort(curve)
    power = float(np.clip(np.interp(observed, np.asarray(curve)[order], grid[order]), 0.0, 1.0))
    derivative = float(abs(np.polyfit(grid, curve, 1)[0]))
    return {
        "esponente": round(power, 3), "errore_standard": round(error / derivative, 3),
        "intervallo_95": [round(max(power - 1.96 * error / derivative, 0.0), 3), round(min(power + 1.96 * error / derivative, 1.0), 3)],
        "pendenza_osservata": round(observed, 4), "errore_pendenza": round(error, 4),
        "curva_motore": {f"{value:g}": round(slope, 4) for value, slope in zip(ATTENUATION_GRID, curve)},
        "partite": int(len(unique)), "simulazioni_per_partita": draws,
        "metodo": "inferenza indiretta: pendenza tiri sbagliati ~ gol (residui Poisson con attacco, difesa, casa) osservata "
                  "contro quella del motore a eventi in modo punteggi con moltiplicatori di stato^a",
        "nota": "lo stesso esponente si applica a tiri, xG, corner di gioco, falli e gialli (ipotesi dichiarata: la stessa "
                "distorsione delle stime dentro la partita); effetti dell'uomo in meno/in più e fasce di minuti invariati.",
    }


def run(bootstrap: int = 200, update_dictionary: bool = True) -> dict:
    matches = load_detail()
    dictionary = tactical_dictionary.load()
    pairs = style_rows(matches, dictionary)
    estimates, updated = dictionary_section(pairs, dictionary)
    config = {
        "nota": "Fase AK: parametri del motore a eventi stimati con python -m tools.stima_motore. " + SOURCE +
                " (StatsBomb Open Data User Agreement) e football-data.co.uk per gli arbitri.",
        "data_stima": date.today().isoformat(),
        "campionati": {league: ("comune: StatsBomb pubblica solo le 34 partite del Leverkusen, nessun effetto proprio"
                                if league in NO_OWN_EFFECTS else "propri")
                       for league in LEAGUE_NAMES.values()},
        "partite": {league: sum(match["league"] == league for match in matches) for league in LEAGUE_NAMES.values()},
        "tipi_tiro": {"ordine": list(SHOT_TYPES),
                      "regola": "rigore > palla inattiva (punizione diretta o azione da corner) > transizione (contropiede) "
                                "> fuori area > testa da cross > azione"},
        "xg_per_tipo": shots_section(matches),
        "corner_falli": corners_fouls_section(matches),
        "stato_partita": state_section(matches, bootstrap),
        "dizionario": estimates,
        "incroci": interactions_section(pairs),
        "arbitri": referee_section(matches),
    }
    config["stato_partita"]["attenuazione"] = attenuation_section(matches, config)
    CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if update_dictionary:
        tactical_dictionary.PATH.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report(config), encoding="utf-8")
    return config


def report(config: dict) -> str:
    lines = [f"# Fase AK, stadio 2: stima del motore a eventi ({config['data_stima']})", "",
             f"{SOURCE}; arbitri da football-data.co.uk. Partite: " +
             ", ".join(f"{league} {count}" for league, count in config["partite"].items()) +
             ". Bundesliga solo nelle stime comuni.", "", "## Tiri per tipo (comune)", "",
             "| tipo | tiri/squadra-partita | quota | xG medio | gol/tiro | parati o respinti | n |", "|---|---|---|---|---|---|---|"]
    for kind, row in config["xg_per_tipo"]["comune"].items():
        lines.append(f"| {kind} | {row['tiri_per_squadra_partita']:.2f} | {row['quota']:.1%} | {row['xg_medio'] or 0:.3f} | "
                     f"{row['gol_per_tiro'] or 0:.3f} | {row['quota_parato_respinto'] or 0:.1%} | {row['n']} |")
    common = config["corner_falli"]["comune"]
    lines += ["", "## Corner e falli (comune)", "",
              "Corner per squadra-partita: " + ", ".join(f"{origin} {value:.2f}" for origin, value in
                                                         common["corner_per_squadra_partita"].items()) +
              f"; corner per tiro parato o respinto {common['corner_per_tiro_parato_respinto']:.2f}; falli per squadra-partita "
              f"{common['falli_per_squadra_partita']:.1f}; gialli per fallo {common['gialli_per_fallo']:.3f}.", "",
              "## Stato di partita (moltiplicatore rispetto al pareggio, ± 2 e.s.)", "",
              "| quantità | −2 | −1 | +1 | +2 |", "|---|---|---|---|---|"]
    for quantity, values in config["stato_partita"]["quantita"].items():
        cells = [f"{values['stato'][s]['moltiplicatore']:.2f} ± {2 * (values['stato'][s]['es'] or 0) * values['stato'][s]['moltiplicatore']:.2f}"
                 for s in ("-2", "-1", "1", "2")]
        lines.append(f"| {quantity} | " + " | ".join(cells) + " |")
    men = config["stato_partita"].get("espulsioni")
    if men:
        lines += ["", "## Espulsioni (moltiplicatore rispetto alla parità numerica, ± 2 e.s.)", "",
                  f"Minuti con un uomo in meno o in più: {men['minuti']['-1']:.0f} su "
                  f"{sum(men['minuti'].values()):.0f}. Rossi diretti per fallo "
                  f"{common['rossi_diretti_per_fallo']:.4f} ({common['rossi_diretti']}), seconda gialla per giallo preso da una "
                  f"squadra già ammonita {common['seconda_gialla_per_giallo_con_precedente']:.4f} ({common['seconde_gialle']}).", "",
                  "| quantità | uomo in meno | uomo in più |", "|---|---|---|"]
        for quantity, values in men["quantita"].items():
            lines.append(f"| {quantity} | " + " | ".join(
                f"{values[m]['moltiplicatore']:.2f} ± {2 * (values[m]['es'] or 0) * values[m]['moltiplicatore']:.2f}"
                for m in ("-1", "1")) + " |")
    attenuation = config["stato_partita"].get("attenuazione")
    if attenuation:
        lines += ["", "## Attenuazione degli effetti di stato (stadio 12)", "",
                  f"Esponente {attenuation['esponente']:g} (IC 95% {attenuation['intervallo_95'][0]:g}-{attenuation['intervallo_95'][1]:g}): "
                  f"pendenza tiri sbagliati ~ gol osservata {attenuation['pendenza_osservata']:+.3f} ± "
                  f"{2 * attenuation['errore_pendenza']:.3f} su {attenuation['partite']} partite; motore con esponente 1: "
                  f"{attenuation['curva_motore']['1']:+.3f}. {attenuation['nota']}"]
    lines += ["", "## Dizionario tattico", "", "| termine → tasso | beta | IC 95% | n | nel dizionario |", "|---|---|---|---|---|"]
    for key, row in config["dizionario"].items():
        if not row["stimabile"]:
            lines.append(f"| {key.replace('|', ' → ')} | — | — | — | null: {row['motivo']} |")
            continue
        verdict = "sì" if row["significativo"] else "0 (non distinguibile da zero)"
        if row["significativo"] and not row["segno_concorde"]:
            verdict += ", segno opposto all'atteso"
        lines.append(f"| {key.replace('|', ' → ')} | {row['beta_grezzo']:+.3f} | [{row['intervallo'][0]:+.3f}, "
                     f"{row['intervallo'][1]:+.3f}] | {row['n']} | {verdict} |")
    lines += ["", "## Incroci (solo stima, spenti)", "", "| incrocio | beta | IC 95% | n |", "|---|---|---|---|"]
    for name, row in config["incroci"].items():
        lines.append(f"| {name} | {row['beta']:+.3f} | [{row['intervallo'][0]:+.3f}, {row['intervallo'][1]:+.3f}] | {row['n']} |")
    lines += ["", "## Arbitri", "", "| fonte | campionato | quantità | arbitri | partite | quota varianza | k | fuori campione |",
              "|---|---|---|---|---|---|---|---|"]
    for source in ("football_data", "statsbomb_2015_16"):
        for league, quantities in config["arbitri"][source].items():
            for name, row in quantities.items():
                if not row.get("stimabile"):
                    lines.append(f"| {source} | {league} | {name} | {row.get('arbitri', 0)} | {row.get('partite', 0)} | — | — | — |")
                    continue
                oos = row.get("fuori_campione", {})
                gain = f"{oos['miglioramento_pct']:+.1f}% MSE" if oos.get("partite") else "—"
                k = f"{row['k']:.1f}" if row.get("k") else "∞"
                lines.append(f"| {source} | {league} | {name} | {row['arbitri']} | {row['partite']} | "
                             f"{row['quota_varianza_arbitro']:.1%} | {k} | {gain} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bootstrap", type=int, default=200)
    parser.add_argument("--no-dizionario", action="store_true", help="non scrivere i beta in config/dizionario_tattico.json")
    args = parser.parse_args()
    config = run(args.bootstrap, not args.no_dizionario)
    print(report(config))


if __name__ == "__main__":
    main()
