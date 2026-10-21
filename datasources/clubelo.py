"""Elo di ClubElo dalle pagine del sito.

L'API ``api.clubelo.com`` (usata anche da soccerdata) risponde 502; le pagine
``clubelo.com/<Squadra>`` contengono invece lo storico datato del rating. Il
punto con data D è il rating *dopo* la partita del giorno D, quindi l'Elo
pre-partita è l'ultimo punto con data precedente alla partita.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re

from datasources.cache import SourceCache
from datasources.names import match_team


BASE_URL = "https://clubelo.com"
CATALOG_PAGES = ("", "ENG", "ITA", "ESP", "GER", "FRA")
# Paesi delle squadre più frequenti nelle coppe europee: caricati solo se serve.
EXTRA_CATALOG_PAGES = ("POR", "NED", "BEL", "TUR", "GRE", "SCO", "AUT", "SUI", "CZE", "DEN", "NOR", "SWE",
                       "CRO", "SRB", "UKR", "POL", "SVK", "CYP", "ISR", "HUN", "ROM", "BUL", "SLO", "RUS",
                       "AZE", "KAZ", "MDA", "ARM", "GEO", "BLR", "FIN", "IRL", "NIR", "WAL", "ISL", "EST", "LVA",
                       "LTU", "ALB", "MKD", "MNE", "BIH", "KOS", "LUX", "MLT", "FRO", "AND", "SMR", "GIB")
_NAVIGATION = {"Ranking", "Fixtures", "Results", "Clubs", "System", "Blog", "Contact", "Links", "Twitter", "API"}
_LINK = re.compile(r'href="/([A-Za-z][A-Za-z0-9-]+)"[^>]*>(.*?)</a>', re.S)
_POINT = re.compile(r'"Date":\s*"(\d{4}-\d{2}-\d{2})T00:00:00",\s*"Elo":\s*([0-9.]+)')


@dataclass(frozen=True)
class EloRating:
    team: str
    slug: str
    value: float
    as_of: date
    source: str
    url: str
    warning: str | None = None
    updated: object = None  # datetime del download (o della cache)
    latest_match: date | None = None  # ultima partita giocata (qualsiasi competizione)


def _clean(text: str) -> str:
    """Nome completo: le pagine ripetono il nome in più span (sigla, nome)."""
    spans = [value.strip() for value in re.findall(r"<span[^>]*>([^<]*)</span>", text) if value.strip()]
    if spans:
        return max(spans, key=len)
    return re.sub(r"<[^>]+>", "", text).strip()


def parse_catalog(html: str) -> dict[str, str]:
    """Slug -> nome visualizzato per ogni club linkato nella pagina."""
    catalog: dict[str, str] = {}
    for slug, label in _LINK.findall(html):
        # I link ai paesi (es. /GRE) contengono la bandiera: non sono club.
        if slug in _NAVIGATION or "<img" in label:
            continue
        catalog.setdefault(slug, _clean(label) or slug)
    return catalog


def parse_history(html: str) -> list[tuple[date, float]]:
    points = {date.fromisoformat(day): float(value) for day, value in _POINT.findall(html)}
    return sorted(points.items())


def elo_before(history: list[tuple[date, float]], match_date: date) -> tuple[date, float] | None:
    """Rating valido prima della partita: ultimo punto con data < ``match_date``."""
    previous = [point for point in history if point[0] < match_date]
    return previous[-1] if previous else None


class ClubElo:
    def __init__(self, cache: SourceCache) -> None:
        self.cache = cache
        self.warnings: list[str] = []

    def _page_catalog(self, page: str) -> dict[str, str]:
        result = self.cache.get(f"{BASE_URL}/{page}", source="clubelo", max_age=timedelta(days=7))
        if result.warning:
            self.warnings.append(result.warning)
        return parse_catalog(result.body.decode("utf-8", "ignore")) if result.ok else {}

    def catalog(self, pages=CATALOG_PAGES) -> dict[str, str]:
        catalog: dict[str, str] = {}
        for page in pages:
            for slug, label in self._page_catalog(page).items():
                catalog.setdefault(slug, label)
        return catalog

    @staticmethod
    def _find(team: str, catalog: dict[str, str]) -> str | None:
        by_label = match_team(team, list(catalog.values()))
        if by_label is not None:
            return next(slug for slug, label in catalog.items() if label == by_label)
        return match_team(team, list(catalog))

    def slug_for(self, team: str) -> str | None:
        catalog = self.catalog()
        found = self._find(team, catalog)
        for page in EXTRA_CATALOG_PAGES:
            if found is not None:
                break
            catalog.update({slug: label for slug, label in self._page_catalog(page).items() if slug not in catalog})
            found = self._find(team, catalog)
        return found

    def history(self, team: str, max_age: timedelta = timedelta(hours=12)) -> list[tuple[date, float]]:
        """Storico datato del rating (vuoto se la squadra non è su ClubElo)."""
        slug = self.slug_for(team)
        if slug is None:
            return []
        result = self.cache.get(f"{BASE_URL}/{slug}", source="clubelo", max_age=max_age)
        return parse_history(result.body.decode("utf-8", "ignore")) if result.ok else []

    def rating(self, team: str, match_date: date | None = None, max_age: timedelta = timedelta(hours=12)) -> EloRating | None:
        match_date = match_date or date.today()
        slug = self.slug_for(team)
        if slug is None:
            self.warnings.append(f"ClubElo: squadra «{team}» non trovata nel catalogo.")
            return None
        url = f"{BASE_URL}/{slug}"
        result = self.cache.get(url, source="clubelo", max_age=max_age)
        if not result.ok:
            self.warnings.append(result.warning or f"ClubElo: nessun dato per {team}.")
            return None
        history = parse_history(result.body.decode("utf-8", "ignore"))
        point = elo_before(history, match_date)
        if point is None:
            self.warnings.append(f"ClubElo: nessuno storico prima del {match_date:%d/%m/%Y} per {team} ({slug}).")
            return None
        return EloRating(
            team=team, slug=slug, value=round(point[1], 1), as_of=point[0], source="ClubElo", url=url,
            warning=result.warning, updated=result.fetched_at,
            latest_match=history[-1][0] if history else None,
        )
