"""«I miei mercati» (fase Z): i mercati che l'utente guarda sempre, per partita e in una tabella unica della giornata.

Probabilità sempre (dalla simulazione); quota, bookmaker, quota equa ed EV solo se la quota è nell'archivio della
giornata (``day_archive.engine_odds``: la stessa quota vista in Oggi, nella pagina Partita e nel registro).
"""

from __future__ import annotations

from typing import Iterable, Mapping

FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1X2", ("1", "X", "2")),
    ("GG/NG", ("Goal", "No Goal")),
    ("U/O goal", ("Over 1.5 gol", "Under 1.5 gol", "Over 2.5 gol", "Under 2.5 gol", "Over 3.5 gol", "Under 3.5 gol")),
    ("U/O corner", ("Over 8.5 corner", "Under 8.5 corner", "Over 9.5 corner", "Under 9.5 corner", "Over 10.5 corner",
                    "Under 10.5 corner")),
    ("U/O cartellini", ("Over 3.5 cartellini", "Under 3.5 cartellini", "Over 4.5 cartellini", "Under 4.5 cartellini",
                        "Over 5.5 cartellini", "Under 5.5 cartellini")),
    ("Cartellini per squadra", ("Casa Over 1.5 cartellini", "Casa Under 1.5 cartellini", "Ospite Over 1.5 cartellini",
                                "Ospite Under 1.5 cartellini")),
    ("Multigol casa", ("Multigol Casa 1-2", "Multigol Casa 1-3", "Multigol Casa 2-3")),
    ("Multigol ospite", ("Multigol Ospite 1-2", "Multigol Ospite 1-3", "Multigol Ospite 2-3")),
    ("Primo tempo", ("1 1T", "X 1T", "2 1T", "Over 0.5 gol 1T", "Under 0.5 gol 1T", "Over 1.5 gol 1T", "Under 1.5 gol 1T")),
)
COLUMNS = ("Partita", "Famiglia", "Selezione", "Prob %", "Quota", "Bookmaker", "Quota equa", "EV %")
EXACT_TOP = 5


def rows_for(match: str, result: Mapping, quotes: Mapping[str, Mapping] | None = None) -> list[dict]:
    """Righe di una partita; ``quotes`` = ``day_archive.consolidated`` (mercato -> quota consolidata)."""
    quotes = quotes or {}
    final = result["components"]["finale"]
    rows = []

    def add(family: str, key: str, probability: float | None) -> None:
        quote = quotes.get(key)
        price = getattr(quote, "quota", None) if quote is not None else None
        fair = round(100.0 / probability, 2) if probability else None
        rows.append({"Partita": match, "Famiglia": family, "Selezione": key,
                     "Prob %": None if probability is None else round(float(probability), 1),
                     "Quota": price, "Bookmaker": getattr(quote, "riferimento", None) if quote is not None else None,
                     "Quota equa": fair,
                     "EV %": round((probability / 100.0 * price - 1.0) * 100.0, 1) if price and probability else None})

    for family, keys in FAMILIES:
        for key in keys:
            add(family, key, final.get(key))
    exact = sorted((result.get("exact_scores") or {}).get("finale", {}).items(), key=lambda item: -item[1])[:EXACT_TOP]
    for score, probability in exact:
        add("Risultati esatti", score, probability)
    return rows


def day_rows(items: Iterable[tuple[str, Mapping, Mapping]]) -> list[dict]:
    """Tabella unica della giornata: (partita, risultato, quote consolidate) per ogni partita analizzata."""
    rows = []
    for match, result, quotes in items:
        rows += rows_for(match, result, quotes)
    return rows
