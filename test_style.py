"""Test dei profili di stile con dati di esempio salvati (nessuna rete)."""

from datetime import date, timedelta
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from datasources.builder import DataProvider, render_block
from datasources.cache import SourceCache
from datasources.sources import parse_understat
from datasources.stats import team_match_rows
from datasources.style import (
    METRICS, ProfileStore, StyleProfile, archetype_name, assign_archetype, describe, footballdata_metrics, kmeans,
    league_profiles, radar_percentiles, silhouette, understat_league_metrics, understat_team_metrics,
)
from parser import parse_match_input
from tools import dataset
from tools.style import build_archetypes

SAMPLES = Path(__file__).resolve().parent / "tests" / "fixtures" / "sources"


def _sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def test_understat_team_shares_from_situations_and_attack_speed():
    payload = json.loads(_sample("understat_team_Napoli_2026.json"))
    metrics = understat_team_metrics(payload)
    situation = payload["statistics"]["situation"]
    expected = sum(situation[key]["xG"] for key in ("FromCorner", "SetPiece", "DirectFreekick") if key in situation)
    assert metrics["set_pieces"] == pytest.approx(expected / sum(value["xG"] for value in situation.values()))
    assert 0.0 <= metrics["transitions"] <= 1.0
    assert understat_team_metrics({"statistics": {}}) == {}


def test_understat_league_metrics_use_ppda():
    rows = parse_understat(_sample("understat_serie_a_2026.json"))
    metrics = understat_league_metrics(rows, "Napoli")
    napoli = rows[rows["team"] == "Napoli"]
    assert metrics["pressing"] == pytest.approx(-np.log(napoli["ppda"].mean()))
    assert metrics["build_up"] == pytest.approx(np.log(napoli["ppda_allowed"].mean()))


def test_footballdata_metrics_and_first_half_share_smoothing():
    raw = dataset.frame_from_csv(_sample("footballdata_P1_2627.csv"), "P1", "2627")
    rows = team_match_rows(dataset.clean_frames([raw]))
    metrics = footballdata_metrics(rows, "Porto")
    porto = rows[rows["team"] == "Porto"]
    assert metrics["corners_for"] == pytest.approx(porto["corners_for"].mean())
    assert metrics["first_half_share"] == pytest.approx((porto["ht_goals_for"].sum() + 0.9) / (porto["goals_for"].sum() + 2))
    assert metrics["matches"] == len(porto)


def _raw_league(seed: int = 0, teams: int = 12, understat: bool = True) -> dict:
    rng = np.random.default_rng(seed)
    raw = {}
    for index in range(teams):
        values = {"corners_for": rng.normal(5, 1), "corners_against": rng.normal(5, 1), "fouls": rng.normal(12, 2),
                  "cards": rng.normal(2, 0.4), "first_half_share": rng.uniform(0.3, 0.6), "xg_for": rng.normal(1.4, 0.3),
                  "xg_against": rng.normal(1.4, 0.3), "shots": rng.normal(12, 2), "matches": 20}
        if understat:
            values |= {"pressing": rng.normal(-2.4, 0.2), "deep_allowed": rng.normal(6, 2), "build_up": rng.normal(2.4, 0.3),
                       "transitions": rng.uniform(0.05, 0.2), "set_pieces": rng.uniform(0.1, 0.35)}
        raw[f"Squadra {index}"] = values
    return raw


def test_league_profiles_are_z_scores_and_flag_partial_profiles():
    profiles = league_profiles(_raw_league(), "Lega", partial=False)
    pressing = np.array([profile.z["pressing"] for profile in profiles.values()])
    assert pressing.mean() == pytest.approx(0.0, abs=1e-9) and pressing.std() == pytest.approx(1.0)
    assert all(not profile.partial and "block_height" in profile.z for profile in profiles.values())

    partial = league_profiles(_raw_league(understat=False), "Lega", partial=True)
    profile = next(iter(partial.values()))
    assert profile.partial and "pressing" in profile.missing and "corners_for" in profile.z
    assert "Profilo parziale" in describe(profile)


def test_kmeans_and_silhouette_find_separated_groups():
    rng = np.random.default_rng(3)
    centers = np.array([[3, 0], [-3, 0], [0, 4]])
    points = np.vstack([center + rng.normal(0, 0.3, (20, 2)) for center in centers])
    scores = {k: silhouette(points, kmeans(points, k)[0]) for k in range(2, 6)}
    assert max(scores, key=scores.get) == 3
    labels = kmeans(points, 3)[0]
    assert len(set(labels[:20])) == 1 and len(set(labels)) == 3


def test_archetype_names_and_assignment():
    assert archetype_name({"pressing": 1.2, "build_up": 0.9, "fouls": 0.1}) == "Pressing alto e possesso manovrato"
    assert archetype_name({"pressing": 0.1}) == "Profilo equilibrato"
    archetypes = {"features": ["pressing", "build_up", "fouls"], "groups": [
        {"name": "Pressing alto", "centroid": {"pressing": 1.0, "build_up": 0.5, "fouls": 0.0}},
        {"name": "Blocco basso", "centroid": {"pressing": -1.0, "build_up": -0.5, "fouls": 0.0}},
    ]}
    profile = StyleProfile("A", "Lega", {}, {"pressing": 0.8, "build_up": 0.4, "fouls": 0.1}, False, 20, "2026-10-21")
    assert assign_archetype(profile, archetypes).archetype == "Pressing alto"
    partial = StyleProfile("B", "Lega", {}, {"fouls": 1.0}, True, 20, "2026-10-21")
    assert assign_archetype(partial, archetypes).archetype is None


def test_build_archetypes_chooses_k_by_silhouette():
    rng = np.random.default_rng(5)
    keys = ["pressing", "block_height", "build_up", "transitions", "set_pieces", "fouls", "cards"]
    profiles = []
    for group, center in enumerate((np.full(7, 1.5), np.full(7, -1.5))):
        for index in range(15):
            values = center + rng.normal(0, 0.3, 7)
            profiles.append(StyleProfile(f"T{group}{index}", "Lega", {}, dict(zip(keys, values)), False, 20, "2026-10-21"))
    result = build_archetypes(profiles)
    assert result["k"] == 2 and len(result["groups"]) == 2
    assert {group["size"] for group in result["groups"]} == {15}
    assert result["features"] == keys


def test_profile_store_respects_the_refresh_threshold(tmp_path):
    store = ProfileStore(SourceCache(tmp_path / "c.sqlite", opener=lambda *args: b""))
    profiles = league_profiles(_raw_league(), "Lega", partial=False)
    store.save(profiles)
    loaded = store.load("Lega", timedelta(hours=24))
    assert set(loaded) == set(profiles)
    assert loaded["Squadra 0"].z == pytest.approx(profiles["Squadra 0"].z)
    assert store.load("Lega", timedelta(0)) is None


def test_radar_percentiles_map_z_to_0_100():
    profile = StyleProfile("A", "Lega", {}, {"pressing": 0.0, "fouls": 1.96}, False, 20, "2026-10-21")
    percentiles = radar_percentiles(profile)
    assert percentiles["pressing"] == pytest.approx(50.0) and percentiles["fouls"] == pytest.approx(97.5, abs=0.1)
    assert {metric.key for metric in METRICS} >= set(percentiles)


def test_teams_outside_understat_leagues_get_their_block_from_footballdata(tmp_path):
    web_pages = {"https://www.football-data.co.uk/mmz4281/2627/P1.csv": _sample("footballdata_P1_2627.csv")}

    def opener(url, headers, timeout):
        if url not in web_pages:
            raise ConnectionError("non disponibile nel test")
        return web_pages[url]

    cache = SourceCache(tmp_path / "c.sqlite", opener=opener, sleep=lambda _: None, min_interval={})
    sheet = DataProvider(cache, today=date(2026, 10, 21), football_data_key=None).build(
        "FC Porto", "Benfica", match_date=date(2026, 10, 25))
    for side in (sheet.home_fields, sheet.away_fields):
        for key in ("attack", "defense", "xg_for", "cards_for", "corners", "form"):
            assert not side[key].missing, key
        assert side["xg_for"].source.startswith("football-data.co.uk")
    # ClubElo non risponde nel test: stesso campionato, quindi Elo calcolato dai risultati e segnalato.
    assert sheet.home_fields["elo"].source == "Elo calcolato dai risultati (ripiego)"
    assert any("ClubElo non disponibile" in warning for warning in sheet.warnings)
    match = parse_match_input(render_block(sheet))
    assert match.home.name == "Porto" and match.home.corners_for > 0
    profiles = DataProvider(cache, today=date(2026, 10, 21), football_data_key=None).style_profiles("Primeira Liga")
    porto = profiles["Porto"]
    assert porto.partial and "pressing" in porto.missing and "corners_for" in porto.z


def test_forced_refresh_invalidates_style_profiles(tmp_path):
    pages = {"https://www.football-data.co.uk/mmz4281/2627/P1.csv": _sample("footballdata_P1_2627.csv")}

    def opener(url, headers, timeout):
        if url not in pages:
            raise ConnectionError("non disponibile nel test")
        return pages[url]

    cache = SourceCache(tmp_path / "c.sqlite", opener=opener, sleep=lambda _: None, min_interval={})
    DataProvider(cache, today=date(2026, 10, 21), football_data_key=None).style_profiles("Primeira Liga")
    store = ProfileStore(cache)
    assert store.load("Primeira Liga", timedelta(hours=24)) is not None
    provider = DataProvider(cache, today=date(2026, 10, 21), football_data_key=None)
    provider.refresh()
    provider.build("FC Porto", "Benfica", match_date=date(2026, 10, 25))
    assert store.load("Primeira Liga", timedelta(hours=24)) is None
