"""Cache SQLite delle risposte HTTP con pause tra le richieste e ripiego offline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Callable, Mapping

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path(os.environ.get("SIMULPRO_CACHE_DB", ROOT / "data" / "cache" / "sources.sqlite"))
USER_AGENT = "Mozilla/5.0 (Simulpro; analisi statistica personale)"

# Secondi minimi tra due richieste alla stessa fonte: le fonti gratuite
# bloccano lo scraping troppo frequente.
MIN_INTERVAL = {
    "clubelo": 3.0,
    "understat": 3.0,
    "football-data.co.uk": 1.0,
    "football-data.org": 6.5,
}

Opener = Callable[[str, Mapping[str, str], float], bytes]


class SourceUnavailable(RuntimeError):
    """La fonte non ha risposto e non esiste un dato in cache."""


@dataclass(frozen=True)
class FetchResult:
    body: bytes | None
    fetched_at: datetime | None
    from_cache: bool
    warning: str | None = None

    @property
    def ok(self) -> bool:
        return self.body is not None


def _requests_opener(url: str, headers: Mapping[str, str], timeout: float) -> bytes:
    response = requests.get(url, headers=dict(headers), timeout=timeout)
    response.raise_for_status()
    return response.content


class SourceCache:
    """Cache su SQLite condivisa da tutte le fonti.

    ``opener``, ``clock`` e ``sleep`` sono iniettabili: i test non toccano la rete.
    """

    def __init__(
        self,
        path: Path | str = DEFAULT_DB,
        *,
        opener: Opener | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: Mapping[str, float] | None = None,
        timeout: float = 25.0,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.opener = opener or _requests_opener
        self.clock = clock
        self.sleep = sleep
        self.min_interval = dict(MIN_INTERVAL if min_interval is None else min_interval)
        self.timeout = timeout
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS responses (
                    url TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    body BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS custom_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    home TEXT NOT NULL,
                    away TEXT NOT NULL,
                    competition TEXT,
                    match_date TEXT,
                    block TEXT NOT NULL,
                    origin TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def cached(self, url: str) -> tuple[bytes, datetime] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT body, fetched_at FROM responses WHERE url = ?", (url,)).fetchone()
        if row is None:
            return None
        return bytes(row[0]), datetime.fromisoformat(row[1])

    def store(self, url: str, source: str, body: bytes, fetched_at: datetime | None = None) -> None:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO responses (url, source, fetched_at, body) VALUES (?, ?, ?, ?)",
                (url, source, fetched_at.isoformat(), body),
            )

    def _pause(self, source: str) -> None:
        interval = self.min_interval.get(source, 1.0)
        with self._lock:
            last = self._last_request.get(source)
            now = self.clock()
            if last is not None and now - last < interval:
                self.sleep(interval - (now - last))
            self._last_request[source] = self.clock()

    def get(
        self,
        url: str,
        *,
        source: str,
        max_age: timedelta,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResult:
        """Dato fresco dalla cache, altrimenti dalla rete; se la rete fallisce, ultimo dato in cache."""
        cached = self.cached(url)
        now = datetime.now(timezone.utc)
        if cached is not None and now - cached[1] <= max_age:
            return FetchResult(cached[0], cached[1], from_cache=True)
        self._pause(source)
        try:
            body = self.opener(url, {"User-Agent": USER_AGENT, **(headers or {})}, self.timeout)
        except Exception as exc:  # rete, HTTP, timeout: la fonte è considerata non disponibile
            reason = f"{type(exc).__name__}: {str(exc)[:120]}"
            if cached is not None:
                return FetchResult(
                    cached[0], cached[1], from_cache=True,
                    warning=f"{source} non raggiungibile ({reason}): uso il dato in cache del "
                            f"{cached[1].astimezone():%d/%m/%Y %H:%M}.",
                )
            return FetchResult(None, None, from_cache=False, warning=f"{source} non raggiungibile ({reason}) e nessun dato in cache.")
        self.store(url, source, body, now)
        return FetchResult(body, now, from_cache=False)

    # --- Partite inserite manualmente -------------------------------------------------

    def save_custom_match(self, home: str, away: str, block: str, *, competition: str | None = None,
                          match_date: str | None = None) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO custom_matches (created_at, home, away, competition, match_date, block, origin) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), home, away, competition, match_date, block,
                 "inserita manualmente"),
            )
            return int(cursor.lastrowid)

    def custom_matches(self) -> list[dict]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM custom_matches ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]
