"""Pagine incollate (fase Z): divisione, riconoscimento del formato, abbinamento alle partite selezionate.

- ``split_pages``: una pagina comincia con un titolo «Casa - Ospite» seguito (righe vuote a parte) da una riga
  «gg/mm hh:mm»; l'anno è quello che porta la data più vicina a oggi, entro ±7 giorni (altrimenti data non letta).
  Le righe prima del primo titolo (menu) e quelle da un piè di pagina in poi sono scartate; le voci di menu note
  sono tolte anche dentro le pagine.
- ``detect_format``: «eurobet» (titoli di sezione Eurobet e un token per riga), «generico» (etichette note con la
  quota sulla stessa riga o sulla successiva), altrimenti «sconosciuto»: mai indovinato.
- ``assign_pages``: squadre con ``names.match_team`` e data ±1 giorno; se più partite restano possibili vince
  quella entro ±3 ore, se anche così non è unica la pagina è «ambigua» (si sceglie a mano). Mai un'assegnazione
  silenziosa di una pagina ambigua.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import re
from typing import Iterable, Sequence

_DATE_LINE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})\s+(\d{1,2})[:.](\d{2})\s*$")
_TITLE = re.compile(r"^\s*(?P<home>[^\d\s|][^|]*?\S)\s+-\s+(?P<away>\S[^|]*?)\s*$")
_QUOTE = re.compile(r"^\d+[.,]\d{2}$")
# Piè di pagina: da qui in poi la pagina finisce. Menu: righe isolate da togliere ovunque.
FOOTER = re.compile(r"^(©|copyright\b|gioco responsabile|il gioco è vietato|gioco vietato ai minori|termini e condizioni|"
                    r"privacy|cookie|adm\b|aams\b|concessione|assistenza clienti|scarica l'app|seguici)", re.IGNORECASE)
MENU = {"home", "sport", "live", "scommesse", "casino", "casinò", "casino live", "poker", "bingo", "virtual", "virtuali",
        "lotterie", "promozioni", "accedi", "registrati", "cerca", "calcio", "tennis", "basket", "il mio conto",
        "schedina", "carrello", "menu", "scommesse sportive", "i miei mercati", "tutti", "antepost", "statistiche"}
STATUS_MATCHED, STATUS_AMBIGUOUS, STATUS_MISSING = "abbinata", "ambigua", "non trovata"


@dataclass
class Page:
    title: str
    home: str
    away: str
    when: datetime | None
    body: str                      # righe dopo la data (menu e piè di pagina tolti)
    date_text: str = ""
    format: str = "sconosciuto"
    warnings: list[str] = field(default_factory=list)


def _year_for(day: int, month: int, today: date) -> date | None:
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    best = min(candidates, key=lambda value: abs((value - today).days), default=None)
    return best if best is not None and abs((best - today).days) <= 7 else None


def _next_nonempty(lines: Sequence[str], start: int) -> int | None:
    for index in range(start, len(lines)):
        if lines[index].strip():
            return index
    return None


def split_pages(text: str, today: date | None = None) -> list[Page]:
    """Pagine dell'incolla, nell'ordine; il testo prima del primo titolo (menu) è scartato."""
    today = today or date.today()
    lines = text.splitlines()
    starts = []
    for index, line in enumerate(lines):
        title = _TITLE.match(line)
        following = _next_nonempty(lines, index + 1)
        if title and following is not None and _DATE_LINE.match(lines[following]) and not _QUOTE.match(line.strip()):
            starts.append((index, following))
    pages = []
    for position, (title_index, date_index) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = []
        for line in lines[date_index + 1:end]:
            clean = line.strip()
            if FOOTER.match(clean):
                break
            if clean.casefold() in MENU:
                continue
            body.append(line)
        match = _TITLE.match(lines[title_index])
        day, month, hour, minute = (int(value) for value in _DATE_LINE.match(lines[date_index]).groups())
        page = Page(lines[title_index].strip(), match["home"].strip(), match["away"].strip(), None, "\n".join(body).strip(),
                    lines[date_index].strip())
        found = _year_for(day, month, today)
        if found is None:
            page.warnings.append(f"data «{page.date_text}» lontana più di 7 giorni da oggi: non letta")
        else:
            page.when = datetime(found.year, found.month, found.day, hour, minute)
        page.format = detect_format(page.body)
        pages.append(page)
    return pages


# --- Formato ----------------------------------------------------------------------------------------------

GENERIC_LABELS = {
    "1": "1", "x": "X", "2": "2", "1x": "1X", "x2": "X2", "12": "12",
    "gg": "Goal", "goal": "Goal", "ng": "No Goal", "no goal": "No Goal", "nogoal": "No Goal",
}
_GENERIC_TOTAL = re.compile(r"^(over|under)\s+(\d+[.,]5)$", re.IGNORECASE)


def generic_market(label: str) -> str | None:
    """Etichetta di un bookmaker qualunque -> chiave del catalogo (solo etichette note)."""
    text = re.sub(r"\s+", " ", label.strip()).casefold()
    if text in GENERIC_LABELS:
        return GENERIC_LABELS[text]
    total = _GENERIC_TOTAL.match(text)
    if total:
        return f"{total[1].title()} {total[2].replace(',', '.')} gol"
    return None


def generic_pairs(body: str) -> list[tuple[str, str, float | None]]:
    """(etichetta, mercato, quota) dalle righe «ETICHETTA quota» o «ETICHETTA» + «quota» sulla riga dopo.

    Un'etichetta nota senza quota subito dopo è una quota sospesa (None)."""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    pairs = []
    index = 0
    while index < len(lines):
        line = lines[index]
        inline = re.match(r"^(.*?\S)\s+(\d+[.,]\d{2})$", line)
        if inline and generic_market(inline[1]):
            pairs.append((inline[1], generic_market(inline[1]), float(inline[2].replace(",", "."))))
            index += 1
            continue
        market = generic_market(line)
        if market is not None:
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if _QUOTE.match(following):
                pairs.append((line, market, float(following.replace(",", "."))))
                index += 2
                continue
            pairs.append((line, market, None))
        index += 1
    return pairs


def detect_format(body: str) -> str:
    from eurobet import _spec_for

    lines = [line.strip() for line in body.splitlines() if line.strip()]
    sections = sum(1 for line in lines if _spec_for(line) is not None)
    tokens = sum(1 for line in lines if _QUOTE.match(line))
    if sections >= 1 and tokens >= 2:
        return "eurobet"
    if len([pair for pair in generic_pairs(body) if pair[2] is not None]) >= 2:
        return "generico"
    return "sconosciuto"


# --- Abbinamento ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Target:
    key: str
    home: str
    away: str
    when: datetime | None


@dataclass
class Assignment:
    index: int
    title: str
    when: datetime | None
    status: str
    key: str | None = None
    candidates: list[str] = field(default_factory=list)
    message: str = ""


def _naive(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment


def assign_pages(pages: Sequence[Page], targets: Iterable[Target]) -> list[Assignment]:
    from datasources.names import match_team

    targets = list(targets)
    result = []
    for index, page in enumerate(pages):
        when = _naive(page.when)
        same_teams = [target for target in targets
                      if match_team(page.home, [target.home]) and match_team(page.away, [target.away])]
        if when is not None:
            same_teams = [target for target in same_teams
                          if target.when is None or abs((_naive(target.when).date() - when.date()).days) <= 1]
        if len(same_teams) > 1 and when is not None:
            close = [target for target in same_teams
                     if target.when is not None and abs(_naive(target.when) - when) <= timedelta(hours=3)]
            same_teams = close if len(close) == 1 else same_teams
        if len(same_teams) == 1:
            note = "" if when is not None else "data non letta: controlla che sia la partita giusta"
            result.append(Assignment(index, page.title, page.when, STATUS_MATCHED, same_teams[0].key, message=note))
        elif same_teams:
            result.append(Assignment(index, page.title, page.when, STATUS_AMBIGUOUS, None, [t.key for t in same_teams],
                                     "più partite possibili: scegli quella giusta"))
        else:
            result.append(Assignment(index, page.title, page.when, STATUS_MISSING, None,
                                     message="nessuna partita selezionata con queste squadre e questa data"))
    return result
