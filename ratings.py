"""Fase P, punto 1: forza delle squadre corretta per il calendario.

Attacco e difesa di tutte le squadre di un campionato stimati insieme con un modello di Poisson log-lineare
(Dixon-Coles senza la correzione dei punteggi bassi, che non cambia le forze): gol attesi della squadra di
casa = exp(base + casa + attacco_casa − difesa_ospite), dell'ospite = exp(base + attacco_ospite − difesa_casa).
Ogni partita pesa exp(−ξ · giorni fa) (decadimento temporale); la risposta può mescolare gol e xG
(quasi-verosimiglianza di Poisson, valida anche per valori non interi). Le forze di squadre con poche partite
sono riavvicinate a 0 (media del campionato) con ``prior`` partite fittizie. Stima per aggiornamenti alternati
in forma chiusa (veloce: serve migliaia di volte nella verifica storica).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math
from typing import Mapping

import numpy as np
import pandas as pd


FLOOR = 0.05  # gol (pesati) minimi: senza riavvicinamento una squadra a 0 gol non ha forza infinita


@dataclass(frozen=True)
class StrengthParams:
    active: bool = False
    decay_per_day: float = 0.002     # ξ
    goal_weight: float = 1.0         # risposta = peso·gol + (1 − peso)·xG
    window_days: int = 730
    prior_matches: float = 3.0
    mode: str = "ingressi"           # «ingressi»: attacco/difesa del blocco; «diretto»: gol attesi del modello


@dataclass
class Strengths:
    attack: dict[str, float]
    defence: dict[str, float]
    base: float
    home: float
    matches: dict[str, float] = field(default_factory=dict)   # partite (pesate) per squadra

    def rates(self, home: str, away: str) -> tuple[float, float]:
        a_h, d_h = self.attack.get(home, 0.0), self.defence.get(home, 0.0)
        a_a, d_a = self.attack.get(away, 0.0), self.defence.get(away, 0.0)
        return math.exp(self.base + self.home + a_h - d_a), math.exp(self.base + a_a - d_h)

    def ratios(self, team: str) -> tuple[float, float]:
        """(attacco, difesa) sulla scala del blocco: 1 = media del campionato, difesa > 1 = subisce meno."""
        return math.exp(self.attack.get(team, 0.0)), math.exp(self.defence.get(team, 0.0))


def fit(matches: pd.DataFrame, as_of: date | pd.Timestamp, params: StrengthParams = StrengthParams(),
        iterations: int = 60) -> Strengths | None:
    """Forze alla data ``as_of`` dalle partite precedenti (colonne date, home_team, away_team, home_goals,
    away_goals e, facoltative, home_xg/away_xg)."""
    as_of = pd.Timestamp(as_of)
    past = matches[(matches["date"] < as_of) & (matches["date"] >= as_of - pd.Timedelta(days=params.window_days))]
    past = past.dropna(subset=["home_goals", "away_goals"])
    if len(past) < 20:
        return None
    age = (as_of - past["date"]).dt.days.to_numpy(float)
    weight = np.exp(-params.decay_per_day * age)
    y_home, y_away = past["home_goals"].to_numpy(float), past["away_goals"].to_numpy(float)
    if params.goal_weight < 1.0 and "home_xg" in past:
        xg_home, xg_away = past["home_xg"].to_numpy(float), past["away_xg"].to_numpy(float)
        has = np.isfinite(xg_home) & np.isfinite(xg_away)
        y_home = np.where(has, params.goal_weight * y_home + (1 - params.goal_weight) * xg_home, y_home)
        y_away = np.where(has, params.goal_weight * y_away + (1 - params.goal_weight) * xg_away, y_away)
    teams, codes = np.unique(np.concatenate([past["home_team"].to_numpy(str), past["away_team"].to_numpy(str)]),
                             return_inverse=True)
    h, a = codes[:len(past)], codes[len(past):]
    n = len(teams)
    attack, defence = np.zeros(n), np.zeros(n)
    base = math.log(max((weight * (y_home + y_away)).sum() / (2 * weight.sum()), 1e-6))
    home_adv = 0.0
    played = np.bincount(h, weight, n) + np.bincount(a, weight, n)
    for _ in range(iterations):
        # Attacco: gol fatti / gol attesi con attacco 0, con il riavvicinamento alla media.
        exposure_home = weight * np.exp(base + home_adv - defence[a])
        exposure_away = weight * np.exp(base - defence[h])
        scored = np.bincount(h, weight * y_home, n) + np.bincount(a, weight * y_away, n)
        exposure = np.bincount(h, exposure_home, n) + np.bincount(a, exposure_away, n)
        prior = params.prior_matches * exposure / np.maximum(played, 1e-9)
        attack = np.log(np.maximum(scored + prior, FLOOR) / (exposure + prior))
        # Difesa: gol attesi subiti con difesa 0 / gol subiti.
        exposure_home = weight * np.exp(base + home_adv + attack[h])   # subiti dalla squadra ospite
        exposure_away = weight * np.exp(base + attack[a])              # subiti dalla squadra di casa
        conceded = np.bincount(a, weight * y_home, n) + np.bincount(h, weight * y_away, n)
        exposure = np.bincount(a, exposure_home, n) + np.bincount(h, exposure_away, n)
        prior = params.prior_matches * exposure / np.maximum(played, 1e-9)
        defence = np.log((exposure + prior) / np.maximum(conceded + prior, FLOOR))
        shift_attack, shift_defence = attack.mean(), defence.mean()
        attack, defence = attack - shift_attack, defence - shift_defence
        base += shift_attack - shift_defence
        expected_home = weight * np.exp(base + attack[h] - defence[a])
        expected_away = weight * np.exp(base + attack[a] - defence[h])
        home_adv = math.log((weight * y_home).sum() / expected_home.sum())
        base = math.log((weight * (y_home + y_away)).sum() / (expected_home.sum() * math.exp(home_adv) + expected_away.sum()))
    return Strengths(dict(zip(teams, attack)), dict(zip(teams, defence)), float(base), float(home_adv),
                     dict(zip(teams, played)))


def params_from_config(section: Mapping | None) -> StrengthParams:
    values = dict((section or {}).get("parametri") or {})
    values["active"] = bool((section or {}).get("attiva", False))
    names = StrengthParams.__dataclass_fields__
    return StrengthParams(**{key: value for key, value in values.items() if key in names})
