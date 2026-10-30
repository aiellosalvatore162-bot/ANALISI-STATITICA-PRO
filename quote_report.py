"""Report quote partita × mercato (fase Z2): legge solo l'archivio unico della giornata, non riscarica e non calcola.

Righe = partite selezionate, colonne = i mercati di «I miei mercati». Ogni cella è ✓ (quota, bookmaker, fonte, ora di
lettura) oppure ✗ con il motivo. Da qui escono anche la lista «Da incollare a mano» e il riepilogo (quote per fonte e
bookmaker, partite complete, crediti dal registro della raccolta). Nessuna chiamata a crediti, nessuna simulazione.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
import re
from typing import Iterable, Mapping, Sequence

import day_archive
from my_markets import FAMILIES

EXACT_FAMILY = "Risultati esatti"
EXACT_KEY = "Risultati esatti (almeno una quota)"
EXACT_PATTERN = re.compile(r"^\d+-\d+$")
LEVEL_A = {"1X2", "U/O goal", "GG/NG"}
LEVEL_B = {"U/O corner", "U/O cartellini", "Primo tempo"}
NOT_OFFERED = {"Cartellini per squadra", "Multigol casa", "Multigol ospite", EXACT_FAMILY}
SKIP_REASONS = ("non offerto", "spento", "solo per evento")
SHEET_FIXED = ("Partita", "Da giocare")


def columns() -> list[tuple[str, str]]:
    """(famiglia, chiave di colonna) nell'ordine di «I miei mercati»; i risultati esatti sono una colonna sola."""
    return [(family, key) for family, keys in FAMILIES for key in keys] + [(EXACT_FAMILY, EXACT_KEY)]


@dataclass(frozen=True)
class Cell:
    ok: bool
    text: str                    # «✓ 2.05 · Pinnacle · The Odds API · 10:20» oppure «✗ sospesa»
    quota: float | None = None
    bookmaker: str = ""
    fonte: str = ""
    ora: str = ""
    motivo: str = ""


@dataclass
class Row:
    key: str
    partita: str
    da_giocare: bool
    cells: dict[str, Cell] = field(default_factory=dict)

    @property
    def missing(self) -> list[str]:
        return [column for column, cell in self.cells.items() if not cell.ok]

    @property
    def complete(self) -> bool:
        return not self.missing


def _hour(text: str | None) -> str:
    try:
        return datetime.fromisoformat(text).strftime("%H:%M") if text else ""
    except (TypeError, ValueError):
        return ""


def _has_paste(entry: Mapping, quotes: Sequence) -> bool:
    return bool(entry.get("pages")) or any(quote.fonte == "incollata" for quote in quotes)


def _failure(not_collected: Iterable[Mapping], partita: str, level: str) -> str:
    for row in not_collected:
        motivo = str(row.get("Motivo", ""))
        if row.get("Partita") == partita and row.get("Livello") == level and not any(word in motivo for word in SKIP_REASONS):
            return motivo
    return ""


def _reason(family: str, entry: Mapping, quotes: Sequence, suspended: bool, not_collected: Iterable[Mapping]) -> str:
    partita = f"{entry['home']} - {entry['away']}"
    pasted = _has_paste(entry, quotes)
    if suspended:
        return "sospesa dal bookmaker"
    if family in NOT_OFFERED:
        return "assente nella pagina incollata" if pasted else "mercato non offerto da The Odds API: da incollare"
    level = "A" if family in LEVEL_A else "B"
    failure = _failure(not_collected, partita, level)
    if pasted and not failure:
        return "assente nella pagina incollata"
    if failure:
        return f"non raccolta: {failure}"
    if family == "GG/NG":
        return "non raccolta: GG/NG solo per evento (spento in config/odds_api.json)"
    if level == "B" and not entry.get("to_play"):
        return "fuori livello B (partita non «Da giocare»)"
    return f"non raccolta (livello {level})"


def _cell(family: str, key: str, entry: Mapping, quotes: Sequence, consolidated: Mapping, not_collected) -> Cell:
    if key == EXACT_KEY:
        priced = [quote for quote in quotes if quote.mercato and EXACT_PATTERN.match(quote.mercato) and quote.quota is not None]
        suspended = not priced and any(quote.mercato and EXACT_PATTERN.match(quote.mercato) for quote in quotes)
        if priced:
            return _good(f"{len(priced)} punteggi", None, priced)
    else:
        item = consolidated.get(key)
        contributing = [quote for quote in quotes if quote.mercato == key and quote.quota is not None]
        if item is not None and contributing:
            chosen = [quote for quote in contributing if quote.bookmaker == item.bookmaker] or contributing
            return _good(item.riferimento, item.quota, chosen)
        suspended = any(quote.mercato == key and quote.quota is None for quote in quotes)
    motivo = _reason(family, entry, quotes, suspended, not_collected)
    return Cell(False, f"✗ {motivo}", motivo=motivo)


def _good(label: str, price: float | None, chosen: Sequence) -> Cell:
    fonte = " / ".join(sorted({quote.fonte for quote in chosen}))
    ora = max((_hour(quote.ora_lettura) for quote in chosen), default="")
    bookmaker = label
    head = f"{price:.2f} · " if price is not None else ""
    return Cell(True, f"✓ {head}{bookmaker} · {fonte}" + (f" · {ora}" if ora else ""), price, bookmaker, fonte, ora)


def build(archive: Mapping, not_collected: Iterable[Mapping] = ()) -> list[Row]:
    """Una riga per partita selezionata, le «Da giocare» per prime."""
    not_collected = list(not_collected)
    entries = day_archive.selected(archive)
    entries = [e for e in entries if e.get("to_play")] + [e for e in entries if not e.get("to_play")]
    rows = []
    for entry in entries:
        quotes = day_archive.quotes_of(entry)
        consolidated = day_archive.consolidated(entry)
        row = Row(entry["key"], f"{entry['home']} - {entry['away']}", bool(entry.get("to_play")))
        for family, key in columns():
            row.cells[key] = _cell(family, key, entry, quotes, consolidated, not_collected)
        rows.append(row)
    return rows


def table(rows: Iterable[Row]) -> list[dict]:
    """Righe per il foglio e la tabella: Partita, Da giocare, una colonna per mercato."""
    return [{"Partita": row.partita, "Da giocare": "sì" if row.da_giocare else "",
             **{key: cell.text for key, cell in row.cells.items()}} for row in rows]


def sheet_columns() -> list[str]:
    return [*SHEET_FIXED, *(key for _, key in columns())]


# --- Da incollare a mano --------------------------------------------------------------------------------------

def suggested_bookmakers(archive: Mapping, rows: Iterable[Row]) -> dict[str, str]:
    """Per mercato, il bookmaker che l'ha già offerto più volte per altre partite selezionate."""
    keys = {row.key for row in rows}
    counts: dict[str, Counter] = {}
    for key, entry in archive.items():
        if key not in keys:
            continue
        for quote in day_archive.quotes_of(entry):
            if quote.quota is None:
                continue
            market = EXACT_KEY if quote.mercato and EXACT_PATTERN.match(quote.mercato) else quote.mercato
            if market:
                counts.setdefault(market, Counter())[quote.bookmaker] += 1
    return {market: counter.most_common(1)[0][0] for market, counter in counts.items()}


def to_paste(archive: Mapping, rows: Sequence[Row]) -> list[dict]:
    """Mercati ✗ per partita (prima le «Da giocare»), con motivo e bookmaker suggerito."""
    suggested = suggested_bookmakers(archive, rows)
    family_of = {key: family for family, key in columns()}
    result = []
    for row in rows:
        for key in row.missing:
            result.append({"Partita": row.partita, "Da giocare": row.da_giocare, "Famiglia": family_of[key], "Mercato": key,
                           "Motivo": row.cells[key].motivo, "Bookmaker suggerito": suggested.get(key, "")})
    return result


def paste_text(items: Sequence[Mapping]) -> str:
    """Testo copiabile: una partita per blocco, i mercati mancanti raggruppati per famiglia."""
    lines: list[str] = []
    for partita in dict.fromkeys(item["Partita"] for item in items):
        mine = [item for item in items if item["Partita"] == partita]
        lines.append(f"{partita}" + (" (Da giocare)" if mine[0]["Da giocare"] else ""))
        for family in dict.fromkeys(item["Famiglia"] for item in mine):
            entries = [item for item in mine if item["Famiglia"] == family]
            names = ", ".join(item["Mercato"] for item in entries)
            hint = {item["Bookmaker suggerito"] for item in entries if item["Bookmaker suggerito"]}
            lines.append(f"  {family}: {names}" + (f" [suggerito: {', '.join(sorted(hint))}]" if hint else ""))
        lines.append("")
    return "\n".join(lines).strip()


# --- Riepilogo ------------------------------------------------------------------------------------------------

def summary(archive: Mapping, rows: Sequence[Row], ledger: Iterable[Mapping] = (), today: date | None = None,
            budget: int = 500) -> dict:
    """Quote per fonte e bookmaker, partite complete, crediti di oggi e del mese dal registro, proiezione a 30 giorni."""
    from quotes.collect import projection

    today = today or date.today()
    keys = {row.key for row in rows}
    sources, bookmakers = Counter(), Counter()
    for key, entry in archive.items():
        if key in keys:
            for quote in day_archive.quotes_of(entry):
                if quote.quota is not None:
                    sources[quote.fonte] += 1
                    bookmakers[quote.bookmaker] += 1
    spent_today = spent_month = 0
    level = Counter()
    for item in ledger:
        real = int(item.get("Reali") or 0)
        when = str(item.get("Data") or "")
        if when[:7] == today.isoformat()[:7]:
            spent_month += real
        if when == today.isoformat():
            spent_today += real
            level[str(item.get("Livello"))] += real
    return {"per_fonte": dict(sources), "per_bookmaker": dict(bookmakers),
            "complete": sum(row.complete for row in rows), "incomplete": sum(not row.complete for row in rows),
            "crediti_oggi": spent_today, "crediti_mese": spent_month, "residui_mese": budget - spent_month,
            "proiezione": projection(level["A"], level["B"], budget=budget)}
