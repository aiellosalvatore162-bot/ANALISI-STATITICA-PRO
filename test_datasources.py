"""Test del livello dati con risposte di esempio salvate: nessuna chiamata di rete."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import engine
from datasources.builder import (
    DataProvider, apply_edits, empty_sheet, missing_fields, plausibility_warnings, provenance_rows, render_block,
)
from datasources.cache import SourceCache
from datasources.clubelo import ClubElo, elo_before, parse_catalog, parse_history
from datasources.names import display_name, match_team
from datasources.sources import (
    FootballDataOrg, parse_fixtures, parse_football_data_org, parse_understat,
)
from datasources.stats import recency_weights, referee_profile, team_match_rows, team_profile
from parser import parse_match_input
from tools import calibrate

SAMPLES = Path(__file__).resolve().parent / "tests" / "fixtures" / "sources"
TODAY = date(2026, 10, 21)


def _sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


class FakeWeb:
    """Serve i file di esempio per URL; ogni altro URL fallisce come una fonte giù."""

    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        if url not in self.pages:
            raise ConnectionError("fonte non raggiungibile (test)")
        return self.pages[url]


def _web() -> FakeWeb:
    return FakeWeb({
        "https://clubelo.com/": _sample("clubelo_catalog.html"),
        "https://clubelo.com/Napoli": _sample("clubelo_Napoli.html"),
        "https://clubelo.com/Roma": _sample("clubelo_Roma.html"),
        "https://understat.com/getLeagueData/Serie_A/2026": _sample("understat_serie_a_2026.json"),
        "https://www.football-data.co.uk/mmz4281/2627/I1.csv": _sample("footballdata_I1_2627.csv"),
        "https://www.football-data.co.uk/fixtures.csv": _sample("fixtures.csv"),
    })


def _cache(tmp_path, web=None) -> SourceCache:
    return SourceCache(tmp_path / "cache.sqlite", opener=web or _web(), sleep=lambda _: None, min_interval={})


# --- Cache ---------------------------------------------------------------------------------

def test_cache_serves_fresh_data_and_falls_back_to_stale_copy(tmp_path):
    web = FakeWeb({"https://x/a": b"uno"})
    cache = SourceCache(tmp_path / "c.sqlite", opener=web, sleep=lambda _: None)
    first = cache.get("https://x/a", source="test", max_age=timedelta(hours=24))
    assert first.body == b"uno" and not first.from_cache
    second = cache.get("https://x/a", source="test", max_age=timedelta(hours=24))
    assert second.from_cache and len(web.calls) == 1

    web.pages.clear()  # la fonte non risponde più
    stale = cache.get("https://x/a", source="test", max_age=timedelta(0))
    assert stale.body == b"uno" and stale.from_cache
    assert "non raggiungibile" in stale.warning and "cache" in stale.warning

    missing = cache.get("https://x/b", source="test", max_age=timedelta(0))
    assert missing.body is None and "nessun dato in cache" in missing.warning


def test_cache_pauses_between_requests_to_the_same_source(tmp_path):
    pauses, clock = [], iter([0.0, 0.0, 1.0, 3.0])
    cache = SourceCache(tmp_path / "c.sqlite", opener=FakeWeb({"https://x/1": b"1", "https://x/2": b"2"}),
                        clock=lambda: next(clock), sleep=pauses.append, min_interval={"clubelo": 3.0})
    cache.get("https://x/1", source="clubelo", max_age=timedelta(0))
    cache.get("https://x/2", source="clubelo", max_age=timedelta(0))
    assert pauses == [pytest.approx(2.0)]


def test_custom_matches_are_saved_as_manual(tmp_path):
    cache = _cache(tmp_path)
    match_id = cache.save_custom_match("Alfa", "Beta", "CASA: Alfa\n", competition="Amichevole", match_date="2026-10-25")
    saved = cache.custom_matches()
    assert saved[0]["id"] == match_id and saved[0]["origin"] == "inserita manualmente"
    assert saved[0]["block"] == "CASA: Alfa\n"


# --- Nomi ----------------------------------------------------------------------------------

@pytest.mark.parametrize("query, candidates, expected", [
    ("Man City", ["Manchester City", "Manchester United"], "Manchester City"),
    ("Manchester City", ["ManCity", "ManUnited"], "ManCity"),
    ("Ath Madrid", ["Atletico Madrid", "Athletic Club"], "Atletico Madrid"),
    ("Ath Bilbao", ["Atletico Madrid", "Athletic Club"], "Athletic Club"),
    ("Barcellona", ["Barcelona", "Espanyol"], "Barcelona"),
    ("AEK Atene", ["AEK", "PAOK"], "AEK"),
    ("Bodo/Glimt", ["BodoeGlimt", "Brann"], "BodoeGlimt"),
    ("Nott'm Forest", ["Nottingham Forest"], "Nottingham Forest"),
    ("Real", ["Real Madrid", "Real Sociedad"], None),
])
def test_team_names_match_across_sources(query, candidates, expected):
    assert match_team(query, candidates) == expected


def test_display_name_uses_the_canonical_name():
    assert display_name("Paris SG") == "Paris Saint Germain"
    assert display_name("Squadra Sconosciuta") == "Squadra Sconosciuta"


# --- ClubElo -------------------------------------------------------------------------------

def test_clubelo_catalog_skips_countries_and_reads_full_names():
    catalog = parse_catalog(_sample("clubelo_catalog.html").decode())
    assert catalog["Napoli"] == "Napoli" and catalog["AEK"] == "AEK"
    assert catalog["parma-calcio-1913"] == "Parma"
    assert "ITA" not in catalog and "GRE" not in catalog and "Ranking" not in catalog


def test_clubelo_pre_match_rating_is_the_point_before_the_match_date():
    history = parse_history(_sample("clubelo_Napoli.html").decode())
    day, value = elo_before(history, date(2026, 10, 20))
    assert day < date(2026, 10, 20)
    assert elo_before(history, history[0][0]) is None
    rating = ClubElo(_cache(Path(_tmp_dir()))).rating("Napoli", date(2026, 10, 20))
    assert rating.value == pytest.approx(round(value, 1)) and rating.as_of == day
    assert rating.latest_match == history[-1][0]


def _tmp_dir() -> str:
    import tempfile

    return tempfile.mkdtemp()


# --- Fonti ---------------------------------------------------------------------------------

def test_understat_sample_is_normalized_per_team_and_venue():
    frame = parse_understat(_sample("understat_serie_a_2026.json"))
    assert set(frame["team"]) == {"Napoli", "Roma"}
    assert set(frame["venue"]) == {"home", "away"}
    assert {"xg_for", "xg_against", "ppda", "deep", "goals_for"} <= set(frame.columns)
    assert (frame["xg_for"] >= 0).all()


def test_fixtures_handle_the_byte_order_mark():
    fixtures = parse_fixtures(_sample("fixtures.csv"))
    assert "league" in fixtures.columns
    row = fixtures[fixtures["home_team"] == "Napoli"].iloc[0]
    assert row["league"] == "I1" and row["odds_home"] == pytest.approx(2.30)


def test_football_data_org_is_skipped_without_key(tmp_path):
    web = FakeWeb({})
    result = FootballDataOrg(SourceCache(tmp_path / "c.sqlite", opener=web), key=None).matches(
        "CL", TODAY, TODAY + timedelta(days=7), timedelta(hours=1))
    assert result.data.empty and "chiave" in result.warnings[0] and web.calls == []
    payload = b'{"competition": {"name": "UEFA Champions League"}, "matches": [{"utcDate": "2026-10-20T19:00:00Z", ' \
              b'"homeTeam": {"name": "SSC Napoli"}, "awayTeam": {"name": "FK Bodo/Glimt"}, "status": "FINISHED", ' \
              b'"referees": [{"name": "A. Rossi", "type": "REFEREE"}]}]}'
    parsed = parse_football_data_org(payload)
    assert parsed.iloc[0]["referee"] == "A. Rossi" and parsed.iloc[0]["home_team"] == "SSC Napoli"


# --- Statistiche ---------------------------------------------------------------------------

def test_recency_weights_halve_every_half_life():
    weights = recency_weights(5, half_life=2.0)
    assert weights[-1] == 1.0 and weights[-3] == pytest.approx(0.5)
    assert np.all(np.diff(weights) > 0)


def _matches(rows):
    frame = pd.DataFrame(rows)
    for column in ("ht_goals", "corners", "yellows", "fouls", "xg_real", "sot"):
        for side in ("home", "away"):
            if f"{side}_{column}" not in frame:
                frame[f"{side}_{column}"] = 1.0
    frame["league"] = "I1"
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def test_team_profile_uses_only_venue_matches_before_the_date():
    rows = []
    for day in range(1, 9):
        rows.append({"date": f"2026-09-{day:02d}", "home_team": "Alfa" if day % 2 else "Beta",
                     "away_team": "Beta" if day % 2 else "Alfa", "home_goals": 2, "away_goals": 0})
    rows.append({"date": "2026-10-30", "home_team": "Alfa", "away_team": "Beta", "home_goals": 9, "away_goals": 0})
    profile = team_profile("Alfa", team_match_rows(_matches(rows)), None, as_of=date(2026, 10, 1), venue="home",
                           matches=10, half_life=5)
    # In casa ogni squadra segna 2: attacco = media lega casa = 1.0; il 9-0 futuro è escluso.
    assert profile.fields["attack"].value == pytest.approx(1.0)
    assert profile.last_match == date(2026, 9, 7)
    assert any("solo 4 partite in casa" in warning for warning in profile.warnings)


def test_referee_is_shrunk_toward_competition_mean_and_flagged_when_few_matches():
    rows = []
    for index in range(30):
        rows.append({"date": pd.Timestamp("2026-08-01") + pd.Timedelta(days=index), "referee": "M Rossi" if index < 4 else "Altro",
                     "home_yellows": 4 if index < 4 else 2, "away_yellows": 4 if index < 4 else 2,
                     "home_fouls": 12, "away_fouls": 12})
    profile = referee_profile("M Rossi", pd.DataFrame(rows), as_of=date(2026, 10, 1))
    competition = (4 * 8 + 26 * 4) / 30
    expected = (4 * 8 + 10 * competition) / 14
    assert profile.yellow.value == pytest.approx(round(expected, 2))
    assert profile.yellow.level == "avviso" and "poco affidabile" in profile.yellow.note
    assert profile.competitions["campionato"]["partite"] == 4
    assert profile.competitions["coppe_europee"]["partite"] == 0

    unknown = referee_profile(None, pd.DataFrame(rows), as_of=date(2026, 10, 1))
    assert unknown.yellow.value == pytest.approx(round(competition, 2)) and "media della competizione" in unknown.yellow.note


# --- Scheda e blocco -----------------------------------------------------------------------

def test_provider_builds_a_parser_ready_block_with_sources_and_dates(tmp_path):
    provider = DataProvider(_cache(tmp_path), today=TODAY, football_data_key=None)
    sheet = provider.build("Napoli", "Roma", match_date=date(2026, 10, 25))
    block = render_block(sheet)
    match = parse_match_input(block)
    assert (match.home.name, match.away.name) == ("Napoli", "Roma")
    assert match.odds["1"] == pytest.approx(2.30)  # quote pre-partita dal calendario
    assert sheet.home_fields["elo"].source == "ClubElo"
    assert sheet.home_fields["xg_for"].source == "Understat"
    rows = provenance_rows(sheet)
    elo_row = next(row for row in rows if row["Soggetto"] == "Napoli" and row["Campo"] == "Elo")
    assert elo_row["Aggiornato"] != "—" and elo_row["Ultima partita inclusa"] != "—"
    assert "# Fonti:" in block
    assert not [warning for warning in plausibility_warnings(block) if "mancante" in warning]
    # Le partite di coppa del 20/10 sono in ClubElo ma non nelle statistiche di campionato.
    assert any("non presente nelle statistiche" in warning for warning in sheet.warnings)


def test_refresh_forces_a_new_download(tmp_path):
    web = _web()
    cache = _cache(tmp_path, web)

    def downloads() -> int:  # solo gli URL che rispondono: quelli che falliscono vengono ritentati
        return sum(url in web.pages for url in web.calls)

    DataProvider(cache, today=TODAY, football_data_key=None).build("Napoli", "Roma", match_date=date(2026, 10, 25))
    before = downloads()
    DataProvider(cache, today=TODAY, football_data_key=None).build("Napoli", "Roma", match_date=date(2026, 10, 25))
    assert downloads() == before  # dati più giovani della soglia: nessun nuovo download
    provider = DataProvider(cache, today=TODAY, football_data_key=None)
    provider.refresh()
    provider.build("Napoli", "Roma", match_date=date(2026, 10, 25))
    assert downloads() > before


def test_unknown_team_leaves_fields_missing_and_highlighted(tmp_path):
    sheet = DataProvider(_cache(tmp_path), today=TODAY, football_data_key=None).build(
        "Napoli", "Squadra Inesistente", match_date=date(2026, 10, 25))
    assert sheet.away_fields["attack"].missing and sheet.away_fields["elo"].missing
    assert any(row["Stato"] == "MANCANTE" for row in provenance_rows(sheet))
    assert "Squadra Inesistente · Attacco" in missing_fields(sheet)


def test_manual_edits_complete_an_empty_sheet():
    sheet = empty_sheet("Alfa", "Beta", date(2026, 10, 25))
    values = {"Attacco": "1.2", "Difesa": "1,1", "Elo": "1700", "Forma": "w-d-l", "xG Fatti": "1.5",
              "xG Subiti": "1.2", "Corner pro/sub": "5.0/4.5", "Cartellini pro": "1.8"}
    rows = provenance_rows(sheet)
    for row in rows:
        row["Valore"] = values.get(row["Campo"]) if row["Soggetto"] != "Arbitro" else ("4.2" if row["Campo"] == "Gialli medi" else "23")
    edited, errors = apply_edits(sheet, rows + [{"Soggetto": "Quote", "Campo": "Quota 1", "Valore": "abc"}])
    assert errors == ["Quote · Quota 1: «abc» non è un numero."]
    assert missing_fields(edited) == []
    assert edited.home_fields["elo"].source == "inserito manualmente"
    match = parse_match_input(render_block(edited))
    assert match.home.defense == pytest.approx(1.1) and match.home.form == "W-D-L"


def test_plausibility_flags_out_of_scale_and_missing_values():
    text = """CASA: Alfa
Attacco: 1.2 | Difesa: 1.1 | Elo: 3000 | Forma: W-W | xG Fatti: 25 | xG Subiti: 1.2 | Corner pro/sub: 5/4 | Cartellini pro: 1.5

OSPITE: Beta
Attacco: 1.0 | Difesa: 1.0 | Forma: L | xG Fatti: 1.1 | xG Subiti: 1.3 | Corner pro/sub: 4/5 | Cartellini pro: 2

ARBITRO: Gialli medi 4.0 | Falli medi 22
QUOTE_MERCATI_PRINCIPALI:
Quota 1: 1.00 | Quota X: 3.5
"""
    warnings = plausibility_warnings(text)
    assert "CASA: Elo 3000 fuori dal range accettato (800-2400)." in warnings
    assert "CASA: xG Fatti 25 fuori dal range accettato (0-10) (forse 2.5?)." in warnings
    assert "OSPITE: Elo mancante." in warnings
    assert any("Quota 1 1: sotto 1.01" in warning for warning in warnings)


# --- Corner e cartellini -------------------------------------------------------------------

def test_vectorized_count_model_matches_the_engine():
    params = engine.CountModelParams(active=True, corner_home_intercept=0.4, corner_away_intercept=0.15,
                                     corner_for_weight=0.43, corner_against_weight=0.4, corner_dispersion=50,
                                     card_intercept=0.47, card_team_weight=0.3, card_referee_yellow_weight=0.25,
                                     card_referee_fouls_weight=0.05)
    data = pd.DataFrame({"home_corners_for": [6.0], "home_corners_against": [4.0], "away_corners_for": [5.0],
                         "away_corners_against": [5.5], "home_cards_for": [1.8], "away_cards_for": [2.2],
                         "referee_yellow_avg": [4.4], "referee_fouls_avg": [23.0]})
    means = calibrate.count_means(params, data)
    team = lambda cf, ca, cards: engine.TeamParams("t", 1, 1, 1500, "W", 1.4, 1.4, cf, ca, cards)
    config = engine.MatchConfig(team(6.0, 4.0, 1.8), team(5.0, 5.5, 2.2), 4.4, 23.0, count_model=params)
    home, away = engine.corner_signals(config)
    assert means["corner_home"][0] == pytest.approx(home) and means["corner_away"][0] == pytest.approx(away)
    assert means["cards"][0] == pytest.approx(engine.card_total_mean(config))


def test_negative_binomial_samples_keep_the_mean_and_add_variance():
    rng = np.random.default_rng(1)
    samples = engine._count_samples(rng, 10.0, 5.0, 200_000)
    assert samples.mean() == pytest.approx(10.0, abs=0.05)
    assert samples.var() == pytest.approx(10.0 + 10.0 ** 2 / 5.0, rel=0.03)
    assert engine._count_samples(rng, 10.0, 0.0, 10).dtype.kind == "i"


def test_calibrated_cards_without_inputs_stay_at_zero():
    params = engine.CountModelParams(active=True, card_intercept=0.5, card_team_weight=0.3)
    team = engine.TeamParams("t", 1, 1, 1500, "W", 1.4, 1.4, 5, 5, 0.0)
    assert engine.card_total_mean(engine.MatchConfig(team, team, 4.0, 22.0, count_model=params)) == 0.0


def test_data_older_than_the_threshold_is_downloaded_again(tmp_path):
    web = _web()
    cache = _cache(tmp_path, web)
    url = "https://www.football-data.co.uk/mmz4281/2627/I1.csv"
    cache.store(url, "football-data.co.uk", _sample("footballdata_I1_2627.csv"),
                datetime.now(timezone.utc) - timedelta(hours=30))
    DataProvider(cache, today=TODAY, max_age=timedelta(hours=48), football_data_key=None).build(
        "Napoli", "Roma", match_date=date(2026, 10, 25))
    assert url not in web.calls  # 30 ore < soglia di 48: resta la cache
    DataProvider(cache, today=TODAY, max_age=timedelta(hours=24), football_data_key=None).build(
        "Napoli", "Roma", match_date=date(2026, 10, 25))
    assert url in web.calls  # 30 ore > soglia di 24: riscaricato prima di compilare
