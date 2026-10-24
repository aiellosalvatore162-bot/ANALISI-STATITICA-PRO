"""Demo della pagina «Oggi» per gli screenshot (solo sviluppo, non serve all'app).

Le quote arrivano dalle risposte The Odds API registrate in ``tests/fixtures/oddsapi`` (nessun credito,
nessuna chiave): le 20 partite di Serie A del file delle quote figurano tutte il 25/10/2026. I dati delle
squadre sono quelli reali delle fonti gratuite (rete necessaria). Uso:
``streamlit run tools/demo_oggi.py`` oppure ``python -m tools.screenshots --oggi``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

import ui_odds  # noqa: E402
from datasources import oddsapi  # noqa: E402
from datasources.cache import SourceCache  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "oddsapi"
NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FixtureOpener:
    """Risposte registrate con le intestazioni dei crediti, come l'API reale."""

    def __init__(self) -> None:
        self.remaining = 500

    def __call__(self, url, params, timeout):
        path = url.replace(oddsapi.BASE_URL, "")
        cost = 0
        if path == "/sports":
            body = _load("sports.json")
        elif path.endswith("/events"):
            league = _load("odds_serie_a.json") if "italy_serie_a" in path else []
            body = [{**{key: event[key] for key in ("id", "sport_key", "sport_title", "home_team", "away_team")},
                     "commence_time": "2026-10-25T" + event["commence_time"][11:]} for event in league]
        elif "/events/" in path:
            body = _load("event_odds.json")
            wanted = set(params["markets"].split(","))
            body["bookmakers"] = [{**bookmaker, "markets": [m for m in bookmaker["markets"] if m["key"] in wanted]}
                                  for bookmaker in body["bookmakers"]]
            cost = len({market["key"] for bookmaker in body["bookmakers"] for market in bookmaker["markets"]})
        else:
            body = [{**event, "commence_time": "2026-10-25T" + event["commence_time"][11:]} for event in _load("odds_serie_a.json")]
            cost = len(params["markets"].split(","))
        self.remaining -= cost
        return 200, json.dumps(body).encode(), {"x-requests-remaining": str(self.remaining), "x-requests-last": str(cost)}


@st.cache_resource(show_spinner=False)
def demo_client() -> oddsapi.OddsApi:
    return oddsapi.OddsApi(SourceCache(ROOT / "data" / "cache" / "demo_oggi.sqlite"), "demo",
                           settings={**oddsapi.load_settings()}, opener=FixtureOpener(), now=lambda: NOW)


ui_odds.odds_client = demo_client
st.session_state.setdefault("page", "Oggi")
st.session_state.setdefault("today_day", date(2026, 10, 25))
exec(compile((ROOT / "streamlit_app.py").read_text(encoding="utf-8"), str(ROOT / "streamlit_app.py"), "exec"))
