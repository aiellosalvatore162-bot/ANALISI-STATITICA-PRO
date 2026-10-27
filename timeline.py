"""Motore minuto per minuto (fase O): ogni simulazione avanza a blocchi di 5 minuti.

I ritmi di gol, corner e cartellini dipendono dal minuto, dal punteggio e dalle espulsioni con le regole
stimate da ``python -m tools.minute_model`` (sezione ``minuto_per_minuto`` di ``config/goal_model.json``).
Le medie già tarate restano quelle: le basi dei gol si riscalano su una simulazione pilota finché i gol
attesi tornano ``λ`` e ``μ`` (e la quota del primo tempo quella tarata); corner e cartellini restano
binomiali negative con la media moltiplicata per un fattore di percorso di media 1. Cambiano la
distribuzione nel tempo e le correlazioni tra mercati.

Ogni componente è un'opzione (``gol_stato``, ``espulsioni``, ``corner_pressione``, ``cartellini_tempo``)
e resta accesa solo se migliora fuori campione (``python -m tools.minute_check``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

BLOCKS = 18
BANDS = ((0, 30), (30, 60), (60, 75), (75, 90))
STATES = (-2, -1, 0, 1, 2)
COMPONENTS = ("gol_stato", "espulsioni", "corner_pressione", "cartellini_tempo")
# Fase Q, punto 0: punteggi finali Dixon-Coles fissi; le regole di stato (e le espulsioni) decidono solo
# QUANDO arrivano i gol già decisi, e guidano corner e cartellini.
HYBRID_COMPONENTS = ("tempi_stato", "espulsioni_tempi")
ALL_COMPONENTS = (*COMPONENTS, *HYBRID_COMPONENTS)


def _block_band(block: int) -> int:
    end = 5 * (block + 1)
    return next(index for index, (low, high) in enumerate(BANDS) if end <= high)


BLOCK_BANDS = np.array([_block_band(block) for block in range(BLOCKS)])


@dataclass(frozen=True)
class TimelineParams:
    active: bool = False
    components: tuple[str, ...] = ()
    goal_weights: tuple[float, ...] = (1.0,) * BLOCKS
    state: Mapping[int, tuple[float, ...]] = field(default_factory=lambda: {s: (1.0,) * len(BANDS) for s in STATES})
    fewer_players: float = 1.0
    more_players: float = 1.0
    corner_weights: tuple[float, ...] = (1.0,) * BLOCKS
    corner_gamma: float = 1.0
    card_weights: tuple[float, ...] = (1.0,) * BLOCKS
    card_level: tuple[float, ...] = (1.0,) * len(BANDS)
    red_weights: tuple[float, ...] = (1.0,) * BLOCKS
    # Fase Q: reazioni dalle schede tattiche (casa in svantaggio, casa in vantaggio, ospite in svantaggio, ospite in
    # vantaggio), moltiplicano lo stato del punteggio della squadra; 1.0 = nessuna scheda.
    reactions: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)

    def uses(self, component: str) -> bool:
        return self.active and component in self.components

    def first_half_shares(self) -> tuple[float, float]:
        """Quota del primo tempo di corner e cartellini dai pesi dei blocchi (StatsBomb), senza effetti di stato."""
        corners, cards = np.asarray(self.corner_weights, float), np.asarray(self.card_weights, float)
        return float(corners[:9].sum() / corners.sum()), float(cards[:9].sum() / cards.sum())

    def with_components(self, components) -> "TimelineParams":
        from dataclasses import replace

        return replace(self, active=bool(components), components=tuple(components))


def params_from_config(section: Mapping[str, Any]) -> TimelineParams:
    values = section.get("parametri") or {}
    if not values:
        return TimelineParams()
    goal = values["gol"]
    return TimelineParams(
        active=bool(section.get("attivo", False)),
        components=tuple(name for name, on in (section.get("componenti") or {}).items() if on),
        goal_weights=tuple(goal["pesi_blocchi"]),
        state={int(key): tuple(value) for key, value in goal["stato"].items()},
        fewer_players=float(goal["superiorita"]["meno_uomini"]), more_players=float(goal["superiorita"]["piu_uomini"]),
        corner_weights=tuple(values["corner"]["pesi_blocchi"]), corner_gamma=float(values["corner"]["gamma"]),
        card_weights=tuple(values["cartellini"]["pesi_blocchi"]), card_level=tuple(values["cartellini"]["parita"]),
        red_weights=tuple(values["espulsioni_pesi_blocchi"]),
    )


def load(path: Path) -> TimelineParams:
    if not path.exists():
        return TimelineParams()
    return params_from_config(json.loads(path.read_text(encoding="utf-8")).get("minuto_per_minuto", {}))


def _half_weights(weights: np.ndarray, first_share: float) -> np.ndarray:
    """Pesi dei blocchi con la quota del primo tempo uguale a quella tarata (``primo_tempo``)."""
    first, second = weights[:9].sum(), weights[9:].sum()
    scaled = weights.copy()
    scaled[:9] *= first_share / first
    scaled[9:] *= (1.0 - first_share) / second
    return scaled / scaled.sum()


def _nb(rng: np.random.Generator, mean: np.ndarray, dispersion: float) -> np.ndarray:
    mean = np.maximum(mean, 0.0)
    if dispersion > 0:
        return rng.poisson(rng.gamma(dispersion, mean / dispersion))
    return rng.poisson(mean)


def _future_mass(weights: np.ndarray, state_rows: np.ndarray, block: int) -> np.ndarray:
    """Σ dei blocchi successivi di peso × moltiplicatore di stato, con lo stato attuale mantenuto (per simulazione)."""
    if block + 1 >= BLOCKS:
        return np.zeros(len(state_rows))
    later = np.arange(block + 1, BLOCKS)
    return state_rows[:, BLOCK_BANDS[later]] @ weights[later]


def _goal_paths(rng, n, base_home, base_away, weights_home, weights_away, params: TimelineParams,
                red_home_blocks: np.ndarray | None, red_away_blocks: np.ndarray | None,
                allocated: tuple[np.ndarray, np.ndarray] | None = None,
                final: tuple[np.ndarray, np.ndarray] | None = None) -> dict[str, np.ndarray]:
    """Percorso della partita blocco per blocco.

    ``allocated``: gol per blocco già dati; ``final``: punteggi finali dati (Dixon-Coles), collocati nel tempo con
    rischio ∝ peso del blocco × stato del punteggio (× espulsioni): in ogni blocco i gol restanti si assottigliano
    con probabilità rischio del blocco / (rischio del blocco + rischio futuro con lo stato attuale), e l'ultimo
    blocco prende tutto il resto, così i totali restano esattamente quelli dati.
    """
    goals_home = np.zeros(n, dtype=np.int64)
    goals_away = np.zeros(n, dtype=np.int64)
    first_home = first_away = None
    pressure_home = np.zeros(n)
    pressure_away = np.zeros(n)
    level_cards = np.zeros(n)
    reds_home = np.zeros(n, dtype=np.int64)
    reds_away = np.zeros(n, dtype=np.int64)
    state_table = np.array([params.state.get(state, (1.0,) * len(BANDS)) for state in STATES])  # 5 × bande
    corner_weights = np.asarray(params.corner_weights) / np.mean(params.corner_weights)
    card_weights = np.asarray(params.card_weights) / np.mean(params.card_weights)
    corner_first_home = np.zeros(n)
    corner_first_away = np.zeros(n)
    cards_first = np.zeros(n)
    timing_state = params.uses("tempi_stato")
    for block in range(BLOCKS):
        band = BLOCK_BANDS[block]
        difference = np.clip(goals_home - goals_away, -2, 2)
        # Pressione offensiva dallo stato del punteggio (e dalle espulsioni): guida i corner anche quando i gol
        # restano quelli Dixon-Coles; sui gol si applica solo con «gol_stato».
        state_home, state_away = state_table[difference + 2, band], state_table[-difference + 2, band]
        react_home = np.where(difference < 0, params.reactions[0], np.where(difference > 0, params.reactions[1], 1.0))
        react_away = np.where(difference > 0, params.reactions[2], np.where(difference < 0, params.reactions[3], 1.0))
        state_home, state_away = state_home * react_home, state_away * react_away
        if red_home_blocks is not None:
            reds_home += red_home_blocks[:, block]
            reds_away += red_away_blocks[:, block]
            advantage = np.clip(reds_away - reds_home, -1, 1)
            red_home = np.where(advantage < 0, params.fewer_players, np.where(advantage > 0, params.more_players, 1.0))
            red_away = np.where(advantage > 0, params.fewer_players, np.where(advantage < 0, params.more_players, 1.0))
        else:
            red_home = red_away = 1.0
        home_factor = (state_home if params.uses("gol_stato") else 1.0) * red_home * np.ones(n)
        away_factor = (state_away if params.uses("gol_stato") else 1.0) * red_away * np.ones(n)
        corner_home_block = corner_weights[block] * (state_home * red_home) ** params.corner_gamma * np.ones(n)
        corner_away_block = corner_weights[block] * (state_away * red_away) ** params.corner_gamma * np.ones(n)
        card_block = card_weights[block] * np.where(goals_home == goals_away, params.card_level[band], 1.0)
        pressure_home += corner_home_block
        pressure_away += corner_away_block
        level_cards += card_block
        if block <= 8:
            corner_first_home += corner_home_block
            corner_first_away += corner_away_block
            cards_first += card_block
        if final is not None:
            # Gol già decisi: quanti arrivano in questo blocco.
            rows_home = state_table[difference + 2] * react_home[:, None] if timing_state else np.ones((n, len(BANDS)))
            rows_away = state_table[-difference + 2] * react_away[:, None] if timing_state else np.ones((n, len(BANDS)))
            hazard_home = weights_home[block] * rows_home[:, band] * red_home
            hazard_away = weights_away[block] * rows_away[:, band] * red_away
            future_home = _future_mass(weights_home, rows_home, block) * red_home
            future_away = _future_mass(weights_away, rows_away, block) * red_away
            left_home, left_away = final[0] - goals_home, final[1] - goals_away
            p_home = np.where(future_home > 0, hazard_home / np.maximum(hazard_home + future_home, 1e-12), 1.0)
            p_away = np.where(future_away > 0, hazard_away / np.maximum(hazard_away + future_away, 1e-12), 1.0)
            goals_home = goals_home + rng.binomial(left_home, np.clip(p_home, 0.0, 1.0))
            goals_away = goals_away + rng.binomial(left_away, np.clip(p_away, 0.0, 1.0))
        elif allocated is not None:
            goals_home = goals_home + allocated[0][:, block]
            goals_away = goals_away + allocated[1][:, block]
        else:
            goals_home = goals_home + rng.poisson(base_home * weights_home[block] * home_factor)
            goals_away = goals_away + rng.poisson(base_away * weights_away[block] * away_factor)
        if block == 8:
            first_home, first_away = goals_home.copy(), goals_away.copy()
    return {"goals_home": goals_home, "goals_away": goals_away, "first_home": first_home, "first_away": first_away,
            "pressure_home": pressure_home / BLOCKS, "pressure_away": pressure_away / BLOCKS,
            "level_cards": level_cards / BLOCKS, "reds_home": reds_home, "reds_away": reds_away,
            "corner_first_share_home": corner_first_home / np.maximum(pressure_home, 1e-12),
            "corner_first_share_away": corner_first_away / np.maximum(pressure_away, 1e-12),
            "card_first_share": cards_first / np.maximum(level_cards, 1e-12)}


def sample(rng: np.random.Generator, n: int, *, lambda_: float, mu: float, first_share_home: float, first_share_away: float,
           corner_home: float, corner_away: float, corner_dispersion: float, yellow_mean: float, card_dispersion: float,
           red_mean: float, card_share: float, params: TimelineParams, scores: tuple[np.ndarray, np.ndarray] | None = None,
           pilot: int = 20_000, passes: int = 3) -> dict[str, np.ndarray]:
    """Gol per tempo, corner per squadra, gialli totali e (con ``espulsioni``) rossi per squadra, ``n`` simulazioni.

    Senza ``gol_stato`` né ``espulsioni`` i punteggi finali sono ``scores`` (Dixon-Coles del motore) e i gol si
    distribuiscono nei blocchi con i pesi dei minuti (stessa quota del primo tempo): i mercati gol restano quelli
    del motore attuale e il percorso serve a corner e cartellini.
    """
    weights = np.asarray(params.goal_weights, float)
    weights_home = _half_weights(weights, first_share_home)
    weights_away = _half_weights(weights, first_share_away)
    red_profile = np.asarray(params.red_weights, float) / np.sum(params.red_weights)

    def red_blocks(generator, size):
        if not (params.uses("espulsioni") or params.uses("espulsioni_tempi")):
            return None, None
        home = generator.poisson(red_mean * card_share * red_profile[None, :], size=(size, BLOCKS))
        away = generator.poisson(red_mean * (1 - card_share) * red_profile[None, :], size=(size, BLOCKS))
        return home, away

    base_home, base_away = lambda_, mu
    if params.uses("gol_stato") or params.uses("espulsioni"):
        # Le regole di stato cambiano la media: si riscala la base finché i gol attesi tornano λ e μ.
        pilot_rng = np.random.default_rng([int(rng.integers(1 << 31)), 7])
        size = min(pilot, n)
        for _ in range(passes):
            reds = red_blocks(pilot_rng, size)
            paths = _goal_paths(pilot_rng, size, base_home, base_away, weights_home, weights_away, params, *reds)
            base_home *= lambda_ / max(paths["goals_home"].mean(), 1e-9)
            base_away *= mu / max(paths["goals_away"].mean(), 1e-9)
    reds = red_blocks(rng, n)
    allocated = final = None
    if not (params.uses("gol_stato") or params.uses("espulsioni")):
        if scores is None:
            raise ValueError("Senza regole sui gol servono i punteggi finali (Dixon-Coles) da distribuire nei blocchi.")
        if params.uses("tempi_stato") or params.uses("espulsioni_tempi"):
            final = (np.asarray(scores[0]), np.asarray(scores[1]))
        else:
            allocated = (rng.multinomial(scores[0], weights_home), rng.multinomial(scores[1], weights_away))
    paths = _goal_paths(rng, n, base_home, base_away, weights_home, weights_away, params, *reds, allocated=allocated,
                        final=final)

    if params.uses("corner_pressione"):
        factor_home = paths["pressure_home"] / paths["pressure_home"].mean()
        factor_away = paths["pressure_away"] / paths["pressure_away"].mean()
    else:
        factor_home = factor_away = np.ones(n)
    home_mean, away_mean = corner_home * factor_home, corner_away * factor_away
    corners = _nb(rng, home_mean + away_mean, corner_dispersion)
    corners_home = rng.binomial(corners, np.where(home_mean + away_mean > 0, home_mean / np.maximum(home_mean + away_mean, 1e-12), 0.5))
    card_factor = paths["level_cards"] / paths["level_cards"].mean() if params.uses("cartellini_tempo") else np.ones(n)
    yellows = _nb(rng, yellow_mean * card_factor, card_dispersion)
    corners_away = corners - corners_home
    return {**{key: paths[key] for key in ("goals_home", "goals_away", "first_home", "first_away", "card_first_share")},
            "corners_home": corners_home, "corners_away": corners_away, "yellows": yellows,
            "corners_first_home": rng.binomial(corners_home, np.clip(paths["corner_first_share_home"], 0, 1)),
            "corners_first_away": rng.binomial(corners_away, np.clip(paths["corner_first_share_away"], 0, 1)),
            "reds_home": paths["reds_home"] if reds[0] is not None else None,
            "reds_away": paths["reds_away"] if reds[0] is not None else None}
