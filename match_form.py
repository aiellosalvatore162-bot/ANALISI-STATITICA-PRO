"""Blocco facoltativo «FORMA:» del report dell'Analista: forma recente delle due squadre, SOLO informativa.

    FORMA:
    casa: V-V-P-N-V | gol_fatti_subiti: 9-4 | in_casa: V-N-V | fonte: https://...
    ospite: P-N-V-P-P | gol_fatti_subiti: 5-8 | in_trasferta: P-P-N | fonte: https://...
    nota: <una riga>

Lettura tollerante come le chiavi del match: un campo non valido è scartato con un avviso, una riga senza
fonte con link è scartata, un blocco assente o vuoto dà ``None``. La forma non entra MAI nel motore
(probabilità, gol attesi, EV, semaforo, ancoraggio): il modello Dixon-Coles ne tiene già conto. Serve a chi
guarda (scheda nella pagina Oggi) e finisce nella colonna «Forma» del registro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

HEADER = "FORMA:"
_HEADER = re.compile(r"^[ \t>*#_-]*FORMA\s*:\s*$", re.IGNORECASE | re.MULTILINE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_RESULTS = re.compile(r"^[VNP](?:\s*[-,/ ]\s*[VNP])*$", re.IGNORECASE)
_GOALS = re.compile(r"^\s*(\d+)\s*[-–:]\s*(\d+)\s*$")
SIDES = {"casa": ("in_casa", "in casa"), "ospite": ("in_trasferta", "in trasferta")}


def _results(text: str) -> list[str] | None:
    text = text.strip()
    if not text or not _RESULTS.match(text):
        return None
    return [letter.upper() for letter in re.findall(r"[VNPvnp]", text)]


@dataclass
class SideForm:
    results: list[str] = field(default_factory=list)      # ultime 5, dalla più vecchia
    goals: tuple[int, int] | None = None                  # gol fatti-subiti
    venue: list[str] = field(default_factory=list)        # ultime 3 in casa (casa) o fuori (ospite)
    source: str = ""

    @property
    def points(self) -> int:
        return sum({"V": 3, "N": 1}.get(result, 0) for result in self.results)

    def text(self, venue_label: str) -> str:
        parts = ["-".join(self.results)] if self.results else []
        if self.goals:
            parts.append(f"gol {self.goals[0]}-{self.goals[1]}")
        if self.venue:
            parts.append(f"{venue_label} {'-'.join(self.venue)}")
        return ", ".join(parts)


@dataclass
class MatchForm:
    home: SideForm | None = None
    away: SideForm | None = None
    note: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.home is None and self.away is None and not self.note

    def summary(self) -> str:
        """Testo per la colonna «Forma» del registro e del foglio Analisi."""
        parts = []
        for label, side, venue in (("Casa", self.home, "in casa"), ("Ospite", self.away, "fuori")):
            if side is not None and side.text(venue):
                parts.append(f"{label} {side.text(venue)}")
        if self.note:
            parts.append(self.note)
        return " | ".join(parts)

    def to_dict(self) -> dict:
        def side(value: SideForm | None) -> dict | None:
            return None if value is None else {"results": value.results, "goals": list(value.goals) if value.goals else None,
                                               "venue": value.venue, "source": value.source}

        return {"home": side(self.home), "away": side(self.away), "note": self.note}


def section(text: str) -> tuple[str, int, int]:
    """(testo del blocco FORMA, inizio, fine) nel corpo di una partita; ("", -1, -1) se assente.

    Il blocco finisce alla prima riga vuota dopo le sue righe o alla prima riga che non è casa/ospite/nota."""
    found = _HEADER.search(text)
    if not found:
        return "", -1, -1
    end, seen = found.end(), False
    for line in text[found.end():].splitlines(keepends=True):
        stripped = line.strip().strip("`*-").strip().lower()
        if not stripped:
            if seen:
                break
            end += len(line)
            continue
        if not stripped.startswith(("casa", "ospite", "nota")):
            break
        end += len(line)
        seen = True
    return text[found.start():end].strip(), found.start(), end


def parse_form(text: str) -> MatchForm | None:
    """Blocco FORMA del testo (``None`` se assente o senza nessun dato valido)."""
    block, _, _ = section(text)
    if not block:
        return None
    form = MatchForm()
    for raw in block.splitlines()[1:]:
        line = raw.strip().strip("`*-").strip()
        key, _, rest = line.partition(":")
        key = key.strip().lower()
        if key == "nota":
            form.note = rest.strip()
            continue
        if key not in SIDES:
            continue
        parts = [part.strip() for part in rest.split("|")]
        side = SideForm()
        values = {"risultati": parts[0]}
        for part in parts[1:]:
            name, _, value = part.partition(":")
            values[name.strip().lower().replace(" ", "_")] = value.strip()
        source = _URL.search(values.get("fonte", ""))
        if source is None:
            form.warnings.append(f"Forma {key}: senza fonte con link, scartata.")
            continue
        side.source = source.group(0).rstrip(").,;")
        results = _results(values["risultati"])
        if results is None:
            form.warnings.append(f"Forma {key}: «{values['risultati']}» non è una sequenza V-N-P, ignorata.")
        else:
            side.results = results[-5:]
        goals = _GOALS.match(values.get("gol_fatti_subiti", ""))
        if goals:
            side.goals = (int(goals[1]), int(goals[2]))
        elif values.get("gol_fatti_subiti"):
            form.warnings.append(f"Forma {key}: gol «{values['gol_fatti_subiti']}» non nel formato x-y, ignorati.")
        venue = _results(values.get(SIDES[key][0], ""))
        if venue is not None:
            side.venue = venue[-3:]
        elif values.get(SIDES[key][0]):
            form.warnings.append(f"Forma {key}: «{values[SIDES[key][0]]}» non è una sequenza V-N-P, ignorata.")
        if side.results or side.goals or side.venue:
            setattr(form, "home" if key == "casa" else "away", side)
    return None if form.empty else form


def without_section(text: str) -> str:
    """Il testo senza il blocco FORMA (per commenti e correzioni)."""
    _, start, end = section(text)
    return text if start < 0 else (text[:start] + text[end:]).strip()
