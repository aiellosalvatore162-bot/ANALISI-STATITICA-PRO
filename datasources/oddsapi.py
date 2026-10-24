"""The Odds API v4: elenco partite, quote per campionato e per evento, punteggi.

Costi in crediti (documentazione ufficiale v4, letta il 23/10/2026; riepilogo in
``config/odds_api.json``): elenco sport ed elenco eventi gratuiti; quote per
campionato = mercati × regioni; quote per evento = mercati *restituiti* ×
regioni; punteggi = 1, oppure 2 con ``daysFrom``. Le risposte vuote non costano.

La chiave si legge solo da ``st.secrets["ODDS_API_KEY"]`` o dall'ambiente e non
entra mai negli URL salvati in cache, nei messaggi o nei log. Ogni risposta
passa dalla cache SQLite (30 minuti di default); i crediti rimasti arrivano
dall'intestazione ``x-requests-remaining`` e restano registrati nella tabella
``odds_api_usage``. Il budget è mensile (``budget_mensile``): avviso
all'80%, conferma esplicita oltre il 95%, blocco oltre il 100%. Ogni download di quote per campionato è salvato anche in
``odds_snapshots``: l'ultima istantanea prima del calcio d'inizio fa da quota
di chiusura per il registro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
import calendar
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

from datasources.cache import SourceCache


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "config" / "odds_api.json"
BASE_URL = "https://api.the-odds-api.com/v4"
SOURCE = "The Odds API"

# Etichette italiane e nome della competizione negli altri lettori (football-data.co.uk, registro).
COMPETITIONS = {
    "soccer_italy_serie_a": "Serie A",
    "soccer_epl": "Premier League",
    "soccer_spain_la_liga": "La Liga",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_france_ligue_one": "Ligue 1",
    "soccer_uefa_champs_league": "Champions League",
    "soccer_uefa_europa_league": "Europa League",
    "soccer_uefa_europa_conference_league": "Conference League",
    "soccer_portugal_primeira_liga": "Primeira Liga",
    "soccer_netherlands_eredivisie": "Eredivisie",
    "soccer_belgium_first_div": "Jupiler Pro League",
    "soccer_turkey_super_league": "Süper Lig",
    "soccer_greece_super_league": "Super League Grecia",
    "soccer_spl": "Premiership scozzese",
    "soccer_italy_serie_b": "Serie B",
    "soccer_efl_champ": "Championship",
    "soccer_germany_bundesliga2": "2. Bundesliga",
    "soccer_france_ligue_two": "Ligue 2",
    "soccer_spain_segunda_division": "Segunda División",
    "soccer_austria_bundesliga": "Bundesliga austriaca",
    "soccer_switzerland_superleague": "Super League svizzera",
    "soccer_denmark_superliga": "Superliga danese",
    "soccer_norway_eliteserien": "Eliteserien",
    "soccer_sweden_allsvenskan": "Allsvenskan",
    "soccer_poland_ekstraklasa": "Ekstraklasa",
}
# Campionati non europei: esclusi dall'elenco «altri campionati europei».
NON_EUROPEAN = ("argentina", "australia", "brazil", "chile", "china", "japan", "korea", "mexico", "usa", "saudi",
                "conmebol", "concacaf", "africa", "fifa", "copa", "libertadores", "sudamericana", "league_of_ireland")

# Mercati dell'API -> chiavi evento del motore (vedi ``market_catalog``).
_TOTALS = {"totals": " gol", "alternate_totals": " gol", "totals_h1": " gol 1T", "alternate_totals_h1": " gol 1T",
           "alternate_totals_corners": " corner", "alternate_totals_cards": " cartellini"}
# Linea principale e linee alternative dello stesso totale: un solo gruppo per linea.
_FAMILY = {"alternate_totals": "totals", "alternate_totals_h1": "totals_h1"}
MARKET_LABELS = {
    "h2h": "1X2", "totals": "Over/Under gol (linea principale)", "btts": "Goal/No Goal",
    "alternate_totals": "Over/Under gol (tutte le linee)", "alternate_totals_corners": "Corner totali",
    "alternate_totals_cards": "Cartellini totali", "h2h_h1": "1X2 primo tempo", "totals_h1": "Over/Under primo tempo",
    "btts_h1": "Goal/No Goal primo tempo",
}


class OddsApiError(RuntimeError):
    """Chiamata non riuscita (chiave assente o non valida, limite, rete) e nessun dato in cache."""


class BudgetExceeded(OddsApiError):
    """Il download supererebbe il budget mensile di crediti o i crediti rimasti."""


class BudgetConfirmationRequired(BudgetExceeded):
    """Il download porterebbe la spesa del mese oltre la soglia di conferma (95%): serve ``allow_high=True``."""


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def odds_api_key() -> str | None:
    """Chiave da ``st.secrets["ODDS_API_KEY"]`` o dall'ambiente; mai nel codice."""
    try:
        import streamlit as st

        key = st.secrets.get("ODDS_API_KEY")
        if key:
            return str(key)
    except Exception:  # nessun secrets.toml o fuori da Streamlit
        pass
    return os.environ.get("ODDS_API_KEY") or None


def competition_label(sport: str, title: str | None = None) -> str:
    return COMPETITIONS.get(sport, title or sport)


def is_european_soccer(sport: Mapping[str, Any]) -> bool:
    key = str(sport.get("key", ""))
    return (key.startswith("soccer_") and not sport.get("has_outrights")
            and not any(word in key for word in NON_EUROPEAN))


# --- Rete --------------------------------------------------------------------------------

Response = tuple[int, bytes, Mapping[str, str]]
Opener = Callable[[str, Mapping[str, str], float], Response]


def _requests_opener(url: str, params: Mapping[str, str], timeout: float) -> Response:
    response = requests.get(url, params=dict(params), timeout=timeout)
    return response.status_code, response.content, dict(response.headers)


@dataclass
class ApiResult:
    payload: Any
    fetched_at: datetime
    from_cache: bool
    cost: int = 0
    warnings: list[str] = field(default_factory=list)


class OddsApi:
    """Client con cache, registro dei crediti e controllo del budget mensile.

    ``opener`` e ``now`` sono iniettabili: i test usano risposte registrate.
    """

    def __init__(self, cache: SourceCache, key: str | None = None, *, settings: Mapping[str, Any] | None = None,
                 opener: Opener | None = None, now: Callable[[], datetime] | None = None, timeout: float = 25.0) -> None:
        self.cache = cache
        self.key = key
        self.settings = dict(settings or load_settings())
        self.opener = opener or _requests_opener
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.timeout = timeout
        with self.cache._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS odds_api_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    cost INTEGER NOT NULL,
                    used INTEGER,
                    remaining INTEGER
                );
                CREATE TABLE IF NOT EXISTS odds_snapshots (
                    event_id TEXT NOT NULL,
                    sport TEXT NOT NULL,
                    commence_time TEXT NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (event_id, fetched_at)
                );
                """
            )

    @property
    def configured(self) -> bool:
        return bool(self.key)

    @property
    def region(self) -> str:
        return str(self.settings.get("regione", "eu"))

    @property
    def max_age(self) -> timedelta:
        return timedelta(minutes=float(self.settings.get("cache_minuti", 30)))

    # --- Crediti ----------------------------------------------------------------------

    def _record(self, endpoint: str, headers: Mapping[str, str]) -> int:
        lowered = {name.lower(): value for name, value in headers.items()}

        def number(name: str) -> int | None:
            try:
                return int(float(lowered[name]))
            except (KeyError, TypeError, ValueError):
                return None

        cost = number("x-requests-last") or 0
        with self.cache._connect() as connection:
            connection.execute("INSERT INTO odds_api_usage (at, endpoint, cost, used, remaining) VALUES (?, ?, ?, ?, ?)",
                               (self.now().isoformat(), endpoint, cost, number("x-requests-used"),
                                number("x-requests-remaining")))
        return cost

    def _spent_since(self, start: datetime) -> int:
        with self.cache._connect() as connection:
            rows = connection.execute("SELECT at, cost FROM odds_api_usage").fetchall()
        return int(sum(cost for at, cost in rows if datetime.fromisoformat(at) >= start))

    def spent_today(self) -> int:
        return self._spent_since(datetime.combine(self.now().astimezone().date(), dtime.min).astimezone(timezone.utc))

    def spent_month(self) -> int:
        """Crediti spesi dal primo giorno del mese (ora locale), dal registro delle chiamate."""
        first = self.now().astimezone().date().replace(day=1)
        return self._spent_since(datetime.combine(first, dtime.min).astimezone(timezone.utc))

    def usage(self) -> dict[str, Any]:
        """Crediti dell'API (ultima intestazione ricevuta) e stato del budget mensile.

        ``left`` = crediti ancora spendibili nel mese: il minimo tra budget meno spesa del mese e crediti rimasti
        dell'API. ``suggested_today`` = ``left`` diviso i giorni di gioco stimati da qui a fine mese
        (``giorni_di_gioco_mese`` in proporzione ai giorni rimanenti, almeno 1).
        """
        with self.cache._connect() as connection:
            row = connection.execute("SELECT at, used, remaining FROM odds_api_usage WHERE remaining IS NOT NULL "
                                     "ORDER BY id DESC LIMIT 1").fetchone()
        remaining = row[2] if row else None
        budget = int(self.settings.get("budget_mensile", 500))
        spent = self.spent_month()
        left = max(0, budget - spent)
        if remaining is not None:
            left = min(left, int(remaining))
        today = self.now().astimezone().date()
        month_days = calendar.monthrange(today.year, today.month)[1]
        days_left = month_days - today.day + 1
        play_days = max(1, math.ceil(float(self.settings.get("giorni_di_gioco_mese", 15)) * days_left / month_days))
        return {
            "remaining": remaining, "used": row[1] if row else None,
            "updated": datetime.fromisoformat(row[0]) if row else None,
            "spent_today": self.spent_today(), "spent_month": spent, "budget": budget, "left": left,
            "days_left": days_left, "play_days_left": play_days, "suggested_today": left // play_days,
            "share": spent / budget if budget > 0 else 1.0,
        }

    def budget_level(self, cost: int, usage: Mapping[str, Any] | None = None) -> str:
        """Stato del budget mensile dopo un download da ``cost`` crediti.

        ``ok``; ``avviso`` dall'80% (``soglia_avviso``); ``conferma`` oltre il 95% (``soglia_conferma``), il
        download parte solo con una conferma esplicita; ``blocco`` oltre il budget o i crediti rimasti.
        """
        usage = usage or self.usage()
        budget = usage["budget"]
        after = usage["spent_month"] + max(cost, 0)
        if cost > 0 and (after > budget or (usage["remaining"] is not None and cost > usage["remaining"])):
            return "blocco"
        if budget <= 0:
            return "blocco" if cost > 0 else "ok"
        if cost > 0 and after > float(self.settings.get("soglia_conferma", 0.95)) * budget:
            return "conferma"
        if after >= float(self.settings.get("soglia_avviso", 0.8)) * budget:
            return "avviso"
        return "ok"

    def check_budget(self, cost: int, *, allow_high: bool = False) -> None:
        usage = self.usage()
        level = self.budget_level(cost, usage)
        if level == "blocco":
            if usage["remaining"] is not None and cost > usage["remaining"]:
                raise BudgetExceeded(f"Crediti insufficienti: ne restano {usage['remaining']}, il download ne costa fino a {cost}.")
            raise BudgetExceeded(
                f"Budget mensile superato: questo mese spesi {usage['spent_month']} crediti, questo download ne costa fino "
                f"a {cost}, budget {usage['budget']} (config/odds_api.json, «budget_mensile»).")
        if level == "conferma" and not allow_high:
            raise BudgetConfirmationRequired(
                f"Con questo download ({cost} crediti) la spesa del mese supera il "
                f"{float(self.settings.get('soglia_conferma', 0.95)):.0%} del budget ({usage['spent_month']} + {cost} su "
                f"{usage['budget']}): serve una conferma esplicita.")

    # --- Chiamate ---------------------------------------------------------------------

    def _sanitize(self, text: str) -> str:
        return text.replace(self.key, "***") if self.key else text

    def cache_url(self, path: str, params: Mapping[str, Any]) -> str:
        """URL usato come chiave della cache: senza la chiave API."""
        return f"{BASE_URL}{path}?{urlencode(sorted(params.items()))}"

    def is_cached(self, path: str, params: Mapping[str, Any], max_age: timedelta | None = None) -> bool:
        cached = self.cache.cached(self.cache_url(path, params))
        return cached is not None and self.now() - cached[1] <= (max_age or self.max_age)

    def _get(self, path: str, params: Mapping[str, Any], *, estimate: int, max_age: timedelta | None = None,
             force: bool = False, allow_high: bool = False) -> ApiResult:
        url = self.cache_url(path, params)
        cached = self.cache.cached(url)
        if cached is not None and not force and self.now() - cached[1] <= (max_age or self.max_age):
            return ApiResult(json.loads(cached[0]), cached[1], from_cache=True)
        if not self.key:
            raise OddsApiError("The Odds API non configurata: manca ODDS_API_KEY in .streamlit/secrets.toml.")
        self.check_budget(estimate, allow_high=allow_high)
        try:
            status, body, headers = self.opener(f"{BASE_URL}{path}", {**{k: str(v) for k, v in params.items()},
                                                                      "apiKey": self.key}, self.timeout)
        except Exception as exc:  # rete, timeout
            reason = self._sanitize(f"{type(exc).__name__}: {str(exc)[:160]}")
            return self._fallback(cached, f"{SOURCE} non raggiungibile ({reason})")
        cost = self._record(path, headers)
        if status != 200:
            try:
                message = json.loads(body).get("message", "")
            except (ValueError, AttributeError):
                message = body[:160].decode("utf-8", "replace")
            hints = {401: "chiave non valida o crediti esauriti", 429: "troppe richieste ravvicinate o crediti esauriti"}
            reason = self._sanitize(f"HTTP {status}: {hints.get(status, '')} {message}".strip())
            return self._fallback(cached, f"{SOURCE}: {reason}")
        fetched_at = self.now()
        self.cache.store(url, SOURCE, body, fetched_at)
        return ApiResult(json.loads(body), fetched_at, from_cache=False, cost=cost)

    def _fallback(self, cached, warning: str) -> ApiResult:
        if cached is None:
            raise OddsApiError(f"{warning}; nessun dato in cache.")
        return ApiResult(json.loads(cached[0]), cached[1], from_cache=True,
                         warnings=[f"{warning}: uso il dato in cache del {cached[1].astimezone():%d/%m/%Y %H:%M}."])

    def sports(self) -> ApiResult:
        """Sport attivi (gratuito)."""
        return self._get("/sports", {}, estimate=0, max_age=timedelta(hours=24))

    def events(self, sport: str, day: date) -> ApiResult:
        """Partite di un giorno (ora locale), senza quote (gratuito)."""
        start = datetime.combine(day, dtime.min).astimezone(timezone.utc)
        params = {"commenceTimeFrom": _iso(start), "commenceTimeTo": _iso(start + timedelta(days=1))}
        return self._get(f"/sports/{sport}/events", params, estimate=0)

    def league_params(self, markets: Iterable[str] | None = None) -> dict[str, str]:
        markets = list(markets or self.settings.get("mercati_campionato", ["h2h", "totals"]))
        return {"regions": self.region, "markets": ",".join(markets), "oddsFormat": "decimal", "dateFormat": "iso"}

    def league_cost(self, markets: Iterable[str] | None = None) -> int:
        params = self.league_params(markets)
        return len(params["markets"].split(",")) * len(params["regions"].split(","))

    def league_odds(self, sport: str, markets: Iterable[str] | None = None, *, force: bool = False,
                    allow_high: bool = False) -> ApiResult:
        """Quote di tutte le partite in programma del campionato: costo mercati × regioni."""
        params = self.league_params(markets)
        result = self._get(f"/sports/{sport}/odds", params, estimate=self.league_cost(markets), force=force,
                           allow_high=allow_high)
        if not result.from_cache:
            self._snapshot(sport, result.payload, result.fetched_at)
        return result

    @property
    def profiles(self) -> dict[str, list[str]]:
        """Profili dei mercati per evento: ``risparmio`` (corner e cartellini) e ``completo``."""
        return {name: list(markets) for name, markets in self.settings.get("profili_mercati_evento", {}).items()}

    def profile_markets(self, profile: str | None = None) -> list[str]:
        profile = profile or str(self.settings.get("profilo_mirato", "risparmio"))
        if profile not in self.profiles:
            raise ValueError(f"Profilo mercati «{profile}» assente in config/odds_api.json (profili: {', '.join(self.profiles)}).")
        return self.profiles[profile]

    def event_params(self, markets: Iterable[str] | None = None) -> dict[str, str]:
        markets = list(markets or self.profile_markets())
        return {"regions": self.region, "markets": ",".join(markets), "oddsFormat": "decimal", "dateFormat": "iso"}

    def event_cost(self, markets: Iterable[str] | None = None) -> int:
        """Costo massimo: si pagano solo i mercati restituiti."""
        params = self.event_params(markets)
        return len(params["markets"].split(",")) * len(params["regions"].split(","))

    def event_odds(self, sport: str, event_id: str, markets: Iterable[str] | None = None, *,
                   allow_high: bool = False) -> ApiResult:
        return self._get(f"/sports/{sport}/events/{event_id}/odds", self.event_params(markets),
                         estimate=self.event_cost(markets), allow_high=allow_high)

    def scores_params(self, days_from: int = 1) -> dict[str, Any]:
        return {"daysFrom": int(min(max(days_from, 1), 3)), "dateFormat": "iso"}

    def scores(self, sport: str, days_from: int = 1, *, allow_high: bool = False) -> ApiResult:
        """Partite concluse negli ultimi ``days_from`` giorni (1-3): costo 2."""
        return self._get(f"/sports/{sport}/scores", self.scores_params(days_from), estimate=2,
                         max_age=timedelta(hours=1), allow_high=allow_high)

    def sports_with_matches(self, sports: Iterable[str], day: date) -> tuple[pd.DataFrame, list[str], list[str]]:
        """Partite del giorno dall'elenco eventi (gratuito), competizioni che ne hanno almeno una e avvisi.

        Si chiama prima di ogni scarico per campionato: le quote si scaricano solo per queste competizioni.
        Le competizioni il cui elenco non è disponibile sono escluse e segnalate negli avvisi.
        """
        frames, warnings = [], []
        for sport in sports:
            try:
                result = self.events(sport, day)
            except OddsApiError as exc:
                warnings.append(f"{competition_label(sport)}: {exc}")
                continue
            warnings.extend(result.warnings)
            frames.append(events_frame(result.payload, sport))
        frames = [frame for frame in frames if not frame.empty]
        events = pd.concat(frames, ignore_index=True) if frames else events_frame([])
        return events, sorted(events["sport"].unique()), warnings

    # --- Istantanee per le quote di chiusura -------------------------------------------

    def _snapshot(self, sport: str, events: list[dict], fetched_at: datetime) -> None:
        with self.cache._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO odds_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(event["id"], sport, event["commence_time"], event["home_team"], event["away_team"],
                  fetched_at.isoformat(), json.dumps(event)) for event in events
                 if pd.Timestamp(event["commence_time"]) > pd.Timestamp(fetched_at)],
            )

    def closing_snapshots(self) -> pd.DataFrame:
        """Per ogni partita l'ultima istantanea scaricata prima del calcio d'inizio."""
        with self.cache._connect() as connection:
            rows = connection.execute("SELECT event_id, sport, commence_time, home_team, away_team, fetched_at, payload "
                                      "FROM odds_snapshots").fetchall()
        frame = pd.DataFrame(rows, columns=["event_id", "sport", "commence_time", "home_team", "away_team", "fetched_at", "payload"])
        if frame.empty:
            return frame
        frame = frame.sort_values("fetched_at").groupby("event_id", as_index=False).last()
        return frame


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Lettura delle risposte -----------------------------------------------------------------

def events_frame(events: Iterable[Mapping[str, Any]], sport: str | None = None) -> pd.DataFrame:
    rows = [{
        "event_id": event["id"], "sport": event.get("sport_key", sport),
        "competition": competition_label(event.get("sport_key", sport or ""), event.get("sport_title")),
        "commence_time": pd.Timestamp(event["commence_time"]).tz_convert(None),
        "home_team": event["home_team"], "away_team": event["away_team"],
    } for event in events]
    return pd.DataFrame(rows, columns=["event_id", "sport", "competition", "commence_time", "home_team", "away_team"])


def _engine_key(market: str, outcome: Mapping[str, Any], home: str, away: str) -> str | None:
    name = str(outcome.get("name", ""))
    if market in ("h2h", "h2h_h1"):
        sign = {home: "1", away: "2", "Draw": "X"}.get(name)
        return None if sign is None else (f"{sign} 1T" if market == "h2h_h1" else sign)
    if market in ("btts", "btts_h1"):
        side = {"Yes": "Goal", "No": "No Goal"}.get(name)
        return None if side is None else (f"{side} 1T" if market == "btts_h1" else side)
    if market in _TOTALS and name in ("Over", "Under") and outcome.get("point") is not None:
        return f"{name} {float(outcome['point']):g}{_TOTALS[market]}"
    return None


def merged_quotes_frame(events: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Quote della stessa partita da più risposte (campionato, poi evento): per bookmaker vale la prima."""
    frames = [quotes_frame(event) for event in events if event]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return quotes_frame({"bookmakers": [], "home_team": "", "away_team": ""})
    return pd.concat(frames, ignore_index=True).drop_duplicates(["key", "bookmaker"], keep="first").reset_index(drop=True)


def quotes_frame(event: Mapping[str, Any]) -> pd.DataFrame:
    """Una riga per bookmaker, mercato ed esito, con la chiave evento del motore (solo mercati del catalogo)."""
    from market_catalog import event_keys

    supported = event_keys()
    rows = []
    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            for outcome in market.get("outcomes", []):
                key = _engine_key(market["key"], outcome, event["home_team"], event["away_team"])
                price = outcome.get("price")
                if key is None or key not in supported or not price or float(price) <= 1.0:
                    continue
                rows.append({
                    "key": key, "market": market["key"], "point": outcome.get("point"),
                    "group": f"{_FAMILY.get(market['key'], market['key'])}|{outcome.get('point', '')}",
                    "bookmaker": bookmaker["key"], "bookmaker_title": bookmaker.get("title", bookmaker["key"]),
                    "price": float(price), "last_update": market.get("last_update") or bookmaker.get("last_update"),
                })
    columns = ["key", "market", "point", "group", "bookmaker", "bookmaker_title", "price", "last_update"]
    frame = pd.DataFrame(rows, columns=columns)
    # Le linee principali e alternative dello stesso totale coincidono: si tiene la principale.
    return frame.drop_duplicates(["key", "bookmaker"], keep="first").reset_index(drop=True)


@dataclass(frozen=True)
class Quote:
    price: float
    reference: str            # «Pinnacle» oppure «mediana di N bookmaker»
    bookmakers: str           # quote dei singoli bookmaker
    count: int
    low: float
    high: float
    updated: str | None


def reference_quotes(frame: pd.DataFrame, prefer: str | None = "pinnacle") -> dict[str, Quote]:
    """Quota di riferimento per ogni chiave: Pinnacle se quota tutti gli esiti della linea, altrimenti la mediana."""
    quotes: dict[str, Quote] = {}
    if frame.empty:
        return quotes
    for _, group in frame.groupby("group"):
        keys = set(group["key"])
        pinnacle = group[group["bookmaker"] == prefer] if prefer else group.iloc[0:0]
        use_pinnacle = not pinnacle.empty and set(pinnacle["key"]) == keys
        for key, rows in group.groupby("key"):
            rows = rows.sort_values("price", ascending=False)
            detail = " · ".join(f"{row.bookmaker_title} {row.price:.2f}" for row in rows.itertuples())
            if use_pinnacle:
                price, label = float(pinnacle.loc[pinnacle["key"] == key, "price"].iloc[0]), "Pinnacle"
            else:
                price = float(np.median(rows["price"]))
                label = f"mediana di {len(rows)} bookmaker" if len(rows) > 1 else rows["bookmaker_title"].iloc[0]
            quotes[key] = Quote(round(price, 3), label, detail, len(rows), float(rows["price"].min()),
                                float(rows["price"].max()), rows["last_update"].dropna().max() if rows["last_update"].notna().any() else None)
    return quotes


def disagreement(frame: pd.DataFrame) -> float:
    """Disaccordo tra bookmaker sull'1X2: media di (quota massima / quota minima − 1). Base della preselezione."""
    h2h = frame[frame["market"] == "h2h"]
    if h2h.empty:
        return float("nan")
    spread = h2h.groupby("key")["price"].agg(lambda prices: prices.max() / prices.min() - 1.0)
    return float(spread.mean())


def preselect(rows: pd.DataFrame, limit: int = 10) -> list[str]:
    """Le ``limit`` partite con più disaccordo tra bookmaker (più spazio per quote fuori linea)."""
    if rows.empty:
        return []
    ranked = rows.dropna(subset=["disaccordo"]).sort_values("disaccordo", ascending=False)
    return list(ranked["event_id"].head(limit))


def scores_frame(scores: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Partite concluse nello schema dei risultati del registro (``date``, squadre, gol)."""
    rows = []
    for event in scores:
        if not event.get("completed") or not event.get("scores"):
            continue
        goals = {item["name"]: item["score"] for item in event["scores"]}
        try:
            home, away = int(goals[event["home_team"]]), int(goals[event["away_team"]])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({"event_id": event["id"], "date": pd.Timestamp(event["commence_time"]).tz_convert(None).normalize(),
                     "home_team": event["home_team"], "away_team": event["away_team"],
                     "home_goals": home, "away_goals": away})
    return pd.DataFrame(rows, columns=["event_id", "date", "home_team", "away_team", "home_goals", "away_goals"])


def with_closing_odds(results: pd.DataFrame, snapshots: pd.DataFrame, prefer: str | None = "pinnacle") -> pd.DataFrame:
    """Aggiunge ai risultati ``closing_odds`` (chiave evento -> quota) dall'ultima istantanea prima del via."""
    if results.empty:
        return results.assign(closing_odds=None)
    closing = {}
    for row in snapshots.itertuples():
        quotes = reference_quotes(quotes_frame(json.loads(row.payload)), prefer)
        closing[row.event_id] = ({key: quote.price for key, quote in quotes.items()},
                                 f"{SOURCE}, {next(iter(quotes.values())).reference if quotes else ''}, "
                                 f"istantanea del {pd.Timestamp(row.fetched_at).tz_convert(None):%d/%m %H:%M} UTC")
    return results.assign(
        closing_odds=[closing.get(event_id, (None, None))[0] for event_id in results["event_id"]],
        closing_source=[closing.get(event_id, (None, None))[1] for event_id in results["event_id"]],
    )


# --- Riepiloghi per l'interfaccia -------------------------------------------------------------

MAIN_KEYS = ("1", "X", "2", "Over 2.5 gol", "Under 2.5 gol")


def league_overview(events: Iterable[Mapping[str, Any]], prefer: str | None = "pinnacle") -> pd.DataFrame:
    """Una riga per partita: quote di riferimento 1X2 e Over/Under 2.5, fonte, bookmaker e disaccordo."""
    rows = []
    for event in events:
        frame = quotes_frame(event)
        quotes = reference_quotes(frame, prefer)
        rows.append({
            "event_id": event["id"], "sport": event.get("sport_key"),
            "competition": competition_label(event.get("sport_key", ""), event.get("sport_title")),
            "commence_time": pd.Timestamp(event["commence_time"]).tz_convert(None),
            "home_team": event["home_team"], "away_team": event["away_team"],
            **{key: quotes[key].price if key in quotes else None for key in MAIN_KEYS},
            "riferimento": quotes["1"].reference if "1" in quotes else None,
            "bookmaker": int(frame["bookmaker"].nunique()) if not frame.empty else 0,
            "disaccordo": disagreement(frame),
        })
    return pd.DataFrame(rows)


def planned_cost(api: OddsApi, calls: Iterable[tuple[str, Mapping[str, Any], int]]) -> tuple[int, int]:
    """Costo massimo delle chiamate (percorso, parametri, costo) non ancora in cache e numero di chiamate in cache."""
    total = cached = 0
    for path, params, cost in calls:
        if api.is_cached(path, params):
            cached += 1
        else:
            total += cost
    return total, cached


def day_cost(api: OddsApi, sports: Iterable[str], targeted: Iterable[tuple[str, str]] | int,
             markets: Iterable[str] | None = None) -> dict[str, Any]:
    """Costo previsto di una giornata: quote per campionato, mercati mirati e punteggi del giorno dopo.

    ``sports`` sono le sole competizioni con partite nel giorno (``OddsApi.sports_with_matches``), ``targeted``
    le coppie (competizione, ID evento) delle partite mirate, oppure solo il loro numero quando non sono
    ancora scelte (stima senza controllo della cache). Le risposte già in cache non costano; i mercati
    mirati sono un massimo (si pagano solo quelli restituiti); i punteggi sono la stima per il giorno dopo
    (2 crediti per competizione, se ci saranno giocate nel registro).
    """
    sports = sorted(set(sports))
    markets = list(markets or api.profile_markets())
    if isinstance(targeted, int):
        count, targeted = targeted, []
    else:
        targeted = list(targeted)
        count = len(targeted)
    league, league_cached = planned_cost(api, [(f"/sports/{sport}/odds", api.league_params(), api.league_cost())
                                               for sport in sports])
    event, event_cached = planned_cost(api, [(f"/sports/{sport}/events/{event_id}/odds", api.event_params(markets),
                                              api.event_cost(markets)) for sport, event_id in targeted])
    if not targeted:
        event = count * api.event_cost(markets)
    scores = 2 * len(sports)
    return {"competitions": sports, "targeted": count, "markets": markets, "league": league,
            "event": event, "per_event": api.event_cost(markets), "cached": league_cached + event_cached,
            "today": league + event, "scores": scores, "total": league + event + scores}


def quote_rows(quotes: Mapping[str, Quote], eurobet: Mapping[str, float] | None = None) -> pd.DataFrame:
    """Tabella delle quote: riferimento, bookmaker di ogni quota ed eventuale quota Eurobet a confronto."""
    eurobet = eurobet or {}
    rows = []
    for key, quote in quotes.items():
        manual = eurobet.get(key)
        rows.append({
            "Mercato": key, "Quota riferimento": quote.price, "Riferimento": quote.reference,
            "Min": quote.low, "Max": quote.high, "Bookmaker": quote.bookmakers,
            "Quota Eurobet": manual,
            "Eurobet vs riferimento": (manual / quote.price - 1.0) if manual and manual > 1.0 else None,
        })
    return pd.DataFrame(rows)


def sheet_odds(quotes: Mapping[str, Quote], fetched_at: datetime | None,
               eurobet: Mapping[str, float] | None = None, use_eurobet: bool = False) -> dict:
    """Campi quota del blocco con fonte e data; con ``use_eurobet`` le quote Eurobet inserite sostituiscono il riferimento."""
    from datasources.stats import FieldValue

    fields = {}
    for key, quote in quotes.items():
        manual = (eurobet or {}).get(key)
        if use_eurobet and manual and manual > 1.0:
            fields[key] = FieldValue(float(manual), "Eurobet (inserita a mano)", fetched_at,
                                     note=f"riferimento {SOURCE} {quote.price:.2f} ({quote.reference})")
        else:
            fields[key] = FieldValue(float(quote.price), f"{SOURCE} · {quote.reference}", fetched_at, note=quote.bookmakers)
    return fields


def scores_plan(frame: pd.DataFrame, today: date, snapshots: pd.DataFrame | None = None) -> dict[str, Any]:
    """Competizioni e ``daysFrom`` per le giocate del registro senza esito degli ultimi 3 giorni.

    Si scaricano i punteggi solo delle competizioni con giocate nel registro. La competizione si riconosce
    dall'etichetta italiana o dalla chiave dell'API; se la colonna non basta, dalla partita nelle istantanee
    delle quote già salvate (stesse squadre, data vicina). Le righe non riconosciute restano escluse
    (``unknown``) invece di scaricare tutte le competizioni. Le partite più vecchie di 3 giorni non sono coperte.
    """
    from performance import find_result

    open_rows = frame[frame["Esito"].isna() & ~frame["Note"].fillna("").str.contains("rimborsata")]
    days = [(today - day).days for day in open_rows["Data"] if day is not None]
    recent = open_rows[[day is not None and 0 <= (today - day).days <= 3 for day in open_rows["Data"]]]
    by_label = {label.lower(): key for key, label in COMPETITIONS.items()} | {key: key for key in COMPETITIONS}
    known = pd.DataFrame(columns=["date", "home_team", "away_team", "sport"])
    if snapshots is not None and not snapshots.empty:
        known = snapshots.assign(date=pd.to_datetime(snapshots["commence_time"], utc=True).dt.tz_convert(None).dt.normalize())
    sports, unknown = set(), []
    for row in recent.itertuples():
        key = by_label.get(str(getattr(row, "Competizione", "") or "").strip().lower())
        if key is None and "Partita" in recent.columns:
            match = find_result(known, row.Partita, row.Data, before=1, after=1)
            key = None if match is None else match["sport"]
        if key:
            sports.add(key)
        else:
            unknown.append(str(getattr(row, "Partita", "")))
    recent_days = [day for day in days if 0 <= day <= 3]
    return {
        "sports": sorted(sports),
        "days_from": max(1, min(3, max(recent_days) + 1 if recent_days else 1)),
        "too_old": sum(1 for day in days if day > 3),
        "rows": len(recent),
        "unknown": sorted(set(unknown)),
    }


def results_from_scores(payloads: Iterable[Iterable[Mapping[str, Any]]], snapshots: pd.DataFrame,
                        prefer: str | None = "pinnacle") -> pd.DataFrame:
    """Risultati finali di più competizioni con le quote di chiusura delle istantanee salvate."""
    frames = [scores_frame(payload) for payload in payloads]
    frames = [frame for frame in frames if not frame.empty]
    results = pd.concat(frames, ignore_index=True) if frames else scores_frame([])
    return with_closing_odds(results, snapshots, prefer)
