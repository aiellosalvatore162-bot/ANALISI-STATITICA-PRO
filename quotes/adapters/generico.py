"""Adattatore generico: righe con etichette note (1, X, 2, 1X, X2, 12, OVER/UNDER x.5, GG/NG) di qualsiasi
bookmaker, con il nome del bookmaker indicato dall'utente. Le righe sconosciute non diventano quote."""

from __future__ import annotations

from quotes.model import QuoteMercato, now_iso
from quotes.pages import generic_pairs


def from_text(text: str, partita: str, bookmaker: str, *, ora: str | None = None) -> list[QuoteMercato]:
    if not bookmaker.strip():
        raise ValueError("Formato generico: indica il nome del bookmaker.")
    ora = ora or now_iso()
    return [QuoteMercato(partita, market, None, label, price, bookmaker.strip(), "incollata", ora)
            for label, market, price in generic_pairs(text)]
