"""Registro delle previsioni (versione minima; la fase H aggiungerà risultati e quota di chiusura).

Ogni riga: partita, mercato, probabilità del simulatore (``Prob_modello``),
probabilità dopo le correzioni di Claude (``Prob_Claude``) e quota, se presente.
Le righe sono salvate nello stesso database SQLite della cache delle fonti.
"""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from typing import Any, Mapping

from datasources.cache import SourceCache


LOGGED_MARKETS = ("1", "X", "2", "Over 2.5 gol", "Under 2.5 gol", "Goal", "No Goal", "Over 0.5 gol 1T",
                  "Over 9.5 corner", "Over 4.5 cartellini")


def registry_rows(before: Mapping[str, Any], after: Mapping[str, Any] | None, *, odds: Mapping[str, float] | None = None,
                  confidence: str | None = None, note: str = "") -> list[dict]:
    """Righe del registro per i mercati principali; ``after`` è la simulazione con le correzioni di Claude."""
    match = f"{before['input']['home']['name']} - {before['input']['away']['name']}"
    final_before = before["components"]["finale"]
    final_after = after["components"]["finale"] if after is not None else {}
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return [{
        "Data": created, "Partita": match, "Mercato": market,
        "Prob_modello": final_before.get(market),
        "Prob_Claude": final_after.get(market) if after is not None else None,
        "Quota": (odds or {}).get(market),
        "Confidenza_Claude": confidence, "Note": note,
    } for market in LOGGED_MARKETS if market in final_before]


class PredictionLog:
    COLUMNS = ("Data", "Partita", "Mercato", "Prob_modello", "Prob_Claude", "Quota", "Confidenza_Claude", "Note")

    def __init__(self, cache: SourceCache) -> None:
        self.path = cache.path
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS registro_previsioni (id INTEGER PRIMARY KEY AUTOINCREMENT, sessione TEXT, "
                + ", ".join(f'"{column}"' for column in self.COLUMNS) + ")"
            )

    def add(self, rows: list[dict], session: str) -> list[int]:
        ids = []
        with sqlite3.connect(self.path) as connection:
            for row in rows:
                cursor = connection.execute(
                    "INSERT INTO registro_previsioni (sessione, " + ", ".join(f'"{column}"' for column in self.COLUMNS)
                    + ") VALUES (?" + ", ?" * len(self.COLUMNS) + ")",
                    (session, *(row.get(column) for column in self.COLUMNS)),
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def rows(self, session: str | None = None) -> list[dict]:
        query = "SELECT * FROM registro_previsioni" + (" WHERE sessione = ?" if session else "") + " ORDER BY id"
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(query, (session,) if session else ())]
