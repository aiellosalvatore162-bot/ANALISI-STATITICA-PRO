"""Report dell'Analista del giorno (fase W): blocchi PARTITA + CORREZIONI_CLAUDE abbinati alle partite di Oggi.

Il report è il testo di un'attività programmata di Claude. Per ogni partita contiene:

    PARTITA: <Casa> - <Ospite> | <competizione> | <gg/mm/aaaa hh:mm>
    <commento>
    CORREZIONI_CLAUDE:
    gol_casa: 0.95 | motivo: ... | fonte: https://...
    confidenza: media
    commento: ...

Testo libero prima, in mezzo e dopo i blocchi è ignorato. Ogni blocco si abbina a una partita della
pagina Oggi con i nomi delle squadre (``datasources.names.match_team``, grafie diverse ammesse) e la
data (un giorno di tolleranza per il fuso orario); le correzioni si leggono con ``claude_bridge``
(stesse regole della fase G: limiti, fonte obbligatoria, media arbitro avvicinata alla media).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import re
from typing import Iterable, Sequence

from claude_bridge import HEADER, ClaudeResponse, ResponseError, parse_response
from match_keys import MatchKey, keys_section, parse_keys, swap_text


_MATCH = re.compile(r"^[ \t>*#_-]*PARTITA\s*:\s*(?P<body>.+)$", re.IGNORECASE | re.MULTILINE)
_DATE = re.compile(r"(?P<d>\d{1,2})[/.-](?P<m>\d{1,2})[/.-](?P<y>\d{2,4})(?:\s+(?P<h>\d{1,2})[:.](?P<min>\d{2}))?")


@dataclass
class ReportBlock:
    header: str                       # riga PARTITA come scritta
    home: str | None
    away: str | None
    competition: str = ""
    when: datetime | None = None
    comment: str = ""                 # testo tra la riga PARTITA e CORREZIONI_CLAUDE
    corrections_text: str = ""        # da «CORREZIONI_CLAUDE:» alla fine del blocco (formato della scheda)
    response: ClaudeResponse | None = None
    error: str = ""                   # blocco illeggibile
    matched: int | None = None        # indice della partita abbinata
    reason: str = ""                  # perché non è abbinato
    keys_text: str = ""               # blocco CHIAVI_MATCH (informativo)
    swapped: bool = False             # casa e ospite invertite rispetto alla partita della pagina
    original: tuple[str, str] = ("", "")  # correzioni e chiavi come scritte nel report

    @property
    def notice(self) -> str:
        return "squadre invertite nel report: correzioni scambiate" if self.swapped else ""

    @property
    def full_text(self) -> str:
        """Correzioni e chiavi nel formato della tab Claude della scheda."""
        return "\n\n".join(part for part in (self.corrections_text, self.keys_text) if part)

    def keys(self) -> tuple[list[MatchKey], list[str]]:
        return parse_keys(self.keys_text) if self.keys_text else ([], [])

    @property
    def label(self) -> str:
        return f"{self.home} - {self.away}" if self.home and self.away else self.header

    def applied(self) -> list[str]:
        if self.response is None:
            return []
        return [f"{key} {correction.applied:g}" for key, correction in self.response.corrections.items() if correction.accepted]

    def discarded(self) -> list[str]:
        if self.response is None:
            return []
        return [f"{key} ({correction.note})" for key, correction in self.response.corrections.items() if not correction.accepted]


@dataclass(frozen=True)
class Target:
    """Partita della pagina Oggi a cui abbinare i blocchi."""
    index: int
    home: str
    away: str
    day: date | None


def _when(text: str) -> datetime | None:
    found = _DATE.search(text)
    if not found:
        return None
    year = int(found["y"]) + (2000 if len(found["y"]) == 2 else 0)
    try:
        return datetime(year, int(found["m"]), int(found["d"]), int(found["h"] or 0), int(found["min"] or 0))
    except ValueError:
        return None


def parse_report(text: str) -> list[ReportBlock]:
    """Tutti i blocchi PARTITA del report, ciascuno con le sue correzioni (o il motivo per cui non si leggono)."""
    from performance import split_match

    headers = list(_MATCH.finditer(text))
    blocks = []
    for position, header in enumerate(headers):
        end = headers[position + 1].start() if position + 1 < len(headers) else len(text)
        body = text[header.end():end]
        parts = [part.strip().strip("*_").strip() for part in header["body"].split("|")]
        teams = split_match(parts[0].strip("*_ "))
        block = ReportBlock(header=header.group(0).strip().strip("*_# >").strip(), home=teams[0] if teams else None,
                            away=teams[1] if teams else None,
                            competition=parts[1] if len(parts) > 1 and not _DATE.fullmatch(parts[1]) else "",
                            when=_when(" | ".join(parts[1:])))
        start = body.upper().find(HEADER)
        if teams is None:
            block.error = "squadre non leggibili nella riga PARTITA (atteso «Casa - Ospite»)"
        if start < 0:
            block.error = block.error or "manca il blocco CORREZIONI_CLAUDE"
            block.comment = body.strip()
        else:
            block.comment = body[:start].strip()
            block.corrections_text = _trim(body[start:])
            try:
                block.response = parse_response(block.corrections_text)
            except ResponseError as exc:
                block.error = str(exc)
        block.keys_text = keys_section(body)
        block.original = (block.corrections_text, block.keys_text)
        blocks.append(block)
    return blocks


def _trim(text: str) -> str:
    """Il blocco delle correzioni fino alla prima riga vuota dopo «commento:» (il testo libero che segue resta fuori)."""
    lines, seen_comment = [], False
    for line in text.strip().splitlines():
        if (seen_comment and not line.strip()) or line.strip().strip("`*-").strip().upper().startswith("CHIAVI_MATCH"):
            break
        lines.append(line)
        seen_comment = seen_comment or line.strip().lower().lstrip("`*-").strip().startswith("commento:")
    return "\n".join(lines).strip().strip("`").strip()


def match_blocks(blocks: Sequence[ReportBlock], targets: Iterable[Target], *, tolerance_days: int = 1) -> list[ReportBlock]:
    """Abbina ogni blocco leggibile a una partita (stesse squadre, data entro ``tolerance_days``); una partita, un blocco."""
    from datasources.names import match_team

    targets = list(targets)
    taken: dict[int, str] = {}
    for block in blocks:
        block.matched, block.reason, block.swapped = None, "", False
        if block.original != ("", ""):
            block.corrections_text, block.keys_text = block.original
        if block.error:
            block.reason = block.error
            continue
        candidates = [target for target in targets
                      if match_team(block.home, [target.home]) and match_team(block.away, [target.away])]
        if not candidates:
            # Casa e ospite invertite nel report: si abbina comunque scambiando le correzioni (e i lati dei duelli).
            candidates = [target for target in targets
                          if match_team(block.home, [target.away]) and match_team(block.away, [target.home])]
            block.swapped = bool(candidates)
        if not candidates:
            block.reason = "nessuna partita della pagina Oggi con queste squadre"
            continue
        if block.when is not None:
            dated = [target for target in candidates
                     if target.day is None or abs((target.day - block.when.date()).days) <= tolerance_days]
            if not dated:
                block.reason = (f"data diversa: report {block.when:%d/%m/%Y}, pagina "
                                + ", ".join(f"{target.day:%d/%m/%Y}" for target in candidates if target.day))
                continue
            candidates = dated
        target = candidates[0]
        if block.swapped:
            block.corrections_text, block.keys_text = swap_text(block.corrections_text), swap_text(block.keys_text)
            block.response = parse_response(block.corrections_text)
        if target.index in taken:
            block.reason = f"partita già abbinata al blocco «{taken[target.index]}»: uso solo il primo"
            continue
        taken[target.index] = block.header
        block.matched = target.index
    return list(blocks)


def report_rows(blocks: Sequence[ReportBlock], names: dict[int, str]) -> list[dict]:
    """Tabella: partita del report, partita abbinata, correzioni applicate e scartate, confidenza."""
    return [{
        "Partita del report": block.label,
        "Data del report": f"{block.when:%d/%m/%Y %H:%M}" if block.when else "",
        "Partita abbinata": names.get(block.matched, "") if block.matched is not None else "",
        "Correzioni applicate": ", ".join(block.applied()),
        "Correzioni scartate": ", ".join(block.discarded()),
        "Confidenza": (block.response.confidence or "") if block.response else "",
        "Chiavi del match": len(block.keys()[0]),
        "Avviso": block.notice,
        "Non abbinato perché": block.reason,
    } for block in blocks]
