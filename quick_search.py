"""Ricerca rapida (fase X): frasi come «dammi 6 over 2.5 per stasera» trasformate in una schedina.

Solo regole sul testo, niente AI: si riconoscono numero di partite, mercato e linea, soglia di
probabilità e fascia oraria. La schedina si costruisce con le partite analizzate nella pagina Oggi,
con l'obiettivo predefinito del costruttore di multiple (probabilità più alta) e il filtro anti-trappola.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from multiples import Leg


EXAMPLES = (
    "dammi 6 over 2.5 per stasera",
    "4 goal più probabili",
    "3 multigol casa sopra il 70%",
    "5 over 8.5 corner",
    "doppia chance sicure oggi",
    "4 under 3.5 nel pomeriggio",
    "3 over 3.5 cartellini sopra il 65%",
)
PRESETS = ("5 over 1.5 sicuri", "6 over 2.5 per stasera", "4 goal più probabili", "doppia chance sicure oggi",
           "5 over 8.5 corner", "3 multigol casa sopra il 70%")
DEFAULT_COUNT = 5
SAFE_THRESHOLD = 0.75            # «sicure» = probabilità almeno 75%
DEFAULT_LINES = {"gol": 2.5, "corner": 8.5, "cartellini": 4.5}
BANDS = {"stasera": (18, 24), "sera": (18, 24), "pomeriggio": (12, 18), "mattina": (0, 13), "pranzo": (11, 15)}
_WORDS = {"una": 1, "un": 1, "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8,
          "nove": 9, "dieci": 10, "undici": 11, "dodici": 12}


@dataclass(frozen=True)
class Query:
    text: str
    market: str                 # over, under, goal, no goal, multigol, multigol casa, multigol ospite, doppia chance, 1x2
    family: str = "gol"         # gol, corner, cartellini
    line: float | None = None
    low_high: tuple[int, int] | None = None
    count: int = DEFAULT_COUNT
    threshold: float | None = None
    band: str | None = None

    def describe(self) -> str:
        what = {"over": "Over", "under": "Under"}.get(self.market, self.market.capitalize())
        if self.line is not None:
            what += f" {self.line:g} {self.family}"
        if self.low_high:
            what += f" {self.low_high[0]}-{self.low_high[1]}"
        parts = [f"{self.count} × {what}"]
        if self.threshold:
            parts.append(f"probabilità almeno {self.threshold:.0%}")
        if self.band:
            parts.append(self.band)
        return " · ".join(parts)


def parse_query(text: str) -> Query | None:
    """Frase -> richiesta; ``None`` se il mercato non è riconosciuto."""
    lowered = " " + re.sub(r"(\d),(\d)", r"\1.\2", text.lower()) + " "
    family = "corner" if "corner" in lowered or "angoli" in lowered else \
        "cartellini" if re.search(r"cartellin|ammonizion|gialli", lowered) else "gol"
    threshold = None
    found = re.search(r"(?:sopra|oltre|almeno|più del|piu del|>=?|≥)\s*(?:il|al|lo)?\s*(\d{1,2})\s*%", lowered) \
        or re.search(r"(\d{1,2})\s*%", lowered)
    if found:
        threshold = int(found.group(1)) / 100.0
        lowered = lowered.replace(found.group(0), " ")
    elif re.search(r"\bsicur[eia]\b", lowered):
        threshold = SAFE_THRESHOLD
    market, line, low_high = None, None, None
    over_under = re.search(r"\b(over|under|o|u)\s*(\d+(?:\.5)?)\b", lowered)
    if over_under and (over_under.group(1) in ("over", "under") or "." in over_under.group(2)):
        market = "over" if over_under.group(1).startswith("o") else "under"
        line = float(over_under.group(2))
        lowered = lowered.replace(over_under.group(0), " ")
    elif re.search(r"\b(over|under)\b", lowered):
        market = re.search(r"\b(over|under)\b", lowered).group(1)
        line = DEFAULT_LINES[family]
    multigol = re.search(r"multigol(?:\s+(casa|ospite|totale))?(?:\s+(\d)\s*-\s*(\d))?", lowered)
    if market is None and multigol:
        market = f"multigol {multigol.group(1)}" if multigol.group(1) in ("casa", "ospite") else "multigol"
        if multigol.group(2):
            low_high = (int(multigol.group(2)), int(multigol.group(3)))
        lowered = lowered.replace(multigol.group(0), " ")
    if market is None and re.search(r"\bno\s*goal\b|\bnogoal\b|\bng\b", lowered):
        market = "no goal"
    if market is None and re.search(r"\bgoal\b|\bgg\b|entrambe (?:le squadre )?(?:segnano|a segno)", lowered):
        market = "goal"
    if market is None and re.search(r"doppi[ae] chance|\bdc\b", lowered):
        market = "doppia chance"
    if market is None and re.search(r"\b(?:segn[oi]|1x2|vittori[ae]|favorit[ei])\b", lowered):
        market = "1x2"
    if market is None:
        return None
    if market in ("over", "under") and family != "gol" and line is None:
        line = DEFAULT_LINES[family]
    count = None
    number = re.search(r"\b(\d{1,2})\b(?!\s*[.%])", lowered)
    if number:
        count = int(number.group(1))
    else:
        word = next((value for name, value in _WORDS.items() if re.search(rf"\b{name}\b", lowered)), None)
        count = word
    band = next((name for name in BANDS if re.search(rf"\b{name}\b", lowered)), "oggi" if " oggi " in lowered else None)
    if band == "sera":
        band = "stasera"
    return Query(text.strip(), market, family, line, low_high, max(1, min(count or DEFAULT_COUNT, 20)), threshold, band)


def candidate_keys(query: Query, keys: Iterable[str]) -> list[str]:
    """Chiavi evento del motore che corrispondono alla richiesta (tra quelle simulate)."""
    keys = list(keys)
    if query.market in ("over", "under"):
        wanted = f"{query.market.capitalize()} {query.line:g} {query.family}"
        return [wanted] if wanted in keys else []
    if query.market == "goal":
        return ["Goal"] if "Goal" in keys else []
    if query.market == "no goal":
        return ["No Goal"] if "No Goal" in keys else []
    if query.market == "doppia chance":
        return [key for key in ("1X", "X2", "12") if key in keys]
    if query.market == "1x2":
        return [key for key in ("1", "X", "2") if key in keys]
    team = {"multigol casa": "Casa ", "multigol ospite": "Ospite "}.get(query.market, "")
    pattern = re.compile(rf"^Multigol {team}(\d+)-(\d+)$")
    found = [key for key in keys if pattern.match(key)]
    if query.low_high:
        found = [key for key in found if tuple(map(int, pattern.match(key).groups())) == query.low_high]
    return found


def in_band(kickoff: datetime, band: str | None) -> bool:
    if band is None or band == "oggi" or band not in BANDS:
        return True
    low, high = BANDS[band]
    return low <= kickoff.hour < high


@dataclass
class Proposal:
    query: Query
    legs: list[Leg] = field(default_factory=list)
    traps: list[Leg] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build(query: Query, matches: Sequence[Mapping[str, Any]], *, trap_ev: float = -5.0) -> Proposal:
    """Per ogni partita la selezione più probabile del mercato; soglia, fascia oraria e trappole; le migliori ``count``.

    ``matches``: dizionari con ``id``, ``label``, ``kickoff`` (ora locale), ``result``, ``odds``.
    """
    proposal = Proposal(query)
    out_of_band = 0
    for match in matches:
        if not in_band(match["kickoff"], query.band):
            out_of_band += 1
            continue
        final = match["result"]["components"]["finale"]
        keys = candidate_keys(query, final)
        if not keys:
            continue
        legs = [Leg(match["id"], match["label"], (key,), float(final[key]) / 100.0,
                    float(match["odds"][key]) if match["odds"].get(key) else None) for key in keys]
        safe = [leg for leg in legs if leg.ev is None or leg.ev * 100.0 >= trap_ev]
        proposal.traps += [leg for leg in legs if leg not in safe and leg.probability == max(l.probability for l in legs)]
        if not safe:
            continue
        best = max(safe, key=lambda leg: leg.probability)
        if query.threshold is not None and best.probability < query.threshold:
            continue
        proposal.legs.append(best)
    proposal.legs.sort(key=lambda leg: -leg.probability)
    found = len(proposal.legs)
    proposal.legs = proposal.legs[:query.count]
    if out_of_band:
        proposal.notes.append(f"{out_of_band} partite fuori dalla fascia «{query.band}» escluse.")
    if found < query.count:
        proposal.notes.append(f"Trovate solo {found} partite su {query.count} richieste"
                              + (f" sopra il {query.threshold:.0%}" if query.threshold else "") + ".")
    if any(leg.odds is None for leg in proposal.legs):
        proposal.notes.append("Alcune gambe non hanno quota (es. multigol senza incollata Eurobet): EV non calcolabile.")
    return proposal
