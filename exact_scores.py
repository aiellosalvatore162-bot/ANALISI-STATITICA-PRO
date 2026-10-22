"""Risultati esatti e gruppi di risultati, dallo stesso campione della simulazione.

La distribuzione dei risultati esatti è ``result["exact_scores"][componente]``
(percentuali, dal più probabile). Un risultato esatto determina tutti i
mercati che dipendono dal solo punteggio finale (1X2, Under/Over, Goal,
multigol…), quindi coerenza e correlazione di un gruppo con questi mercati
sono esatte sul campione, senza ricampionare.
"""

from __future__ import annotations

from functools import lru_cache
import re
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

SCORE = re.compile(r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*$")
GROUP = re.compile(r"^\d{1,2}-\d{1,2}(?:/\d{1,2}-\d{1,2})*$")
# Mercati mostrati nel controllo di coerenza, nell'ordine.
COHERENCE_MARKETS = ("1", "X", "2", "1X", "X2", "12", "Over 1.5 gol", "Under 1.5 gol", "Over 2.5 gol", "Under 2.5 gol",
                     "Over 3.5 gol", "Under 3.5 gol", "Goal", "No Goal")
UNCERTAINTY_NOTE = ("Il risultato esatto è il mercato meno stabile: anche con l'ancoraggio alle quote, la probabilità "
                    "di ogni singolo risultato dipende molto da λ, μ e dalla correzione Dixon-Coles e ha un'incertezza alta. "
                    "Usa i gruppi più che i singoli risultati e confronta modello e mercato.")


def parse_score(text: str) -> tuple[int, int]:
    match = SCORE.match(str(text))
    if not match:
        raise ValueError(f"Risultato «{text}» non valido: usa il formato casa-ospite, es. 2-1.")
    return int(match[1]), int(match[2])


def group_selection(scores: Iterable[str]) -> str:
    """Selezione del registro: risultati unici ordinati (casa, ospite) separati da «/», es. «1-0/2-0/2-1»."""
    parsed = sorted({parse_score(score) for score in scores})
    if not parsed:
        raise ValueError("Il gruppo deve contenere almeno un risultato.")
    return "/".join(f"{home}-{away}" for home, away in parsed)


def is_group(selection: str) -> bool:
    return bool(GROUP.match(selection.strip()))


def group_scores(selection: str) -> list[str]:
    return [f"{home}-{away}" for home, away in (parse_score(part) for part in selection.split("/"))]


def group_probability(distribution: Mapping[str, float], scores: Iterable[str]) -> float:
    """Probabilità (0-1) del gruppo nella distribuzione in percentuali."""
    return sum(float(distribution.get(score, 0.0)) for score in {f"{h}-{a}" for h, a in map(parse_score, scores)}) / 100.0


def settle_group(selection: str, home_goals: int, away_goals: int) -> int:
    return int(f"{int(home_goals)}-{int(away_goals)}" in set(group_scores(selection)))


def score_table(distribution: Mapping[str, float]) -> pd.DataFrame:
    """Risultati dal più probabile, con probabilità cumulata e quota equa (1/probabilità)."""
    rows, cumulative = [], 0.0
    for score, percentage in sorted(distribution.items(), key=lambda item: -item[1]):
        cumulative += percentage
        rows.append({"Risultato": score, "Probabilità %": round(percentage, 2), "Cumulata %": round(min(cumulative, 100.0), 2),
                     "Quota equa": round(100.0 / percentage, 2) if percentage > 0 else None})
    return pd.DataFrame(rows, columns=["Risultato", "Probabilità %", "Cumulata %", "Quota equa"])


def minimum_group(distribution: Mapping[str, float], coverage: float) -> tuple[list[str], float]:
    """Il minor numero di risultati (i più probabili) con probabilità totale ≥ ``coverage`` (0-1)."""
    chosen, total = [], 0.0
    for score, percentage in sorted(distribution.items(), key=lambda item: -item[1]):
        if total >= coverage * 100.0 - 1e-9:
            break
        chosen.append(score)
        total += percentage
    return chosen, total / 100.0


def group_value(probability: float, odds: float | None) -> dict[str, float | None]:
    """Quota equa e valore atteso per 1 unità puntata alla quota offerta."""
    fair = 1.0 / probability if probability > 0 else None
    ev = probability * odds - 1.0 if odds and odds > 1.0 else None
    return {"probability": probability, "fair_odds": fair, "ev": ev}


@lru_cache(maxsize=1)
def score_only_markets() -> tuple[str, ...]:
    """Eventi del motore che dipendono solo dal punteggio finale (stesso valore con ogni primo tempo, corner e cartellini)."""
    from engine import _event_catalog

    scores = [(home, away) for home in range(7) for away in range(7)]
    home = np.array([score[0] for score in scores])
    away = np.array([score[1] for score in scores])
    zero = np.zeros_like(home)
    variants = [
        _event_catalog(home, away, zero, zero, home, away, zero, zero, zero, zero),
        _event_catalog(home, away, home, away, zero, zero, zero + 9, zero + 7, zero + 5, zero + 4),
        _event_catalog(home, away, home // 2, away, home - home // 2, zero, zero + 3, zero + 12, zero + 1, zero + 6),
    ]
    keys = set(variants[0]).intersection(*variants[1:])
    return tuple(sorted(key for key in keys if all(np.array_equal(variants[0][key], other[key]) for other in variants[1:])))


def _membership(scores: Sequence[str], market: str) -> np.ndarray:
    from engine import _event_catalog

    parsed = [parse_score(score) for score in scores]
    home = np.array([score[0] for score in parsed])
    away = np.array([score[1] for score in parsed])
    zero = np.zeros_like(home)
    events = _event_catalog(home, away, zero, zero, home, away, zero, zero, zero, zero)
    return np.asarray(events[market], dtype=bool)


def coherence(distribution: Mapping[str, float], scores: Sequence[str],
              markets: Sequence[str] = COHERENCE_MARKETS) -> pd.DataFrame:
    """Quota della probabilità del gruppo che cade in ciascun mercato; 100% = il mercato contiene tutto il gruppo."""
    scores = group_scores(group_selection(scores))
    weights = np.array([float(distribution.get(score, 0.0)) for score in scores])
    total = weights.sum()
    rows = []
    for market in markets:
        inside = _membership(scores, market)
        share = float(weights[inside].sum() / total) if total > 0 else float(inside.mean())
        rows.append({"Mercato": market, "Quota del gruppo %": round(share * 100.0, 1),
                     "Risultati dentro": f"{int(inside.sum())}/{len(scores)}",
                     "Contiene tutto il gruppo": bool(inside.all())})
    return pd.DataFrame(rows)


def coherence_summary(table: pd.DataFrame) -> str:
    full = list(table.loc[table["Contiene tutto il gruppo"], "Mercato"])
    if not full:
        return "Il gruppo è distribuito su più esiti: nessuno dei mercati principali lo contiene per intero."
    return "Il gruppo è tutto " + ", tutto ".join(full) + "."


def correlation(distribution: Mapping[str, float], scores: Sequence[str], legs: Sequence[str],
                market_probabilities: Mapping[str, float]) -> pd.DataFrame:
    """Gruppo combinato in schedina con altri mercati: probabilità congiunta e ridondanza.

    Come nel Combo Builder, la probabilità della schedina è congiunta sul campione,
    non il prodotto delle probabilità. ``market_probabilities`` sono le percentuali
    finali dei mercati (``components["finale"]``).
    """
    scores = group_scores(group_selection(scores))
    weights = np.array([float(distribution.get(score, 0.0)) for score in scores]) / 100.0
    group = float(weights.sum())
    score_only = set(score_only_markets())
    rows = []
    for leg in legs:
        market = float(market_probabilities.get(leg, 0.0)) / 100.0
        if leg not in score_only:
            rows.append({"Mercato": leg, "Probabilità mercato %": round(market * 100, 2), "Probabilità congiunta %": None,
                         "Rapporto con l'indipendenza": None,
                         "Giudizio": "non calcolabile dai risultati esatti (dipende da primo tempo, corner o cartellini)"})
            continue
        inside = _membership(scores, leg)
        joint = float(weights[inside].sum())
        ratio = joint / (group * market) if group > 0 and market > 0 else None
        if inside.all():
            verdict = "ridondante: il mercato contiene già tutto il gruppo, la schedina vale quanto il solo gruppo"
        elif not inside.any():
            verdict = "incompatibile: nessun risultato del gruppo vince anche questo mercato"
        elif ratio is not None and ratio > 1.05:
            verdict = "correlazione positiva: la quota combinata sopravvaluta la schedina se calcolata come prodotto"
        elif ratio is not None and ratio < 0.95:
            verdict = "correlazione negativa"
        else:
            verdict = "quasi indipendenti"
        rows.append({"Mercato": leg, "Probabilità mercato %": round(market * 100, 2), "Probabilità congiunta %": round(joint * 100, 2),
                     "Rapporto con l'indipendenza": round(ratio, 3) if ratio is not None else None, "Giudizio": verdict})
    return pd.DataFrame(rows, columns=["Mercato", "Probabilità mercato %", "Probabilità congiunta %",
                                       "Rapporto con l'indipendenza", "Giudizio"])
