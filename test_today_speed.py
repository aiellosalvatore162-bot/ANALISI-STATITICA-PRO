"""Fase V/L: today.prepare, tabella «Partite non analizzate», fasi di «Tempi». Solo fixture, nessuna rete."""

from datetime import date, datetime, timezone
from pathlib import Path
import time

import pytest
import requests

import engine
import timing
import today
from datasources.builder import DataProvider
from datasources.cache import SourceCache
from test_datasources import SAMPLES, _sample
from today import TodayMatch, analyze, prepare, problem_rows

TODAY = date(2026, 10, 21)


class FullWeb:
    """Tutte le fonti dagli esempi (ogni stagione e campionato), ClubElo bloccato (403)."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        if "clubelo.com" in url:
            raise requests.HTTPError(f"403 Client Error: Forbidden for url: {url}")
        if "understat.com" in url:
            return _sample("understat_serie_a_2026.json")
        if url.endswith("fixtures.csv"):
            return _sample("fixtures.csv")
        if "football-data.co.uk" in url:
            return _sample("footballdata_P1_2627.csv" if url.endswith("/P1.csv") else "footballdata_I1_2627.csv")
        raise ConnectionError("fonte sconosciuta (test)")


def _cache(path, web) -> SourceCache:
    return SourceCache(path, opener=web, sleep=lambda _: None, min_interval={})


def _match(home: str, away: str) -> TodayMatch:
    when = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)
    return TodayMatch(f"{home}-{away}", "soccer", "Serie A", when, home, away)


def _provider(path, web) -> DataProvider:
    return DataProvider(_cache(path, web), today=TODAY, football_data_key=None)


def test_prepare_never_simulates_or_touches_the_odds_api(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("prepare non deve simulare né usare The Odds API")

    monkeypatch.setattr(today, "simulate_match", boom)
    monkeypatch.setattr(today, "simulate", boom)
    monkeypatch.setattr(engine, "simulate_match", boom)
    monkeypatch.setattr("datasources.oddsapi.OddsApi", boom)
    monkeypatch.setattr("datasources.oddsapi.sheet_odds", boom)
    analysis = prepare(_match("Napoli", "Roma"), _provider(tmp_path / "c.sqlite", FullWeb()).build, {}, simulations=2000)
    assert analysis.config is not None and analysis.result is None and analysis.problem is None
    assert analysis.block.startswith("#") and not analysis.ok


def test_after_prepare_analyze_makes_no_http_requests(tmp_path):
    db = tmp_path / "c.sqlite"
    first = FullWeb()
    prepared = prepare(_match("Napoli", "Roma"), _provider(db, first).build, {}, simulations=2000)
    assert prepared.config is not None and first.calls  # il primo giro ha scaricato
    second = FullWeb()  # nuova sessione: stessa cache SQLite, provider nuovo
    analysis = analyze(_match("Napoli", "Roma"), _provider(db, second).build, {}, simulations=2000)
    assert analysis.ok and second.calls == []
    # Stessi dati, stesso seed: la preparazione non cambia il risultato.
    alone = analyze(_match("Napoli", "Roma"), _provider(tmp_path / "altro.sqlite", FullWeb()).build, {}, simulations=2000)
    assert alone.result["components"] == analysis.result["components"]


def test_one_analyzed_and_two_rows_for_source_error_and_missing_elo(tmp_path):
    provider = _provider(tmp_path / "c.sqlite", FullWeb())

    def build(home, away, **kwargs):
        if home == "Rotta":
            raise ConnectionError("football-data.co.uk non raggiungibile")
        return provider.build(home, away, **kwargs)

    matches = [_match("Napoli", "Roma"), _match("Rotta", "Roma"), _match("Napoli", "FC Porto")]  # ultima: coppa tra campionati
    analyses = [analyze(match, build, {}, simulations=2000) for match in matches]
    assert [analysis.ok for analysis in analyses] == [True, False, False]
    rows = problem_rows(analyses)
    assert len(rows) == 2 and {row["Partita"] for row in rows} == {"Rotta - Roma", "Napoli - FC Porto"}
    error = next(row for row in rows if row["Partita"] == "Rotta - Roma")
    assert error["Fase"] == "dati automatici" and "ConnectionError" in error["Messaggio"]
    elo = next(row for row in rows if row["Partita"] == "Napoli - FC Porto")
    assert (elo["Fase"], elo["Fonte"]) == ("dati", "Elo da risultati")
    assert elo["Messaggio"] == "Elo MANCANTE: inseriscilo a mano nel blocco CASA/OSPITE"
    assert all(analysis.skipped for analysis in analyses[1:])  # il motivo resta anche in ``skipped``


def test_unexpected_errors_are_isolated_too(tmp_path, monkeypatch):
    monkeypatch.setattr(today, "simulate", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    analysis = analyze(_match("Napoli", "Roma"), _provider(tmp_path / "c.sqlite", FullWeb()).build, {}, simulations=2000)
    assert not analysis.ok and analysis.problem[:2] == ("simulazione", "motore")
    assert problem_rows([analysis])[0]["Partita"] == "Napoli - Roma"


def test_timing_phases_add_up_to_the_total(tmp_path):
    db = tmp_path / "c.sqlite"
    matches = [_match("Napoli", "Roma"), _match("Roma", "Napoli"), _match("Napoli", "Roma")]
    for match in matches[:1]:  # riscaldamento: import e prime letture fuori dalla misura
        analyze(match, _provider(db, FullWeb()).build, {}, simulations=2000)
    provider = _provider(db, FullWeb())
    with timing.registra() as registro:
        started = time.perf_counter()
        for match in matches:
            analyze(match, provider.build, {}, simulations=2000)
        total = time.perf_counter() - started
    rows = registro.breakdown(total)
    leaves = [row for row in rows if row["Fase"] not in ("TOTALE", "altro (cicli, tabelle)")]
    other = next(row["Secondi"] for row in rows if row["Fase"].startswith("altro"))
    names = {row["Fase"] for row in leaves}
    assert {"simulazione", "blocco e configurazione", "Elo ClubElo"} <= names and "dati automatici (totale)" not in names
    assert other <= 0.05 * total  # quasi tutto il tempo è attribuito a una fase
    assert sum(row["Secondi"] for row in rows[:-1]) == pytest.approx(rows[-1]["Secondi"], abs=0.02)
    sources = {row["Fonte"]: row for row in registro.sources()}
    assert "clubelo" not in sources  # già segnato «non disponibile» nella cache: nessuna richiesta a ClubElo


def test_problem_table_and_timing_expander_render(tmp_path):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "pagina.py"
    script.write_text(
        "import sys\nsys.path.insert(0, %r)\nimport streamlit as st\nimport ui_today\n"
        "st.session_state['today_problems'] = [{'Partita': 'A - B', 'Fase': 'dati', 'Fonte': 'Elo da risultati', "
        "'Messaggio': 'Elo MANCANTE: inseriscilo a mano nel blocco CASA/OSPITE'}]\n"
        "st.session_state['today_timing'] = {'label': 'Analizza tutte', 'total': 6.5, 'matches': 13, "
        "'phases': [{'Fase': 'simulazione', 'Secondi': 5.0}, {'Fase': 'TOTALE', 'Secondi': 6.5}], "
        "'sources': [{'Fonte': 'understat', 'Richieste HTTP': 0, 'Hit di cache': 8, 'Errori': 0, 'Secondi': 0.0}]}\n"
        "ui_today._render_problems()\nui_today._render_timing()\n" % str(Path(__file__).parent))
    at = AppTest.from_file(str(script), default_timeout=60).run()
    assert not at.exception
    assert any("Partite non analizzate (1)" in header.value for header in at.subheader)
    expander = at.expander[0]
    assert expander.label.startswith("Tempi · Analizza tutte: 6.5 s per 13 partite") and len(at.dataframe) == 3
