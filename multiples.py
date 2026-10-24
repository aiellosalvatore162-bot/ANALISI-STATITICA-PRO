"""Costruttore di multiple (fase S): singole, doppie, multipla corta e multipla lunga con Combo Builder.

Una gamba è una giocata su una partita: una selezione singola oppure un Combo
Builder (due mercati di famiglie diverse della stessa partita: gol+corner,
cartellini+corner, cartellini+gol) con probabilità congiunta dai run simulati
(``result["joint_pairs"]``), non il prodotto. Tra partite diverse le gambe sono
indipendenti: la probabilità della multipla è il prodotto. Mai la stessa
partita in due gambe.

Obiettivo predefinito: probabilità più alta (anche con quote basse); l'unico
filtro sono le «trappole», gambe con EV sotto ``trappola_ev`` (default −5%).
Con l'obiettivo «valore» le gambe si scelgono per EV (log di p × quota).
Il bonus multipla (Eurobet) moltiplica la quota quando tutte le gambe hanno
almeno la quota minima. Solo presentazione: nessun calcolo del modello.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from engine import COMBO_FAMILIES, COMBO_PAIRS


SETTINGS_PATH = Path(__file__).resolve().parent / "config" / "oggi.json"
OBJECTIVES = ("probabilità", "valore")
LEG_SEPARATOR, MARKET_SEPARATOR = " | ", " & "


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Leg:
    match_id: str
    match: str                      # «Casa - Ospite»
    selections: tuple[str, ...]     # una selezione, oppure due per il Combo Builder
    probability: float              # 0-1
    odds: float | None
    estimated_odds: bool = False    # quota del Combo Builder stimata (prodotto × sconto CB): inserisci quella vera
    note: str = ""
    product_odds: float | None = None   # Combo Builder: prodotto delle quote dei due mercati

    @property
    def key(self) -> str:
        """Chiave della quota CB Eurobet inserita a mano: partita e mercati."""
        return f"{self.match}|{self.label}"

    @property
    def kind(self) -> str:
        return "combo builder" if len(self.selections) > 1 else "singola"

    @property
    def label(self) -> str:
        return MARKET_SEPARATOR.join(self.selections)

    @property
    def ev(self) -> float | None:
        return None if not self.odds else self.probability * self.odds - 1.0

    @property
    def fair_odds(self) -> float | None:
        return 1.0 / self.probability if self.probability > 0 else None

    def score(self, objective: str) -> float:
        """Criterio di scelta: log(probabilità) oppure log(probabilità × quota)."""
        if self.probability <= 0:
            return -math.inf
        if objective == "valore":
            return math.log(self.probability * self.odds) if self.odds else -math.inf
        return math.log(self.probability)


def _family(selection: str) -> str | None:
    return next((name for name, keys in COMBO_FAMILIES.items() if selection in keys), None)


def candidate_legs(match_id: str, match: str, result: Mapping[str, Any], odds: Mapping[str, float],
                   combinable: Iterable[str] | None = None, *, cb_discount: float = 1.0,
                   cb_real_odds: Mapping[str, float] | None = None) -> list[Leg]:
    """Gambe possibili di una partita: le selezioni del registro con quota e i Combo Builder delle due famiglie.

    ``combinable``: mercati marcati «Combo Builder» nell'incollata Eurobet; ``None`` = flag non noti
    (combo ammesse, da verificare su Eurobet). Quota di un Combo Builder: quella vera di Eurobet se inserita
    (``cb_real_odds``, chiave ``Leg.key``), altrimenti il prodotto delle due quote × ``cb_discount`` (stimata).
    """
    from prediction_log import market_of

    final = result["components"]["finale"]
    legs = []
    for key, price in odds.items():
        if price and float(price) > 1.0 and key in final and market_of(key) is not None:
            legs.append(Leg(match_id, match, (key,), float(final[key]) / 100.0, float(price)))
    allowed = set(combinable) if combinable is not None else None
    for pair, probability in (result.get("joint_pairs") or {}).items():
        first, second = pair.split(MARKET_SEPARATOR)
        if not (odds.get(first) and odds.get(second)):
            continue
        if allowed is not None and not (first in allowed and second in allowed):
            continue
        note = "" if allowed is not None else "flag Combo Builder non noti: verifica su Eurobet che la combinazione sia ammessa"
        product = round(float(odds[first]) * float(odds[second]), 3)
        leg = Leg(match_id, match, (first, second), float(probability) / 100.0, round(product * cb_discount, 3),
                  estimated_odds=True, note=note, product_odds=product)
        real = (cb_real_odds or {}).get(leg.key)
        if real and float(real) > 1.0:
            leg = replace(leg, odds=float(real), estimated_odds=False)
        legs.append(leg)
    return legs


@dataclass
class LegFilter:
    kept: list[Leg] = field(default_factory=list)
    traps: list[Leg] = field(default_factory=list)
    below_min: list[Leg] = field(default_factory=list)


def filter_legs(legs: Iterable[Leg], *, trap_ev: float = -5.0, min_odds: float = 1.0) -> LegFilter:
    """Esclude le trappole (EV sotto ``trap_ev`` punti) e le gambe sotto la quota minima, tenendone traccia."""
    result = LegFilter()
    for leg in legs:
        if leg.ev is not None and leg.ev * 100.0 < trap_ev:
            result.traps.append(leg)
        elif leg.odds is not None and leg.odds < min_odds:
            result.below_min.append(leg)
        else:
            result.kept.append(leg)
    return result


@dataclass
class Multiple:
    name: str
    legs: list[Leg]
    bonus_pct: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def probability(self) -> float:
        return math.prod(leg.probability for leg in self.legs) if self.legs else 0.0

    @property
    def base_odds(self) -> float | None:
        return math.prod(leg.odds for leg in self.legs) if self.legs and all(leg.odds for leg in self.legs) else None

    @property
    def odds(self) -> float | None:
        """Quota pagata: prodotto delle quote con il bonus multipla incluso."""
        return None if self.base_odds is None else self.base_odds * (1.0 + self.bonus_pct / 100.0)

    @property
    def fair_odds(self) -> float | None:
        return 1.0 / self.probability if self.probability > 0 else None

    @property
    def ev(self) -> float | None:
        return None if self.odds is None else self.probability * self.odds - 1.0

    @property
    def one_in(self) -> int | None:
        return round(1.0 / self.probability) if self.probability > 0 else None

    def sentence(self) -> str:
        return f"passa circa 1 volta su {self.one_in}" if self.one_in else "probabilità nulla"

    def leg_warnings(self) -> list[str]:
        notes = list(self.warnings)
        notes += [f"{leg.match} · {leg.label}: EV {leg.ev * 100:+.1f}% (negativo)" for leg in self.legs
                  if leg.ev is not None and leg.ev < 0]
        notes += [f"{leg.match} · {leg.label}: quota Combo Builder stimata {leg.odds:.2f} (prodotto {leg.product_odds:.2f} "
                  f"× sconto CB): inserisci la quota vera di Eurobet" for leg in self.legs if leg.estimated_odds]
        notes += [f"{leg.match} · {leg.label}: {leg.note}" for leg in self.legs if leg.note]
        return notes

    def selection(self) -> str:
        """Selezione del registro: «Casa - Ospite: mercato | …», con «&» tra i due mercati di un Combo Builder."""
        return LEG_SEPARATOR.join(f"{leg.match}: {leg.label}" for leg in self.legs)

    def with_leg(self, index: int, leg: Leg) -> "Multiple":
        """Sostituzione manuale di una gamba (mai due gambe della stessa partita)."""
        legs = list(self.legs)
        if any(other.match_id == leg.match_id for position, other in enumerate(legs) if position != index):
            raise ValueError(f"{leg.match} è già in un'altra gamba della multipla.")
        legs[index] = leg
        return replace(self, legs=legs)


def _by_match(legs: Iterable[Leg]) -> dict[str, list[Leg]]:
    grouped: dict[str, list[Leg]] = {}
    for leg in legs:
        grouped.setdefault(leg.match_id, []).append(leg)
    return grouped


def _best(legs: Iterable[Leg], objective: str, kind: str | None = None) -> Leg | None:
    pool = [leg for leg in legs if kind is None or leg.kind == kind]
    return max(pool, key=lambda leg: (leg.score(objective), leg.probability), default=None)


def best_singles(legs: Iterable[Leg], objective: str = "probabilità", count: int = 5) -> list[Leg]:
    """Le migliori giocate singole, una per partita."""
    best = [_best(group, objective, "singola") for group in _by_match(legs).values()]
    ranked = sorted((leg for leg in best if leg), key=lambda leg: leg.score(objective), reverse=True)
    return ranked[:count]


def build_short(legs: Iterable[Leg], size: int, objective: str = "probabilità", bonus_pct: float = 0.0,
                name: str | None = None) -> Multiple:
    """Multipla di ``size`` gambe singole, una per partita, le migliori secondo l'obiettivo."""
    chosen = best_singles(legs, objective, size)
    multiple = Multiple(name or f"Multipla {size} gambe", chosen, bonus_pct)
    if len(chosen) < size:
        multiple.warnings.append(f"Solo {len(chosen)} partite con una gamba valida: la multipla ha meno di {size} gambe.")
    return multiple


def build_doubles(legs: Iterable[Leg], objective: str = "probabilità", count: int = 3, bonus_pct: float = 0.0) -> list[Multiple]:
    """Le migliori doppie tra le migliori singole di partite diverse."""
    singles = best_singles(legs, objective, 8)
    pairs = [(a, b) for i, a in enumerate(singles) for b in singles[i + 1:]]
    pairs.sort(key=lambda pair: pair[0].score(objective) + pair[1].score(objective), reverse=True)
    return [Multiple(f"Doppia {index}", list(pair), bonus_pct) for index, pair in enumerate(pairs[:count], start=1)]


def build_long(legs: Iterable[Leg], total: int = 12, combos: int = 5, objective: str = "probabilità",
               bonus_pct: float = 0.0, name: str | None = None) -> Multiple:
    """Multipla lunga: ``combos`` Combo Builder + singole, ``total`` gambe su partite tutte diverse.

    Scelta esatta per programmazione dinamica: massimizza la somma dei punteggi (log della probabilità, o
    di probabilità × quota con l'obiettivo «valore») con esattamente ``total`` partite di cui ``combos``
    con un Combo Builder; se le partite o le combo non bastano, si scende al massimo possibile.
    """
    groups = list(_by_match(legs).values())
    options = [(_best(group, objective, "singola"), _best(group, objective, "combo builder")) for group in groups]
    total = min(total, sum(1 for single, combo in options if single or combo))
    requested = combos
    combos = min(combos, sum(1 for _, combo in options if combo), total)
    warnings = []
    if combos < requested:
        warnings.append(f"Combo Builder possibili: {combos} invece di {requested}. Servono le quote di entrambi i mercati "
                        "(quote mirate di corner e cartellini o incollata Eurobet); con la quota stimata molti finiscono "
                        "tra le trappole: inserisci la quota CB vera in «Quote reali dei Combo Builder».")
    if total < 12:
        warnings.append(f"Partite con gambe valide: {total}. La multipla lunga ne vuole 12-13: analizza più partite.")
    for wanted in range(combos, -1, -1):
        chosen = _long_dp(options, total, wanted, objective)
        if chosen is not None:
            if wanted < combos:
                warnings.append(f"Combo Builder possibili: {wanted} invece di {combos} (partite insufficienti).")
            break
    else:
        chosen = []
    return Multiple(name or f"Multipla lunga {len(chosen)} gambe", chosen, bonus_pct, warnings)


def _long_dp(options, total: int, combos: int, objective: str) -> list[Leg] | None:
    # best[j][c] = (punteggio, gambe) scegliendo j partite, c delle quali con il Combo Builder.
    best = {(0, 0): (0.0, [])}
    for single, combo in options:
        updated = dict(best)
        for (j, c), (score, chosen) in best.items():
            if j >= total:
                continue
            for leg, extra in ((single, 0), (combo, 1)):
                if leg is None or c + extra > combos or leg.score(objective) == -math.inf:
                    continue
                key, value = (j + 1, c + extra), score + leg.score(objective)
                if key not in updated or value > updated[key][0]:
                    updated[key] = (value, chosen + [leg])
        best = updated
    found = best.get((total, combos))
    return None if found is None else sorted(found[1], key=lambda leg: (leg.kind != "combo builder", -leg.probability))


def format_probability(number: float) -> str:
    """Probabilità leggibile anche quando è minuscola (multiple lunghe)."""
    if number >= 0.01:
        return f"{number:.1%}"
    return f"{number:.2%}" if number >= 0.0001 else "< 0.01%"


def comparison_line(probable: Multiple | None, value: Multiple | None) -> str | None:
    """«più valore: probabilità X% (1 su N), EV Y% — differenza rispetto a più probabile»."""
    if not probable or not value or not probable.legs or not value.legs or probable.ev is None or value.ev is None:
        return None

    ratio = probable.probability / value.probability if value.probability > 0 else None
    return (f"Più valore: probabilità {format_probability(value.probability)} (1 su {value.one_in}), EV {value.ev:+.1%} — rispetto a più "
            f"probabile ({format_probability(probable.probability)}, 1 su {probable.one_in}, EV {probable.ev:+.1%}): probabilità "
            f"{(value.probability - probable.probability) * 100:+.2f} punti"
            + (f" ({ratio:.1f} volte meno probabile)" if ratio and ratio > 1 else "")
            + f", EV {(value.ev - probable.ev) * 100:+.1f} punti.")


# --- Registro ---------------------------------------------------------------------------------

def multiple_row(multiple: Multiple, *, day: date | str, time: str, competition: str, kind: str, version: str,
                 note: str = "") -> dict:
    """Riga «Multipla» del registro: Selezione = elenco delle gambe, Prob_finale = probabilità della multipla."""
    from prediction_log import COLUMNS

    selection = multiple.selection()
    digest = hashlib.sha1(selection.encode("utf-8")).hexdigest()[:10]
    day_text = day.isoformat() if isinstance(day, date) else str(day)
    extra = [f"{len(multiple.legs)} gambe", f"bonus {multiple.bonus_pct:g}%" if multiple.bonus_pct else "",
             *[cb_note(leg) for leg in multiple.legs if leg.kind == "combo builder"], note]
    row = {column: None for column in COLUMNS}
    row.update({
        "ID": f"{day_text}|Multipla|Multipla|{digest}", "Data": day_text, "Ora": time, "Competizione": competition,
        "Partita": f"Multipla {len(multiple.legs)} gambe", "Mercato": "Multipla", "Selezione": selection,
        "Prob_finale": round(multiple.probability, 6),
        "Quota_presa": round(multiple.odds, 3) if multiple.odds else None, "Tipo": kind, "Versione_modello": version,
        "Note": "; ".join(part for part in extra if part),
    })
    return row


def cb_note(leg: Leg) -> str:
    """Nota del registro per un Combo Builder: «quota CB reale 2.80 / prodotto 3.35 [partita: mercati]» o «stimata»."""
    state = "stimata" if leg.estimated_odds else "reale"
    product = f" / prodotto {leg.product_odds:.2f}" if leg.product_odds else ""
    return f"quota CB {state} {leg.odds:.2f}{product} [{leg.match}: {leg.label}]"


def parse_selection(selection: str) -> list[tuple[str, list[str]]]:
    """Gambe della Selezione di una riga «Multipla»: [(partita, [mercati])]."""
    legs = []
    for part in str(selection).split(LEG_SEPARATOR):
        match, _, markets = part.rpartition(": ")
        if match and markets:
            legs.append((match.strip(), [market.strip() for market in markets.split(MARKET_SEPARATOR)]))
    return legs


def leg_markets(legs: Sequence[Leg]) -> list[tuple[str, str]]:
    """(partita, mercato) di tutte le gambe: le singole selezioni da salvare nel registro con la multipla."""
    return [(leg.match_id, selection) for leg in legs for selection in leg.selections]


def pair_key(first: str, second: str) -> str | None:
    """Chiave di ``joint_pairs`` per due mercati, nell'ordine delle famiglie di ``COMBO_PAIRS``."""
    families = (_family(first), _family(second))
    for a, b in COMBO_PAIRS:
        if families == (a, b):
            return f"{first}{MARKET_SEPARATOR}{second}"
        if families == (b, a):
            return f"{second}{MARKET_SEPARATOR}{first}"
    return None
