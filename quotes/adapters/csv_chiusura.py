"""Adattatore delle quote di chiusura dei CSV football-data.co.uk (gratis): 1X2 e Over/Under 2.5, media dei
bookmaker di chiusura. Servono al CLV nella pagina Prestazioni e, prima della partita, non esistono ancora."""

from __future__ import annotations

from typing import Any, Mapping

from quotes.model import QuoteMercato

COLUMNS = {"close_home": "1", "close_draw": "X", "close_away": "2", "close_over25": "Over 2.5 gol",
           "close_under25": "Under 2.5 gol"}


def from_row(row: Mapping[str, Any], *, read_at: str) -> list[QuoteMercato]:
    partita = f"{row.get('home_team', '')} - {row.get('away_team', '')}"
    quotes = []
    for column, market in COLUMNS.items():
        value = row.get(column)
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price == price and price > 1.0:
            quotes.append(QuoteMercato(partita, market, None, market, price, "chiusura media", "CSV football-data.co.uk", read_at))
    return quotes
