"""Adattatore The Odds API: le risposte (campionato o evento) diventano ``QuoteMercato`` per bookmaker.

Le chiamate a crediti stanno in ``quotes.collect``; qui si legge solo il JSON già scaricato."""

from __future__ import annotations

from typing import Any, Mapping

from quotes.model import QuoteMercato


def from_event(event: Mapping[str, Any], *, fetched_at: str) -> list[QuoteMercato]:
    from datasources.oddsapi import quotes_frame

    partita = f"{event.get('home_team', '')} - {event.get('away_team', '')}"
    frame = quotes_frame(event)
    return [QuoteMercato(partita, row.key, None if row.point is None or row.point != row.point else str(row.point),
                         row.key, float(row.price), str(row.bookmaker), "The Odds API", str(row.last_update or fetched_at))
            for row in frame.itertuples()]
