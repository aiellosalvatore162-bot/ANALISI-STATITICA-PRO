"""The Odds API con risposte registrate (tests/fixtures/oddsapi): nessuna chiamata di rete."""

from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import pytest

import engine
from datasources.builder import empty_sheet, render_block
from datasources.cache import SourceCache
from datasources import oddsapi
from market_catalog import event_keys
from parser import parse_match_input
from performance import fill_from_results


FIXTURES = Path(__file__).parent / "tests" / "fixtures" / "oddsapi"
KEY = "chiave-di-prova-0123"
NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
SETTINGS = {**oddsapi.load_settings(), "budget_giornaliero": 40}


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeApi:
    """Serve le risposte registrate e le intestazioni dei crediti come l'API reale."""

    def __init__(self, status: int = 200):
        self.calls: list[tuple[str, dict]] = []
        self.status = status
        self.remaining = 500

    def __call__(self, url, params, timeout):
        self.calls.append((url, dict(params)))
        path = url.replace(oddsapi.BASE_URL, "")
        if self.status != 200:
            return self.status, json.dumps({"message": f"API key {params['apiKey']} is not valid"}).encode(), {}
        if path == "/sports":
            body, cost = load("sports.json"), 0
        elif path.endswith("/events"):
            body, cost = load("events_serie_a.json"), 0
        elif path.endswith("/scores"):
            body, cost = load("scores_champions.json"), 2
        elif "/events/" in path:
            body = load("event_odds.json")
            cost = len({market["key"] for bookmaker in body["bookmakers"] for market in bookmaker["markets"]})
        else:
            body, cost = load("odds_serie_a.json"), len(params["markets"].split(","))
        self.remaining -= cost
        headers = {"x-requests-remaining": str(self.remaining), "x-requests-used": str(500 - self.remaining),
                   "x-requests-last": str(cost)}
        return 200, json.dumps(body).encode(), headers


@pytest.fixture
def api(tmp_path):
    fake = FakeApi()
    client = oddsapi.OddsApi(SourceCache(tmp_path / "cache.sqlite"), KEY, settings=SETTINGS, opener=fake, now=lambda: NOW)
    client.fake = fake
    return client


def test_free_endpoints_and_league_costs_follow_the_documentation(api):
    assert api.sports().cost == 0 and api.events("soccer_italy_serie_a", date(2026, 10, 25)).cost == 0
    assert api.league_cost() == 2 and api.event_cost() == 6
    league = api.league_odds("soccer_italy_serie_a")
    assert league.cost == 2 and len(league.payload) == 20
    usage = api.usage()
    assert usage["remaining"] == 498 and usage["spent_today"] == 2
    event = api.event_odds("soccer_italy_serie_a", "0b4894e9fb123ef3045269f97e339eba")
    assert event.cost == 6 and api.usage()["spent_today"] == 8
    params = api.fake.calls[2][1]
    assert params["regions"] == "eu" and params["markets"] == "h2h,totals"


def test_cache_for_30_minutes_costs_nothing_and_never_stores_the_key(api, tmp_path):
    api.league_odds("soccer_italy_serie_a")
    again = api.league_odds("soccer_italy_serie_a")
    assert again.from_cache and again.cost == 0 and len(api.fake.calls) == 1
    later = oddsapi.OddsApi(api.cache, KEY, settings=SETTINGS, opener=api.fake,
                            now=lambda: NOW.replace(minute=NOW.minute + 31))
    assert not later.league_odds("soccer_italy_serie_a").from_cache
    with sqlite3.connect(tmp_path / "cache.sqlite") as connection:
        stored = " ".join(str(value) for row in connection.execute("SELECT url, body FROM responses") for value in row)
    assert KEY not in stored and "apiKey" not in stored


def test_budget_is_checked_before_calling_the_api(api):
    small = oddsapi.OddsApi(api.cache, KEY, settings={**SETTINGS, "budget_giornaliero": 5}, opener=api.fake, now=lambda: NOW)
    small.league_odds("soccer_italy_serie_a")
    with pytest.raises(oddsapi.BudgetExceeded, match="Budget giornaliero"):
        small.event_odds("soccer_italy_serie_a", "0b4894e9fb123ef3045269f97e339eba")
    assert len(api.fake.calls) == 1


def test_errors_hide_the_key_and_fall_back_to_the_cache(api):
    api.league_odds("soccer_italy_serie_a")
    broken = oddsapi.OddsApi(api.cache, KEY, settings=SETTINGS, opener=FakeApi(status=401), now=lambda: NOW)
    fallback = broken.league_odds("soccer_italy_serie_a", force=True)
    assert fallback.from_cache and KEY not in fallback.warnings[0] and "HTTP 401" in fallback.warnings[0]
    with pytest.raises(oddsapi.OddsApiError) as error:
        broken.scores("soccer_uefa_champs_league", 3)
    assert KEY not in str(error.value)
    with pytest.raises(oddsapi.OddsApiError, match="ODDS_API_KEY"):
        oddsapi.OddsApi(api.cache, None, settings=SETTINGS, opener=api.fake).event_odds("x", "y")


def test_reference_is_pinnacle_when_it_quotes_the_whole_line_otherwise_the_median():
    event = next(event for event in load("odds_serie_a.json") if event["home_team"] == "Napoli")
    quotes = oddsapi.reference_quotes(oddsapi.quotes_frame(event))
    pinnacle = next(bookmaker for bookmaker in event["bookmakers"] if bookmaker["key"] == "pinnacle")
    home = next(outcome["price"] for outcome in pinnacle["markets"][0]["outcomes"] if outcome["name"] == "Napoli")
    assert quotes["1"].price == home and quotes["1"].reference == "Pinnacle" and "Pinnacle" in quotes["1"].bookmakers
    without = {**event, "bookmakers": [bookmaker for bookmaker in event["bookmakers"] if bookmaker["key"] != "pinnacle"]}
    frame = oddsapi.quotes_frame(without)
    median = oddsapi.reference_quotes(frame)["1"]
    assert median.price == pytest.approx(np.median(frame.loc[frame["key"] == "1", "price"]))
    assert median.reference.startswith("mediana di")


def test_event_markets_map_to_engine_keys_and_skip_unsupported_lines():
    frame = oddsapi.merged_quotes_frame([load("event_odds.json")])
    keys = set(frame["key"])
    assert {"Goal", "No Goal", "1 1T", "X 1T", "Over 9.5 corner", "Under 4.5 cartellini", "Over 3.5 gol"} <= keys
    assert not any(key.startswith(("Over 9 ", "Over 4 ")) for key in keys)  # linee asiatiche intere escluse
    assert keys <= event_keys()


def test_league_overview_and_system_preselection():
    overview = oddsapi.league_overview(load("odds_serie_a.json"))
    assert len(overview) == 20 and overview["riferimento"].eq("Pinnacle").all()
    chosen = oddsapi.preselect(overview, 3)
    assert len(chosen) == 3
    assert overview.set_index("event_id").loc[chosen, "disaccordo"].min() >= overview["disaccordo"].nlargest(3).min()


def test_block_with_api_odds_keeps_the_parser_format():
    league = next(event for event in load("odds_serie_a.json") if event["home_team"] == "Napoli")
    quotes = oddsapi.reference_quotes(oddsapi.merged_quotes_frame([league, load("event_odds.json")]))
    sheet = empty_sheet("Napoli", "Roma", date(2026, 10, 24), "Serie A")
    sheet.odds = oddsapi.sheet_odds(quotes, NOW, {"1": 2.95}, use_eurobet=True)
    block = render_block(sheet)
    teams = ("CASA: Napoli\nAttacco: 1.2 | Difesa: 1.1 | Elo: 1850 | Forma: W-W-D-W-L | xG Fatti: 1.8 | xG Subiti: 1.0 | "
             "Corner pro/sub: 5.5/4.0 | Cartellini pro: 2.0\nOSPITE: Roma\nAttacco: 1.1 | Difesa: 1.2 | Elo: 1800 | "
             "Forma: W-D-W-W-L | xG Fatti: 1.5 | xG Subiti: 1.1 | Corner pro/sub: 5.0/4.5 | Cartellini pro: 2.2\n"
             "ARBITRO: Gialli medi 4.2 | Falli medi 24\n")
    parsed = parse_match_input(teams + block[block.index("QUOTE_MERCATI_PRINCIPALI"):])
    assert parsed.odds["1"] == 2.95 and parsed.odds["Over 9.5 corner"] == quotes["Over 9.5 corner"].price
    assert "Eurobet (inserita a mano)" in block and "The Odds API · Pinnacle" in block


def test_scores_settle_goal_markets_and_snapshots_give_closing_odds(api):
    league = load("odds_serie_a.json")
    # Istantanea di una partita di coppa finta con l'ID reale del punteggio Napoli - Bodø/Glimt.
    score = next(event for event in load("scores_champions.json") if event["home_team"] == "Napoli")
    snapshot = {**league[3], "id": score["id"], "home_team": "Napoli", "away_team": "Bodø/Glimt",
                "commence_time": score["commence_time"]}
    api._snapshot("soccer_uefa_champs_league", [snapshot], datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc))
    results = oddsapi.results_from_scores([load("scores_champions.json")], api.closing_snapshots())
    assert len(results) == 18 and results.loc[results["home_team"] == "Napoli", "home_goals"].iloc[0] == 4
    frame = pd.DataFrame([
        {"_riga": 2, "ID": "a", "Data": date(2026, 10, 20), "Partita": "Napoli - Bodo/Glimt", "Selezione": "Over 2.5 gol",
         "Esito": np.nan, "Quota_chiusura": np.nan, "Note": ""},
        {"_riga": 3, "ID": "b", "Data": date(2026, 10, 21), "Partita": "Inter - Shakhtar", "Selezione": "Goal",
         "Esito": np.nan, "Quota_chiusura": np.nan, "Note": ""},
        {"_riga": 4, "ID": "c", "Data": date(2026, 10, 21), "Partita": "Inter - Shakhtar", "Selezione": "Over 0.5 gol 1T",
         "Esito": np.nan, "Quota_chiusura": np.nan, "Note": ""},
    ])
    report = fill_from_results(frame, results, source="The Odds API (punteggi)", today=date(2026, 10, 23))
    filled = report.frame.set_index("ID")
    assert filled.loc["a", "Esito"] == 1.0 and filled.loc["b", "Esito"] == 0.0 and pd.isna(filled.loc["c", "Esito"])
    over = oddsapi.reference_quotes(oddsapi.quotes_frame(snapshot))["Over 2.5 gol"].price
    assert filled.loc["a", "Quota_chiusura"] == over and "istantanea" in filled.loc["a", "Note"]
    assert "The Odds API (punteggi)" in filled.loc["b", "Note"]


def test_scores_plan_covers_recent_rows_only():
    frame = pd.DataFrame({"Data": [date(2026, 10, 21), date(2026, 10, 10), date(2026, 10, 22)],
                          "Competizione": ["Champions League", "Serie A", ""], "Esito": [np.nan, np.nan, np.nan],
                          "Note": ["", "", ""]})
    plan = oddsapi.scores_plan(frame, date(2026, 10, 23), ["soccer_epl"])
    assert plan["sports"] == ["soccer_epl", "soccer_uefa_champs_league"]
    assert plan["days_from"] == 3 and plan["too_old"] == 1 and plan["rows"] == 2


# --- Ancoraggio di corner e cartellini ------------------------------------------------------

def _config(odds=None, **overrides):
    team = lambda name, elo: engine.TeamParams(name, 1.1, 1.0, elo, "W-D-W-L-W", 1.5, 1.2, 5.5, 4.5, 2.0)
    return engine.MatchConfig(team("Napoli", 1850), team("Roma", 1800), 4.4, 24.0, odds=odds, simulations=40_000, **overrides)


def test_counts_without_lines_stay_model_only():
    details = engine.count_anchoring(_config({"1": 2.8, "X": 3.4, "2": 2.6}))
    assert not details["corner"]["active"] and details["corner"]["reason"].startswith("Solo modello")
    assert details["corner"]["final_mean"] == pytest.approx(sum(engine.corner_signals(_config())))


def test_corner_and_card_lines_anchor_the_means_with_weight_08():
    quotes = oddsapi.reference_quotes(oddsapi.quotes_frame(load("event_odds.json")))
    odds = {key: quote.price for key, quote in quotes.items() if "corner" in key or "cartellini" in key}
    config = _config(odds)
    details = engine.count_anchoring(config)
    corner, cards = details["corner"], details["cartellini"]
    assert corner["active"] and cards["active"] and config.count_anchor.market_weight == 0.8
    assert corner["final_mean"] == pytest.approx(corner["market_mean"] ** 0.8 * corner["model_mean"] ** 0.2)
    # La media del mercato riprezza le linee senza margine.
    dispersion = config.count_model.corner_dispersion
    for line in corner["lines"]:
        assert engine._count_sf(line["linea"], corner["market_mean"], dispersion) == pytest.approx(line["over_senza_margine"], abs=0.04)
    for line in cards["lines"]:
        fitted = engine.card_points_sf(line["linea"], cards["market_mean"], config.count_model, config.card_rule)
        assert fitted == pytest.approx(line["over_senza_margine"], abs=0.04)
    result = engine.simulate_match(config)
    assert result["markets"]["corners"]["mean"] == pytest.approx(corner["final_mean"], rel=0.02)
    assert result["count_anchoring"]["corner"]["active"]


def test_claude_corner_factor_applies_after_the_market_anchor():
    odds = {"Over 9.5 corner": 2.19, "Under 9.5 corner": 1.67}
    base = _config(odds)
    adjusted = replace(base, claude=engine.ClaudeAdjustment(corners=1.1))
    assert sum(engine.corner_signals(adjusted)) == pytest.approx(sum(engine.corner_signals(base)) * 1.1)


def test_card_points_distribution_matches_the_calibration_tool():
    from tools.calibrate import points_sf

    params, rule = engine.DEFAULT_COUNT_MODEL, engine.DEFAULT_CARD_RULE
    for threshold in (3.5, 4.5, 5.5):
        expected = points_sf(threshold, np.array([4.2]), params.card_dispersion, np.array([4.2 * params.card_red_ratio]), rule)[0]
        assert engine.card_points_sf(threshold, 4.2, params, rule) == pytest.approx(expected, abs=1e-6)
