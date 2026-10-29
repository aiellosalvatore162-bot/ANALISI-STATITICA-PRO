"""Adattatore Eurobet: avvolge ``eurobet.parse_eurobet`` (formato a un token per riga) senza un secondo parser.

Quota sospesa (etichetta senza numero dopo) = ``None``. Voci senza campo nel simulatore: ``mercato=None``
(«non simulate»). I risultati esatti e i loro gruppi («1-0», «1-0/2-0/2-1») restano come mercato: il simulatore
li calcola dalla distribuzione dei punteggi.
"""

from __future__ import annotations

from eurobet import DUPLICATE, NOT_SIMULATED, OK, SUSPENDED, EurobetPaste, parse_eurobet
from quotes.model import QuoteMercato, now_iso

BOOKMAKER = "Eurobet"


def from_paste(paste: EurobetPaste, partita: str, *, fonte: str = "incollata", ora: str | None = None) -> list[QuoteMercato]:
    ora = ora or now_iso()
    quotes = []
    for item in paste.quotes:
        if item.status == DUPLICATE:
            continue
        market = item.market if item.status in (OK, SUSPENDED) else None
        price = None if item.status == SUSPENDED or item.price is None else float(item.price)
        quotes.append(QuoteMercato(partita, market, item.line, item.selection, price, BOOKMAKER, fonte, ora))
    return quotes


def from_text(text: str, partita: str, *, ora: str | None = None) -> tuple[list[QuoteMercato], EurobetPaste]:
    paste = parse_eurobet(text)
    return from_paste(paste, partita, ora=ora), paste


def not_simulated(quotes: list[QuoteMercato]) -> list[str]:
    return [f"{quote.selezione}{f' {quote.linea}' if quote.linea else ''}" for quote in quotes if quote.mercato is None]


__all__ = ["BOOKMAKER", "from_paste", "from_text", "not_simulated", "NOT_SIMULATED"]
