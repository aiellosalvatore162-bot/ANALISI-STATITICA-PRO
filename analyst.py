"""Report dell'Analista del giorno (fase W): blocchi PARTITA + CORREZIONI_CLAUDE abbinati alle partite di Oggi.

Il report è il testo di un'attività programmata di Claude. Per ogni partita contiene:

    PARTITA: <Casa> - <Ospite> | <competizione> | <gg/mm/aaaa hh:mm>
    <commento>
    CORREZIONI_CLAUDE:
    gol_casa: 0.95 | motivo: ... | fonte: https://...
    confidenza: media
    commento: ...

Fase Y: il report può contenere anche blocchi ESITO (partite di ieri: risultato, primo tempo, corner, gialli,
rossi e doppie ammonizioni, anche per tempo, con la fonte) e PROFILO_TATTICO (schede delle squadre, stesso
formato della fase Q); ogni blocco finisce dove inizia il successivo, di qualunque tipo. ``parse_full`` li
legge tutti.

Testo libero prima, in mezzo e dopo i blocchi è ignorato. Ogni blocco si abbina a una partita della
pagina Oggi con i nomi delle squadre (``datasources.names.match_team``, grafie diverse ammesse) e la
data (un giorno di tolleranza per il fuso orario); le correzioni si leggono con ``claude_bridge``
(stesse regole della fase G: limiti, fonte obbligatoria, media arbitro avvicinata alla media).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import re
from typing import Any, Iterable, Sequence

from claude_bridge import HEADER, ClaudeResponse, ResponseError, parse_response
from match_form import parse_form, without_section
from match_keys import MatchKey, keys_section, parse_keys, swap_text


_MATCH = re.compile(r"^[ \t>*#_-]*PARTITA\s*:\s*(?P<body>.+)$", re.IGNORECASE | re.MULTILINE)
_OUTCOME = re.compile(r"^[ \t>*#_-]*ESITO\s*:\s*(?P<body>.+)$", re.IGNORECASE | re.MULTILINE)
_PROFILE = re.compile(r"^[ \t>*#_-]*PROFILO_TATTICO\s*:", re.IGNORECASE | re.MULTILINE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
# Righe dell'ESITO (casa-ospite) → colonne dei risultati (``performance.settle``).
OUTCOME_FIELDS = {
    "risultato": ("home_goals", "away_goals"), "primo_tempo": ("home_ht_goals", "away_ht_goals"),
    "corner": ("home_corners", "away_corners"), "corner_1t": ("home_corners_1t", "away_corners_1t"),
    "gialli": ("home_yellows", "away_yellows"), "gialli_1t": ("home_yellows_1t", "away_yellows_1t"),
    "rossi": ("home_reds", "away_reds"), "rossi_1t": ("home_reds_1t", "away_reds_1t"),
    "doppie_ammonizioni": ("home_double_yellows", "away_double_yellows"),
}


def _boundaries(text: str) -> list[int]:
    """Inizio di ogni blocco (PARTITA, ESITO, PROFILO_TATTICO): un blocco finisce dove inizia il successivo."""
    return sorted({found.start() for pattern in (_MATCH, _OUTCOME, _PROFILE) for found in pattern.finditer(text)})


def _end(text: str, start: int) -> int:
    return next((position for position in _boundaries(text) if position > start), len(text))
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
    form: Any = None                  # match_form.MatchForm: solo informativa, mai nel motore
    form_original: Any = None         # forma come scritta nel report (prima di un eventuale scambio di squadre)

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
    for header in headers:
        body = text[header.end():_end(text, header.start())]
        # Blocco FORMA facoltativo: letto a parte e tolto dal corpo, così correzioni e commento restano come prima.
        form = parse_form(body)
        body = without_section(body)
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
        block.form = block.form_original = form
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
        block.form = block.form_original
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
            if block.form is not None:
                from dataclasses import replace

                block.form = replace(block.form, home=block.form.away, away=block.form.home)
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
        "Forma": block.form.summary() if block.form is not None else "",
        "Avviso": block.notice,
        "Non abbinato perché": block.reason,
    } for block in blocks]


# --- Fase Y: ESITO e PROFILO_TATTICO ----------------------------------------------------------------------

@dataclass
class OutcomeBlock:
    """Esito di una partita dal report: colonne di ``performance.settle`` (anche per tempo) e fonte."""
    header: str
    home: str | None
    away: str | None
    competition: str = ""
    when: datetime | None = None
    values: dict[str, int] = field(default_factory=dict)
    source: str | None = None
    error: str = ""

    @property
    def label(self) -> str:
        return f"{self.home} - {self.away}" if self.home and self.away else self.header

    def result_row(self) -> dict:
        """Riga per ``performance.find_result``/``settle``; punti cartellini con la regola della configurazione."""
        return {"date": self.when.replace(hour=0, minute=0) if self.when else None, "home_team": self.home,
                "away_team": self.away, "source": self.source, **self.values}

    @property
    def has_halves(self) -> bool:
        return all(key in self.values for key in ("home_corners_1t", "away_corners_1t", "home_yellows_1t", "away_yellows_1t"))


def parse_outcomes(text: str) -> list[OutcomeBlock]:
    """Blocchi «ESITO: Casa - Ospite | competizione | data»; senza fonte o senza risultato il blocco ha ``error``."""
    from performance import split_match

    blocks = []
    for header in _OUTCOME.finditer(text):
        body = text[header.end():_end(text, header.start())]
        parts = [part.strip().strip("*_").strip() for part in header["body"].split("|")]
        teams = split_match(parts[0].strip("*_ "))
        block = OutcomeBlock(header=header.group(0).strip().strip("*_# >").strip(), home=teams[0] if teams else None,
                             away=teams[1] if teams else None,
                             competition=parts[1] if len(parts) > 1 and not _DATE.fullmatch(parts[1]) else "",
                             when=_when(" | ".join(parts[1:])))
        for raw in body.splitlines():
            key, _, value = raw.strip().strip("`*-").strip().partition(":")
            key = key.strip().lower().replace(" ", "_").replace("°", "")
            if key == "fonte":
                url = _URL.search(value)
                block.source = url.group(0).rstrip(").,;") if url else block.source
                continue
            pair = re.fullmatch(r"\s*(\d+)\s*[-–:]\s*(\d+)\s*", value)
            columns = OUTCOME_FIELDS.get(key)
            if columns and pair:
                block.values[columns[0]], block.values[columns[1]] = int(pair[1]), int(pair[2])
        if teams is None:
            block.error = "squadre non leggibili (atteso «Casa - Ospite»)"
        elif block.when is None:
            block.error = "manca la data"
        elif block.source is None:
            block.error = "senza fonte con link: ignorato"
        elif "home_goals" not in block.values:
            block.error = "manca il risultato finale"
        blocks.append(block)
    return blocks


def parse_profiles(text: str, day: date | None = None):
    """Profili tattici del report (parser della fase Q), con origine «Analista» e la data del report."""
    from tactical_sheets import parse_profiles as parse_one

    sheets, warnings = [], []
    for found in _PROFILE.finditer(text):
        part, part_warnings = parse_one(text[found.start():_end(text, found.start())], origin="Analista", day=day)
        sheets += part
        warnings += part_warnings
    return sheets, warnings


@dataclass
class FullReport:
    matches: list[ReportBlock]
    outcomes: list[OutcomeBlock]
    profiles: list
    warnings: list[str]


def parse_full(text: str, day: date | None = None) -> FullReport:
    profiles, warnings = parse_profiles(text, day)
    return FullReport(parse_report(text), parse_outcomes(text), profiles, warnings)


def fill_registry(rows: Sequence[dict], outcomes: Sequence[OutcomeBlock], today: date | None = None) -> tuple[list[dict], int]:
    """Esiti mancanti delle righe del registro dai blocchi ESITO validi (mai sovrascritti), fonte e data in Note.

    Restituisce le righe cambiate (complete, da salvare) e quante selezioni hanno ricevuto l'esito."""
    import pandas as pd

    from performance import fill_from_results, read_registry
    from prediction_log import to_excel

    valid = [block for block in outcomes if not block.error]
    if not rows or not valid:
        return [], 0
    frame = read_registry(to_excel(rows)).frame
    changed: dict[str, dict] = {}
    count = 0
    for block in valid:
        results = pd.DataFrame([block.result_row()])
        results["date"] = pd.to_datetime(results["date"])
        report = fill_from_results(frame, results, source=f"Analista ({block.source})", today=today)
        frame = report.frame
        count += report.outcomes
        for change in report.changes:
            changed[change["ID"]] = change
    by_id = {row["ID"]: dict(row) for row in rows}
    out = []
    for row_id, change in changed.items():
        row = by_id[row_id]
        row.update({key: value for key, value in change.items() if key in ("Esito", "Note", "Quota_chiusura")})
        out.append(row)
    return out, count


def fill_slips(slips: Sequence[dict], outcomes: Sequence[OutcomeBlock]) -> tuple[list[dict], int]:
    """Gambe in attesa delle schedine salvate, con gli esiti dei blocchi ESITO validi."""
    import pandas as pd

    from slips import Slip, update_from_results

    valid = [block for block in outcomes if not block.error]
    updated, count = [], 0
    for data in slips:
        slip = Slip.from_dict(data)
        for block in valid:
            results = pd.DataFrame([block.result_row()])
            results["date"] = pd.to_datetime(results["date"])
            count += update_from_results(slip, results, source=f"Analista ({block.source})")
        updated.append(slip.to_dict())
    return updated, count


def merge_profiles(saved: Sequence[dict], profiles: Sequence) -> tuple[list[dict], list[dict], list]:
    """Profili del report sopra le schede salvate: (schede aggiornate senza cambi di valore, cambi da confermare,
    profili in attesa di conferma)."""
    from tactical_sheets import find_sheet, merge_profile, upsert

    sheets = [dict(item) for item in saved]
    pending_changes, pending = [], []
    for profile in profiles:
        merged, changes = merge_profile(find_sheet(sheets, profile.team), profile)
        if changes:
            pending_changes += changes
            pending.append(merged)
        else:
            sheets = upsert(sheets, [merged])
    return sheets, pending_changes, pending
