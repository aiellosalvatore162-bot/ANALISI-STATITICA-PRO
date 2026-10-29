"""Modello neutro delle quote (fase Z).

``QuoteMercato`` è una quota letta da una fonte qualunque: partita, mercato (chiave evento di ``market_catalog``,
oppure ``None`` se il simulatore non la calcola), linea, selezione come scritta, quota (``None`` = sospesa, mai
zero), bookmaker, fonte (incollata / API / CSV / a mano) e ora di lettura.

Al motore va UNA quota per mercato (``consolidate``): quella del bookmaker «sharp» (Pinnacle o quelli in
``config/oggi.json``, ``bookmaker_sharp``) se c'è, altrimenti la mediana dei bookmaker. Uno scarto oltre
``SPREAD_LIMIT`` tra bookmaker sulla stessa selezione viene segnalato.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import statistics
from typing import Iterable, Mapping

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "oggi.json"
SPREAD_LIMIT = 0.05
DEFAULT_SHARP = ("pinnacle",)


@dataclass(frozen=True)
class QuoteMercato:
    partita: str                 # «Casa - Ospite» come letta dalla fonte
    mercato: str | None          # chiave evento del catalogo (None = non simulato)
    linea: str | None
    selezione: str               # etichetta come nella fonte
    quota: float | None          # None = sospesa (mai zero)
    bookmaker: str
    fonte: str                   # «incollata», «The Odds API», «CSV football-data.co.uk», «a mano»
    ora_lettura: str             # ISO

    def __post_init__(self) -> None:
        if self.quota is not None and self.quota <= 1.0:
            raise ValueError(f"Quota {self.quota} non valida per {self.selezione}: le sospese sono None, mai zero.")

    @property
    def simulata(self) -> bool:
        return self.mercato is not None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping) -> "QuoteMercato":
        return cls(**{key: data.get(key) for key in cls.__dataclass_fields__})


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sharp_bookmakers(path: Path = CONFIG_PATH) -> tuple[str, ...]:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    names = data.get("bookmaker_sharp") or DEFAULT_SHARP
    return tuple(str(name).lower() for name in names)


@dataclass(frozen=True)
class Consolidated:
    mercato: str
    quota: float
    riferimento: str             # «Pinnacle», «mediana di 3 bookmaker», «Eurobet»
    bookmaker: str               # bookmaker della quota usata (o «mediana»)
    quote: dict                  # bookmaker -> quota
    scarto: float                # (max − min) / min tra bookmaker
    avviso: str = ""


def consolidate(quotes: Iterable[QuoteMercato], sharp: Iterable[str] | None = None) -> dict[str, Consolidated]:
    """Una quota per mercato: sharp se c'è, altrimenti mediana; scarto oltre il 5% segnalato. Sospese escluse."""
    sharp = tuple(name.lower() for name in (sharp if sharp is not None else sharp_bookmakers()))
    by_market: dict[str, dict[str, float]] = {}
    for quote in quotes:
        if quote.mercato is None or quote.quota is None:
            continue
        by_market.setdefault(quote.mercato, {})[quote.bookmaker] = quote.quota   # per bookmaker vale l'ultima lettura
    result = {}
    for market, prices in by_market.items():
        sharp_name = next((name for name in prices if name.lower() in sharp), None)
        if sharp_name is not None:
            price, label, book = prices[sharp_name], sharp_name.title(), sharp_name
        elif len(prices) == 1:
            book, price = next(iter(prices.items()))
            label = book
        else:
            price, label, book = statistics.median(prices.values()), f"mediana di {len(prices)} bookmaker", "mediana"
        spread = (max(prices.values()) - min(prices.values())) / min(prices.values()) if len(prices) > 1 else 0.0
        warning = (f"scarto {spread:.0%} tra bookmaker ({', '.join(f'{name} {value:.2f}' for name, value in sorted(prices.items()))})"
                   if spread > SPREAD_LIMIT else "")
        result[market] = Consolidated(market, round(float(price), 3), label, book, dict(prices), round(spread, 4), warning)
    return result


def engine_odds(quotes: Iterable[QuoteMercato], sharp: Iterable[str] | None = None) -> dict[str, float]:
    """Quote per il motore: una per mercato (vedi ``consolidate``)."""
    return {market: item.quota for market, item in consolidate(quotes, sharp).items()}
