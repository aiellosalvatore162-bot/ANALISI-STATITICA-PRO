"""Motore a eventi per partita (fase AK, stadi 3-5): stato della partita, azioni a passi, tiri e gol.

Ogni simulazione avanza a passi di ``passo`` minuti (default 5, divisore di 15 così che i passi non scavalchino le fasce
0-30/30-60/60-75/75-90 né l'intervallo). A ogni passo, per ciascuna squadra, i tiri di ogni tipo (rigore, palla inattiva,
transizione, fuori area, testa da cross, azione) nascono da un Poisson con tasso

    tasso base del tipo (StatsBomb, ``config/motore_eventi.json``) × forza f della squadra × dizionario tattico
    × stato del punteggio × fascia di minuti / normalizzazione

e ogni tiro diventa gol con la conversione del tipo × qualità del tiro per stato e fascia (rapporto xG/tiri stimato).
Tutti i parametri vengono da ``python -m tools.stima_motore``: qui non c'è nessun numero scelto a mano. Le normalizzazioni
fanno sì che, con la distribuzione tipica degli stati (``minuti_per_stato``), le medie per partita restino quelle stimate.

Due modi:
- «punteggi» (``scores`` dati, scelta della ricognizione): i punteggi finali sono quelli Dixon-Coles del motore, quindi la
  correzione sui punteggi bassi e tutti i mercati gol restano quelli attuali. Per assottigliamento di Poisson gol e tiri
  sbagliati sono processi indipendenti: i gol già decisi si collocano nei passi con rischio ∝ intensità di gol del passo
  (stato attuale mantenuto per il futuro, come ``timeline``), il tipo del gol si estrae ∝ tasso × conversione, i tiri
  sbagliati si simulano a parte. I totali restano esattamente quelli dati.
- «libero» (``scores`` = None): i gol nascono dai tiri; la forza f si riscala su una simulazione pilota finché i gol attesi
  tornano λ e μ (anticipo del vincolo di coerenza dello stadio 9).

Rigori: tasso e conversione costanti (gli effetti di stato e fascia sono stimati senza rigori). Espulsioni, corner, falli e
cartellini arrivano con gli stadi 6-8; i tiri parati o respinti (``saved_*``) servono ai corner da tiro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

import tactical_dictionary

PATH = Path(__file__).resolve().parent / "config" / "motore_eventi.json"
SHOT_TYPES = ("rigore", "palla_inattiva", "transizione", "fuori_area", "testa_da_cross", "azione")
PENALTY = SHOT_TYPES.index("rigore")
BANDS = (("0-30", 0, 30), ("30-60", 30, 60), ("60-75", 60, 75), ("75-90", 75, 90))
STATES = (-2, -1, 0, 1, 2)
MINUTES = 90
HALF = 45
# Codici football-data (``MatchConfig.league``) → campionati di ``config/motore_eventi.json``.
LEAGUE_CODES = {"E0": "Premier League", "SP1": "La Liga", "I1": "Serie A", "F1": "Ligue 1", "D1": "Bundesliga"}
# Tassi del dizionario tattico che spostano i tiri della squadra (attacco) o quelli dell'avversario (concessi).
ATTACK_RATES = {"azioni_pericolose": ("azione",), "tiri_transizione": ("transizione",), "tiri_fuori_area": ("fuori_area",),
                "tiri_da_cross": ("testa_da_cross",)}
CONCEDED_RATES = {"tiri_transizione_concessi": ("transizione",)}
# «gestione_blocco_basso» conta solo contro un avversario con la linea bassa: tiri su azione e da fuori.
LOW_BLOCK_RATE, LOW_BLOCK_TYPES = "tiri_contro_blocco_basso", ("azione", "fuori_area")
SPIN_RATES = ("spinta_in_svantaggio", "spinta_in_vantaggio")


def _band_index(minute: float) -> int:
    return next(index for index, (_, low, high) in enumerate(BANDS) if low <= minute < high)


def league_name(league: str | None) -> str | None:
    if not league:
        return None
    return LEAGUE_CODES.get(str(league).upper(), str(league))


@dataclass(frozen=True)
class EventParams:
    """Parametri del motore per un campionato (o «comune»), letti da ``config/motore_eventi.json``."""

    source: str
    shots: tuple[float, ...]            # tiri per squadra-partita per tipo
    conversion: tuple[float, ...]       # gol per tiro per tipo
    xg: tuple[float, ...]               # xG medio per tipo
    saved: tuple[float, ...]            # quota di tiri parati o respinti per tipo (sul totale dei tiri)
    state_shots: tuple[float, ...]      # moltiplicatore dei tiri per stato −2…+2
    state_xg: tuple[float, ...]         # moltiplicatore degli xG per stato −2…+2
    band_shots: tuple[float, ...]       # moltiplicatore dei tiri per fascia
    band_xg: tuple[float, ...]
    state_minutes: tuple[float, ...]    # minuti osservati per stato (pesi della normalizzazione)
    note: str = ""

    @classmethod
    def from_config(cls, data: Mapping[str, Any], league: str | None = None) -> "EventParams":
        name = league_name(league)
        own = (data.get("campionati") or {}).get(name, "") if name else ""
        key = name if own == "propri" and name in data["xg_per_tipo"] else "comune"
        rows = data["xg_per_tipo"][key]
        state = data["stato_partita"]["quantita"]
        note = f"parametri {key}" + (f" ({name}: {own})" if name and key == "comune" and own else "")
        if name and not own:
            note = f"parametri comune ({name} non stimato)"
        return cls(
            source=key,
            shots=tuple(float(rows[kind]["tiri_per_squadra_partita"]) for kind in SHOT_TYPES),
            conversion=tuple(float(rows[kind]["gol_per_tiro"]) for kind in SHOT_TYPES),
            xg=tuple(float(rows[kind]["xg_medio"]) for kind in SHOT_TYPES),
            saved=tuple(float(rows[kind]["quota_parato_respinto"]) for kind in SHOT_TYPES),
            state_shots=tuple(float(state["tiri"]["stato"][str(s)]["moltiplicatore"]) for s in STATES),
            state_xg=tuple(float(state["xg"]["stato"][str(s)]["moltiplicatore"]) for s in STATES),
            band_shots=tuple(float(state["tiri"]["fascia"][band]["moltiplicatore"]) for band, _, _ in BANDS),
            band_xg=tuple(float(state["xg"]["fascia"][band]["moltiplicatore"]) for band, _, _ in BANDS),
            state_minutes=tuple(float(data["stato_partita"]["minuti_per_stato"][str(s)]) for s in STATES),
            note=note,
        )


def load(league: str | None = None, path: Path = PATH) -> EventParams:
    return EventParams.from_config(json.loads(path.read_text(encoding="utf-8")), league)


@dataclass(frozen=True)
class TeamInput:
    """Una squadra: gol attesi finali del motore (λ o μ), termini del dizionario tattico, quota di gol nel primo tempo."""

    goals: float
    profile: Mapping[str, Any] = field(default_factory=dict)
    first_share: float | None = None


# ---------------------------------------------------------------------------------------------------------------- stadio 3


@dataclass
class MatchState:
    """Stato della partita per ``n`` simulazioni: punteggio, passo, minuto; lo stato di ogni squadra è la differenza reti
    dal suo punto di vista, limitata a −2…+2 come nelle stime."""

    n: int
    step_minutes: int
    goals_home: np.ndarray = None
    goals_away: np.ndarray = None
    step: int = 0

    def __post_init__(self):
        if 15 % self.step_minutes:
            raise ValueError(f"Passo di {self.step_minutes} minuti non valido: deve dividere 15 (1, 3, 5 o 15).")
        if self.goals_home is None:
            self.goals_home = np.zeros(self.n, dtype=np.int64)
            self.goals_away = np.zeros(self.n, dtype=np.int64)

    @property
    def steps(self) -> int:
        return MINUTES // self.step_minutes

    @property
    def minute(self) -> int:
        return self.step * self.step_minutes

    @property
    def band(self) -> int:
        return _band_index(self.minute)

    @property
    def first_half(self) -> bool:
        return self.minute < HALF

    def state_index(self, home: bool) -> np.ndarray:
        """Indice in ``STATES`` (0 = −2 … 4 = +2) per ogni simulazione."""
        difference = self.goals_home - self.goals_away
        return np.clip(difference if home else -difference, -2, 2) + 2

    def add(self, home: np.ndarray, away: np.ndarray) -> None:
        self.goals_home = self.goals_home + home
        self.goals_away = self.goals_away + away


# ---------------------------------------------------------------------------------------------------------------- stadio 4


def _profile_multipliers(profile: Mapping[str, Any], dictionary) -> tuple[dict[str, float], list[dict], list[str]]:
    if not profile:
        return {}, [], []
    return tactical_dictionary.apply_profile(profile, dictionary)


def _low_block(profile: Mapping[str, Any], dictionary) -> bool:
    raw = profile.get("altezza_linea") if profile else None
    if raw in (None, ""):
        return False
    value, _ = tactical_dictionary.normalize("altezza_linea", raw, dictionary)
    return value is not None and dictionary["termini"]["altezza_linea"]["punteggio"][value] < 0


def type_multipliers(own: Mapping[str, float], opponent: Mapping[str, float], opponent_low_block: bool) -> np.ndarray:
    """Moltiplicatore per tipo di tiro dal dizionario: tassi propri, concessi dall'avversario, blocco basso avversario."""
    out = np.ones(len(SHOT_TYPES))
    for rate, kinds in ATTACK_RATES.items():
        for kind in kinds:
            out[SHOT_TYPES.index(kind)] *= own.get(rate, 1.0)
    for rate, kinds in CONCEDED_RATES.items():
        for kind in kinds:
            out[SHOT_TYPES.index(kind)] *= opponent.get(rate, 1.0)
    if opponent_low_block:
        for kind in LOW_BLOCK_TYPES:
            out[SHOT_TYPES.index(kind)] *= own.get(LOW_BLOCK_RATE, 1.0)
    return out


@dataclass(frozen=True)
class Tables:
    """Intensità per squadra, tipo, stato e passo: ``shots[k, s, t]`` tiri attesi nel passo, ``conversion[k, s, t]``."""

    shots: np.ndarray
    conversion: np.ndarray

    @property
    def goals(self) -> np.ndarray:
        return self.shots * self.conversion

    @property
    def misses(self) -> np.ndarray:
        return self.shots * (1.0 - self.conversion)


def build_tables(params: EventParams, strength: float, types: np.ndarray, step_minutes: int,
                 first_share: float | None = None, spin: tuple[float, float] = (1.0, 1.0)) -> Tables:
    """Tabelle dei tassi di una squadra. Le normalizzazioni tengono le medie per partita uguali a quelle stimate quando gli
    stati seguono la distribuzione osservata; ``first_share`` riporta la quota di gol del primo tempo a quella tarata."""
    steps = MINUTES // step_minutes
    bands = np.array([_band_index(step * step_minutes) for step in range(steps)])
    band_length = np.array([high - low for _, low, high in BANDS], float) / MINUTES
    state_weight = np.asarray(params.state_minutes) / np.sum(params.state_minutes)
    state_shots, state_xg = np.asarray(params.state_shots), np.asarray(params.state_xg)
    band_shots, band_xg = np.asarray(params.band_shots), np.asarray(params.band_xg)
    # Reazioni (svantaggio, vantaggio) del dizionario: moltiplicano la spinta dello stato, 1 finché non stimate.
    spin_row = np.array([spin[0], spin[0], 1.0, spin[1], spin[1]])
    count = (state_shots * spin_row)[:, None] * band_shots[bands][None, :]                        # stato × passo
    count /= (state_weight @ state_shots) * (band_length @ band_shots)
    quality = (state_xg / state_shots)[:, None] * (band_xg / band_shots)[bands][None, :]
    weight = state_shots[:, None] * band_shots[None, :]
    quality /= np.sum(state_weight[:, None] * band_length[None, :] * weight * (state_xg / state_shots)[:, None]
                      * (band_xg / band_shots)[None, :]) / np.sum(state_weight[:, None] * band_length[None, :] * weight)
    base = np.asarray(params.shots) * types * strength * step_minutes / MINUTES
    shots = base[:, None, None] * count[None, :, :]
    conversion = np.clip(np.asarray(params.conversion)[:, None, None] * quality[None, :, :], 0.0, 0.99)
    # Rigori: niente effetti di stato e fascia (stimati senza rigori).
    shots[PENALTY] = base[PENALTY]
    conversion[PENALTY] = params.conversion[PENALTY]
    if first_share is not None:
        neutral = (shots * conversion)[:, STATES.index(0), :].sum(axis=0)
        first = np.arange(steps) * step_minutes < HALF
        factor = np.where(first, first_share / neutral[first].sum(), (1 - first_share) / neutral[~first].sum()) * neutral.sum()
        shots = shots * factor[None, None, :]
    return Tables(shots=shots, conversion=conversion)


def base_goals(params: EventParams, types: np.ndarray) -> float:
    """Gol attesi per partita con forza 1 e stati tipici (Σ tiri × conversione per tipo)."""
    return float(np.sum(np.asarray(params.shots) * types * np.asarray(params.conversion)))


# ---------------------------------------------------------------------------------------------------------------- stadio 5


def _suffix(values: np.ndarray) -> np.ndarray:
    """Somma dei passi successivi (escluso il passo stesso) lungo l'ultimo asse."""
    total = np.cumsum(values[..., ::-1], axis=-1)[..., ::-1]
    return total - values


def _run(rng: np.random.Generator, n: int, home: Tables, away: Tables, params: EventParams, step_minutes: int,
         scores: tuple[np.ndarray, np.ndarray] | None) -> dict[str, np.ndarray]:
    state = MatchState(n, step_minutes)
    kinds = len(SHOT_TYPES)
    out = {f"{key}_{side}": np.zeros((n, kinds), dtype=np.int64) for key in ("shots", "goals_by_type", "saved")
           for side in ("home", "away")}
    out.update({"xg_home": np.zeros(n), "xg_away": np.zeros(n), "first_goal_minute": np.full(n, np.nan),
                "first_goal_team": np.zeros(n, dtype=np.int8),
                "state_steps_home": np.zeros((n, len(STATES)), dtype=np.int16)})
    conversion = np.asarray(params.conversion)
    saved_given_miss = np.clip(np.asarray(params.saved) / np.maximum(1.0 - conversion, 1e-9), 0.0, 1.0)
    xg = np.asarray(params.xg) / conversion   # xG del tiro = xG medio del tipo × qualità (conversione relativa)
    tables = {"home": home, "away": away}
    goal_rate = {side: table.goals.sum(axis=0) for side, table in tables.items()}            # stato × passo
    future = {side: _suffix(rate) for side, rate in goal_rate.items()}
    rows = np.arange(n)
    for step in range(state.steps):
        state.step = step
        index = {"home": state.state_index(True), "away": state.state_index(False)}
        out["state_steps_home"][rows, index["home"]] += 1
        scored = {}
        for side in ("home", "away"):
            table, s = tables[side], index[side]
            goals_mean = table.goals[:, s, step].T                                            # n × tipi
            if scores is None:
                goals = rng.poisson(goals_mean)
            else:
                final = scores[0] if side == "home" else scores[1]
                left = final - (state.goals_home if side == "home" else state.goals_away)
                hazard, later = goal_rate[side][s, step], future[side][s, step]
                p = np.where(later > 0, hazard / np.maximum(hazard + later, 1e-12), 1.0)
                count = rng.binomial(left, np.clip(p, 0.0, 1.0))
                goals = np.zeros((n, kinds), dtype=np.int64)
                for value in range(len(STATES)):
                    chosen = (s == value) & (count > 0)
                    if chosen.any():
                        pvals = table.goals[:, value, step]
                        goals[chosen] = rng.multinomial(count[chosen], pvals / pvals.sum())
            misses = rng.poisson(table.misses[:, s, step].T)
            saved = rng.binomial(misses, saved_given_miss[None, :])
            quality = table.conversion[:, s, step].T * xg[None, :]
            out[f"shots_{side}"] += goals + misses
            out[f"goals_by_type_{side}"] += goals
            out[f"saved_{side}"] += saved
            out[f"xg_{side}"] += ((goals + misses) * quality).sum(axis=1)
            scored[side] = goals.sum(axis=1)
        # Primo gol: minuto uniforme nel passo; se segnano entrambe nello stesso passo, squadra ∝ gol del passo.
        new = np.isnan(out["first_goal_minute"]) & ((scored["home"] + scored["away"]) > 0)
        if new.any():
            out["first_goal_minute"][new] = state.minute + rng.uniform(0, step_minutes, new.sum())
            total = scored["home"][new] + scored["away"][new]
            out["first_goal_team"][new] = np.where(rng.random(new.sum()) * total < scored["home"][new], 1, 2)
        state.add(scored["home"], scored["away"])
        if state.minute + step_minutes == HALF:
            out["first_home"], out["first_away"] = state.goals_home.copy(), state.goals_away.copy()
    out["goals_home"], out["goals_away"] = state.goals_home, state.goals_away
    return out


def simulate(rng: np.random.Generator, n: int, home: TeamInput, away: TeamInput, params: EventParams, *,
             scores: tuple[np.ndarray, np.ndarray] | None = None, step_minutes: int = 5, dictionary=None,
             pilot: int = 20_000, passes: int = 3) -> dict[str, Any]:
    """``n`` partite a eventi. Con ``scores`` (punteggi Dixon-Coles) i gol finali sono quelli; senza, nascono dai tiri e la
    forza si riscala sui gol attesi ``home.goals`` / ``away.goals``. Restituisce gli array per simulazione (tiri, gol e
    parate per tipo, xG, primo tempo, primo gol, passi per stato) più ``ledger`` e ``warnings``."""
    dictionary = dictionary if dictionary is not None else (tactical_dictionary.load() if home.profile or away.profile else None)
    mult_home, rows_home, warn_home = _profile_multipliers(home.profile, dictionary)
    mult_away, rows_away, warn_away = _profile_multipliers(away.profile, dictionary)
    types_home = type_multipliers(mult_home, mult_away, _low_block(away.profile, dictionary))
    types_away = type_multipliers(mult_away, mult_home, _low_block(home.profile, dictionary))
    strength = {"home": home.goals / base_goals(params, types_home), "away": away.goals / base_goals(params, types_away)}

    def tables(scale_home=1.0, scale_away=1.0):
        return (build_tables(params, strength["home"] * scale_home, types_home, step_minutes, home.first_share,
                             (mult_home.get(SPIN_RATES[0], 1.0), mult_home.get(SPIN_RATES[1], 1.0))),
                build_tables(params, strength["away"] * scale_away, types_away, step_minutes, away.first_share,
                             (mult_away.get(SPIN_RATES[0], 1.0), mult_away.get(SPIN_RATES[1], 1.0))))

    if scores is None:
        # Vincolo sui gol attesi: lo stato del punteggio cambia la media, la forza si riscala su una simulazione pilota.
        pilot_rng = np.random.default_rng([int(rng.integers(1 << 31)), 11])
        size = min(pilot, n)
        for _ in range(passes):
            paths = _run(pilot_rng, size, *tables(), params, step_minutes, None)
            strength["home"] *= home.goals / max(paths["goals_home"].mean(), 1e-9)
            strength["away"] *= away.goals / max(paths["goals_away"].mean(), 1e-9)
    else:
        scores = (np.asarray(scores[0], dtype=np.int64), np.asarray(scores[1], dtype=np.int64))
        if len(scores[0]) != n or len(scores[1]) != n:
            raise ValueError("I punteggi Dixon-Coles devono essere uno per simulazione.")
    out = _run(rng, n, *tables(), params, step_minutes, scores)
    ledger = [
        {"voce": "parametri", "valore": params.source, "nota": params.note or "config/motore_eventi.json"},
        {"voce": "modo", "valore": "punteggi" if scores is not None else "libero",
         "nota": "punteggi finali Dixon-Coles fissi, eventi condizionati" if scores is not None
         else "gol dai tiri, forza riscalata sui gol attesi"},
        {"voce": "forza_casa", "valore": round(strength["home"], 4), "nota": f"gol attesi {home.goals:.3f}"},
        {"voce": "forza_ospite", "valore": round(strength["away"], 4), "nota": f"gol attesi {away.goals:.3f}"},
        *({"voce": f"tipi_{side}", "valore": {kind: round(float(value), 4) for kind, value in zip(SHOT_TYPES, types)},
           "nota": "moltiplicatori del dizionario tattico per tipo di tiro"}
          for side, types in (("casa", types_home), ("ospite", types_away))),
    ]
    out.update({"types": SHOT_TYPES, "ledger": ledger, "dictionary_rows": {"casa": rows_home, "ospite": rows_away},
                "warnings": [*(f"casa: {w}" for w in warn_home), *(f"ospite: {w}" for w in warn_away)],
                "possession_home": _possession(mult_home, mult_away)})
    return out


def _possession(home: Mapping[str, float], away: Mapping[str, float]) -> float:
    """Quota di possesso attesa della casa dal tasso «quota_possesso» del dizionario (0.5 senza profili)."""
    h, a = home.get("quota_possesso", 1.0), away.get("quota_possesso", 1.0)
    return h / (h + a)


def summary(sample: Mapping[str, Any]) -> dict[str, float]:
    """Medie per partita (per i test di buon senso e per la scheda): gol, tiri, xG, quote per tipo, primo tempo."""
    out = {}
    for side in ("home", "away"):
        out[f"gol_{side}"] = float(np.mean(sample[f"goals_{side}"]))
        out[f"tiri_{side}"] = float(np.mean(sample[f"shots_{side}"].sum(axis=1)))
        out[f"xg_{side}"] = float(np.mean(sample[f"xg_{side}"]))
        out[f"gol_1t_{side}"] = float(np.mean(sample[f"first_{side}"]))
        for kind, value in zip(SHOT_TYPES, sample[f"shots_{side}"].mean(axis=0)):
            out[f"tiri_{kind}_{side}"] = float(value)
    out["nessun_gol"] = float(np.mean(sample["first_goal_team"] == 0))
    out["minuto_primo_gol"] = float(np.nanmean(sample["first_goal_minute"])) if np.any(sample["first_goal_team"]) else math.nan
    return out
