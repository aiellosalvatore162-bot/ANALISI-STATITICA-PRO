"""Transparent on-demand football probability engine.

All predictions are derived from the supplied match input. No database,
calendar, bookmaker fallback, narrative template, or hidden team defaults is
used here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from scipy.optimize import brentq, minimize
from scipy.stats import binom, poisson

from market_catalog import (
    CARD_HALF_LINES, CARD_TEAM_BANDS, CARD_TOTAL_BANDS, CORNER_HALF_LINES, CORNER_TEAM_BANDS, CORNER_TOTAL_BANDS,
    GOAL_LINES, MARKET_CATALOG, MULTIGOL_1T_RANGES, MULTIGOL_2T_RANGES, MULTIGOL_RANGES, TEAM_PAIR_RANGES,
    definition_for_event, range_label,
)
from parser import MatchInput


_DEFAULT_TEAM_MULTIGOL_RANGES = MULTIGOL_RANGES
_TEAM_MULTIGOL_KEY = re.compile(r"^Multigol (?P<team>Casa|Ospite) (?P<low>\d+)-(?P<high>\d+)$")


@dataclass(frozen=True)
class TeamParams:
    name: str
    attack: float
    defense: float
    elo: float
    form: str
    xg_for: float
    xg_against: float
    corners_for: float
    corners_against: float
    cards_for: float
    # Gialli presi dagli avversari contro la squadra (fase T, divisione dei cartellini); None = non disponibile.
    cards_provoked: float | None = None


GOAL_MODEL_PATH = Path(__file__).resolve().parent / "config" / "goal_model.json"
GOAL_MODELS = ("calibrato", "legacy")
_LEGACY_RHO = -0.11


@dataclass(frozen=True)
class GoalModelParams:
    """Parameters of the log-linear goal model, fitted by ``tools/calibrate.py``."""

    base_goals: float = 1.40
    home_advantage: float = 0.25
    attack_weight: float = 1.0
    defense_weight: float = 1.0
    attack_xg_share: float = 0.5
    defense_xg_share: float = 0.5
    elo_k: float = 1.0
    form_weight: float = 0.05
    dixon_coles_rho: float = _LEGACY_RHO


def load_goal_model(path: Path = GOAL_MODEL_PATH) -> tuple[str, GoalModelParams]:
    """Return the active model name and its fitted parameters.

    Without a calibration file the engine keeps the original formula, so an
    uncalibrated model is never enabled silently.
    """
    if not path.exists():
        return "legacy", GoalModelParams()
    data = json.loads(path.read_text(encoding="utf-8"))
    active = data.get("modello_attivo", "legacy")
    if active not in GOAL_MODELS:
        raise ValueError(f"{path.name}: modello_attivo deve essere uno di {GOAL_MODELS}.")
    strength = data.get("forza_calendario") or {}
    if strength.get("attiva") and (strength.get("parametri") or {}).get("mode") == "ingressi" and strength.get("pesi_modello_gol"):
        # Fase P, punto 1: con Attacco/Difesa dalle forze Dixon-Coles valgono i pesi ristimati con quegli ingressi.
        return active, GoalModelParams(**strength["pesi_modello_gol"])
    return active, GoalModelParams(**data["parametri"])


DEFAULT_GOAL_MODEL, DEFAULT_GOAL_PARAMS = load_goal_model()

DEVIG_METHODS = ("proporzionale", "shin")
ANCHOR_MARKETS = ("1", "X", "2", "Over 2.5 gol", "Under 2.5 gol")


@dataclass(frozen=True)
class MarketAnchorParams:
    """Blend of model and market goal rates, tuned by ``tools/baseline.py``.

    ``market_weight`` is the market share in log scale; the model may move the
    market rates only within ``[correction_min, correction_max]``.
    ``no_value_markets`` keeps EV visible but never flags those markets as
    VALORE: on historical closing odds the draw signals lost money because
    Poisson + Dixon-Coles cannot reprice the quoted draw exactly.
    """

    active: bool = True
    market_weight: float = 0.7
    devig_method: str = "proporzionale"
    correction_min: float = 0.80
    correction_max: float = 1.20
    suspicious_gap_pct: float = 10.0
    no_value_markets: tuple[str, ...] = ("X",)


def load_market_anchor(path: Path = GOAL_MODEL_PATH) -> MarketAnchorParams:
    if not path.exists():
        return MarketAnchorParams()
    data = json.loads(path.read_text(encoding="utf-8"))
    params = dict(data.get("ancoraggio_mercato", {}).get("parametri", {}))
    if "no_value_markets" in params:
        params["no_value_markets"] = tuple(params["no_value_markets"])
    return MarketAnchorParams(**params)


DEFAULT_MARKET_ANCHOR = load_market_anchor()


@dataclass(frozen=True)
class ModelV2Params:
    """Fase P (motore v2): opzioni verificate una per una (``tools/model_v2.py``, ``tools/recalibration_check.py``).

    Ogni parte agisce solo se la sua sezione di ``config/goal_model.json`` ha ``attiva``: pesi del mercato per
    campionato e tipo (totale/supremazia), riposo, incertezza dei parametri, ricalibrazione finale per mercato.
    """

    league_weights_active: bool = False
    league_weights: Mapping[str, tuple[float, float]] = field(default_factory=dict)   # codice → (totale, supremazia)
    rest_active: bool = False
    rest_per_day: float = 0.0
    rest_short: float = 0.0
    uncertainty_active: bool = False
    sigma_goals: float = 0.0
    sigma_corners: float = 0.0
    sigma_cards: float = 0.0
    recalibration_active: bool = False
    recalibration: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    thresholds_active: bool = False
    thresholds: Mapping[str, float] = field(default_factory=dict)   # punto 7: gruppo di mercato → EV minimo (punti %)
    # Fase Y, punto 0: forza corretta per il calendario solo quando mancano le quote 1X2/O-U (modello da solo).
    strength_model_only: bool = False
    strength_goal_params: Any = None   # GoalModelParams ristimati con gli ingressi Dixon-Coles


def load_model_v2(path: Path = GOAL_MODEL_PATH) -> ModelV2Params:
    if not path.exists():
        return ModelV2Params()
    data = json.loads(path.read_text(encoding="utf-8"))
    weights = data.get("peso_mercato_campionato", {})
    rest = data.get("contesto_riposo", {})
    uncertainty = data.get("incertezza_parametri", {})
    sigma = uncertainty.get("sigma", {})
    recalibration = data.get("ricalibrazione", {})
    thresholds = data.get("soglie_valore", {})
    strength = data.get("forza_calendario", {})
    return ModelV2Params(
        league_weights_active=bool(weights.get("attiva")),
        league_weights={league: (float(row["totale"]), float(row["supremazia"]))
                        for league, row in (weights.get("pesi") or {}).items()},
        rest_active=bool(rest.get("attiva")), rest_per_day=float((rest.get("parametri") or {}).get("per_giorno", 0.0)),
        rest_short=float((rest.get("parametri") or {}).get("riposo_corto", 0.0)),
        uncertainty_active=bool(uncertainty.get("attiva")), sigma_goals=float(sigma.get("gol", 0.0)),
        sigma_corners=float(sigma.get("corner", 0.0)), sigma_cards=float(sigma.get("cartellini", 0.0)),
        recalibration_active=bool(recalibration.get("attiva")), recalibration=dict(recalibration.get("mappe") or {}),
        thresholds_active=bool(thresholds.get("attiva")), thresholds=dict(thresholds.get("soglie_ev") or {}),
        strength_model_only=bool(strength.get("solo_modello")) and bool(strength.get("pesi_modello_gol")),
        strength_goal_params=GoalModelParams(**strength["pesi_modello_gol"]) if strength.get("pesi_modello_gol") else None,
    )


DEFAULT_MODEL_V2 = load_model_v2()


def rest_factor(rest_days: tuple[float, float] | None, params: ModelV2Params) -> float:
    """Fattore sui gol di casa (l'ospite ha l'inverso) dai giorni di riposo, come ``tools.model_v2.rest_factors``."""
    if not params.rest_active or rest_days is None:
        return 1.0
    home, away = (float(np.clip(7.0 if value is None else value, 2, 7)) for value in rest_days)
    return math.exp(params.rest_per_day * (home - away) / 7.0 + params.rest_short * (float(away <= 3) - float(home <= 3)))


def recalibrate(probability_pct: float, mapping: Mapping[str, Any]) -> float:
    """Mappa finale (Platt o isotonica) da ``tools/recalibration_check.py``, su percentuali."""
    p = min(max(probability_pct / 100.0, 1e-6), 1 - 1e-6)
    if mapping.get("metodo") == "platt":
        q = 1.0 / (1.0 + math.exp(-(mapping["a"] + mapping["b"] * math.log(p / (1 - p)))))
    else:
        q = float(np.interp(p, mapping["x"], mapping["y"]))
    return round(100.0 * q, 2)


def value_threshold(selection: str) -> float | None:
    """Fase P, punto 7: EV minimo (punti %) del mercato della selezione dalle soglie stimate."""
    from today import ev_threshold

    return ev_threshold(selection)


# Complementi tenuti coerenti quando un mercato è ricalibrato (somma 100).
_COMPLEMENT = re.compile(r"^(Over|Under) (.+)$")


def apply_recalibration(percentages: Mapping[str, float], params: ModelV2Params) -> tuple[dict[str, float], list[str]]:
    """Probabilità finali ricalibrate (solo le mappe accese) con i complementi Over/Under coerenti."""
    if not params.recalibration_active or not params.recalibration:
        return dict(percentages), []
    out, changed = dict(percentages), []
    for key, mapping in params.recalibration.items():
        if key not in out:
            continue
        out[key] = recalibrate(out[key], mapping)
        changed.append(key)
        match = _COMPLEMENT.match(key)
        if match:
            other = f"{'Under' if match.group(1) == 'Over' else 'Over'} {match.group(2)}"
            if other in out:
                out[other] = round(100.0 - out[key], 2)
    return out, changed


@dataclass(frozen=True)
class HalfTimeParams:
    """Share of each team's full-time goals scored in the first half.

    Each goal is assigned to the first half with probability
    ``logistic(logit(share) + total_slope * (lambda + mu - reference_total))``,
    fitted by ``python -m tools.calibrate --primo-tempo``.  The defaults
    reproduce an even split.
    """

    home_share: float = 0.5
    away_share: float = 0.5
    total_slope: float = 0.0
    reference_total: float = 2.7


def load_half_time(path: Path = GOAL_MODEL_PATH) -> HalfTimeParams:
    if not path.exists():
        return HalfTimeParams()
    data = json.loads(path.read_text(encoding="utf-8"))
    return HalfTimeParams(**data.get("primo_tempo", {}).get("parametri", {}))


DEFAULT_HALF_TIME = load_half_time()


@dataclass(frozen=True)
class CountModelParams:
    """Log-linear corner and card means, fitted by ``python -m tools.calibrate --corner-cartellini``.

    Corners: ``log m_home = corner_home_intercept + corner_for_weight·log(corner pro casa)
    + corner_against_weight·log(corner sub ospite)`` (away symmetric).
    Cards: ``log m = card_intercept + card_team_weight·log(cartellini casa + ospite)
    + card_referee_yellow_weight·log(gialli arbitro) + card_referee_fouls_weight·log(falli arbitro)``.
    ``*_dispersion`` is the negative-binomial shape (0 = Poisson). With
    ``active=False`` the original averages are used.

    Fase M (``python -m tools.calibrate --estremi``): the corner total is shrunk
    towards ``corner_shrink_reference`` (``total' = R·(total/R)^corner_shrink_weight``,
    home/away share unchanged; reference 0 = off) and the yellow mean is
    multiplied by ``exp(card_balance_intercept + card_balance_weight·|ΔElo|/100)``
    (both 0 = off).
    """

    active: bool = False
    corner_home_intercept: float = 0.0
    corner_away_intercept: float = 0.0
    corner_for_weight: float = 0.5
    corner_against_weight: float = 0.5
    corner_dispersion: float = 0.0
    card_intercept: float = 0.0
    card_team_weight: float = 1.0
    card_referee_yellow_weight: float = 1.0
    card_referee_fouls_weight: float = 1.0
    card_dispersion: float = 0.0
    # Rossi attesi per giallo atteso (Poisson): 0 = solo gialli. Tarato con
    # ``python -m tools.calibrate --cartellini-punti``.
    card_red_ratio: float = 0.0
    corner_shrink_reference: float = 0.0
    corner_shrink_weight: float = 1.0
    card_balance_intercept: float = 0.0
    card_balance_weight: float = 0.0


def load_count_model(path: Path = GOAL_MODEL_PATH) -> CountModelParams:
    if not path.exists():
        return CountModelParams()
    data = json.loads(path.read_text(encoding="utf-8"))
    return CountModelParams(**data.get("corner_cartellini", {}).get("parametri", {}))


DEFAULT_COUNT_MODEL = load_count_model()


DOUBLE_YELLOW_RULES = ("giallo_e_rosso", "solo_rosso", "due_gialli_e_rosso")
# football-data.co.uk notes.txt: in English and Scottish leagues the first yellow of a double booking is not
# among the yellows (only the red); in the European leagues it is counted as yellow plus red.
SECOND_YELLOW_EXCLUDED_LEAGUES = ("E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "SC2", "SC3")


@dataclass(frozen=True)
class CardRule:
    """How the card market counts bookings (default: Eurobet, yellow 1, red 2).

    Counts follow the European football-data convention: a player sent off for
    a second yellow has the first yellow among the yellows and the red among
    the reds; the second yellow is not counted. ``double_yellow`` says what such
    a player is worth: ``giallo_e_rosso`` = yellow + red weight (Eurobet, 3),
    ``solo_rosso`` = red weight only, ``due_gialli_e_rosso`` = two yellows + red.
    The data do not tell second-yellow reds from straight reds, so the other
    two rules need ``double_yellow_share`` (share of reds that come from a second
    yellow) written explicitly in the configuration: there is no hidden default.
    """

    yellow_weight: int = 1
    red_weight: int = 2
    double_yellow: str = "giallo_e_rosso"
    double_yellow_share: float | None = None

    def __post_init__(self) -> None:
        if self.double_yellow not in DOUBLE_YELLOW_RULES:
            raise ValueError(f"regola_cartellini.doppia_ammonizione deve essere una di {DOUBLE_YELLOW_RULES}.")
        if any(not float(weight).is_integer() or weight < 0 for weight in (self.yellow_weight, self.red_weight)):
            raise ValueError("I pesi di giallo e rosso devono essere interi non negativi (linee x.5 senza pareggi).")
        if self.double_yellow != "giallo_e_rosso" and (self.double_yellow_share is None or not 0.0 <= self.double_yellow_share <= 1.0):
            raise ValueError("Con la regola di doppia ammonizione «" + self.double_yellow + "» serve "
                             "regola_cartellini.quota_rossi_doppia_ammonizione (0-1): i dati non la forniscono.")

    @property
    def double_yellow_extra(self) -> int:
        """Points added (or removed) for each red that comes from a second yellow."""
        return {"giallo_e_rosso": 0, "solo_rosso": -self.yellow_weight, "due_gialli_e_rosso": self.yellow_weight}[self.double_yellow]

    def describe(self) -> str:
        return f"giallo {self.yellow_weight}, rosso {self.red_weight}, doppia ammonizione {self.double_yellow.replace('_', ' ')}"


def card_points(yellows, reds, rule: CardRule, double_yellows=0):
    """Card-market points from counted yellows and reds (European convention, see ``CardRule``)."""
    return rule.yellow_weight * yellows + rule.red_weight * reds + rule.double_yellow_extra * double_yellows


def load_card_rule(path: Path = GOAL_MODEL_PATH) -> CardRule:
    if not path.exists():
        return CardRule()
    data = json.loads(path.read_text(encoding="utf-8")).get("regola_cartellini", {})
    return CardRule(
        yellow_weight=int(data.get("peso_giallo", 1)), red_weight=int(data.get("peso_rosso", 2)),
        double_yellow=data.get("doppia_ammonizione", "giallo_e_rosso"),
        double_yellow_share=data.get("quota_rossi_doppia_ammonizione"),
    )


DEFAULT_CARD_RULE = load_card_rule()


@dataclass(frozen=True)
class CountAnchorParams:
    """Corner and card means anchored to the quoted Over/Under lines (fase N).

    The market mean is the one whose distribution (same negative binomial and
    card-point rule as the simulation) best prices the margin-free Over
    probabilities; final mean = market^market_weight · model^(1 − market_weight).
    The weight is a declared default, not fitted: there are no historical
    corner or card odds to tune it on.
    """

    active: bool = True
    market_weight: float = 0.8
    devig_method: str = "proporzionale"


def load_count_anchor(path: Path = GOAL_MODEL_PATH) -> CountAnchorParams:
    if not path.exists():
        return CountAnchorParams()
    return CountAnchorParams(**json.loads(path.read_text(encoding="utf-8")).get("ancoraggio_conteggi", {}).get("parametri", {}))


DEFAULT_COUNT_ANCHOR = load_count_anchor()


@dataclass(frozen=True)
class CardSplitParams:
    """How the card total is divided between the teams (fase T, ``python -m tools.card_split``).

    Inactive = the original division ``p = cards_for casa / (casa + ospite)``. Active: logit p = ``home`` +
    ``rate_weight``·log(c_casa/c_ospite) + ``provoked_weight``·log(prov_ospite/prov_casa) + ``underdog_weight``·
    (P(2) − P(1)) + ``referee_weight``·log(gialli arbitro/4.5)·log(c_casa/c_ospite); the split of the
    yellows is a multiplicative binomial (``balance`` = log θ, > 0 favours balanced splits) or a
    beta-binomial (``concentration``); reds are divided with the same p. With 1X2 cards or team lines
    quoted, logit p moves towards the market by ``market_weight`` (declared, not fitted: no card odds in
    the history).
    """

    active: bool = False
    home: float = 0.0
    rate_weight: float = 1.0
    provoked_weight: float = 0.0
    underdog_weight: float = 0.0
    referee_weight: float = 0.0
    balance: float = 0.0
    concentration: float = 0.0
    market_weight: float = 0.8


def load_card_split(path: Path = GOAL_MODEL_PATH) -> CardSplitParams:
    if not path.exists():
        return CardSplitParams()
    section = json.loads(path.read_text(encoding="utf-8")).get("divisione_cartellini", {})
    names = {item.name for item in fields(CardSplitParams)}
    values = {key: value for key, value in section.get("parametri", {}).items() if key in names}
    return CardSplitParams(active=bool(section.get("attiva", False)), **values,
                           market_weight=float(section.get("peso_mercato", 0.8)))


DEFAULT_CARD_SPLIT = load_card_split()

import timeline as _timeline  # noqa: E402  (motore minuto per minuto, fase O)

DEFAULT_TIMELINE = _timeline.load(GOAL_MODEL_PATH)

import event_engine as _event_engine  # noqa: E402  (motore a eventi, fase AK)


@dataclass(frozen=True)
class EventEngineParams:
    """Fase AK: motore a eventi (sezione ``motore_eventi`` di ``config/goal_model.json``). Con ``active`` i punteggi restano
    quelli Dixon-Coles e il motore a eventi genera primo tempo, corner, falli e cartellini, riscalati sulle medie attuali
    (``event_engine.coherence``) e con arresto adattivo (``event_engine.simulate_adaptive``). Spento finché lo stadio 14 non
    lo verifica."""

    active: bool = False
    step_minutes: int = 5
    pilot: int = 10_000
    passes: int = 2
    batch: int = 10_000
    minimum: int = 20_000
    tolerance_pp: float = 0.25
    lanes: bool = False


def load_event_engine(path: Path = GOAL_MODEL_PATH) -> EventEngineParams:
    if not path.exists():
        return EventEngineParams()
    section = json.loads(path.read_text(encoding="utf-8")).get("motore_eventi", {})
    return EventEngineParams(
        active=bool(section.get("attivo", False)), step_minutes=int(section.get("passo_minuti", 5)),
        pilot=int(section.get("pilota", 10_000)), passes=int(section.get("passate", 2)),
        batch=int(section.get("lotto", 10_000)), minimum=int(section.get("minimo", 20_000)),
        tolerance_pp=float(section.get("tolleranza_pp", 0.25)), lanes=bool(section.get("corsie", False)),
    )


DEFAULT_EVENT_ENGINE = load_event_engine()


@lru_cache(maxsize=16)
def _event_params(league: str | None) -> "_event_engine.EventParams":
    return _event_engine.load(league)


@dataclass(frozen=True)
class StyleModelParams:
    """Forma reale (fase AD): al posto della covariata W-D-L, e peso xG più alto con poche gare.

    ``phi`` pesa la differenza di forma reale (xG−xGA per gara, centrata sul campionato) come ``form_weight`` pesa la
    forma W-D-L; ``k_xg`` alza la quota xG di attacco/difesa con poche gare: α_eff = α + (1−α)·k/(n+k).
    """

    active: bool = False
    phi: float = 0.0
    k_xg: float = 0.0


def load_style_model(path: Path = GOAL_MODEL_PATH.parent / "stile.json") -> StyleModelParams:
    if not path.exists():
        return StyleModelParams()
    section = json.loads(path.read_text(encoding="utf-8")).get("forma_reale", {})
    return StyleModelParams(active=bool(section.get("attiva", False)), phi=float(section.get("phi") or 0.0),
                            k_xg=float(section.get("k_xg") or 0.0))


DEFAULT_STYLE_MODEL = load_style_model()


@dataclass(frozen=True)
class TacticalSwitches:
    """Which tactical corrections are applied (validated by ``python -m tools.tactical``)."""

    goals: bool = False
    goals_supremacy: bool = False
    first_half: bool = False
    corners: bool = False
    cards: bool = False


@dataclass(frozen=True)
class TacticalFactors:
    """Corrections from matches against similar opponents (``datasources/similar.py``).

    ``lambda_``/``mu`` multiply the model goal rates before the market blend,
    ``first_half`` the first-half goal shares, the others the corner and card means.
    """

    lambda_: float = 1.0
    mu: float = 1.0
    first_half: float = 1.0
    corners_home: float = 1.0
    corners_away: float = 1.0
    cards: float = 1.0


@dataclass(frozen=True)
class ClaudeAdjustment:
    """Corrections pasted from a Claude answer (``claude_bridge.py``), already bounded.

    Goal factors multiply the final rates *after* the market blend; corner
    and card factors multiply the respective means.
    """

    goals_home: float = 1.0
    goals_away: float = 1.0
    corners: float = 1.0
    cards: float = 1.0


def load_tactical_switches(path: Path = GOAL_MODEL_PATH) -> TacticalSwitches:
    if not path.exists():
        return TacticalSwitches()
    data = json.loads(path.read_text(encoding="utf-8"))
    switches = data.get("scenario_tattico", {}).get("attivo", {})
    return TacticalSwitches(**{key: bool(value) for key, value in switches.items() if key in TacticalSwitches.__dataclass_fields__})


DEFAULT_TACTICAL_SWITCHES = load_tactical_switches()


def first_half_shares(lambda_, mu, params: HalfTimeParams):
    """First-half goal shares for home and away; scalars or numpy arrays."""
    shift = params.total_slope * (np.asarray(lambda_, dtype=float) + np.asarray(mu, dtype=float) - params.reference_total)

    def share(base: float):
        return 1.0 / (1.0 + np.exp(-(math.log(base / (1.0 - base)) + shift)))

    return share(params.home_share), share(params.away_share)


@dataclass(frozen=True)
class MatchConfig:
    home: TeamParams
    away: TeamParams
    referee_yellow_avg: float
    referee_fouls_avg: float
    simulations: int = 100_000
    seed: int = 42
    home_advantage: float = 1.15
    base_goals_home: float = 1.38
    base_goals_away: float = 1.12
    dixon_coles_rho: float | None = None
    odds: dict[str, float] | None = None
    # Quote per l'ancoraggio di gol, corner e cartellini quando diverse da quelle giocate (``odds``: EV e
    # semaforo). Es. quota sharp dell'API per i gol e tutta la scala Eurobet per corner e cartellini.
    # None = si ancorano le stesse ``odds``.
    anchor_odds: dict[str, float] | None = None
    goal_model: str = DEFAULT_GOAL_MODEL
    goal_params: GoalModelParams = DEFAULT_GOAL_PARAMS
    market_anchor: MarketAnchorParams = DEFAULT_MARKET_ANCHOR
    half_time: HalfTimeParams = DEFAULT_HALF_TIME
    count_model: CountModelParams = DEFAULT_COUNT_MODEL
    card_rule: CardRule = DEFAULT_CARD_RULE
    count_anchor: CountAnchorParams = DEFAULT_COUNT_ANCHOR
    card_split: CardSplitParams = DEFAULT_CARD_SPLIT
    timeline: Any = DEFAULT_TIMELINE  # timeline.TimelineParams (fase O); attivo solo se verificato
    tactical: TacticalFactors | None = None
    tactical_switches: TacticalSwitches = DEFAULT_TACTICAL_SWITCHES
    claude: ClaudeAdjustment | None = None
    # Fase P: campionato (codice football-data, es. «I1») e giorni di riposo (casa, ospite); usati solo dalle
    # opzioni accese di ``v2``.
    league: str | None = None
    rest_days: tuple[float | None, float | None] | None = None
    v2: ModelV2Params = DEFAULT_MODEL_V2
    # Fase Y: (attacco, difesa) Dixon-Coles per lato «home»/«away» (``datasources.builder.strength_inputs``).
    strength_inputs: Mapping[str, tuple[float, float]] | None = None
    # Fase Z: conserva i campioni simulati degli eventi (bit compressi) per il combo builder; le probabilità non cambiano.
    keep_samples: bool = False
    # Fase AD: {"home": {"forma_reale": x, "n_gare": n}, "away": {...}} da ``style_profile.get_style_params``; None = come prima.
    style: Mapping[str, Mapping[str, float]] | None = None
    style_model: StyleModelParams = DEFAULT_STYLE_MODEL
    # Fase AL: {"home": {"attack": f, "defense": g}, "away": {...}} da ``lineup.get_lineup_params(...)["motore"]``:
    # f moltiplica i gol della squadra (formazione vs XI tipo, già con l'esponente stimato), g quelli dell'avversario
    # (difesa indebolita). Agisce sul modello PRIMA dell'ancoraggio al mercato; None = come prima.
    lineup: Mapping[str, Mapping[str, float]] | None = None
    # Fase AK: motore a eventi (spento di default) e suoi ingressi facoltativi per lato «home»/«away»: {"profile": termini
    # del dizionario tattico, "module": «4-3-3»}; None = nessun profilo (solo medie e stato della partita).
    event_engine: EventEngineParams = DEFAULT_EVENT_ENGINE
    event_inputs: Mapping[str, Mapping[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.goal_model not in GOAL_MODELS:
            raise ValueError(f"goal_model deve essere uno di {GOAL_MODELS}.")
        if self.market_anchor.devig_method not in DEVIG_METHODS:
            raise ValueError(f"devig_method deve essere uno di {DEVIG_METHODS}.")
        if self.dixon_coles_rho is None:
            rho = _LEGACY_RHO if self.goal_model == "legacy" else self.goal_params.dixon_coles_rho
            object.__setattr__(self, "dixon_coles_rho", rho)


def config_from_input(match: MatchInput, simulations: int = 100_000, seed: int = 42) -> MatchConfig:
    def team(value: Any) -> TeamParams:
        return TeamParams(
            name=value.name,
            attack=value.attack,
            defense=value.defense,
            elo=value.elo,
            form=value.form,
            xg_for=value.xg_for,
            xg_against=value.xg_against,
            corners_for=value.corners_for,
            corners_against=value.corners_against,
            cards_for=value.cards_for,
            cards_provoked=getattr(value, "cards_provoked", None),
        )

    return MatchConfig(
        home=team(match.home),
        away=team(match.away),
        referee_yellow_avg=match.referee.yellow_avg,
        referee_fouls_avg=match.referee.fouls_avg,
        simulations=simulations,
        seed=seed,
        odds=dict(match.odds),
    )


def _form_weights(length: int) -> np.ndarray:
    """Recency weights: the most recent result (last token) weighs 1."""
    return np.array([0.7 ** index for index in range(length - 1, -1, -1)])


def _form_multiplier(form: str) -> float:
    values = {"W": 1.06, "D": 1.0, "L": 0.94}
    tokens = form.split("-")
    factors = np.array([values[token] for token in tokens])
    return float(np.average(factors, weights=_form_weights(len(tokens))))


def form_score(form: str) -> float:
    """Recency-weighted points in [-1, 1]: W=+1, D=0, L=-1."""
    values = {"W": 1.0, "D": 0.0, "L": -1.0}
    tokens = form.split("-")
    points = np.array([values[token] for token in tokens])
    return float(np.average(points, weights=_form_weights(len(tokens))))


def goal_rates(
    params: GoalModelParams,
    *,
    home_attack, home_defense, home_xg_for, home_xg_against, home_form,
    away_attack, away_defense, away_xg_for, away_xg_against, away_form,
    elo_diff,
    real_form: tuple | None = None, real_form_weight: float = 0.0, xg_k: float = 0.0, history: tuple | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Log-linear goal rates; works on scalars and on numpy arrays.

    Each team's rate multiplies, with full weight, its own attacking strength
    and the opponent's defensive weakness.  Each of those two factors blends
    the season coefficient with the xG ratio to ``base_goals``.  Elo adds a
    goal-supremacy term split evenly between the two rates, form is a small
    correction and home advantage is applied once, split between the rates.
    """
    base = params.base_goals

    def share(alpha, games):
        """Quota xG: con poche gare pesa di più (fase AD, solo se ``xg_k`` > 0 e il numero di gare è noto)."""
        if xg_k > 0 and games is not None:
            return alpha + (1.0 - alpha) * xg_k / (np.asarray(games, dtype=float) + xg_k)
        return alpha

    def attack(coefficient, xg_for, games=None):
        weight = share(params.attack_xg_share, games)
        return ((1.0 - weight) * np.log(np.clip(coefficient, 0.2, 3.0))
                + weight * np.log(np.clip(np.asarray(xg_for) / base, 0.1, 5.0)))

    def weak_defense(coefficient, xg_against, games=None):
        weight = share(params.defense_xg_share, games)
        return ((1.0 - weight) * -np.log(np.clip(coefficient, 0.2, 3.0))
                + weight * np.log(np.clip(np.asarray(xg_against) / base, 0.1, 5.0)))

    home_games, away_games = history if history is not None else (None, None)
    elo_term = 0.5 * params.elo_k * np.asarray(elo_diff, dtype=float) / 400.0
    if real_form is not None:   # forma reale AL POSTO della forma W-D-L
        form_term = 0.5 * real_form_weight * (np.asarray(real_form[0], dtype=float) - np.asarray(real_form[1], dtype=float))
    else:
        form_term = 0.5 * params.form_weight * (np.asarray(home_form) - np.asarray(away_form))
    parts = {
        "home_advantage": np.full_like(elo_term, 0.5 * params.home_advantage),
        "home_attack": params.attack_weight * attack(home_attack, home_xg_for, home_games),
        "away_attack": params.attack_weight * attack(away_attack, away_xg_for, away_games),
        "home_weak_defense": params.defense_weight * weak_defense(home_defense, home_xg_against, home_games),
        "away_weak_defense": params.defense_weight * weak_defense(away_defense, away_xg_against, away_games),
        "elo": elo_term,
        "form": form_term,
    }
    log_lambda = (math.log(base) + parts["home_advantage"] + parts["home_attack"]
                  + parts["away_weak_defense"] + elo_term + form_term)
    log_mu = (math.log(base) - parts["home_advantage"] + parts["away_attack"]
              + parts["home_weak_defense"] - elo_term - form_term)
    return np.clip(np.exp(log_lambda), 0.05, 5.0), np.clip(np.exp(log_mu), 0.05, 5.0), parts


def expected_goals(config: MatchConfig) -> tuple[float, float, dict[str, Any]]:
    """Return lambda/mu and a complete, human-readable contribution ledger."""
    if config.goal_model == "legacy":
        return _legacy_expected_goals(config)
    params = config.goal_params
    home_form, away_form = form_score(config.home.form), form_score(config.away.form)
    real = _real_form_inputs(config)
    lambda_, mu, parts = goal_rates(
        params,
        home_attack=config.home.attack, home_defense=config.home.defense,
        home_xg_for=config.home.xg_for, home_xg_against=config.home.xg_against, home_form=home_form,
        away_attack=config.away.attack, away_defense=config.away.defense,
        away_xg_for=config.away.xg_for, away_xg_against=config.away.xg_against, away_form=away_form,
        elo_diff=config.home.elo - config.away.elo,
        **(real or {}),
    )
    lineup = config.lineup
    if lineup:
        lambda_ = float(np.clip(lambda_ * lineup["home"]["attack"] * lineup["away"]["defense"], 0.05, 5.0))
        mu = float(np.clip(mu * lineup["away"]["attack"] * lineup["home"]["defense"], 0.05, 5.0))
    value = {key: float(part) for key, part in parts.items()}

    def side(sign: float, attack_key: str, defense_key: str, score: float) -> dict[str, float]:
        return {
            "base_goals": params.base_goals,
            "home_advantage_multiplier": math.exp(sign * value["home_advantage"]),
            "attack_multiplier": math.exp(value[attack_key]),
            "opponent_defense_multiplier": math.exp(value[defense_key]),
            "elo_multiplier": math.exp(sign * value["elo"]),
            "form_multiplier": math.exp(sign * value["form"]),
            "form_score": score,
        }

    ledger = {
        "model": "calibrato",
        "formula": (
            "log λ = log(base) + h/2 + β_att·[(1-α)·log Attacco + α·log(xG fatti/base)]"
            " + β_def·[(1-α_d)·log(1/Difesa avv.) + α_d·log(xG subiti avv./base)]"
            " + (k/2)·ΔElo/400 + φ·(forma - forma avv.)/2; μ simmetrica con segni opposti"
        ),
        "home": side(1.0, "home_attack", "away_weak_defense", home_form),
        "away": side(-1.0, "away_attack", "home_weak_defense", away_form),
        "weights": asdict(params),
    }
    if lineup:
        ledger["formazione"] = {"usata": True, "casa": dict(lineup["home"]), "ospite": dict(lineup["away"]),
                                "formula": "λ × attacco casa × difesa ospite; μ × attacco ospite × difesa casa "
                                           "(fase AL: XI atteso vs XI tipo, esponente e pesi di ruolo stimati dal backtest)"}
    style_model = config.style_model
    if style_model.active:
        ledger["forma_reale"] = _real_form_ledger(config, real)
        if real is not None:
            ledger["formula"] += (" | forma reale (fase AD): il termine forma usa φ_reale·(FR casa − FR ospite)/2 con "
                                  "FR = xG−xGA per gara centrata sul campionato, AL POSTO della forma W-D-L; "
                                  "α_xG,eff = α + (1−α)·k/(n+k)")
    return float(lambda_), float(mu), ledger


def _real_form_inputs(config: MatchConfig) -> dict[str, Any] | None:
    """Argomenti extra di ``goal_rates`` se la forma reale è accesa e il profilo di stile è disponibile."""
    model, style = config.style_model, config.style
    if not model.active or not style:
        return None
    home, away = style.get("home") or {}, style.get("away") or {}
    if home.get("forma_reale") is None or away.get("forma_reale") is None:
        return None
    return {"real_form": (float(home["forma_reale"]), float(away["forma_reale"])), "real_form_weight": model.phi,
            "xg_k": model.k_xg, "history": (float(home.get("n_gare", 0)), float(away.get("n_gare", 0)))}


def _real_form_ledger(config: MatchConfig, real: dict[str, Any] | None) -> dict[str, Any]:
    model = config.style_model
    if real is None:
        return {"attiva": True, "usata": False, "motivo": "profilo di stile non disponibile: resta la forma W-D-L"}
    k = model.k_xg
    alpha = config.goal_params.attack_xg_share
    games = real["history"]
    return {"attiva": True, "usata": True, "phi": model.phi, "k_xg": k,
            "forma_reale": {"casa": real["real_form"][0], "ospite": real["real_form"][1]},
            "gare": {"casa": games[0], "ospite": games[1]},
            "quota_xg_attacco": {"casa": alpha + (1 - alpha) * k / (games[0] + k) if k > 0 else alpha,
                                 "ospite": alpha + (1 - alpha) * k / (games[1] + k) if k > 0 else alpha},
            "formula": "termine forma = φ·(FR casa − FR ospite)/2, al posto della forma W-D-L; α_eff = α + (1−α)·k/(n+k)"}


def _legacy_expected_goals(config: MatchConfig) -> tuple[float, float, dict[str, Any]]:
    """Original formula, kept for comparison (``goal_model="legacy"``)."""
    elo_delta = config.home.elo - config.away.elo
    elo_home = 10.0 ** (elo_delta / 2400.0)
    elo_away = 10.0 ** (-elo_delta / 2400.0)
    home_form = _form_multiplier(config.home.form)
    away_form = _form_multiplier(config.away.form)

    home_xg_signal = np.mean([config.home.xg_for / config.base_goals_home, config.away.xg_against / config.base_goals_home])
    away_xg_signal = np.mean([config.away.xg_for / config.base_goals_away, config.home.xg_against / config.base_goals_away])
    home_attack = (config.home.attack ** 0.35) * (1.0 / config.away.defense) ** 0.25
    away_attack = (config.away.attack ** 0.35) * (1.0 / config.home.defense) ** 0.25
    home_strength = home_attack * (home_xg_signal ** 0.20) * (home_form ** 0.10) * (elo_home ** 0.10)
    away_strength = away_attack * (away_xg_signal ** 0.20) * (away_form ** 0.10) * (elo_away ** 0.10)
    lambda_ = float(np.clip(config.base_goals_home * config.home_advantage * home_strength, 0.05, 5.0))
    mu = float(np.clip(config.base_goals_away * away_strength, 0.05, 5.0))
    ledger = {
        "model": "legacy",
        "formula": "lambda = base_home * home_advantage * attack^0.35 * opponent_defense^-0.25 * xG^0.20 * form^0.10 * Elo^0.10",
        "home": {"attack_signal": home_attack, "xg_signal": home_xg_signal, "form_multiplier": home_form, "elo_multiplier": elo_home},
        "away": {"attack_signal": away_attack, "xg_signal": away_xg_signal, "form_multiplier": away_form, "elo_multiplier": elo_away},
        "weights": {"attack": 0.35, "opponent_defense": 0.25, "xg": 0.20, "form": 0.10, "elo": 0.10},
    }
    return lambda_, mu, ledger


def dixon_coles_matrix(lambda_: float, mu: float, rho: float, max_goals: int = 12) -> np.ndarray:
    goals = np.arange(max_goals + 1)
    matrix = np.outer(poisson.pmf(goals, lambda_), poisson.pmf(goals, mu))
    corrections = {(0, 0): 1 - lambda_ * mu * rho, (0, 1): 1 + mu * rho, (1, 0): 1 + lambda_ * rho, (1, 1): 1 - rho}
    for (home, away), factor in corrections.items():
        if factor < 0.0:
            raise ValueError("rho produce una probabilità Dixon-Coles negativa.")
        matrix[home, away] *= factor
    return matrix / matrix.sum()


def half_time_matrix(matrix: np.ndarray, home_share: float, away_share: float) -> np.ndarray:
    """First-half score matrix implied by a full-time matrix and goal shares.

    Every full-time goal falls in the first half independently with the
    team's share, as in the simulation.
    """
    goals = np.arange(matrix.shape[0])

    def thinning(share: float) -> np.ndarray:
        return binom.pmf(goals[None, :], goals[:, None], share)

    return thinning(home_share).T @ matrix @ thinning(away_share)


def remove_margin(odds: Sequence[float], method: str = "proporzionale") -> np.ndarray:
    """Fair probabilities of one market's mutually exclusive outcomes.

    ``proporzionale`` rescales the implied probabilities; ``shin`` assumes the
    margin protects against insiders and removes more of it from longshots.
    """
    implied = 1.0 / np.asarray(odds, dtype=float)
    total = implied.sum()
    if method == "proporzionale" or total <= 1.0:
        return implied / total
    if method != "shin":
        raise ValueError(f"Metodo di rimozione del margine sconosciuto: {method}")

    def shin(z: float) -> np.ndarray:
        return (np.sqrt(z * z + 4.0 * (1.0 - z) * implied ** 2 / total) - z) / (2.0 * (1.0 - z))

    z = brentq(lambda value: shin(value).sum() - 1.0, 0.0, 0.999)
    probabilities = shin(z)
    return probabilities / probabilities.sum()


def _score_market_probabilities(lambda_: float, mu: float, rho: float) -> dict[str, float]:
    matrix = dixon_coles_matrix(lambda_, mu, rho, max_goals=10)
    home, away = np.indices(matrix.shape)
    over = float(matrix[home + away > 2].sum())
    return {
        "1": float(matrix[home > away].sum()),
        "X": float(np.trace(matrix)),
        "2": float(matrix[home < away].sum()),
        "Over 2.5 gol": over,
        "Under 2.5 gol": 1.0 - over,
    }


def market_goal_rates(
    odds: Mapping[str, float] | None, method: str = "proporzionale", rho: float = _LEGACY_RHO
) -> dict[str, Any] | None:
    """Goal rates whose Poisson + Dixon-Coles prices best match the market.

    Needs the 1X2 odds; Under/Over 2.5 is used when both sides are quoted.
    Returns ``None`` when the 1X2 quotes are missing or invalid.
    """
    odds = odds or {}

    def valid(key: str) -> bool:
        try:
            value = float(odds[key])
        except (KeyError, TypeError, ValueError):
            return False
        return math.isfinite(value) and value > 1.0

    if not all(valid(key) for key in ("1", "X", "2")):
        return None
    target = dict(zip(("1", "X", "2"), remove_margin([odds[key] for key in ("1", "X", "2")], method)))
    if valid("Over 2.5 gol") and valid("Under 2.5 gol"):
        over, under = remove_margin([odds["Over 2.5 gol"], odds["Under 2.5 gol"]], method)
        target |= {"Over 2.5 gol": float(over), "Under 2.5 gol": float(under)}

    def cross_entropy(log_rates: np.ndarray) -> float:
        fitted = _score_market_probabilities(*np.exp(log_rates), rho)
        return -sum(
            probability * math.log(max(fitted[key], 1e-12)) for key, probability in target.items()
        )

    bounds = [(math.log(0.05), math.log(5.0))] * 2
    fitted = minimize(cross_entropy, np.log([1.4, 1.1]), method="L-BFGS-B", bounds=bounds)
    lambda_, mu = (float(value) for value in np.exp(fitted.x))
    fitted_probabilities = _score_market_probabilities(lambda_, mu, rho)
    return {
        "lambda": lambda_,
        "mu": mu,
        "method": method,
        "markets_used": list(target),
        "probabilities_pct": {key: round(value * 100.0, 2) for key, value in target.items()},
        "fitted_probabilities_pct": {key: round(fitted_probabilities[key] * 100.0, 2) for key in target},
        "max_fit_error_pct": round(
            max(abs(fitted_probabilities[key] - value) for key, value in target.items()) * 100.0, 2
        ),
    }


def _anchor_source(config: MatchConfig) -> Mapping[str, float] | None:
    """Quote da ancorare: ``anchor_odds`` se indicate, altrimenti le quote giocate."""
    return config.anchor_odds if config.anchor_odds is not None else config.odds


def anchor_goal_rates(model_lambda, model_mu, market_lambda, market_mu, params: MarketAnchorParams):
    """Log-scale blend; the model correction to the market rate is bounded.

    Works on scalars and numpy arrays.  Returns final lambda, final mu and the
    two applied corrections (final / market).
    """
    shift = 1.0 - params.market_weight
    corrections = [
        np.clip(np.exp(shift * (np.log(model) - np.log(market))), params.correction_min, params.correction_max)
        for model, market in ((model_lambda, market_lambda), (model_mu, market_mu))
    ]
    return (
        np.asarray(market_lambda) * corrections[0],
        np.asarray(market_mu) * corrections[1],
        corrections[0],
        corrections[1],
    )


def anchor_goal_rates_split(model_lambda, model_mu, market_lambda, market_mu, params: MarketAnchorParams,
                            weight_total, weight_supremacy):
    """Fase P, punto 5: come ``anchor_goal_rates`` ma con un peso del mercato per il totale (media geometrica
    di λ e μ) e uno per la supremazia (λ/μ). Con i due pesi uguali coincide con ``anchor_goal_rates``."""
    gap_lambda = np.log(model_lambda) - np.log(market_lambda)
    gap_mu = np.log(model_mu) - np.log(market_mu)
    total, supremacy = (gap_lambda + gap_mu) / 2.0, (gap_lambda - gap_mu) / 2.0
    total, supremacy = (1.0 - np.asarray(weight_total)) * total, (1.0 - np.asarray(weight_supremacy)) * supremacy
    corrections = [np.clip(np.exp(total + supremacy), params.correction_min, params.correction_max),
                   np.clip(np.exp(total - supremacy), params.correction_min, params.correction_max)]
    return (np.asarray(market_lambda) * corrections[0], np.asarray(market_mu) * corrections[1],
            corrections[0], corrections[1])


def final_goal_rates(config: MatchConfig) -> tuple[float, float, dict[str, Any]]:
    """Expected goals used by the simulation: model anchored to market odds.

    Without valid 1X2 odds, or with anchoring disabled, the model rates are
    returned unchanged. Claude's goal corrections, when present, multiply the
    rates after the market blend.
    """
    lambda_, mu, details = _anchored_goal_rates(config)
    factor = rest_factor(config.rest_days, config.v2)
    if factor != 1.0:
        # Fase P, punto 6: riposo, dopo l'ancoraggio al mercato.
        details = {**details, "rest": {"giorni": config.rest_days, "fattore_casa": factor}}
        lambda_, mu = lambda_ * factor, mu / factor
    if config.claude is not None:
        details = {**details, "claude": {"lambda_before": lambda_, "mu_before": mu,
                                         "goals_home": config.claude.goals_home, "goals_away": config.claude.goals_away}}
        lambda_, mu = lambda_ * config.claude.goals_home, mu * config.claude.goals_away
    return lambda_, mu, details


def strength_model_config(config: MatchConfig) -> MatchConfig | None:
    """Fase Y, punto 0: la stessa partita con Attacco/Difesa corretti per il calendario e i pesi del modello
    ristimati, quando l'opzione «solo modello» è accesa e non ci sono quote 1X2 per l'ancoraggio."""
    from dataclasses import replace

    if not (config.v2.strength_model_only and config.strength_inputs and config.goal_model != "legacy"):
        return None
    if config.market_anchor.active and market_goal_rates(_anchor_source(config), config.market_anchor.devig_method,
                                                         config.dixon_coles_rho) is not None:
        return None
    (home_attack, home_defense), (away_attack, away_defense) = config.strength_inputs["home"], config.strength_inputs["away"]
    return replace(config, goal_params=config.v2.strength_goal_params,
                   home=replace(config.home, attack=home_attack, defense=home_defense),
                   away=replace(config.away, attack=away_attack, defense=away_defense))


def _anchored_goal_rates(config: MatchConfig) -> tuple[float, float, dict[str, Any]]:
    strength_config = strength_model_config(config)
    model_lambda, model_mu, ledger = expected_goals(strength_config or config)
    if strength_config is not None:
        ledger = {**ledger, "forza_calendario": {
            "nota": "Partita senza quote 1X2/O-U: modello con attacco e difesa corretti per il calendario (Dixon-Coles), "
                    "che fuori campione migliora il modello da solo.",
            "ingressi": dict(config.strength_inputs)}}
    tactical = _tactical(config, "goals")
    supremacy = _tactical(config, "goals_supremacy")
    if tactical is not None:
        # Correzione degli avversari simili sul modello, prima della combinazione con il mercato.
        model_lambda, model_mu = model_lambda * tactical.lambda_, model_mu * tactical.mu
        ledger = {**ledger, "tactical": {"lambda_factor": tactical.lambda_, "mu_factor": tactical.mu}}
    elif supremacy is not None:
        # Solo il rapporto di forza: λ·μ (e quindi circa il totale) resta invariato.
        shift = math.sqrt(supremacy.lambda_ / supremacy.mu)
        model_lambda, model_mu = model_lambda * shift, model_mu / shift
        ledger = {**ledger, "tactical": {"lambda_factor": shift, "mu_factor": 1.0 / shift, "mode": "solo rapporto di forza"}}
    params = config.market_anchor
    anchoring: dict[str, Any] = {
        "active": False,
        "model_lambda": model_lambda,
        "model_mu": model_mu,
        "params": asdict(params),
    }
    market = (
        market_goal_rates(_anchor_source(config), params.devig_method, config.dixon_coles_rho)
        if params.active
        else None
    )
    if market is None:
        anchoring["reason"] = (
            "Ancoraggio disattivato nella configurazione." if not params.active
            else "Quote 1X2 assenti: si usa solo il modello."
        )
        return model_lambda, model_mu, {"ledger": ledger, "anchoring": anchoring}
    league_weights = config.v2.league_weights.get(config.league or "") if config.v2.league_weights_active else None
    if league_weights is not None:
        # Fase P, punto 5: peso del mercato del campionato, separato per totale gol e supremazia.
        lambda_, mu, correction_home, correction_away = anchor_goal_rates_split(
            model_lambda, model_mu, market["lambda"], market["mu"], params, *league_weights)
        anchoring["league_weights"] = {"campionato": config.league, "totale": league_weights[0],
                                       "supremazia": league_weights[1]}
    else:
        lambda_, mu, correction_home, correction_away = anchor_goal_rates(
            model_lambda, model_mu, market["lambda"], market["mu"], params
        )
    anchoring.update({
        "active": True,
        "reason": f"Gol attesi = mercato^{params.market_weight:g} · modello^{1 - params.market_weight:g}, "
                  f"correzione limitata a [{params.correction_min:g}, {params.correction_max:g}].",
        "market": market,
        "market_lambda": market["lambda"],
        "market_mu": market["mu"],
        "correction_home": float(correction_home),
        "correction_away": float(correction_away),
    })
    return float(lambda_), float(mu), {"ledger": ledger, "anchoring": anchoring}


def _market(mask: np.ndarray) -> dict[str, Any]:
    count = int(mask.sum())
    interval = _confidence(mask)
    probability = count / len(mask)
    return {
        "count": count,
        "percentage": round(probability * 100.0, 2),
        "fair_odds": round(1.0 / probability, 3) if probability > 0.0 else None,
        "confidence_interval_95": interval,
        "reliability_pct": _reliability(interval),
    }


def _confidence(mask: np.ndarray) -> list[float]:
    n = len(mask)
    p = float(mask.mean())
    z = 1.96
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [round(max(0.0, center - margin) * 100, 2), round(min(1.0, center + margin) * 100, 2)]


def _reliability(interval: list[float]) -> float:
    """Convert a Wilson interval width into a sample-stability indicator."""
    return round(float(np.clip(100.0 - (interval[1] - interval[0]), 0.0, 100.0)), 2)


def _event_catalog(
    home: np.ndarray,
    away: np.ndarray,
    first_home: np.ndarray,
    first_away: np.ndarray,
    second_home: np.ndarray,
    second_away: np.ndarray,
    home_corners: np.ndarray,
    away_corners: np.ndarray,
    home_cards: np.ndarray,
    away_cards: np.ndarray,
    team_multigol_ranges: tuple[tuple[int, int], ...] = _DEFAULT_TEAM_MULTIGOL_RANGES,
    half_counts: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> dict[str, np.ndarray]:
    """Eventi del catalogo dallo stesso campione. ``half_counts`` = corner casa/ospite e punti cartellini
    casa/ospite del primo tempo (fase Q): senza, i mercati di corner e cartellini per tempo non ci sono."""
    total = home + away
    first_total = first_home + first_away
    second_total = second_home + second_away
    corners = home_corners + away_corners
    cards = home_cards + away_cards
    events = {
        "1": home > away,
        "1X": home >= away,
        "12": home != away,
        "X": home == away,
        "X2": away >= home,
        "2": home < away,
        "Goal": (home > 0) & (away > 0),
        "No Goal": (home == 0) | (away == 0),
        "Goal 1T": (first_home > 0) & (first_away > 0),
        "No Goal 1T": (first_home == 0) | (first_away == 0),
        "Casa segna": home > 0,
        "Casa non segna": home == 0,
        "Ospite segna": away > 0,
        "Ospite non segna": away == 0,
        "Casa DNB": home > away,
        "Ospite DNB": away > home,
        "Casa DNB push": home == away,
        "Ospite DNB push": home == away,
        "BTTS entrambi i tempi": (first_home > 0) & (first_away > 0) & (second_home > 0) & (second_away > 0),
        "BTTS almeno un tempo": ((first_home > 0) & (first_away > 0)) | ((second_home > 0) & (second_away > 0)),
        "1 secondo tempo": second_home > second_away,
        "X secondo tempo": second_home == second_away,
        "2 secondo tempo": second_home < second_away,
        "1X secondo tempo": second_home >= second_away,
        "X2 secondo tempo": second_away >= second_home,
        "12 secondo tempo": second_home != second_away,
    }
    for prefix, values in (("", total), ("1T ", first_total), ("2T ", second_total)):
        for threshold in GOAL_LINES:
            events[f"Over {threshold:g} gol {prefix}".strip()] = values > threshold
            events[f"Under {threshold:g} gol {prefix}".strip()] = values < threshold
    for team_name, values in (("Casa", home), ("Ospite", away)):
        for threshold in (0.5, 1.5, 2.5):
            events[f"{team_name} Over {threshold:g} gol"] = values > threshold
            events[f"{team_name} Under {threshold:g} gol"] = values < threshold
    for low, high in MULTIGOL_RANGES:
        events[f"Multigol {low}-{high}"] = (total >= low) & (total <= high)
    for half, values, ranges in (("1T", first_total, MULTIGOL_1T_RANGES), ("2T", second_total, MULTIGOL_2T_RANGES)):
        for low, high in ranges:
            events[f"Multigol {half} {range_label(low, high)}"] = (values >= low) & (values <= high)
    for home_low, home_high in TEAM_PAIR_RANGES:
        home_in = (home >= home_low) & (home <= home_high)
        for away_low, away_high in TEAM_PAIR_RANGES:
            events[f"Multigol Casa {home_low}-{home_high} + Ospite {away_low}-{away_high}"] = home_in & (away >= away_low) & (away <= away_high)
    for low, high in CORNER_TOTAL_BANDS:
        events[f"Corner totali {range_label(low, high)}"] = (corners >= low) & (corners <= high)
    for team_name, values in (("casa", home_corners), ("ospite", away_corners)):
        for low, high in CORNER_TEAM_BANDS:
            events[f"Corner {team_name} {range_label(low, high)}"] = (values >= low) & (values <= high)
    for low, high in CARD_TOTAL_BANDS:
        events[f"Cartellini totali {range_label(low, high)}"] = (cards >= low) & (cards <= high)
    for team_name, values in (("casa", home_cards), ("ospite", away_cards)):
        for low, high in CARD_TEAM_BANDS:
            events[f"Cartellini {team_name} {range_label(low, high)}"] = (values >= low) & (values <= high)
    if half_counts is not None:
        corner_first_home, corner_first_away, card_first_home, card_first_away = half_counts
        halves = {"1T": (corner_first_home, corner_first_away, card_first_home, card_first_away),
                  "2T": (home_corners - corner_first_home, away_corners - corner_first_away,
                         home_cards - card_first_home, away_cards - card_first_away)}
        for half, (corner_home_half, corner_away_half, card_home_half, card_away_half) in halves.items():
            for threshold in CORNER_HALF_LINES:
                events[f"Over {threshold:g} corner {half}"] = corner_home_half + corner_away_half > threshold
                events[f"Under {threshold:g} corner {half}"] = corner_home_half + corner_away_half < threshold
            for threshold in CARD_HALF_LINES[half]:
                events[f"Over {threshold:g} cartellini {half}"] = card_home_half + card_away_half > threshold
                events[f"Under {threshold:g} cartellini {half}"] = card_home_half + card_away_half < threshold
        events.update({"1 corner 1T": corner_first_home > corner_first_away, "X corner 1T": corner_first_home == corner_first_away,
                       "2 corner 1T": corner_first_home < corner_first_away, "1 cartellini 1T": card_first_home > card_first_away,
                       "X cartellini 1T": card_first_home == card_first_away, "2 cartellini 1T": card_first_home < card_first_away})
    for team_name, values in (("Casa", home), ("Ospite", away)):
        for low, high in team_multigol_ranges:
            events[f"Multigol {team_name} {low}-{high}"] = (values >= low) & (values <= high)
    for value in range(5):
        events[f"Somma gol {value}"] = total == value
    events["Somma gol 5+"] = total >= 5
    for result_prefix, result_home, result_away in (
        ("", home, away),
        ("1T ", first_home, first_away),
        ("2T ", second_home, second_away),
    ):
        events[f"1 {result_prefix}".strip()] = result_home > result_away
        events[f"X {result_prefix}".strip()] = result_home == result_away
        events[f"2 {result_prefix}".strip()] = result_home < result_away
        events[f"1X {result_prefix}".strip()] = result_home >= result_away
        events[f"X2 {result_prefix}".strip()] = result_away >= result_home
        events[f"12 {result_prefix}".strip()] = result_home != result_away
    for threshold in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5):
        events[f"Over {threshold:g} corner"] = corners > threshold
        events[f"Under {threshold:g} corner"] = corners < threshold
    for team_name, values in (("Casa", home_corners), ("Ospite", away_corners)):
        for threshold in (2.5, 3.5, 4.5, 5.5, 6.5):
            events[f"{team_name} Over {threshold:g} corner"] = values > threshold
            events[f"{team_name} Under {threshold:g} corner"] = values < threshold
    for threshold in (2.5, 3.5, 4.5, 5.5, 6.5):
        events[f"Over {threshold:g} cartellini"] = cards > threshold
        events[f"Under {threshold:g} cartellini"] = cards < threshold
    for team_name, values in (("Casa", home_cards), ("Ospite", away_cards)):
        for threshold in (0.5, 1.5, 2.5, 3.5, 4.5):
            events[f"{team_name} Over {threshold:g} cartellini"] = values > threshold
            events[f"{team_name} Under {threshold:g} cartellini"] = values < threshold
    events.update({
        "1 corner": home_corners > away_corners,
        "X corner": home_corners == away_corners,
        "2 corner": home_corners < away_corners,
        "1 cartellini": home_cards > away_cards,
        "X cartellini": home_cards == away_cards,
        "2 cartellini": home_cards < away_cards,
    })
    for first_result, second_result, label in (
        ("1", "Over 1.5 gol", "1 + Over 1.5"),
        ("1", "Over 2.5 gol", "1 + Over 2.5"),
        ("1", "Over 3.5 gol", "1 + Over 3.5"),
        ("X2", "Under 2.5 gol", "X2 + Under 2.5"),
        ("X2", "Under 3.5 gol", "X2 + Under 3.5"),
        ("1X", "Goal", "1X + Goal"),
        ("1X", "No Goal", "1X + No Goal"),
        ("2", "Goal", "2 + Goal"),
        ("2", "No Goal", "2 + No Goal"),
        ("1", "Multigol 1-3", "1 + Multigol 1-3"),
    ):
        events[label] = events[first_result] & events[second_result]
    for low, high in MULTIGOL_RANGES:
        events[f"1 + Multigol {low}-{high}"] = events["1"] & events[f"Multigol {low}-{high}"]
        events[f"2 + Multigol {low}-{high}"] = events["2"] & events[f"Multigol {low}-{high}"]
    # Combo del catalogo non elencate sopra (fase Q: 1X2/DC + U/O completi, GG/NG + U/O): unione logica delle gambe.
    for definition in MARKET_CATALOG:
        if definition.combo_legs and definition.event_key not in events and all(leg in events for leg in definition.combo_legs):
            mask = events[definition.combo_legs[0]]
            for leg in definition.combo_legs[1:]:
                mask = mask & events[leg]
            events[definition.event_key] = mask
    return events


def _team_multigol_ranges(odds: Mapping[str, float] | None) -> tuple[tuple[int, int], ...]:
    """Return default plus every valid team range explicitly requested by odds."""
    ranges = set(_DEFAULT_TEAM_MULTIGOL_RANGES)
    for key in odds or {}:
        match = _TEAM_MULTIGOL_KEY.fullmatch(key.strip())
        if not match:
            continue
        low, high = int(match["low"]), int(match["high"])
        if low <= high:
            ranges.add((low, high))
    return tuple(sorted(ranges))


def _validate_event_catalog(events: Mapping[str, np.ndarray], simulations: int) -> None:
    """Fail fast if any published market can disagree with the score sample."""
    required_partitions = (
        (("1", "X", "2"), "1X2"),
        (("1X", "X2"), "double chance"),
        (("Goal", "No Goal"), "goal/no goal"),
    )
    for keys, label in required_partitions:
        masks = [events[key] for key in keys]
        if any(len(mask) != simulations for mask in masks):
            raise RuntimeError(f"Maschere {label} non allineate al campione dei gol.")
    if not np.all(events["1"] | events["X"] | events["2"]):
        raise RuntimeError("Il catalogo 1X2 non copre ogni risultato simulato.")
    if np.any(events["1"] & events["X"]) or np.any(events["X"] & events["2"]) or np.any(events["1"] & events["2"]):
        raise RuntimeError("Il catalogo 1X2 contiene esiti sovrapposti.")
    if not np.array_equal(events["1X"], events["1"] | events["X"]):
        raise RuntimeError("La doppia chance 1X non è coerente con il risultato esatto.")
    if not np.array_equal(events["X2"], events["X"] | events["2"]):
        raise RuntimeError("La doppia chance X2 non è coerente con il risultato esatto.")
    if not np.array_equal(events["12"], events["1"] | events["2"]):
        raise RuntimeError("La doppia chance 12 non è coerente con il risultato esatto.")
    if not np.array_equal(events["Goal"], ~events["No Goal"]):
        raise RuntimeError("Goal e No Goal non sono complementari.")
    for threshold in (0.5, 1.5, 2.5, 3.5, 4.5):
        over = events[f"Over {threshold:g} gol"]
        under = events[f"Under {threshold:g} gol"]
        if not np.array_equal(over, ~under):
            raise RuntimeError(f"Over/Under {threshold:g} non è coerente con la somma gol.")
    for value in range(5):
        exact = events[f"Somma gol {value}"]
        expected = (
            ~events["Over 0.5 gol"]
            if value == 0
            else events[f"Over {value - 0.5:g} gol"] & ~events[f"Over {value + 0.5:g} gol"]
        )
        if not np.array_equal(exact, expected):
            raise RuntimeError(f"Somma gol {value} non è coerente con Over/Under.")
    if not np.array_equal(events["Somma gol 5+"], events["Over 4.5 gol"]):
        raise RuntimeError("Somma gol 5+ non è coerente con Over 4.5.")


def _probability(mask: np.ndarray) -> float:
    return float(mask.mean())


def _conditional_scenarios(
    events: Mapping[str, np.ndarray], outcomes: Mapping[str, np.ndarray]
) -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    for sign, condition in outcomes.items():
        sample_count = int(condition.sum())
        markets = {
            market: round(float(mask[condition].mean()) * 100.0, 2)
            if sample_count
            else None
            for market, mask in events.items()
        }
        scenarios[sign] = {
            "sample_count": sample_count,
            "sample_share_pct": round(sample_count / len(condition) * 100.0, 2),
            "markets": markets,
        }
    return scenarios


def financial_analysis(
    events: Mapping[str, np.ndarray],
    odds: Mapping[str, float] | None,
    components: Mapping[str, Mapping[str, float] | None] | None = None,
    suspicious_gap_pct: float = MarketAnchorParams().suspicious_gap_pct,
    no_value_markets: Sequence[str] = MarketAnchorParams().no_value_markets,
    recalibrated: Mapping[str, float] | None = None,
    threshold: Callable[[str], float | None] | None = None,
) -> dict[str, Any]:
    """Calculate settlement-aware EV and quarter-Kelly stake for user odds.

    With ``components`` (model-only and market-only percentages per event) a
    positive-EV market is flagged as suspicious when the two sources diverge
    by more than ``suspicious_gap_pct`` points.  Markets in
    ``no_value_markets`` keep their EV but are never reported as value.
    """
    model_only = (components or {}).get("modello") or {}
    market_only = (components or {}).get("mercato") or {}
    candidates: list[dict[str, Any]] = []
    for market, raw_odd in (odds or {}).items():
        if market not in events:
            continue
        try:
            odd = float(raw_odd)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(odd) or odd <= 1.0:
            continue
        probability = _probability(events[market])
        if recalibrated and market in recalibrated:
            probability = recalibrated[market] / 100.0  # fase P, punto 4: mappa finale accesa
        confidence_interval = _confidence(events[market])
        definition = definition_for_event(market)
        push_probability = _probability(events[f"{market} push"]) if definition and definition.settlement == "push" else 0.0
        loss_probability = max(0.0, 1.0 - probability - push_probability)
        non_push_probability = probability + loss_probability
        conditional_win_probability = (
            probability / non_push_probability if non_push_probability else 0.0
        )
        edge = conditional_win_probability - (1.0 / odd)
        ev = probability * (odd - 1.0) - loss_probability
        denominator = (odd - 1.0) * (probability + loss_probability)
        full_kelly = max(0.0, (probability * (odd - 1.0) - loss_probability) / denominator) if denominator else 0.0
        settlement_fair_odds = (
            1.0 + loss_probability / probability if probability > 0 else None
        )
        fair_odds = settlement_fair_odds
        gap = (
            round(abs(model_only[market] - market_only[market]), 2)
            if market in model_only and market in market_only
            else None
        )
        value_allowed = market not in no_value_markets
        minimum = threshold(market) if threshold is not None else None
        candidates.append({
            "market": market,
            "odds": odd,
            "simulated_probability_pct": round(probability * 100.0, 2),
            "implied_probability_pct": round(100.0 / odd, 2),
            "edge_pct": round(edge * 100.0, 2),
            "ev_pct": round(ev * 100.0, 2),
            "push_probability_pct": round(push_probability * 100.0, 2),
            "loss_probability_pct": round(loss_probability * 100.0, 2),
            "fair_odds": round(fair_odds, 3) if fair_odds is not None else None,
            "settlement_fair_odds": (
                round(settlement_fair_odds, 3)
                if settlement_fair_odds is not None
                else None
            ),
            "kelly_pct": round(full_kelly * 100.0, 2),
            "kelly_fraction": 0.25,
            "recommended_quarter_kelly_pct": round(full_kelly * 25.0, 2),
            "recommended_stake_pct": round(full_kelly * 25.0, 2),
            "confidence_interval_95": confidence_interval,
            "reliability_pct": _reliability(confidence_interval),
            # Fase P, punto 7: con le soglie stimate accese serve un EV almeno pari all'errore tipico del mercato.
            "ev_threshold_pct": minimum,
            "is_value": ev > 0.0 and value_allowed and ev * 100.0 >= (minimum or 0.0),
            "value_excluded": not value_allowed,
            "model_only_probability_pct": model_only.get(market),
            "market_only_probability_pct": market_only.get(market),
            "model_market_gap_pct": gap,
            "suspicious_value": ev > 0.0 and value_allowed and gap is not None and gap > suspicious_gap_pct,
        })
    candidates.sort(key=lambda item: (item["ev_pct"], item["edge_pct"]), reverse=True)
    value_bets = [item for item in candidates if item["is_value"]]
    return {
        "quotes_provided": len(candidates),
        "markets": candidates,
        "value_bets": value_bets,
        "best_value": value_bets[0] if value_bets else None,
        "value_threshold_ev_pct": 0.0,
        "no_value_markets": list(no_value_markets),
        "risk_note": "Kelly è una stima sensibile all'errore del modello; viene mostrato un quarto Kelly, non una garanzia.",
    }


# Famiglie dei Combo Builder (fase S): due mercati di famiglie diverse della stessa partita.
COMBO_FAMILIES = {
    "gol": tuple([f"{side} {line} gol" for line in ("1.5", "2.5", "3.5") for side in ("Over", "Under")]
                 + ["Goal", "No Goal"] + [f"Multigol {low}-{high}" for low, high in MULTIGOL_RANGES]),
    "corner": tuple(f"{side} {line:g} corner" for line in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5) for side in ("Over", "Under")),
    "cartellini": tuple(f"{side} {line:g} cartellini" for line in (2.5, 3.5, 4.5, 5.5, 6.5) for side in ("Over", "Under")),
}
COMBO_PAIRS = (("gol", "corner"), ("cartellini", "corner"), ("cartellini", "gol"))


def joint_pair_probabilities(events: Mapping[str, np.ndarray]) -> dict[str, float]:
    """Probabilità congiunta (%) di ogni coppia di famiglie diverse, dagli stessi run simulati (non il prodotto).

    Chiave «A & B» con A della prima famiglia della coppia (vedi ``COMBO_PAIRS``).
    """
    joint = {}
    for first, second in COMBO_PAIRS:
        for a in COMBO_FAMILIES[first]:
            if a not in events:
                continue
            for b in COMBO_FAMILIES[second]:
                if b in events:
                    joint[f"{a} & {b}"] = round(float(np.mean(events[a] & events[b])) * 100.0, 3)
    return joint


def smart_combo(
    events: Mapping[str, np.ndarray],
    odds: Mapping[str, float] | None,
    no_value_markets: Sequence[str] = (),
) -> dict[str, Any]:
    """Rank every quoted two-leg combination by value and stability."""
    if not odds:
        return {"status": "no_quotes", "legs": [], "message": "Inserire almeno due quote per calcolare una schedina."}
    options: list[dict[str, Any]] = []
    available = [
        market
        for market in odds
        if market in events
        and definition_for_event(market)
        and definition_for_event(market).settlement != "push"
        and " + " not in market
        and market not in no_value_markets
    ]
    for index, first in enumerate(available):
        for second in available[index + 1:]:
            if first == second:
                continue
            try:
                odd_a, odd_b = float(odds[first]), float(odds[second])
            except (TypeError, ValueError):
                continue
            if odd_a <= 1.0 or odd_b <= 1.0:
                continue
            joint = events[first] & events[second]
            probability = _probability(joint)
            total_odd = odd_a * odd_b
            ev = probability * total_odd - 1.0
            if ev <= 0.0:
                continue
            confidence_interval = _confidence(joint)
            denominator = total_odd - 1.0
            full_kelly = max(0.0, ev / denominator) if denominator else 0.0
            reliability = _reliability(confidence_interval)
            options.append({
                "legs": [first, second],
                "odds": [odd_a, odd_b],
                "combined_odds": round(total_odd, 3),
                "simulated_probability_pct": round(probability * 100.0, 2),
                "ev_pct": round(ev * 100.0, 2),
                "joint_count": int(joint.sum()),
                "kelly_pct": round(full_kelly * 100.0, 2),
                "kelly_fraction": 0.25,
                "recommended_quarter_kelly_pct": round(full_kelly * 25.0, 2),
                "recommended_stake_pct": round(full_kelly * 25.0, 2),
                "confidence_interval_95": confidence_interval,
                "reliability_pct": reliability,
                "risk_reward_score": round(ev * (reliability / 100.0), 6),
                "is_value": True,
            })
    options.sort(key=lambda item: (item["risk_reward_score"], item["ev_pct"]), reverse=True)
    return {
        "status": "ready" if options else "insufficient_quotes",
        "recommendation": options[0] if options else None,
        "candidates": options,
        "message": "La probabilità è congiunta sui campioni simulati, non il prodotto di probabilità indipendenti.",
    }


def _catalog_markets(events: Mapping[str, np.ndarray]) -> dict[str, dict[str, dict[str, Any]]]:
    """Materialize every catalog definition from the shared event namespace."""
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for definition in MARKET_CATALOG:
        if definition.event_key not in events:
            continue
        groups.setdefault(definition.group, {})[definition.key] = _market(events[definition.event_key])
    return groups


def statistical_report(config: MatchConfig, result: Mapping[str, Any]) -> str:
    """Generate a metric-only contextual report, with no fixed football claims."""
    model = result["model"]
    summary = result["summary"]
    markets = result["markets"]
    home, away = config.home.name, config.away.name
    p1, px, p2 = (markets["1x2"][key]["percentage"] for key in ("1", "X", "2"))
    leader = home if p1 >= max(px, p2) else away if p2 >= px else "il pareggio"
    score = summary["modal_score"]
    xg_gap = model["lambda"] - model["mu"]
    direction = "favore casa" if xg_gap > 0 else "favore ospite" if xg_gap < 0 else "equilibrato"
    return (
        f"Sintesi statistica: {leader} è l'esito 1X2 più frequente "
        f"({max(p1, px, p2):.2f}%). λ={model['lambda']:.3f}, μ={model['mu']:.3f}, "
        f"scarto xG {xg_gap:+.3f} ({direction}). Score modale "
        f"{score['home']}-{score['away']} nel {score['share_pct']:.2f}% dei campioni. "
        f"Over 2.5: {markets['over_under']['Over_2.5']['percentage']:.2f}%; "
        f"Goal: {markets['goal_no_goal']['Goal']['percentage']:.2f}%. "
        f"Il risultato è descrittivo della simulazione, non una certezza."
    )


def _tactical(config: MatchConfig, family: str) -> TacticalFactors | None:
    """Tactical factors if present and enabled for ``family``."""
    if config.tactical is None or not getattr(config.tactical_switches, family):
        return None
    return config.tactical


def _log(value: float) -> float:
    return math.log(max(float(value), 0.1))


def _model_corner_signals(config: MatchConfig) -> tuple[float, float]:
    """Model corners per team (with the similar-opponents factors), before market and Claude."""
    params = config.count_model
    if not params.active:
        home = (config.home.corners_for + config.away.corners_against) / 2.0
        away = (config.away.corners_for + config.home.corners_against) / 2.0
    else:
        home = math.exp(params.corner_home_intercept + params.corner_for_weight * _log(config.home.corners_for)
                        + params.corner_against_weight * _log(config.away.corners_against))
        away = math.exp(params.corner_away_intercept + params.corner_for_weight * _log(config.away.corners_for)
                        + params.corner_against_weight * _log(config.home.corners_against))
        total = home + away
        if params.corner_shrink_reference > 0.0 and total > 0.0:
            # Team averages are noisy: shrink the total towards the reference, keep the home/away split.
            shrunk = params.corner_shrink_reference * (total / params.corner_shrink_reference) ** params.corner_shrink_weight
            home, away = home * shrunk / total, away * shrunk / total
    tactical = _tactical(config, "corners")
    if tactical is not None:
        home, away = home * tactical.corners_home, away * tactical.corners_away
    return home, away


def corner_signals(config: MatchConfig) -> tuple[float, float]:
    """Expected corners per team: model, anchored to the corner lines when quoted, then Claude's factor."""
    home, away = _model_corner_signals(config)
    anchoring = _anchor_count(config, "corner", home + away)
    if anchoring["active"] and home + away > 0.0:
        factor = anchoring["final_mean"] / (home + away)
        home, away = home * factor, away * factor
    if config.claude is not None:
        home, away = home * config.claude.corners, away * config.claude.corners
    return home, away


# --- Corner and card lines of the market ------------------------------------------------

_COUNT_SUFFIX = {"corner": "corner", "cartellini": "cartellini"}


def count_market_lines(odds: Mapping[str, float] | None, kind: str, method: str = "proporzionale") -> list[tuple[float, float]]:
    """Margin-free Over probability of every x.5 line quoted on both sides (``kind``: corner or cartellini)."""
    lines = []
    for key, over in (odds or {}).items():
        match = re.fullmatch(rf"Over (\d+\.5) {_COUNT_SUFFIX[kind]}", key)
        under = (odds or {}).get(f"Under {match.group(1)} {_COUNT_SUFFIX[kind]}") if match else None
        try:
            valid = match is not None and under is not None and float(over) > 1.0 and float(under) > 1.0
        except (TypeError, ValueError):
            valid = False
        if valid:
            lines.append((float(match.group(1)), float(remove_margin([over, under], method)[0])))
    return sorted(lines)


def _count_sf(threshold: float, mean: float, dispersion: float) -> float:
    """P(count > threshold): negative binomial (``dispersion`` > 0) or Poisson, as in ``_count_samples``."""
    from scipy.stats import nbinom, poisson

    if dispersion > 0.0:
        return float(nbinom.sf(math.floor(threshold), dispersion, dispersion / (dispersion + mean)))
    return float(poisson.sf(math.floor(threshold), mean))


def card_points_sf(threshold: float, yellow_mean: float, count_model: CountModelParams, rule: CardRule) -> float:
    """P(card points > threshold) with the simulation's distribution: yellows, reds = ratio × yellow mean, rule weights."""
    from scipy.stats import nbinom, poisson

    dispersion = count_model.card_dispersion if count_model.active else 0.0
    yellows = np.arange(61)
    yellow_pmf = (nbinom.pmf(yellows, dispersion, dispersion / (dispersion + yellow_mean)) if dispersion > 0.0
                  else poisson.pmf(yellows, yellow_mean))
    red_mean = count_model.card_red_ratio * yellow_mean
    share = rule.double_yellow_share or 0.0
    red_points = rule.red_weight + rule.double_yellow_extra * share
    total = 0.0
    for reds in range(9):
        weight = poisson.pmf(reds, red_mean) if red_mean > 0.0 else float(reds == 0)
        if weight > 0.0:
            points = rule.yellow_weight * yellows + red_points * reds
            total += weight * float(yellow_pmf[points > threshold].sum())
    return total


def _implied_mean(lines: list[tuple[float, float]], sf: Callable[[float, float], float], start: float) -> float:
    """Mean whose distribution best prices the quoted Over probabilities (cross-entropy)."""
    from scipy.optimize import minimize_scalar

    def loss(log_mean: float) -> float:
        mean = math.exp(log_mean)
        total = 0.0
        for threshold, over in lines:
            fitted = min(max(sf(threshold, mean), 1e-9), 1.0 - 1e-9)
            total -= over * math.log(fitted) + (1.0 - over) * math.log(1.0 - fitted)
        return total

    centre = math.log(max(start, 0.5))
    return float(math.exp(minimize_scalar(loss, bounds=(centre - 2.0, centre + 2.0), method="bounded").x))


def _anchor_count(config: MatchConfig, kind: str, model_mean: float) -> dict[str, Any]:
    """Model mean (total corners or expected yellows) blended with the mean implied by the quoted lines."""
    params = config.count_anchor
    details: dict[str, Any] = {"active": False, "model_mean": model_mean, "final_mean": model_mean,
                               "market_weight": params.market_weight, "lines": []}
    lines = count_market_lines(_anchor_source(config), kind, params.devig_method) if params.active and model_mean > 0.0 else []
    if not lines:
        details["reason"] = ("Ancoraggio di corner e cartellini disattivato nella configurazione." if not params.active
                             else "Solo modello: nessuna linea Over/Under quotata su entrambi i lati.")
        return details
    if kind == "corner":
        dispersion = config.count_model.corner_dispersion if config.count_model.active else 0.0
        market = _implied_mean(lines, lambda t, m: _count_sf(t, m, dispersion), model_mean)
    else:
        market = _implied_mean(lines, lambda t, m: card_points_sf(t, m, config.count_model, config.card_rule), model_mean)
    final = market ** params.market_weight * model_mean ** (1.0 - params.market_weight)
    details.update({
        "active": True, "market_mean": market, "final_mean": final,
        "lines": [{"linea": threshold, "over_senza_margine": round(over, 4)} for threshold, over in lines],
        "reason": f"Media = mercato^{params.market_weight:g} · modello^{1 - params.market_weight:g} "
                  f"({len(lines)} linee senza margine, metodo {params.devig_method}).",
    })
    return details


def count_anchoring(config: MatchConfig) -> dict[str, dict[str, Any]]:
    """Anchoring details for the result: corner totals and expected yellows (card points scale with them)."""
    home, away = _model_corner_signals(config)
    return {"corner": _anchor_count(config, "corner", home + away),
            "cartellini": _anchor_count(config, "cartellini", _model_card_mean(config))}


# --- Division of the cards between the teams (fase T) -------------------------------------------------

CARD_SPLIT_MAX_YELLOWS = 16
CARD_SPLIT_MAX_REDS = 3


def split_log_pmf(total, p, balance: float = 0.0, concentration: float = 0.0, max_total: int = CARD_SPLIT_MAX_YELLOWS):
    """log P(gialli casa = k | totale) per k = 0..max_total (matrice N × (max_total+1), -inf oltre il totale).

    Binomiale (balance = concentration = 0), binomiale moltiplicativa di Altham (balance = log θ) o
    beta-binomiale (concentration).
    """
    from scipy.special import betaln, gammaln

    k = np.arange(max_total + 1)[None, :]
    total = np.atleast_1d(np.asarray(total, float))[:, None]
    p = np.clip(np.atleast_1d(np.asarray(p, float)), 1e-9, 1 - 1e-9)[:, None]
    rest = np.maximum(total - k, 0)
    combinations = gammaln(total + 1) - gammaln(k + 1) - gammaln(rest + 1)
    if concentration > 0:
        alpha, beta = concentration * p, concentration * (1 - p)
        terms = combinations + betaln(k + alpha, rest + beta) - betaln(alpha, beta)
    else:
        terms = combinations + k * np.log(p) + rest * np.log(1 - p) + balance * k * rest
    terms = np.where(k <= total, terms, -np.inf)
    return terms - np.logaddexp.reduce(terms, axis=1, keepdims=True)


def card_points_joint(yellow_mean, p, count_model: CountModelParams, rule: CardRule, *, balance: float = 0.0,
                      concentration: float = 0.0) -> np.ndarray:
    """P[n, punti casa, punti ospite]: gialli totali NB (o Poisson), divisi con p, rossi Poisson divisi con p."""
    from scipy.stats import nbinom, poisson

    yellow_mean = np.atleast_1d(np.asarray(yellow_mean, float))
    p = np.broadcast_to(np.asarray(p, float), yellow_mean.shape)
    size = CARD_SPLIT_MAX_YELLOWS + 1
    totals = np.arange(size)
    dispersion = count_model.card_dispersion if count_model.active else 0.0
    if dispersion > 0:
        total_pmf = nbinom.pmf(totals[None, :], dispersion, dispersion / (dispersion + yellow_mean[:, None]))
    else:
        total_pmf = poisson.pmf(totals[None, :], yellow_mean[:, None])
    joint = np.zeros((len(yellow_mean), size, size))
    for total in totals:
        home = np.arange(total + 1)
        split = np.exp(split_log_pmf(np.full(len(yellow_mean), total), p, balance, concentration))[:, :total + 1]
        joint[:, home, total - home] += total_pmf[:, [total]] * split
    red_mean = count_model.card_red_ratio * yellow_mean
    reds = np.arange(CARD_SPLIT_MAX_REDS + 1)[None, :]
    red_home, red_away = poisson.pmf(reds, (red_mean * p)[:, None]), poisson.pmf(reds, (red_mean * (1 - p))[:, None])
    width = size + rule.red_weight * CARD_SPLIT_MAX_REDS
    points = np.zeros((len(yellow_mean), width, width))
    for home_reds in range(CARD_SPLIT_MAX_REDS + 1):
        for away_reds in range(CARD_SPLIT_MAX_REDS + 1):
            x, y = rule.red_weight * home_reds, rule.red_weight * away_reds
            points[:, x:x + size, y:y + size] += (red_home[:, home_reds] * red_away[:, away_reds])[:, None, None] * joint
    return points / points.sum(axis=(1, 2), keepdims=True)


def card_split_markets(points: np.ndarray, lines: Sequence[float] = (0.5, 1.5, 2.5, 3.5, 4.5)) -> dict[str, np.ndarray]:
    """1X2 cartellini e Over per squadra dalla distribuzione congiunta dei punti (chiavi evento del motore)."""
    index = np.arange(points.shape[1])
    one = (points * (index[:, None] > index[None, :])).sum(axis=(1, 2))
    draw = (points * (index[:, None] == index[None, :])).sum(axis=(1, 2))
    result = {"1 cartellini": one, "X cartellini": draw, "2 cartellini": 1.0 - one - draw}
    home, away = points.sum(axis=2), points.sum(axis=1)
    for line in lines:
        result[f"Casa Over {line:g} cartellini"] = home[:, int(line) + 1:].sum(axis=1)
        result[f"Ospite Over {line:g} cartellini"] = away[:, int(line) + 1:].sum(axis=1)
    return result


def card_split_logit(config: MatchConfig, underdog: float) -> tuple[float, dict[str, Any]]:
    """Logit della quota di casa del modello e componenti usate (fase T)."""
    params = config.card_split
    home, away = max(config.home.cards_for, 0.05), max(config.away.cards_for, 0.05)
    rate = math.log(home / away)
    if not params.active:
        return rate, {"modello": "divisione originale: cartellini pro casa / totale"}
    value = params.home + params.rate_weight * rate
    used = {"ritmo": params.rate_weight}
    provoked = (config.home.cards_provoked, config.away.cards_provoked)
    if params.provoked_weight and all(value is not None and value > 0 for value in provoked):
        value += params.provoked_weight * math.log(provoked[1] / provoked[0])
        used["provocati"] = params.provoked_weight
    elif params.provoked_weight:
        used["provocati"] = "non disponibili: termine escluso"
    if params.underdog_weight:
        value += params.underdog_weight * underdog
        used["sfavorita"] = params.underdog_weight
    if params.referee_weight and config.referee_yellow_avg > 0:
        value += params.referee_weight * math.log(config.referee_yellow_avg / 4.5) * rate
        used["arbitro"] = params.referee_weight
    if params.balance:
        used["bilanciamento"] = params.balance
    return value, used


def _card_split_targets(config: MatchConfig) -> dict[str, float]:
    """Probabilità senza margine dalle quote 1X2 cartellini e Over/Under cartellini per squadra (se quotate entrambe)."""
    odds = _anchor_source(config) or {}
    method = config.count_anchor.devig_method
    targets: dict[str, float] = {}

    def valid(key: str) -> bool:
        try:
            return float(odds[key]) > 1.0
        except (KeyError, TypeError, ValueError):
            return False

    signs = ("1 cartellini", "X cartellini", "2 cartellini")
    if all(valid(key) for key in signs):
        targets.update(zip(signs, (float(value) for value in remove_margin([odds[key] for key in signs], method))))
    for key in list(odds):
        found = re.fullmatch(r"(Casa|Ospite) Over (\d+\.5) cartellini", key)
        under = f"{found.group(1)} Under {found.group(2)} cartellini" if found else None
        if found and valid(key) and valid(under):
            targets[key] = float(remove_margin([odds[key], odds[under]], method)[0])
    return targets


def card_split_share(config: MatchConfig, underdog: float, yellow_mean: float) -> tuple[float, dict[str, Any]]:
    """Quota dei cartellini della squadra di casa: modello, eventualmente ancorato al mercato (fase T)."""
    from scipy.optimize import minimize_scalar

    params = config.card_split
    logit, used = card_split_logit(config, underdog)
    p_model = 1.0 / (1.0 + math.exp(-logit))
    details: dict[str, Any] = {"active": params.active, "p_model": p_model, "p": p_model, "components": used,
                               "anchored": False}
    if not params.active:
        details["reason"] = "Divisione originale (fase T disattivata in configurazione)."
        return p_model, details
    targets = _card_split_targets(config)
    if not targets:
        details["reason"] = "Non ancorato: nessuna quota 1X2 cartellini o Over/Under cartellini per squadra."
        return p_model, details

    def loss(shift: float) -> float:
        points = card_points_joint(yellow_mean, 1.0 / (1.0 + math.exp(-(logit + shift))), config.count_model,
                                   config.card_rule, balance=params.balance, concentration=params.concentration)
        model = {key: float(value[0]) for key, value in card_split_markets(points).items()}
        total = 0.0
        if "1 cartellini" in targets:
            total -= sum(targets[key] * math.log(max(model[key], 1e-9)) for key in ("1 cartellini", "X cartellini", "2 cartellini"))
        for key, over in targets.items():
            if key.startswith(("Casa", "Ospite")):
                fitted = min(max(model.get(key, 0.5), 1e-9), 1 - 1e-9)
                total -= over * math.log(fitted) + (1 - over) * math.log(1 - fitted)
        return total

    shift = float(minimize_scalar(loss, bounds=(-3.0, 3.0), method="bounded").x)
    p = 1.0 / (1.0 + math.exp(-(logit + params.market_weight * shift)))
    details.update({"anchored": True, "p": p, "market_shift": shift, "targets": targets,
                    "reason": f"Quota di casa = modello spostato verso il mercato con peso {params.market_weight:g} "
                              f"(dichiarato, non tarato) su {len(targets)} probabilità senza margine."})
    return p, details


COUNT_DISAGREEMENT_PP = 10.0
COUNT_DISAGREEMENT_TEXT = "disaccordo forte col bookmaker: probabile errore del modello, verifica"
_COUNT_LINE = re.compile(r"^(?:(Casa|Ospite) )?(Over|Under) (\d+\.5) (corner|cartellini)$")


def count_market_gaps(final: Mapping[str, float], odds: Mapping[str, float] | None,
                      method: str = "proporzionale") -> dict[str, dict[str, float]]:
    """Corner e cartellini: probabilità del modello contro il mercato senza margine (punti percentuali).

    Gruppi completi soltanto: 1X2 corner/cartellini (tre esiti) e coppie Over/Under della stessa linea.
    """
    odds = {key: float(value) for key, value in (odds or {}).items() if value and float(value) > 1.0}
    groups: list[tuple[str, ...]] = [tuple(f"{sign} {kind}" for sign in ("1", "X", "2")) for kind in ("corner", "cartellini")]
    for key in odds:
        found = _COUNT_LINE.match(key)
        if found and found.group(2) == "Over":
            groups.append((key, key.replace(" Over ", " Under ") if found.group(1) else key.replace("Over ", "Under ", 1)))
    gaps = {}
    for group in groups:
        if not all(key in odds and key in final for key in group):
            continue
        market = remove_margin([odds[key] for key in group], method)
        for key, probability in zip(group, market):
            model = float(final[key])
            gaps[key] = {"model": model, "market": round(float(probability) * 100.0, 2), "gap": round(model - float(probability) * 100.0, 2)}
    return gaps


def flag_count_disagreements(financial: dict[str, Any], final: Mapping[str, float], odds: Mapping[str, float] | None,
                             threshold: float = COUNT_DISAGREEMENT_PP) -> dict[str, dict[str, float]]:
    """Righe di corner e cartellini con |modello − mercato| > ``threshold``: avviso e niente semaforo verde."""
    strong = {key: value for key, value in count_market_gaps(final, odds).items() if abs(value["gap"]) > threshold}
    for row in financial["markets"]:
        if row["market"] in strong:
            row.update(count_disagreement=strong[row["market"]], suspicious_value=True, is_value=False,
                       model_market_gap_pct=abs(strong[row["market"]]["gap"]))
    financial["value_bets"] = [row for row in financial["value_bets"] if row["market"] not in strong]
    return strong


def _split_samples(rng: np.random.Generator, totals: np.ndarray, p: float, params: CardSplitParams) -> np.ndarray:
    """Gialli della squadra di casa per ogni simulazione, dato il totale."""
    if not params.active or (not params.balance and not params.concentration):
        return rng.binomial(totals, p)
    home = np.zeros_like(totals)
    uniform = rng.random(len(totals))
    for total in np.unique(totals):
        mask = totals == total
        cdf = np.cumsum(np.exp(split_log_pmf([total], [p], params.balance, params.concentration,
                                             max_total=int(total)))[0][:int(total) + 1])
        home[mask] = np.minimum(np.searchsorted(cdf, uniform[mask] * cdf[-1]), total)
    return home


def card_points_mean(config: MatchConfig) -> float:
    """Expected card-market points: yellows plus reds (``card_red_ratio`` per expected yellow) with the rule weights."""
    rule = config.card_rule
    share = rule.double_yellow_share or 0.0
    red_points = rule.red_weight + rule.double_yellow_extra * share
    return card_total_mean(config) * (rule.yellow_weight + config.count_model.card_red_ratio * red_points)


def card_balance_log_factor(params: CountModelParams, home_elo, away_elo):
    """Log-correction of the yellow mean for match balance (balanced games are booked more)."""
    return params.card_balance_intercept + params.card_balance_weight * np.abs(np.asarray(home_elo, float) - np.asarray(away_elo, float)) / 100.0


def _model_card_mean(config: MatchConfig) -> float:
    """Model yellows (with the similar-opponents factor), before market and Claude.

    The yellow average is the level factor and the fouls average is the tempo
    factor.
    """
    team_cards = config.home.cards_for + config.away.cards_for
    params = config.count_model
    tactical = _tactical(config, "cards")
    factor = tactical.cards if tactical is not None else 1.0
    if params.active:
        if team_cards <= 0.0 or config.referee_yellow_avg <= 0.0 or config.referee_fouls_avg <= 0.0:
            return 0.0
        return factor * math.exp(
            params.card_intercept + params.card_team_weight * math.log(team_cards)
            + params.card_referee_yellow_weight * math.log(config.referee_yellow_avg)
            + params.card_referee_fouls_weight * math.log(config.referee_fouls_avg)
            + card_balance_log_factor(params, config.home.elo, config.away.elo)
        )
    foul_factor = max(0.0, config.referee_fouls_avg / 24.0)
    referee_severity = max(0.0, config.referee_yellow_avg / 4.5)
    return factor * max(0.0, team_cards * referee_severity * foul_factor)


def card_total_mean(config: MatchConfig) -> float:
    """Expected yellow cards: model, anchored to the card lines when quoted, then Claude's factor."""
    anchoring = _anchor_count(config, "cartellini", _model_card_mean(config))
    return anchoring["final_mean"] * (config.claude.cards if config.claude is not None else 1.0)


def _count_samples(rng: np.random.Generator, mean: float, dispersion: float, size: int, sigma: float = 0.0) -> np.ndarray:
    """Poisson counts, or negative binomial (gamma-Poisson) when ``dispersion`` > 0.

    ``sigma`` > 0 (fase P, punto 3): media di ogni simulazione × exp(σZ − σ²/2)."""
    if sigma > 0.0 and mean > 0.0:
        mean = mean * np.exp(sigma * rng.standard_normal(size) - sigma ** 2 / 2)
        if dispersion > 0.0:
            return rng.poisson(rng.gamma(dispersion, mean / dispersion))
        return rng.poisson(mean)
    if dispersion > 0.0 and mean > 0.0:
        return rng.poisson(rng.gamma(dispersion, mean / dispersion, size))
    return rng.poisson(mean, size)


def _first_half_targets(config: MatchConfig, lambda_: float, mu: float) -> tuple[float, float]:
    """Quota dei gol nel primo tempo per squadra: tarata (``primo_tempo``) × fattore tattico."""
    home_share, away_share = first_half_shares(lambda_, mu, config.half_time)
    tactical = _tactical(config, "first_half")
    if tactical is not None:
        home_share = float(np.clip(home_share * tactical.first_half, 0.05, 0.95))
        away_share = float(np.clip(away_share * tactical.first_half, 0.05, 0.95))
    return float(home_share), float(away_share)


def event_engine_sample(config: MatchConfig, lambda_: float, mu: float, scores: tuple[np.ndarray, np.ndarray],
                        corners: tuple[float, float], yellow_mean: float, home_card_share: float) -> tuple[dict, dict]:
    """Fase AK: eventi della partita dal motore a eventi sui punteggi Dixon-Coles ``scores``, con le medie attuali come
    vincolo (corner per squadra, gialli divisi con ``home_card_share``, rossi = ``card_red_ratio`` × gialli, varianze della
    binomiale negativa, quota del primo tempo) e arresto adattivo. Restituisce (campione, dettagli per il risultato)."""
    settings, count = config.event_engine, config.count_model
    params = _event_params(config.league)
    shares = _first_half_targets(config, lambda_, mu)
    inputs = config.event_inputs or {}

    def team(side: str, goals: float, share: float) -> _event_engine.TeamInput:
        extra = inputs.get(side) or {}
        return _event_engine.TeamInput(goals, profile=extra.get("profile") or {}, first_share=share, module=extra.get("module"))

    sigma = config.v2.uncertainty_active
    rule = config.card_rule
    targets = _event_engine.Targets(
        corners=(float(corners[0]), float(corners[1])),
        yellows=(yellow_mean * home_card_share, yellow_mean * (1.0 - home_card_share)),
        reds=count.card_red_ratio * yellow_mean,
        double_share=rule.double_yellow_share if rule.double_yellow_extra else None,
        corner_variance=_event_engine.count_variance(sum(corners), count.corner_dispersion if count.active else 0.0,
                                                     config.v2.sigma_corners if sigma else 0.0),
        yellow_variance=_event_engine.count_variance(yellow_mean, count.card_dispersion if count.active else 0.0,
                                                     config.v2.sigma_cards if sigma else 0.0),
        first_share=shares,
    )
    options = {"step_minutes": settings.step_minutes, "lanes": settings.lanes}
    home, away, mix, rows = _event_engine.coherence(
        np.random.default_rng([config.seed, 4]), team("home", lambda_, shares[0]), team("away", mu, shares[1]), params, targets,
        scores=scores, pilot=settings.pilot, passes=settings.passes, **options)
    sample = _event_engine.simulate_adaptive(
        np.random.default_rng([config.seed, 5]), home, away, params, maximum=len(scores[0]), batch=settings.batch,
        minimum=settings.minimum, tolerance_pp=settings.tolerance_pp, scores=scores, rule=rule, mix=mix, **options)
    details = {
        "active": True, "parametri": params.source, "nota": params.note, "simulazioni": sample["adaptive"]["simulazioni"],
        "arresto": sample["adaptive"], "coerenza": rows, "dispersione": mix,
        "scale": {side: {key: round(float(getattr(value, key)), 4) for key in (
            "corner_scale", "card_scale", "red_scale", "second_yellow_scale", "first_share")}
            for side, value in (("home", home), ("away", away))},
        "ledger": sample["ledger"], "warnings": sample["warnings"],
        "medie": {key: round(value, 4) for key, value in _event_engine.summary(sample).items()},
        "falli": "media del campionato (StatsBomb) senza effetto dell'arbitro: i gialli seguono già la media attuale",
    }
    return sample, details


def _sample_scores(config: MatchConfig, lambda_: float, mu: float) -> tuple[np.ndarray, ...]:
    """Sample full-time scores from Dixon-Coles and split them across halves.

    The half split reconciles every partial-time outcome exactly with the
    final score.
    """
    rng = np.random.default_rng(config.seed)
    max_goals = max(
        12,
        int(max(poisson.ppf(1.0 - 1e-12, lambda_), poisson.ppf(1.0 - 1e-12, mu))),
    )
    sigma = config.v2.sigma_goals if config.v2.uncertainty_active else 0.0
    if sigma > 0.0:
        # Fase P, punto 3: in ogni simulazione λ e μ moltiplicati per exp(σZ − σ²/2) (stessa media); le simulazioni
        # sono divise tra i nodi di Gauss-Hermite in proporzione ai pesi.
        nodes, weights = np.polynomial.hermite_e.hermegauss(5)
        weights = np.outer(weights, weights).ravel() / np.outer(weights, weights).sum()
        sizes = rng.multinomial(config.simulations, weights)
        homes, aways = [], []
        for (i, j), size in zip(np.ndindex(5, 5), sizes):
            matrix = dixon_coles_matrix(lambda_ * math.exp(sigma * nodes[i] - sigma ** 2 / 2),
                                        mu * math.exp(sigma * nodes[j] - sigma ** 2 / 2), config.dixon_coles_rho,
                                        max_goals=max_goals + 4)
            drawn = rng.choice(matrix.size, size=size, p=(matrix / matrix.sum()).ravel())
            home, away = np.unravel_index(drawn, matrix.shape)
            homes.append(home)
            aways.append(away)
        order = rng.permutation(config.simulations)
        goals_home, goals_away = np.concatenate(homes)[order], np.concatenate(aways)[order]
    else:
        score_probabilities = dixon_coles_matrix(
            lambda_, mu, config.dixon_coles_rho, max_goals=max_goals
        )
        score_samples = rng.choice(
            score_probabilities.size,
            size=config.simulations,
            p=score_probabilities.ravel(),
        )
        goals_home, goals_away = np.unravel_index(score_samples, score_probabilities.shape)
    home_share, away_share = _first_half_targets(config, lambda_, mu)
    return (
        goals_home, goals_away,
        rng.binomial(goals_home, float(home_share)), rng.binomial(goals_away, float(away_share)),
    )


def _events_for_scores(
    config: MatchConfig, scores: tuple[np.ndarray, ...], counts: tuple[np.ndarray, ...]
) -> dict[str, np.ndarray]:
    goals_home, goals_away, first_home, first_away = scores
    events = _event_catalog(
        goals_home, goals_away, first_home, first_away,
        goals_home - first_home, goals_away - first_away,
        *counts[:4],
        _team_multigol_ranges(getattr(config, "odds", None)),
        half_counts=tuple(counts[4:8]) if len(counts) >= 8 else None,
    )
    for market in getattr(config, "odds", {}) or {}:
        if " + " not in market or market in events:
            continue  # le combo del catalogo (es. «1 + Over 1.5») ci sono già
        legs = market.split(" + ")
        if len(legs) != 2 or any(leg not in events for leg in legs):
            raise ValueError(f"Combo {market}: una o più gambe non sono supportate dal motore.")
        events[market] = events[legs[0]] & events[legs[1]]
    _validate_event_catalog(events, config.simulations)
    return events


def _score_percentages(goals_home: np.ndarray, goals_away: np.ndarray) -> dict[str, float]:
    """Exact-score distribution of one sample, «casa-ospite» -> percentage, most likely first."""
    pairs, counts = np.unique(np.column_stack((goals_home, goals_away)), axis=0, return_counts=True)
    order = np.argsort(-counts, kind="stable")
    total = float(len(goals_home))
    return {f"{int(pairs[index][0])}-{int(pairs[index][1])}": round(float(counts[index]) / total * 100.0, 4) for index in order}


def _event_percentages(events: Mapping[str, np.ndarray]) -> dict[str, float]:
    return {key: round(float(mask.mean()) * 100.0, 2) for key, mask in events.items()}


def simulate_match(config: MatchConfig) -> dict[str, Any]:
    """Run one reproducible sample and derive every score market from it.

    ``goals_home`` and ``goals_away`` are created once per simulation.  No
    market below samples goals again, so all score-dependent probabilities are
    projections of the same exact-score observations.
    """
    if config.event_engine.active and config.timeline.active:
        raise ValueError("Motore a blocchi (fase O) e motore a eventi (fase AK) non possono essere accesi insieme.")
    lambda_, mu, details = final_goal_rates(config)
    ledger, anchoring = details["ledger"], details["anchoring"]
    goals_home, goals_away, first_home, first_away = _sample_scores(config, lambda_, mu)
    second_home = goals_home - first_home
    second_away = goals_away - first_away

    # Corners and cards use their own random stream, so the model-only and
    # market-only score samples below share exactly the same count samples.
    rng = np.random.default_rng([config.seed, 1])
    # Estimate each team's corners from its average won and its opponent's
    # average conceded, then sample and allocate one match total.
    home_corner_signal, away_corner_signal = corner_signals(config)
    lambda_corners = home_corner_signal + away_corner_signal
    corners = _count_samples(rng, lambda_corners, config.count_model.corner_dispersion if config.count_model.active else 0.0,
                             config.simulations, config.v2.sigma_corners if config.v2.uncertainty_active else 0.0)
    home_corner_share = (
        home_corner_signal / lambda_corners if lambda_corners > 0.0 else 0.5
    )
    home_corners = rng.binomial(corners, home_corner_share)
    away_corners = corners - home_corners

    yellow_mean = card_total_mean(config)
    yellows = _count_samples(rng, yellow_mean, config.count_model.card_dispersion if config.count_model.active else 0.0,
                             config.simulations, config.v2.sigma_cards if config.v2.uncertainty_active else 0.0)
    card_signal_total = max(0.0, config.home.cards_for + config.away.cards_for)
    home_card_share = (
        config.home.cards_for / card_signal_total if card_signal_total > 0.0 else 0.5
    )
    card_split_details = {"active": False, "p": home_card_share}
    if config.card_split.active:
        # Fase T: quota di casa dal modello della divisione (sfavorita = P(2) − P(1) dei gol simulati).
        underdog = float(np.mean(goals_home < goals_away) - np.mean(goals_home > goals_away))
        home_card_share, card_split_details = card_split_share(config, underdog, yellow_mean)
    timeline_details = {"active": False}
    timeline_reds = None
    if config.timeline.active:
        # Fase O: percorso a blocchi di 5 minuti; medie invariate (gol λ, μ; corner e cartellini delle fasi M/N/T).
        first_share_home, first_share_away = first_half_shares(lambda_, mu, config.half_time)
        path = _timeline.sample(
            np.random.default_rng([config.seed, 2]), config.simulations, lambda_=lambda_, mu=mu,
            first_share_home=first_share_home, first_share_away=first_share_away,
            corner_home=home_corner_signal, corner_away=away_corner_signal,
            corner_dispersion=config.count_model.corner_dispersion if config.count_model.active else 0.0,
            yellow_mean=yellow_mean, card_dispersion=config.count_model.card_dispersion if config.count_model.active else 0.0,
            red_mean=config.count_model.card_red_ratio * yellow_mean, card_share=home_card_share,
            params=config.timeline, scores=(goals_home, goals_away))
        goals_home, goals_away, first_home, first_away = path["goals_home"], path["goals_away"], path["first_home"], path["first_away"]
        second_home, second_away = goals_home - first_home, goals_away - first_away
        home_corners, away_corners, yellows = path["corners_home"], path["corners_away"], path["yellows"]
        if path["reds_home"] is not None:
            timeline_reds = (path["reds_home"], path["reds_away"])
        timeline_details = {"active": True, "components": list(config.timeline.components)}
    home_yellows = _split_samples(rng, yellows, home_card_share, config.card_split)
    away_yellows = yellows - home_yellows
    # Reds after the yellows, so the yellow samples do not depend on the rule.
    if timeline_reds is not None:
        home_reds, away_reds = timeline_reds
    else:
        reds = rng.poisson(config.count_model.card_red_ratio * yellow_mean, config.simulations)
        home_reds = rng.binomial(reds, home_card_share)
        away_reds = reds - home_reds
    rule = config.card_rule
    if rule.double_yellow_extra:
        home_double = rng.binomial(home_reds, rule.double_yellow_share)
        away_double = rng.binomial(away_reds, rule.double_yellow_share)
    else:
        home_double = away_double = 0
    home_cards = card_points(home_yellows, home_reds, rule, home_double)
    away_cards = card_points(away_yellows, away_reds, rule, away_double)
    cards = home_cards + away_cards
    # Fase Q (6b): corner e cartellini del primo tempo. Con il motore a blocchi acceso dal suo percorso;
    # altrimenti con la quota del primo tempo stimata su StatsBomb (non verificabile: niente dati per tempo).
    half_rng = np.random.default_rng([config.seed, 3])
    corner_share, card_share = config.timeline.first_half_shares() if hasattr(config.timeline, "first_half_shares") else (0.49, 0.39)
    if timeline_details.get("active"):
        corners_first_home, corners_first_away = path["corners_first_home"], path["corners_first_away"]
        card_share = np.clip(path["card_first_share"], 0.0, 1.0)
    else:
        corners_first_home = half_rng.binomial(home_corners, corner_share)
        corners_first_away = half_rng.binomial(away_corners, corner_share)
    cards_first_home = card_points(half_rng.binomial(home_yellows, card_share), half_rng.binomial(home_reds, card_share), rule)
    cards_first_away = card_points(half_rng.binomial(away_yellows, card_share), half_rng.binomial(away_reds, card_share), rule)
    counts = (home_corners, away_corners, home_cards, away_cards,
              corners_first_home, corners_first_away, cards_first_home, cards_first_away)
    event_details = {"active": False}
    if config.event_engine.active:
        # Fase AK: stessi punteggi Dixon-Coles; primo tempo, corner e cartellini dal motore a eventi (medie attuali come
        # vincolo). Con l'arresto adattivo il campione si accorcia ai primi n punteggi, per TUTTI i mercati.
        sample, event_details = event_engine_sample(config, lambda_, mu, (goals_home, goals_away),
                                                    (home_corner_signal, away_corner_signal), yellow_mean, home_card_share)
        size = event_details["simulazioni"]
        if size < config.simulations:
            config = replace(config, simulations=size)
        goals_home, goals_away = goals_home[:size], goals_away[:size]
        first_home, first_away = sample["first_home"], sample["first_away"]
        second_home, second_away = goals_home - first_home, goals_away - first_away
        home_corners, away_corners = sample["corners_home"], sample["corners_away"]
        corners = home_corners + away_corners
        home_cards = card_points(sample["yellows_home"], sample["reds_home"], rule, sample["double_yellows_home"])
        away_cards = card_points(sample["yellows_away"], sample["reds_away"], rule, sample["double_yellows_away"])
        cards = home_cards + away_cards
        counts = (home_corners, away_corners, home_cards, away_cards,
                  sample["corners_first_home"], sample["corners_first_away"],
                  card_points(sample["yellows_first_home"], sample["reds_first_home"], rule),
                  card_points(sample["yellows_first_away"], sample["reds_first_away"], rule))

    events = _events_for_scores(config, (goals_home, goals_away, first_home, first_away), counts)
    finale, recalibrated = apply_recalibration(_event_percentages(events), config.v2)
    components = {"finale": finale, "modello": None, "mercato": None}
    exact_scores = {"finale": _score_percentages(goals_home, goals_away), "modello": None, "mercato": None}
    if anchoring["active"]:
        for name, rates in (
            ("modello", (anchoring["model_lambda"], anchoring["model_mu"])),
            ("mercato", (anchoring["market_lambda"], anchoring["market_mu"])),
        ):
            component_scores = _sample_scores(config, *rates)
            components[name] = _event_percentages(_events_for_scores(config, component_scores, counts))
            exact_scores[name] = _score_percentages(*component_scores[:2])
    else:
        components["modello"] = components["finale"]
        exact_scores["modello"] = exact_scores["finale"]
    markets = {
        "1x2": {key: _market(events[key]) for key in ("1", "X", "2")},
        "double_chance": {key: _market(events[key]) for key in ("1X", "X2", "12")},
        "first_half_1x2": {key: _market(events[f"{key} 1T"]) for key in ("1", "X", "2")},
        "first_half_double_chance": {key: _market(events[f"{key} 1T"]) for key in ("1X", "X2", "12")},
        "second_half_1x2": {key: _market(events[f"{key} 2T"]) for key in ("1", "X", "2")},
        "second_half_double_chance": {key: _market(events[f"{key} 2T"]) for key in ("1X", "X2", "12")},
        "draw_no_bet": {"Casa": _market(events["Casa DNB"]), "Ospite": _market(events["Ospite DNB"])},
        "over_under": {
            **{f"Over_{threshold}": _market(events[f"Over {threshold:g} gol"]) for threshold in (0.5, 1.5, 2.5, 3.5, 4.5)},
            **{f"Under_{threshold}": _market(events[f"Under {threshold:g} gol"]) for threshold in (0.5, 1.5, 2.5, 3.5, 4.5)},
        },
        "first_half_over_under": {
            **{f"Over_{threshold}": _market(events[f"Over {threshold:g} gol 1T"]) for threshold in (0.5, 1.5)},
            **{f"Under_{threshold}": _market(events[f"Under {threshold:g} gol 1T"]) for threshold in (0.5, 1.5)},
        },
        "team_goals": {key: _market(events[key]) for key in events if key.startswith(("Casa ", "Ospite ")) and "gol" in key},
        "multigol": {
            key.replace("Multigol ", ""): _market(events[f"Multigol {key}"])
            for key in ("1-2", "1-3", "2-4", "2-5")
        },
        "multigol_complete": {key.replace("Multigol ", ""): _market(value) for key, value in events.items() if key.startswith("Multigol ") and key.count(" ") == 1},
        "team_multigol": {
            key.replace("Multigol ", ""): _market(value)
            for key, value in events.items()
            if key.startswith("Multigol ") and key.count(" ") == 2
        },
        "goal_no_goal": {"Goal": _market(events["Goal"]), "No_Goal": _market(events["No Goal"])},
        "first_half_goal_no_goal": {"Goal": _market(events["Goal 1T"]), "No_Goal": _market(events["No Goal 1T"])},
        "goal_sums": {str(value): _market(events[f"Somma gol {value}"]) for value in range(5)} | {"5+": _market(events["Somma gol 5+"])},
        "team_scoring": {key: _market(events[key]) for key in ("Casa segna", "Casa non segna", "Ospite segna", "Ospite non segna")},
        "both_teams": {key: _market(events[key]) for key in ("BTTS entrambi i tempi", "BTTS almeno un tempo")},
        "combos": {key: _market(value) for key, value in events.items() if " + " in key},
        "corners": {
            "mean": round(float(corners.mean()), 3),
            **{f"Over_{threshold:g}": _market(events[f"Over {threshold:g} corner"]) for threshold in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)},
            **{f"Under_{threshold:g}": _market(events[f"Under {threshold:g} corner"]) for threshold in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)},
        },
        "cards": {
            "mean": round(float(cards.mean()), 3),
            **{f"Over_{threshold:g}": _market(events[f"Over {threshold:g} cartellini"]) for threshold in (2.5, 3.5, 4.5, 5.5, 6.5)},
            **{f"Under_{threshold:g}": _market(events[f"Under {threshold:g} cartellini"]) for threshold in (2.5, 3.5, 4.5, 5.5, 6.5)},
        },
        "corner_1x2": {key: _market(events[f"{key} corner"]) for key in ("1", "X", "2")},
        "team_corners": {key.replace(" ", "_"): _market(value) for key, value in events.items() if key.startswith(("Casa ", "Ospite ")) and "corner" in key},
        "card_1x2": {key: _market(events[f"{key} cartellini"]) for key in ("1", "X", "2")},
        "team_cards": {key.replace(" ", "_"): _market(value) for key, value in events.items() if key.startswith(("Casa ", "Ospite ")) and "cartellini" in key},
    }
    markets["catalog"] = _catalog_markets(events)
    outcomes = {"1": goals_home > goals_away, "X": goals_home == goals_away, "2": goals_home < goals_away}
    conditional_scenarios = _conditional_scenarios(events, outcomes)
    score_pairs, counts = np.unique(np.column_stack((goals_home, goals_away)), axis=0, return_counts=True)
    overall_mode_index = int(np.argmax(counts))
    overall_mode = score_pairs[overall_mode_index]
    favorite_sign = max(outcomes, key=lambda sign: int(outcomes[sign].sum()))
    favorite_mask = outcomes[favorite_sign]
    favorite_pairs, favorite_counts = np.unique(
        np.column_stack((goals_home[favorite_mask], goals_away[favorite_mask])),
        axis=0,
        return_counts=True,
    )
    favorite_mode_index = int(np.argmax(favorite_counts))
    mode = favorite_pairs[favorite_mode_index]
    fixed_score_mask = (goals_home == mode[0]) & (goals_away == mode[1])
    fixed_score_scenario = _conditional_scenarios(events, {"score": fixed_score_mask})["score"]
    result = {
        "input": {"home": config.home.__dict__, "away": config.away.__dict__, "referee_yellow_avg": config.referee_yellow_avg, "referee_fouls_avg": config.referee_fouls_avg},
        "model": {"lambda": round(lambda_, 6), "mu": round(mu, 6), "lambda_modello": round(anchoring["model_lambda"], 6), "mu_modello": round(anchoring["model_mu"], 6), "goal_model": config.goal_model, "card_rule": config.card_rule.describe(), "card_yellow_mean": round(card_total_mean(config), 4), "card_red_mean": round(card_total_mean(config) * config.count_model.card_red_ratio, 4), "first_half_shares": dict(zip(("home", "away"), (round(float(share), 4) for share in first_half_shares(lambda_, mu, config.half_time)))), "dixon_coles_rho": config.dixon_coles_rho, "simulation_count": config.simulations, "seed": config.seed, "formula_ledger": ledger},
        "markets": markets,
        "conditional_scenarios": conditional_scenarios,
        "fixed_score_scenario": fixed_score_scenario,
        "summary": {
            "favorite_sign": favorite_sign,
            "favorite_sign_probability_pct": round(
                _probability(favorite_mask) * 100.0, 2
            ),
            "modal_score": {
                "home": int(mode[0]),
                "away": int(mode[1]),
                "share_pct": round(float(favorite_counts[favorite_mode_index] / config.simulations * 100), 2),
                "conditional_share_pct": round(
                    float(favorite_counts[favorite_mode_index] / favorite_mask.sum() * 100), 2
                ),
            },
            "most_likely_exact_score": {
                "home": int(overall_mode[0]),
                "away": int(overall_mode[1]),
                "share_pct": round(float(counts[overall_mode_index] / config.simulations * 100), 2),
            },
            "confidence_intervals_95": {key: _confidence(mask) for key, mask in outcomes.items()},
        },
    }
    interval_width = np.mean([
        bounds[1] - bounds[0]
        for bounds in result["summary"]["confidence_intervals_95"].values()
    ])
    result["summary"]["reliability"] = {
        "index_pct": round(float(np.clip(100.0 - interval_width, 0.0, 100.0)), 2),
        "method": "100 - media ampiezza degli intervalli Wilson 95% sugli esiti 1X2",
        "warning": "La stabilità Monte Carlo non misura la qualità degli input né l'incertezza strutturale del modello.",
        "sampling_stability_pct": round(float(np.clip(100.0 - interval_width, 0.0, 100.0)), 2),
        "model_uncertainty": "Non stimata: richiede una distribuzione sui parametri e validazione out-of-sample.",
    }
    result["market_anchoring"] = anchoring
    result["count_anchoring"] = count_anchoring(config)
    result["card_split"] = card_split_details
    result["timeline"] = timeline_details
    result["event_engine"] = event_details
    result["recalibrated"] = recalibrated  # fase P, punto 4: mercati con la mappa finale accesa
    result["components"] = components
    result["exact_scores"] = exact_scores
    result["financial"] = financial_analysis(
        events, getattr(config, "odds", None), components,
        config.market_anchor.suspicious_gap_pct, config.market_anchor.no_value_markets,
        recalibrated={key: components["finale"][key] for key in recalibrated},
        threshold=value_threshold if config.v2.thresholds_active else None,
    )
    result["count_disagreements"] = flag_count_disagreements(result["financial"], components["finale"],
                                                             getattr(config, "odds", None))
    result["smart_combo"] = smart_combo(
        events, getattr(config, "odds", None), config.market_anchor.no_value_markets
    )
    result["joint_pairs"] = joint_pair_probabilities(events)
    if config.keep_samples:
        # Fase Z: un bit per simulazione e per evento (stessa estrazione di tutte le probabilità qui sopra).
        result["event_samples"] = {key: np.packbits(np.asarray(values, dtype=bool)) for key, values in events.items()
                                   if getattr(values, "dtype", None) == bool}
        result["sample_size"] = int(config.simulations)
        if event_details.get("active"):
            # Fase AK: percorsi grezzi del motore a eventi (tiri, corner per origine, falli, cartellini, minuti), stesso campione.
            result["event_engine_sample"] = {key: value for key, value in sample.items() if isinstance(value, np.ndarray)}
    result["statistical_report"] = statistical_report(config, result)
    result["dashboard"] = {
        "goals_distribution": {
            "goals": [*(str(value) for value in range(8)), "8+"],
            "home": [
                round(float(np.mean(np.minimum(goals_home, 8) == value) * 100), 2)
                for value in range(9)
            ],
            "away": [
                round(float(np.mean(np.minimum(goals_away, 8) == value) * 100), 2)
                for value in range(9)
            ],
        },
        "exact_score_distribution": {
            "labels": [*(str(value) for value in range(8)), "8+"],
            "probabilities_pct": np.bincount(
                np.minimum(goals_home, 8) * 9 + np.minimum(goals_away, 8),
                minlength=81,
            ).reshape(9, 9).astype(float).__truediv__(config.simulations).__mul__(100).round(3).tolist(),
        },
        "strength_comparison": {
            "labels": ["Attacco", "Difesa inversa", "xG fatti", "xG subiti", "Elo normalizzato"],
            "home": [config.home.attack, 1 / config.home.defense, config.home.xg_for, config.home.xg_against, config.home.elo / 1500],
            "away": [config.away.attack, 1 / config.away.defense, config.away.xg_for, config.away.xg_against, config.away.elo / 1500],
        },
    }
    return result
