"""Fase Z: quote da qualunque bookmaker, selezione del giorno, archivio unico, raccolta a crediti, combo builder.

Nessuna rete: pagine incollate dalle fixture, The Odds API con risposte finte (nessun credito consumato)."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import time

import numpy as np
import pytest
import requests

import combo
import day_archive
import my_markets
from datasources.cache import SourceCache
from engine import config_from_input, simulate_match
from parser import parse_match_input
from quotes import collect as quote_collect
from quotes.adapters import eurobet as eurobet_adapter, generico
from quotes.model import QuoteMercato, consolidate
from quotes.pages import STATUS_AMBIGUOUS, STATUS_MATCHED, STATUS_MISSING, Target, assign_pages, detect_format, split_pages
from test_engine import VALID
from today import TodayMatch

ROOT = Path(__file__).parent
FIXTURES = ROOT / "tests" / "fixtures" / "quote"
TODAY = date(2026, 10, 27)


def _match(home, away, day=26, hour=18, minute=0, sport="soccer_italy_serie_a", event=None):
    when = datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)
    return TodayMatch(event or f"{home}-{away}-{day}", sport, "Serie A", when, home, away)


def _quote(market, price, bookmaker="Eurobet", fonte="incollata"):
    return QuoteMercato("Napoli - Roma", market, None, market, price, bookmaker, fonte, "2026-10-26T10:00:00+00:00")


# --- 1. Selezione del giorno ----------------------------------------------------------------------------------

def test_ninth_match_and_sixth_to_play_are_refused():
    store = {}
    keys = [day_archive.add_match(store, _match(f"Casa{i}", f"Ospite{i}")) for i in range(9)]
    for key in keys[:8]:
        assert day_archive.set_selection(store, key, selected=True) is None
    message = day_archive.set_selection(store, keys[8], selected=True)
    assert "Massimo 8 partite" in message and not store[keys[8]]["selected"]
    for key in keys[:5]:
        assert day_archive.set_selection(store, key, to_play=True) is None
    assert "Massimo 5 partite «Da giocare»" in day_archive.set_selection(store, keys[5], to_play=True)
    assert day_archive.counter_text(store) == "Selezionate 8/8, Da giocare 5/5"
    day_archive.set_selection(store, keys[0], selected=False)  # togliere la selezione toglie anche «Da giocare»
    assert not store[keys[0]]["to_play"] and day_archive.counts(store)[:3:2] == (7, 4)
    day_archive.deselect_all(store)
    assert day_archive.select_all(store, keys) == keys[8:] and day_archive.counts(store)[0] == 8


# --- 3-4. Pagine, formato, abbinamento ----------------------------------------------------------------------

def test_split_three_pages_with_menu_and_footer_and_detect_formats():
    pages = split_pages((FIXTURES / "tre_pagine.txt").read_text(encoding="utf-8"), TODAY)
    assert [page.title for page in pages] == ["Napoli - Roma", "Inter - Milan", "Juventus - Lazio"]
    assert [page.format for page in pages] == ["eurobet", "generico", "sconosciuto"]
    assert pages[0].when == datetime(2026, 10, 28, 18, 30) and pages[2].when == datetime(2026, 10, 29, 15, 0)
    for page in pages:
        assert "Gioco responsabile" not in page.body and "SPORT" not in page.body and "Accedi" not in page.body
        assert "©" not in page.body and "Privacy" not in page.body
    assert detect_format("solo testo qualunque") == "sconosciuto"


def test_year_is_the_closest_date_within_seven_days():
    pages = split_pages("Napoli - Roma\n30/12 20:45\n1X2\n1\n2.10\nX\n3.30\n", date(2027, 1, 3))
    assert pages[0].when == datetime(2026, 12, 30, 20, 45)
    far = split_pages("Napoli - Roma\n15/06 20:45\n1 2.10\nX 3.30\n", date(2026, 10, 27))
    assert far[0].when is None and "lontana più di 7 giorni" in far[0].warnings[0]


def test_assign_pages_names_days_missing_and_ambiguous():
    targets = [Target("utd", "Manchester United", "Tottenham Hotspur", datetime(2026, 10, 28, 16, 0)),
               Target("inter26", "Internazionale", "AC Milan", datetime(2026, 10, 26, 20, 45)),
               Target("inter02", "Internazionale", "AC Milan", datetime(2026, 11, 2, 20, 45)),
               Target("roma18", "SSC Napoli", "AS Roma", datetime(2026, 10, 28, 18, 0)),
               Target("roma21", "SSC Napoli", "AS Roma", datetime(2026, 10, 28, 20, 0))]
    text = ("Man Utd - Tottenham\n28/10 16:00\n1 2.10\nX 3.30\n"
            "Inter - Milan\n02/11 20:45\n1 2.10\nX 3.30\n"
            "Genoa - Venezia\n28/10 15:00\n1 2.10\nX 3.30\n"
            "Napoli - Roma\n28/10 19:00\n1 2.10\nX 3.30\n")
    result = assign_pages(split_pages(text, TODAY), targets)
    assert [(item.status, item.key) for item in result[:3]] == [(STATUS_MATCHED, "utd"), (STATUS_MATCHED, "inter02"),
                                                              (STATUS_MISSING, None)]
    ambiguous = result[3]  # 19:00 è entro 3 ore da entrambe: mai assegnata in silenzio
    assert ambiguous.status == STATUS_AMBIGUOUS and ambiguous.key is None and set(ambiguous.candidates) == {"roma18", "roma21"}


def test_thirteen_pages_assigned_and_read_quickly():
    targets = [Target(f"k{index}", home, away, datetime(2026, month, day, hour, minute)) for index, (home, away, month, day, hour, minute)
               in enumerate([("Manchester United", "Tottenham Hotspur", 10, 25, 16, 0), ("Internazionale", "AC Milan", 10, 26, 20, 45),
                             ("Paris Saint-Germain", "Marseille", 10, 26, 21, 0), ("Atletico Madrid", "Sevilla", 10, 26, 16, 15),
                             ("Bayern Munich", "Borussia Dortmund", 10, 25, 18, 30), ("SSC Napoli", "AS Roma", 10, 26, 18, 0),
                             ("SS Lazio", "Juventus", 10, 26, 15, 0), ("Wolverhampton Wanderers", "Nottingham Forest", 10, 25, 16, 0),
                             ("Real Madrid", "Barcelona", 10, 26, 16, 15), ("Bayer Leverkusen", "RB Leipzig", 10, 25, 15, 30),
                             ("Atalanta BC", "Bologna", 10, 25, 20, 45), ("Fiorentina", "Torino", 10, 27, 18, 30),
                             ("Internazionale", "AC Milan", 11, 2, 20, 45)])]
    started = time.perf_counter()
    pages = split_pages((FIXTURES / "tredici_pagine.txt").read_text(encoding="utf-8"), TODAY)
    result = assign_pages(pages, targets)
    quotes = [eurobet_adapter.from_text(page.body, page.title)[0] for page in pages]
    elapsed = time.perf_counter() - started
    assert len(pages) == 13 and elapsed < 3.0
    correct = sum(item.status == STATUS_MATCHED and item.key == f"k{item.index}" for item in result)
    assert correct >= 12
    assert all(any(quote.mercato == "Over 2.5 gol" for quote in page) for page in quotes)


# --- 2-3. Adattatori -----------------------------------------------------------------------------------------

def test_eurobet_adapter_keeps_suspended_as_none_and_lists_not_simulated():
    page = split_pages((FIXTURES / "tre_pagine.txt").read_text(encoding="utf-8"), TODAY)[0]
    quotes, paste = eurobet_adapter.from_text(page.body, page.title)
    by_market = {quote.mercato: quote.quota for quote in quotes if quote.mercato}
    assert by_market["1"] == 2.10 and by_market["Over 2.5 gol"] == 2.00 and by_market["Goal"] == 1.80
    assert by_market["Somma gol 5+"] == 7.50 and by_market["2-1"] == 8.50
    assert by_market["4-4"] is None and all(quote.quota is None or quote.quota > 1.0 for quote in quotes)
    with pytest.raises(ValueError):
        QuoteMercato("x", "1", None, "1", 0.0, "b", "f", "t")  # mai zero


def test_generic_adapter_needs_the_bookmaker_and_reads_known_labels():
    page = split_pages((FIXTURES / "tre_pagine.txt").read_text(encoding="utf-8"), TODAY)[1]
    with pytest.raises(ValueError):
        generico.from_text(page.body, page.title, "")
    quotes = {quote.mercato: quote.quota for quote in generico.from_text(page.body, page.title, "Snai")}
    assert quotes == {"1": 1.95, "X": 3.40, "2": 4.00, "Over 2.5 gol": 1.80, "Under 2.5 gol": 2.00, "Goal": 1.70, "No Goal": 2.10}


# --- 5. Più bookmaker ----------------------------------------------------------------------------------------

def test_sharp_median_and_spread_warning():
    quotes = [_quote("1", 2.10), _quote("1", 2.05, "pinnacle", "The Odds API"), _quote("X", 3.30), _quote("X", 3.40, "Snai"),
              _quote("X", 3.60, "Bet365"), _quote("2", 3.40), _quote("2", None, "Snai")]
    result = consolidate(quotes, sharp=["pinnacle"])
    assert result["1"].quota == 2.05 and result["1"].riferimento == "Pinnacle"
    assert result["X"].quota == 3.40 and result["X"].riferimento == "mediana di 3 bookmaker"
    assert result["X"].scarto == pytest.approx(0.3 / 3.3, abs=1e-4) and "scarto" in result["X"].avviso
    assert result["1"].avviso == ""  # 2.10 contro 2.05: sotto il 5%
    assert result["2"].quota == 3.40 and list(result["2"].quote) == ["Eurobet"]  # la sospesa non entra
    manual = consolidate([*quotes, _quote("1", 2.30, "a mano", "a mano")], sharp=["pinnacle"])
    assert manual["1"].quota == 2.30


def test_archive_conflicts_change_only_after_confirmation():
    store = {}
    key = day_archive.add_match(store, _match("Napoli", "Roma"))
    assert day_archive.add_quotes(store, key, [_quote("1", 2.10)])["aggiunte"] == 1
    assert day_archive.add_quotes(store, key, [_quote("1", 2.10)])["uguali"] == 1
    assert day_archive.add_quotes(store, key, [_quote("1", 2.20)])["conflitti"] == 1
    assert day_archive.engine_odds(store[key])["1"] == 2.10 and len(store[key]["pending"]) == 1
    day_archive.resolve_pending(store, key, accept=True)
    assert day_archive.engine_odds(store[key])["1"] == 2.20 and store[key]["pending"] == []
    day_archive.add_quotes(store, key, [_quote("1", 2.50)])
    day_archive.resolve_pending(store, key, accept=False)
    assert day_archive.engine_odds(store[key])["1"] == 2.20


# --- 6. The Odds API (finta) -------------------------------------------------------------------------------

def _event(event_id, home, away):
    return {"id": event_id, "home_team": home, "away_team": away, "commence_time": "2026-10-26T18:00:00Z",
            "bookmakers": [{"key": "pinnacle", "title": "Pinnacle", "markets": [
                {"key": "h2h", "outcomes": [{"name": home, "price": 2.05}, {"name": "Draw", "price": 3.4}, {"name": away, "price": 3.8}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": 1.9, "point": 2.5}, {"name": "Under", "price": 1.95, "point": 2.5}]}]}]}


class FakeApi:
    def __init__(self, behaviour="ok"):
        self.calls, self.behaviour = [], behaviour

    def __call__(self, url, params, timeout):
        self.calls.append((url, timeout))
        if self.behaviour == "timeout":
            raise requests.Timeout("lettura scaduta")
        if url.endswith("/odds") and "/events/" not in url:
            body = json.dumps([_event("e1", "Napoli", "Roma")]).encode()
        else:
            body = json.dumps(_event(url.split("/events/")[1].split("/")[0], "Napoli", "Roma")).encode()
        return 200, body, {"x-requests-last": "2", "x-requests-remaining": "480", "x-requests-used": "20"}


def _api(tmp_path, behaviour="ok", now=datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)):
    from datasources.oddsapi import OddsApi

    cache = SourceCache(tmp_path / "c.sqlite", sleep=lambda _: None, min_interval={})
    opener = FakeApi(behaviour)
    return OddsApi(cache, "chiave-di-prova", opener=opener, now=lambda: now), opener


def _day(store):
    sports = ["soccer_italy_serie_a", "soccer_epl", "soccer_spain_la_liga"]
    keys = [day_archive.add_match(store, _match(f"Casa{i}", f"Ospite{i}", sport=sports[i % 3], event=f"e{i}")) for i in range(8)]
    for index, key in enumerate(keys):
        day_archive.set_selection(store, key, selected=True, to_play=index < 5)
    return keys


def test_preconto_for_eight_selected_and_five_to_play(tmp_path):
    api, opener = _api(tmp_path)
    store = {}
    _day(store)
    level_a = quote_collect.plan_level_a(api, day_archive.selected(store))
    level_b = quote_collect.plan_level_b(api, day_archive.to_play(store))
    assert (len(level_a.calls), level_a.total) == (3, 6)       # una chiamata per campionato, h2h + totals
    assert (len(level_b.calls), level_b.total) == (5, 10)      # corner e cartellini: 2 crediti a «Da giocare»
    assert {row["Mercato"] for row in level_b.not_offered} >= {"multigol", "risultati esatti", "cartellini per squadra"}
    check = quote_collect.preconto(api, level_a)
    assert check["tetto_giorno"] == 500 // 30 and check["consentito"] and opener.calls == []
    projection = quote_collect.projection(level_a.total, level_b.total)
    assert projection["totale_mese"] == 480 and projection["entro_budget"]


def test_daily_cap_blocks_every_call(tmp_path):
    api, opener = _api(tmp_path)
    with api.cache._connect() as connection:  # 15 crediti già spesi oggi: il livello A (6) supera il tetto di 16
        connection.execute("INSERT INTO odds_api_usage (at, endpoint, cost, used, remaining) VALUES (?, ?, ?, ?, ?)",
                           (api.now().isoformat(), "/sports/x/odds", 15, 30, 470))
    store = {}
    _day(store)
    plan = quote_collect.plan_level_a(api, day_archive.selected(store))
    outcome = quote_collect.collect(api, plan, store, confirmed=True)
    assert outcome["eseguite"] == 0 and "tetto" in outcome["motivo"] and opener.calls == []
    assert quote_collect.collect(api, plan, store, confirmed=False)["motivo"] == "serve la conferma"


def test_collection_writes_quotes_and_ledger(tmp_path):
    api, opener = _api(tmp_path)
    store = {}
    key = day_archive.add_match(store, _match("Napoli", "Roma", event="e1"))
    day_archive.set_selection(store, key, selected=True)
    outcome = quote_collect.collect(api, quote_collect.plan_level_a(api, day_archive.selected(store)), store, confirmed=True)
    assert outcome["eseguite"] == 1 and outcome["reali"] == 2 and opener.calls[0][1] == 8.0  # timeout breve
    assert day_archive.engine_odds(store[key])["1"] == 2.05 and day_archive.sharp_odds(store[key])["1"] == 2.05
    ledger = quote_collect.ledger_rows(api)
    assert ledger[0]["Livello"] == "A" and ledger[0]["Stimati"] == 2 and ledger[0]["Reali"] == 2


def test_timeout_is_retried_only_once(tmp_path):
    api, opener = _api(tmp_path, behaviour="timeout")
    store = {}
    key = day_archive.add_match(store, _match("Napoli", "Roma", event="e1"))
    day_archive.set_selection(store, key, selected=True)
    outcome = quote_collect.collect(api, quote_collect.plan_level_a(api, day_archive.selected(store)), store, confirmed=True)
    assert len(opener.calls) == 2 and outcome["eseguite"] == 0
    assert outcome["non_raccolte"][0]["Partita"] == "Napoli - Roma"
    assert quote_collect.ledger_rows(api)[0]["Esito"].startswith("non riuscita")


# --- 7. Analizza tutte senza crediti ----------------------------------------------------------------------

ANALYZE = '''
import sys
sys.path.insert(0, {root!r})
import streamlit as st
import day_archive, ui_quotes, ui_today
from multiples import load_settings
from quotes.model import QuoteMercato
from today import TodayMatch
from datetime import datetime, timezone
if "done" not in st.session_state:
    store = ui_quotes.archive()
    when = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)
    for home, away in (("Napoli", "Roma"), ("Napoli", "FC Porto")):
        key = day_archive.add_match(store, TodayMatch(home + away, "soccer_italy_serie_a", "Serie A", when, home, away))
        day_archive.set_selection(store, key, selected=True)
    first = list(store)[0]
    day_archive.set_selection(store, first, to_play=True)
    day_archive.add_quotes(store, first, [QuoteMercato("Napoli - Roma", "1", None, "1", 2.05, "pinnacle", "The Odds API", "x"),
                                          QuoteMercato("Napoli - Roma", "Over 2.5 gol", None, "Over 2.5", 1.90, "Eurobet", "incollata", "x")])
    ui_today._analyze_day(day_archive.selected(store), 2000, load_settings())
    st.session_state["done"] = True
'''


def test_analyze_all_never_calls_credit_endpoints(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import datasources.oddsapi as oddsapi
    import ui_data
    from test_today_speed import FullWeb

    def forbidden(*args, **kwargs):
        raise AssertionError("«Analizza tutte» ha chiamato The Odds API")

    monkeypatch.setattr(oddsapi.OddsApi, "_get", forbidden)
    monkeypatch.setattr(ui_data, "source_cache", lambda: SourceCache(tmp_path / "c.sqlite", opener=FullWeb(),
                                                                     sleep=lambda _: None, min_interval={}))
    script = tmp_path / "oggi.py"
    script.write_text(ANALYZE.format(root=str(ROOT)))
    at = AppTest.from_file(str(script), default_timeout=120).run()
    assert not at.exception
    analyses = at.session_state["today_analyses"]
    napoli, cup = analyses
    assert napoli.ok and not cup.ok and cup.problem[1] == "Elo da risultati"  # coppa: Elo MANCANTE, mai un default
    assert napoli.odds["1"] == 2.05 and napoli.odds["Over 2.5 gol"] == 1.90
    assert napoli.result["event_samples"]  # «Da giocare»: campioni per il combo builder


# --- 8-9. I miei mercati e combo builder -------------------------------------------------------------------

def test_my_markets_have_all_columns_even_without_quotes():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=3000, seed=5))
    rows = my_markets.rows_for("Inter - Milan", result)
    assert all(tuple(row) == my_markets.COLUMNS for row in rows)
    families = {row["Famiglia"] for row in rows}
    assert families == {name for name, _ in my_markets.FAMILIES} | {"Risultati esatti"}
    assert sum(row["Famiglia"] == "Risultati esatti" for row in rows) == 5
    assert all(row["Prob %"] is not None for row in rows) and all(row["Quota"] is None for row in rows)
    quoted = my_markets.rows_for("Inter - Milan", result, consolidate([_quote("Goal", 1.80)]))
    goal = next(row for row in quoted if row["Selezione"] == "Goal")
    assert goal["Quota"] == 1.80 and goal["Bookmaker"] == "Eurobet" and goal["EV %"] is not None


def test_combo_joint_comes_from_samples_not_from_the_product():
    config = replace(config_from_input(parse_match_input(VALID), simulations=20_000, seed=7), keep_samples=True)
    result = simulate_match(config)
    plain = simulate_match(replace(config, keep_samples=False))
    assert result["components"] == plain["components"]  # i campioni non cambiano le probabilità
    data = combo.evaluate(result, ["Over 2.5 gol", "Goal"], odds=2.0)
    over, goal = combo.samples(result, "Over 2.5 gol"), combo.samples(result, "Goal")
    assert data["congiunta"] == pytest.approx(np.mean(over & goal))
    assert data["congiunta"] - data["prodotto"] > 0.03  # correlate: la congiunta supera il prodotto
    assert data["marginali"]["Goal"] * 100 == pytest.approx(result["components"]["finale"]["Goal"], abs=0.01)
    assert data["quota_equa"] == pytest.approx(1 / data["congiunta"]) and data["ev"] == pytest.approx(2.0 * data["congiunta"] - 1)
    with pytest.raises(ValueError):
        combo.evaluate(result, ["Goal"])


# --- 1b. Una sola fonte di verità ---------------------------------------------------------------------------

PARTITA = '''
import sys
sys.path.insert(0, {root!r})
import streamlit as st
import day_archive, manual_data, ui_quotes
from quotes.model import QuoteMercato
from datetime import date
if "seeded" not in st.session_state:
    store = ui_quotes.archive()
    key = day_archive.ensure(store, "Inter", "Milan", date(2026, 10, 26))
    day_archive.add_quotes(store, key, [QuoteMercato("Inter - Milan", "1", None, "1", 2.10, "Eurobet", "incollata", "x"),
                                        QuoteMercato("Inter - Milan", "1", None, "1", 2.05, "pinnacle", "The Odds API", "x")])
    store[key]["manual"] = manual_data.merge(None, {{"home": {{"elo": 1650.0}}}}, "Inter - Milan")
    st.session_state["input_text"] = {block!r}
    st.session_state["seeded"] = True
exec(open({app!r}, encoding="utf-8").read())
'''


def test_same_quote_everywhere_and_manual_data_reach_the_match_page(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from market_catalog import MARKET_CATALOG
    from prediction_log import SaveInfo, prediction_rows
    from ui_quotes import odds_fields

    monkeypatch.setenv("SIMULPRO_CACHE_DB", str(tmp_path / "app.sqlite"))
    block = VALID.split("QUOTE")[0].strip() + "\n"
    script = tmp_path / "partita.py"
    script.write_text(PARTITA.format(root=str(ROOT), block=block, app=str(ROOT / "streamlit_app.py")))
    at = AppTest.from_file(str(script), default_timeout=180).run()
    assert not at.exception
    store = at.session_state["day_archive"]
    entry = next(iter(store.values()))
    # Oggi: campo quota del blocco dall'archivio.
    assert odds_fields(entry)["1"].value == 2.05
    # Pagina Partita: il campo quota «1» parte dalla quota della giornata (sharp).
    token = str(abs(hash(block)))
    definition = next(item for item in MARKET_CATALOG if item.event_key == "1")
    assert at.number_input(key=f"odd_{token}_{definition.key}").value == 2.05
    # Dati a mano di Oggi: mostrati come differenza e applicati solo con il pulsante.
    assert any("Dati inseriti a mano in Oggi" in warning.value for warning in at.warning)
    at.button(key=f"use_day_manual_{entry['key']}").click().run()
    assert "Elo: 1650" in at.session_state["input_text"]
    next(button for button in at.button if button.label == "Esegui simulazione").click().run()
    assert not at.exception
    result, config = at.session_state["result"], at.session_state["result_config"]
    assert config.home.elo == 1650.0 and config.odds["1"] == 2.05
    # I miei mercati e registro: la stessa quota.
    row = next(item for item in my_markets.rows_for("Inter - Milan", result, day_archive.consolidated(entry)) if item["Selezione"] == "1")
    assert row["Quota"] == 2.05
    info = SaveInfo(date(2026, 10, 26), "20:45", "Serie A", "A carta", "test")
    assert prediction_rows(result, ["1"], info, odds=config.odds)[0]["Quota_presa"] == 2.05


def test_archive_roundtrip_in_the_day_excel():
    from match_memory import day_workbook, read_day_workbook

    store = {}
    key = day_archive.add_match(store, _match("Napoli", "Roma"))
    day_archive.set_selection(store, key, selected=True, to_play=True)
    day_archive.add_quotes(store, key, [_quote("1", 2.10), _quote("4-4", None)])
    restored = {}
    day_archive.restore(restored, read_day_workbook(day_workbook([], [], quotes_archive=store)).archive)
    assert restored == store
