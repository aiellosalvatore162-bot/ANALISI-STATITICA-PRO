"""Motore a eventi per partita (fase AK, stadi 3-8): stato della partita, azioni a passi, tiri e gol, corner, falli e cartellini.

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

Rigori: tasso e conversione costanti (gli effetti di stato e fascia sono stimati senza rigori).

Stadi 6-8, nello stesso ciclo a passi (tutto stimato da ``tools.stima_motore``):
- corner per origine: da tiro = binomiale sui tiri parati o respinti del passo (corner per tiro parato), da cross e «altro»
  = Poisson col tasso per squadra-partita × stato e fascia dei corner non da tiro × uomini in campo; il dizionario
  (``corner_fasce`` sui cross, ``corner_concessi`` dell'avversario) e, solo con ``lanes=True``, le corsie dei moduli
  (``formation.lane_shares``, pesi dichiarati e NON verificati: spente di default) spostano i corner di gioco;
- falli: Poisson col tasso per squadra-partita × stato e fascia dei falli × uomini × ``falli_fatti`` del dizionario ×
  arbitro (scarto dalla media di campionato ristretto con lo shrinkage k stimato, n/(n+k));
- gialli: binomiale sui falli del passo con probabilità gialli per fallo × (stato e fascia dei gialli / quelli dei
  falli) × arbitro (gialli / falli); rossi diretti per fallo; seconda gialla tra i gialli di una squadra già ammonita.
  Conteggi come ``engine.CardRule``: il primo giallo dell'espulso per doppia ammonizione resta tra i gialli, la seconda
  gialla no, il rosso tra i rossi (``double_yellows_*`` = rossi da doppia ammonizione).
- un'espulsione cambia, dal passo successivo, tiri, xG, corner di gioco, falli e gialli di entrambe le squadre (uomo in
  meno o in più, stimati a parità di stato e fascia). Nel modo «punteggi» non sposta i gol già decisi (il rischio di
  ogni passo e quello futuro si moltiplicano per lo stesso fattore).
Le medie per squadra delle formule attuali (corner, falli, gialli) entrano con ``TeamInput.*_scale`` (vincolo di
coerenza dello stadio 9); con scala 1 restano le medie StatsBomb del campionato.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

import formation
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
CORNER_ORIGINS = ("tiro", "cross", "altro")
MEN = (-1, 0, 1)
# Quantità con l'effetto dell'uomo in meno/in più (sezione «espulsioni» di ``config/motore_eventi.json``).
MEN_QUANTITIES = ("tiri", "xg", "corner_gioco", "falli", "gialli")


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
    corners: tuple[float, float] = (0.0, 0.0)       # corner da cross e «altro» per squadra-partita
    corner_per_saved: float = 0.0                   # corner per tiro parato o respinto
    fouls: float = 0.0                              # falli per squadra-partita
    yellow_per_foul: float = 0.0                    # gialli (comprese le seconde gialle) per fallo
    straight_red_per_foul: float = 0.0              # rossi diretti per fallo (comune: eventi rari)
    second_yellow: float = 0.0                      # seconda gialla tra i gialli di una squadra già ammonita (comune)
    state_corner: tuple[float, ...] = (1.0,) * 5    # corner non da tiro per stato e fascia
    band_corner: tuple[float, ...] = (1.0,) * 4
    state_fouls: tuple[float, ...] = (1.0,) * 5
    band_fouls: tuple[float, ...] = (1.0,) * 4
    state_yellow: tuple[float, ...] = (1.0,) * 5
    band_yellow: tuple[float, ...] = (1.0,) * 4
    men: Mapping[str, tuple[float, float, float]] = field(default_factory=dict)   # quantità → uomo in meno, pari, in più
    referee_k: tuple[float | None, float | None] = (None, None)                   # shrinkage arbitro su falli e gialli
    referee_source: str = ""
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
            **_count_fields(data, key, name),
            note=note,
        )


def _count_fields(data: Mapping[str, Any], key: str, name: str | None) -> dict[str, Any]:
    """Corner, falli e cartellini del campionato ``key``; rossi e seconde gialle sempre «comune» (pochi eventi)."""
    rows, common = data["corner_falli"][key], data["corner_falli"]["comune"]
    state = data["stato_partita"]["quantita"]
    men = data["stato_partita"].get("espulsioni", {}).get("quantita", {})

    def states(quantity):
        return tuple(float(state[quantity]["stato"][str(s)]["moltiplicatore"]) for s in STATES)

    def bands(quantity):
        return tuple(float(state[quantity]["fascia"][band]["moltiplicatore"]) for band, _, _ in BANDS)

    k, source = referee_k(data.get("arbitri", {}), name)
    return {
        "corners": (float(rows["corner_per_squadra_partita"]["cross"]), float(rows["corner_per_squadra_partita"]["altro"])),
        "corner_per_saved": float(rows["corner_per_tiro_parato_respinto"]),
        "fouls": float(rows["falli_per_squadra_partita"]), "yellow_per_foul": float(rows["gialli_per_fallo"]),
        "straight_red_per_foul": float(common.get("rossi_diretti_per_fallo", 0.0)),
        "second_yellow": float(common.get("seconda_gialla_per_giallo_con_precedente", 0.0)),
        "state_corner": states("corner_gioco"), "band_corner": bands("corner_gioco"),
        "state_fouls": states("falli"), "band_fouls": bands("falli"),
        "state_yellow": states("gialli"), "band_yellow": bands("gialli"),
        "men": {quantity: tuple(float(men[quantity][str(m)]["moltiplicatore"]) for m in MEN)
                for quantity in MEN_QUANTITIES if quantity in men},
        "referee_k": k, "referee_source": source,
    }


def referee_k(section: Mapping[str, Any], league: str | None) -> tuple[tuple[float | None, float | None], str]:
    """Shrinkage dell'arbitro (falli, gialli): football-data del campionato se stimato, poi StatsBomb 2015/16, poi la
    mediana delle stime disponibili. k None (varianza tra arbitri nulla) = arbitro senza effetto."""
    def pick(source: str) -> tuple[float | None, float | None] | None:
        rows = (section.get(source) or {}).get(league or "")
        if not rows or not all(rows.get(q, {}).get("stimabile") for q in ("falli", "gialli")):
            return None
        return rows["falli"].get("k"), rows["gialli"].get("k")

    for source in ("football_data", "statsbomb_2015_16"):
        found = pick(source)
        if found is not None:
            return found, f"{source} {league}"
    values = {q: [rows[q]["k"] for source in ("football_data", "statsbomb_2015_16")
                  for rows in (section.get(source) or {}).values() if rows.get(q, {}).get("stimabile") and rows[q].get("k")]
              for q in ("falli", "gialli")}
    return ((float(np.median(values["falli"])) if values["falli"] else None,
             float(np.median(values["gialli"])) if values["gialli"] else None), "mediana delle stime")


def load(league: str | None = None, path: Path = PATH) -> EventParams:
    return EventParams.from_config(json.loads(path.read_text(encoding="utf-8")), league)


@dataclass(frozen=True)
class TeamInput:
    """Una squadra: gol attesi finali del motore (λ o μ), termini del dizionario tattico, quota di gol nel primo tempo."""

    goals: float
    profile: Mapping[str, Any] = field(default_factory=dict)
    first_share: float | None = None
    module: str | None = None            # modulo («4-3-3»): corsie dei corner da cross, solo con ``lanes=True``
    corner_scale: float = 1.0            # scale del vincolo di coerenza (stadio 9) sulle medie attuali
    foul_scale: float = 1.0
    card_scale: float = 1.0


@dataclass(frozen=True)
class RefereeInput:
    """Arbitro: partite dirette e medie per partita (falli, gialli) con le medie di campionato DELLA STESSA FONTE."""

    matches: int
    fouls: float | None = None
    yellows: float | None = None
    league_fouls: float | None = None
    league_yellows: float | None = None
    name: str = ""

    def factors(self, k: tuple[float | None, float | None]) -> tuple[float, float, list[str]]:
        """(fattore falli, fattore gialli, avvisi): 1 + n/(n+k)·(media arbitro / media campionato − 1)."""
        out, warnings = [], []
        for value, league, shrink, label in ((self.fouls, self.league_fouls, k[0], "falli"),
                                             (self.yellows, self.league_yellows, k[1], "gialli")):
            if value is None:
                out.append(1.0)
                continue
            if not league:
                warnings.append(f"arbitro: media {label} di campionato mancante, effetto sui {label} non usato.")
                out.append(1.0)
                continue
            weight = self.matches / (self.matches + shrink) if shrink else 0.0
            out.append(max(1.0 + weight * (float(value) / float(league) - 1.0), 0.05))
        return out[0], out[1], warnings


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


def count_profile(params: EventParams, state_mult, band_mult, step_minutes: int) -> np.ndarray:
    """Quota della media per partita in ogni stato × passo: con la distribuzione tipica degli stati la somma è 1."""
    steps = MINUTES // step_minutes
    bands = np.array([_band_index(step * step_minutes) for step in range(steps)])
    band_length = np.array([high - low for _, low, high in BANDS], float) / MINUTES
    weight = np.asarray(params.state_minutes) / np.sum(params.state_minutes)
    state_mult, band_mult = np.asarray(state_mult, float), np.asarray(band_mult, float)
    table = state_mult[:, None] * band_mult[bands][None, :] / ((weight @ state_mult) * (band_length @ band_mult))
    return table * step_minutes / MINUTES


def ratio_profile(params: EventParams, num_state, num_band, den_state, den_band, step_minutes: int) -> np.ndarray:
    """Probabilità relativa per evento (es. giallo per fallo) per stato × passo, media 1 pesata sugli eventi tipici."""
    steps = MINUTES // step_minutes
    bands = np.array([_band_index(step * step_minutes) for step in range(steps)])
    band_length = np.array([high - low for _, low, high in BANDS], float) / MINUTES
    weight = np.asarray(params.state_minutes) / np.sum(params.state_minutes)
    ratio_state = np.asarray(num_state, float) / np.asarray(den_state, float)
    ratio_band = np.asarray(num_band, float) / np.asarray(den_band, float)
    events = weight[:, None] * band_length[None, :] * np.outer(den_state, den_band)
    norm = np.sum(events * np.outer(ratio_state, ratio_band)) / np.sum(events)
    return ratio_state[:, None] * ratio_band[bands][None, :] / norm


def men_factor(params: EventParams, quantity: str, men: np.ndarray) -> np.ndarray:
    """Moltiplicatore per simulazione dagli uomini in campo (−1, 0, +1); 1 se la stima manca."""
    values = params.men.get(quantity)
    if values is None:
        return np.ones(len(men))
    return np.asarray(values, float)[men + 1]


def wide_factor(own_module: str | None, opponent_module: str | None) -> float:
    """Corner da cross: quota di azioni sulle fasce (``formation.lane_shares``) rispetto a 4-4-2 contro 4-4-2."""
    def wide(attack, defense):
        return 1.0 - formation.lane_shares(attack, defense)["centro"]
    return wide(own_module, opponent_module) / wide(formation.DEFAULT_MODULE, formation.DEFAULT_MODULE)


@dataclass(frozen=True)
class CountTables:
    """Tassi per passo di una squadra: corner da cross e «altro», falli (stato × passo), giallo per fallo (stato × passo)."""

    corner_cross: np.ndarray
    corner_other: np.ndarray
    fouls: np.ndarray
    yellow: np.ndarray


def build_count_tables(params: EventParams, step_minutes: int, *, cross: float = 1.0, other: float = 1.0,
                       fouls: float = 1.0, yellow: float = 1.0) -> CountTables:
    corner = count_profile(params, params.state_corner, params.band_corner, step_minutes)
    foul = count_profile(params, params.state_fouls, params.band_fouls, step_minutes)
    ratio = ratio_profile(params, params.state_yellow, params.band_yellow, params.state_fouls, params.band_fouls, step_minutes)
    return CountTables(corner_cross=params.corners[0] * cross * corner, corner_other=params.corners[1] * other * corner,
                       fouls=params.fouls * fouls * foul, yellow=np.clip(params.yellow_per_foul * yellow * ratio, 0.0, 1.0))


def base_goals(params: EventParams, types: np.ndarray) -> float:
    """Gol attesi per partita con forza 1 e stati tipici (Σ tiri × conversione per tipo)."""
    return float(np.sum(np.asarray(params.shots) * types * np.asarray(params.conversion)))


# ---------------------------------------------------------------------------------------------------------------- stadio 5


def _suffix(values: np.ndarray) -> np.ndarray:
    """Somma dei passi successivi (escluso il passo stesso) lungo l'ultimo asse."""
    total = np.cumsum(values[..., ::-1], axis=-1)[..., ::-1]
    return total - values


def _run(rng: np.random.Generator, n: int, home: Tables, away: Tables, params: EventParams, step_minutes: int,
         scores: tuple[np.ndarray, np.ndarray] | None, counts: Mapping[str, CountTables] | None = None) -> dict[str, np.ndarray]:
    state = MatchState(n, step_minutes)
    kinds = len(SHOT_TYPES)
    out = {f"{key}_{side}": np.zeros((n, kinds), dtype=np.int64) for key in ("shots", "goals_by_type", "saved")
           for side in ("home", "away")}
    out.update({"xg_home": np.zeros(n), "xg_away": np.zeros(n), "first_goal_minute": np.full(n, np.nan),
                "first_goal_team": np.zeros(n, dtype=np.int8),
                "state_steps_home": np.zeros((n, len(STATES)), dtype=np.int16)})
    for side in ("home", "away"):
        out[f"corners_by_origin_{side}"] = np.zeros((n, len(CORNER_ORIGINS)), dtype=np.int64)
        for key in ("fouls", "yellows", "reds", "double_yellows"):
            out[f"{key}_{side}"] = np.zeros(n, dtype=np.int64)
        out[f"first_red_minute_{side}"] = np.full(n, np.nan)
    conversion = np.asarray(params.conversion)
    saved_given_miss = np.clip(np.asarray(params.saved) / np.maximum(1.0 - conversion, 1e-9), 0.0, 1.0)
    xg = np.asarray(params.xg) / conversion   # xG del tiro = xG medio del tipo × qualità (conversione relativa)
    tables = {"home": home, "away": away}
    goal_rate = {side: table.goals.sum(axis=0) for side, table in tables.items()}            # stato × passo
    future = {side: _suffix(rate) for side, rate in goal_rate.items()}
    rows = np.arange(n)
    other = {"home": "away", "away": "home"}
    for step in range(state.steps):
        state.step = step
        index = {"home": state.state_index(True), "away": state.state_index(False)}
        out["state_steps_home"][rows, index["home"]] += 1
        # Uomini in campo all'inizio del passo: espulsi dell'avversario meno i propri, limitati a −1…+1.
        men = {side: np.clip(out[f"reds_{other[side]}"] - out[f"reds_{side}"], -1, 1) for side in ("home", "away")}
        scored = {}
        for side in ("home", "away"):
            table, s = tables[side], index[side]
            shots_factor = men_factor(params, "tiri", men[side])[:, None]
            xg_factor = men_factor(params, "xg", men[side])[:, None]
            goals_mean = table.goals[:, s, step].T                                            # n × tipi
            if scores is None:
                goals = rng.poisson(goals_mean * xg_factor)
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
            misses_mean = np.maximum(table.shots[:, s, step].T * shots_factor - goals_mean * xg_factor, 0.0)
            misses = rng.poisson(misses_mean)
            saved = rng.binomial(misses, saved_given_miss[None, :])
            quality = table.conversion[:, s, step].T * xg[None, :] * (xg_factor / shots_factor)
            out[f"shots_{side}"] += goals + misses
            out[f"goals_by_type_{side}"] += goals
            out[f"saved_{side}"] += saved
            out[f"xg_{side}"] += ((goals + misses) * quality).sum(axis=1)
            scored[side] = goals.sum(axis=1)
            if counts is not None:
                _count_step(rng, out, counts[side], params, side, s, step, saved.sum(axis=1), men[side],
                            state.minute + step_minutes / 2)
        # Primo gol: minuto uniforme nel passo; se segnano entrambe nello stesso passo, squadra ∝ gol del passo.
        new = np.isnan(out["first_goal_minute"]) & ((scored["home"] + scored["away"]) > 0)
        if new.any():
            out["first_goal_minute"][new] = state.minute + rng.uniform(0, step_minutes, new.sum())
            total = scored["home"][new] + scored["away"][new]
            out["first_goal_team"][new] = np.where(rng.random(new.sum()) * total < scored["home"][new], 1, 2)
        state.add(scored["home"], scored["away"])
        if state.minute + step_minutes == HALF:
            out["first_home"], out["first_away"] = state.goals_home.copy(), state.goals_away.copy()
            if counts is not None:
                for side in ("home", "away"):
                    out[f"corners_first_{side}"] = out[f"corners_by_origin_{side}"].sum(axis=1)
                    for key in ("fouls", "yellows", "reds"):
                        out[f"{key}_first_{side}"] = out[f"{key}_{side}"].copy()
    out["goals_home"], out["goals_away"] = state.goals_home, state.goals_away
    if counts is not None:
        for side in ("home", "away"):
            out[f"corners_{side}"] = out[f"corners_by_origin_{side}"].sum(axis=1)
    return out


def _count_step(rng: np.random.Generator, out: dict, table: CountTables, params: EventParams, side: str, s: np.ndarray,
                step: int, saved: np.ndarray, men: np.ndarray, minute: float) -> None:
    """Corner, falli e cartellini di una squadra in un passo (stadi 6-8)."""
    corner_factor = men_factor(params, "corner_gioco", men)
    corners = out[f"corners_by_origin_{side}"]
    corners[:, 0] += rng.binomial(saved, min(params.corner_per_saved, 1.0))
    corners[:, 1] += rng.poisson(table.corner_cross[s, step] * corner_factor)
    corners[:, 2] += rng.poisson(table.corner_other[s, step] * corner_factor)
    foul_factor = men_factor(params, "falli", men)
    fouls = rng.poisson(table.fouls[s, step] * foul_factor)
    yellow_p = np.clip(table.yellow[s, step] * men_factor(params, "gialli", men) / foul_factor, 0.0, 1.0)
    cards = rng.binomial(fouls, yellow_p)
    straight = rng.binomial(fouls - cards, min(params.straight_red_per_foul, 1.0))
    # Seconda gialla: solo tra i gialli presi quando la squadra è già ammonita (nel passo, dal secondo giallo in poi) e mai
    # più dei giocatori ammoniti e ancora in campo (ogni doppia ammonizione consuma un primo giallo).
    booked = out[f"yellows_{side}"] - out[f"double_yellows_{side}"]
    eligible = np.where(booked > 0, cards, np.maximum(cards - 1, 0))
    second = np.minimum(rng.binomial(eligible, min(params.second_yellow, 1.0)), (booked + cards) // 2)
    out[f"fouls_{side}"] += fouls
    out[f"yellows_{side}"] += cards - second
    out[f"double_yellows_{side}"] += second
    reds = straight + second
    first = np.isnan(out[f"first_red_minute_{side}"]) & (reds > 0)
    out[f"first_red_minute_{side}"][first] = minute
    out[f"reds_{side}"] += reds


def simulate(rng: np.random.Generator, n: int, home: TeamInput, away: TeamInput, params: EventParams, *,
             scores: tuple[np.ndarray, np.ndarray] | None = None, step_minutes: int = 5, dictionary=None,
             pilot: int = 20_000, passes: int = 3, referee: RefereeInput | None = None,
             lanes: bool = False) -> dict[str, Any]:
    """``n`` partite a eventi. Con ``scores`` (punteggi Dixon-Coles) i gol finali sono quelli; senza, nascono dai tiri e la
    forza si riscala sui gol attesi ``home.goals`` / ``away.goals``. Restituisce gli array per simulazione (tiri, gol e
    parate per tipo, xG, primo tempo, primo gol, passi per stato, corner per origine, falli, gialli, rossi e doppie
    ammonizioni, anche nel primo tempo) più ``ledger`` e ``warnings``. ``referee`` porta l'effetto dell'arbitro su falli e
    gialli; ``lanes`` accende le corsie dei moduli sui corner da cross (pesi dichiarati, da verificare al banco)."""
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

    referee_fouls, referee_yellows, referee_warnings = (referee.factors(params.referee_k) if referee is not None
                                                        else (1.0, 1.0, []))
    lane = {"home": wide_factor(home.module, away.module) if lanes else 1.0,
            "away": wide_factor(away.module, home.module) if lanes else 1.0}
    lane_warnings = [f"{label}: {formation.parse_module(team.module)[1]}" for label, team in (("casa", home), ("ospite", away))
                     if lanes and formation.parse_module(team.module)[1]]

    def count_tables(team: TeamInput, own: Mapping[str, float], opponent: Mapping[str, float], side: str) -> CountTables:
        conceded = opponent.get("corner_concessi", 1.0)
        return build_count_tables(
            params, step_minutes, cross=own.get("corner_fasce", 1.0) * conceded * lane[side] * team.corner_scale,
            other=conceded * team.corner_scale, fouls=own.get("falli_fatti", 1.0) * referee_fouls * team.foul_scale,
            yellow=(referee_yellows / referee_fouls) * team.card_scale / team.foul_scale)

    counts = {"home": count_tables(home, mult_home, mult_away, "home"),
              "away": count_tables(away, mult_away, mult_home, "away")}

    if scores is None:
        # Vincolo sui gol attesi: lo stato del punteggio cambia la media, la forza si riscala su una simulazione pilota.
        pilot_rng = np.random.default_rng([int(rng.integers(1 << 31)), 11])
        size = min(pilot, n)
        for _ in range(passes):
            paths = _run(pilot_rng, size, *tables(), params, step_minutes, None, counts)
            strength["home"] *= home.goals / max(paths["goals_home"].mean(), 1e-9)
            strength["away"] *= away.goals / max(paths["goals_away"].mean(), 1e-9)
    else:
        scores = (np.asarray(scores[0], dtype=np.int64), np.asarray(scores[1], dtype=np.int64))
        if len(scores[0]) != n or len(scores[1]) != n:
            raise ValueError("I punteggi Dixon-Coles devono essere uno per simulazione.")
    out = _run(rng, n, *tables(), params, step_minutes, scores, counts)
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
        {"voce": "arbitro", "valore": {"falli": round(referee_fouls, 4), "gialli": round(referee_yellows, 4)},
         "nota": (f"{referee.name or 'arbitro'}: {referee.matches} partite, k falli {params.referee_k[0]}, k gialli "
                  f"{params.referee_k[1]} ({params.referee_source})") if referee is not None else "nessun arbitro: effetto 1"},
        {"voce": "corsie", "valore": {"casa": round(lane["home"], 4), "ospite": round(lane["away"], 4)},
         "nota": "corner da cross per le corsie dei moduli (pesi dichiarati, non verificati)" if lanes else "spente"},
        {"voce": "conteggi", "valore": {"corner_scala": (home.corner_scale, away.corner_scale),
                                        "falli_scala": (home.foul_scale, away.foul_scale),
                                        "gialli_scala": (home.card_scale, away.card_scale)},
         "nota": "corner per origine, falli, gialli, rossi diretti e seconde gialle; espulsioni con uomo in meno/in più"},
    ]
    out.update({"types": SHOT_TYPES, "ledger": ledger, "dictionary_rows": {"casa": rows_home, "ospite": rows_away},
                "warnings": [*(f"casa: {w}" for w in warn_home), *(f"ospite: {w}" for w in warn_away),
                             *referee_warnings, *lane_warnings],
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
        if f"corners_{side}" in sample:
            out[f"corner_{side}"] = float(np.mean(sample[f"corners_{side}"]))
            for origin, value in zip(CORNER_ORIGINS, sample[f"corners_by_origin_{side}"].mean(axis=0)):
                out[f"corner_{origin}_{side}"] = float(value)
            for key, name in (("fouls", "falli"), ("yellows", "gialli"), ("reds", "rossi"), ("double_yellows", "doppie")):
                out[f"{name}_{side}"] = float(np.mean(sample[f"{key}_{side}"]))
            out[f"corner_1t_{side}"] = float(np.mean(sample[f"corners_first_{side}"]))
            out[f"gialli_1t_{side}"] = float(np.mean(sample[f"yellows_first_{side}"]))
    out["nessun_gol"] = float(np.mean(sample["first_goal_team"] == 0))
    out["minuto_primo_gol"] = float(np.nanmean(sample["first_goal_minute"])) if np.any(sample["first_goal_team"]) else math.nan
    return out


def card_points(sample: Mapping[str, Any], rule, side: str | None = None) -> np.ndarray:
    """Punti cartellino per simulazione con la regola del bookmaker (``engine.CardRule``): gialli × peso + rossi × peso +
    supplemento della doppia ammonizione. ``side`` = «home», «away» o None (totale)."""
    sides = (side,) if side else ("home", "away")
    return sum(rule.yellow_weight * sample[f"yellows_{s}"] + rule.red_weight * sample[f"reds_{s}"]
               + rule.double_yellow_extra * sample[f"double_yellows_{s}"] for s in sides)
