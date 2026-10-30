"""Campi facoltativi del blocco PARTITA del report dell'Analista (fase AH): ASSENTI_PESATI, RIPOSO, TURNOVER.

    ASSENTI_PESATI:
    casa: Mario Rossi | ruolo: ATT | peso: 0.12 | fonte: https://...
    RIPOSO:
    casa: 3 | ospite: 6 | fonte: https://...
    TURNOVER:
    casa: probabile | fonte: https://...
    ospite: no | fonte: https://...

Lettura tollerante: una riga non valida (peso non numerico, ruolo sconosciuto, giorni fuori scala, senza fonte con link) è
scartata con un avviso e il resto del blocco resta com'era; i blocchi vengono tolti dal corpo prima di correzioni, forma e
chiavi, quindi un report vecchio dà lo stesso risultato di prima. ASSENTI_PESATI serve solo dove Understat non ha il
giocatore (il peso è la quota di produzione offensiva persa, 0-1); RIPOSO solo se manca il calendario; TURNOVER dichiara se si
prevede una formazione rimaneggiata. Un peso esorbitante (> ``MAX_WEIGHT``) è riportato al limite con un avviso.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

SECTIONS = ("ASSENTI_PESATI", "RIPOSO", "TURNOVER")
MAX_WEIGHT = 0.35
MAX_REST_DAYS = 30
ROLES = {"POR": "POR", "PORTIERE": "POR", "DIF": "DIF", "DIFENSORE": "DIF", "CEN": "CEN", "CENTROCAMPISTA": "CEN",
         "ATT": "ATT", "ATTACCANTE": "ATT"}
SIDES = ("casa", "ospite")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_HEADER = re.compile(r"^[ \t>*#_-]*(?P<name>[A-Z][A-Z_]{2,})\s*:\s*$")
_SECTION = re.compile(rf"^[ \t>*#_-]*(?P<name>{'|'.join(SECTIONS)})\s*:\s*$", re.IGNORECASE)


@dataclass
class WeightedAbsent:
    side: str
    player: str
    role: str
    weight: float
    source: str
    note: str = ""


@dataclass
class MatchExtras:
    absent: list[WeightedAbsent] = field(default_factory=list)
    rest_days: dict[str, int] = field(default_factory=dict)
    rest_source: str = ""
    turnover: dict[str, tuple[bool, str]] = field(default_factory=dict)       # lato -> (probabile, fonte)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.absent or self.rest_days or self.turnover)

    def swapped(self) -> "MatchExtras":
        """Con le squadre invertite nel report (casa ↔ ospite)."""
        flip = {"casa": "ospite", "ospite": "casa"}
        return MatchExtras([WeightedAbsent(flip[a.side], a.player, a.role, a.weight, a.source, a.note) for a in self.absent],
                           {flip[side]: days for side, days in self.rest_days.items()}, self.rest_source,
                           {flip[side]: value for side, value in self.turnover.items()}, list(self.warnings))


def _source(parts: dict[str, str]) -> str | None:
    found = _URL.search(parts.get("fonte", ""))
    return found.group(0).rstrip(").,;") if found else None


def _fields(line: str) -> tuple[str, str, dict[str, str]]:
    """«casa: valore | chiave: valore» → (lato, valore, altri campi)."""
    parts = [part.strip() for part in line.split("|")]
    side, _, value = parts[0].partition(":")
    others = {}
    for part in parts[1:]:
        key, _, content = part.partition(":")
        others[key.strip().lower()] = content.strip()
    return side.strip().lower(), value.strip(), others


def _blocks(body: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = None
    for raw in body.splitlines():
        found = _SECTION.match(raw)
        if found:
            current = found["name"].upper()
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        if not raw.strip() or _HEADER.match(raw):
            current = None
            continue
        sections[current].append(raw.strip().strip("`*-").strip())
    return sections


def parse_extras(body: str) -> MatchExtras:
    extras = MatchExtras()
    sections = _blocks(body)
    for line in sections.get("ASSENTI_PESATI", []):
        side, player, other = _fields(line)
        source = _source(other)
        role = ROLES.get(other.get("ruolo", "").upper())
        try:
            weight = float(other.get("peso", "").replace(",", "."))
        except ValueError:
            weight = None
        reason = ("lato non valido (casa/ospite)" if side not in SIDES else "giocatore mancante" if not player else
                  "ruolo sconosciuto (POR/DIF/CEN/ATT)" if role is None else "peso non numerico" if weight is None else
                  "peso fuori scala (0-1)" if not 0 < weight <= 1 else "senza fonte con link" if source is None else "")
        if reason:
            extras.warnings.append(f"ASSENTI_PESATI «{line}»: {reason}, riga scartata.")
            continue
        note = ""
        if weight > MAX_WEIGHT:
            note = f"peso {weight:g} esorbitante: riportato a {MAX_WEIGHT:g}"
            extras.warnings.append(f"ASSENTI_PESATI {player}: {note}.")
            weight = MAX_WEIGHT
        extras.absent.append(WeightedAbsent(side, player, role, weight, source, note))
    for line in sections.get("RIPOSO", []):
        first, _, other = _fields(line)[0:3]
        parts = [part.strip() for part in line.split("|")]
        values = {}
        for part in parts:
            key, _, content = part.partition(":")
            values[key.strip().lower()] = content.strip()
        source = _source(values)
        if source is None:
            extras.warnings.append(f"RIPOSO «{line}»: senza fonte con link, riga scartata.")
            continue
        for side in SIDES:
            if side in values:
                try:
                    days = int(values[side])
                except ValueError:
                    extras.warnings.append(f"RIPOSO {side} «{values[side]}»: non è un numero di giorni, scartato.")
                    continue
                if not 0 <= days <= MAX_REST_DAYS:
                    extras.warnings.append(f"RIPOSO {side} {days}: fuori scala (0-{MAX_REST_DAYS} giorni), scartato.")
                    continue
                extras.rest_days[side] = days
                extras.rest_source = source
    for line in sections.get("TURNOVER", []):
        side, value, other = _fields(line)
        source = _source(other)
        choice = {"probabile": True, "si": True, "sì": True, "no": False}.get(value.lower())
        if side not in SIDES or choice is None or source is None:
            reason = "lato non valido" if side not in SIDES else "valore non valido (probabile/no)" if choice is None else "senza fonte con link"
            extras.warnings.append(f"TURNOVER «{line}»: {reason}, riga scartata.")
            continue
        extras.turnover[side] = (choice, source)
    return extras


def without_extras(body: str) -> str:
    """Il corpo senza i tre blocchi: correzioni, forma e chiavi si leggono come prima."""
    kept, skipping = [], False
    for raw in body.splitlines():
        if _SECTION.match(raw):
            skipping = True
            continue
        if skipping and (not raw.strip() or _HEADER.match(raw)):
            skipping = False
        if not skipping:
            kept.append(raw)
    return "\n".join(kept)
