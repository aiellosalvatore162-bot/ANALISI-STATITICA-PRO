"""Fase AK, stadi 12-13: buon senso calcistico del motore a eventi acceso su partite tipo (``tools.event_sense``)."""

from dataclasses import replace

import numpy as np
import pytest

import engine
import event_engine as ee
from tools import event_sense

N = 20_000


def _run(name, active=True, **changes):
    config = event_sense.scenario_config(name, N, active=active)
    if active:
        config = replace(config, event_engine=replace(config.event_engine, tolerance_pp=0.0, pilot=5_000, **changes))
    return engine.simulate_match(config)


@pytest.fixture(scope="module")
def runs():
    return {name: _run(name) for name in ("favorita netta", "chiusa", "arbitro severo", "arbitro permissivo")}


def test_attenuazione_degli_stati_stimata_e_applicata():
    raw, used = ee.load("I1", attenuate=False), ee.load("I1")
    assert raw.state_power == 1.0 and 0.3 < used.state_power < 0.8
    for before, after in ((raw.state_shots, used.state_shots), (raw.state_corner, used.state_corner)):
        assert all(abs(np.log(a)) <= abs(np.log(b)) + 1e-12 for a, b in zip(after, before))
        assert np.sign(np.log(after)).tolist() == np.sign(np.log(before)).tolist()
    assert used.with_state_power(1.0).state_shots == pytest.approx(raw.state_shots)
    # Gialli: esponente proprio del legame cartellini (stimato sui CSV), non quello comune.
    power = used.yellow_state_power
    assert power is not None and used.red_heat >= 1.0
    assert used.state_yellow == pytest.approx(tuple(value ** power for value in raw.state_yellow))
    assert used.with_card_link(None, 1.0).state_yellow == pytest.approx(
        tuple(value ** used.state_power for value in raw.state_yellow))


def test_punteggi_identici_e_medie_attuali(runs):
    off = _run("favorita netta", active=False)
    on = runs["favorita netta"]
    assert on["sample_size"] == off["sample_size"] == N
    for key in ("1", "X", "2"):
        assert on["markets"]["1x2"][key] == off["markets"]["1x2"][key]
    assert on["exact_scores"]["finale"] == off["exact_scores"]["finale"]
    assert on["markets"]["corners"]["mean"] == pytest.approx(off["markets"]["corners"]["mean"], rel=0.03)
    assert on["markets"]["cards"]["mean"] == pytest.approx(off["markets"]["cards"]["mean"], rel=0.04)


def test_chi_e_sotto_spinge_chi_e_avanti_gestisce(runs):
    sample = runs["favorita netta"]["event_engine_sample"]
    second = sample["corners_home"] - sample["corners_first_home"]
    behind, level, ahead = (sample["first_home"] < sample["first_away"], sample["first_home"] == sample["first_away"],
                            sample["first_home"] > sample["first_away"])
    assert second[behind].mean() > second[level].mean() > second[ahead].mean()
    # Correlazione negativa ma moderata tra differenza reti e differenza corner (reale circa −0,16 sui residui).
    correlation = np.corrcoef(sample["goals_home"] - sample["goals_away"], sample["corners_home"] - sample["corners_away"])[0, 1]
    assert -0.35 < correlation < -0.05


def test_espulsione_presto_cambia_la_partita(runs):
    sample = runs["chiusa"]["event_engine_sample"]
    early = sample["first_red_minute_home"] < 30
    assert early.sum() >= 30
    assert sample["shots_home"].sum(axis=1)[early].mean() < 0.85 * sample["shots_home"].sum(axis=1).mean()
    assert sample["corners_away"][early].mean() > 1.1 * sample["corners_away"].mean()


def test_arbitro_severo_contro_permissivo(runs):
    strict, loose = runs["arbitro severo"]["event_engine_sample"], runs["arbitro permissivo"]["event_engine_sample"]
    yellows = lambda s: (s["yellows_home"] + s["yellows_away"]).mean()
    reds = lambda s: ((s["reds_home"] + s["reds_away"]) > 0).mean()
    assert yellows(strict) > 1.1 * yellows(loose) and reds(strict) > reds(loose)


def test_ritmo_della_partita(runs):
    fav, closed = runs["favorita netta"]["event_engine_sample"], runs["chiusa"]["event_engine_sample"]
    # Primo gol prima nella partita con più gol attesi; meno gol nel primo tempo che nel secondo; gialli soprattutto nel 2T.
    assert np.nanmean(fav["first_goal_minute"]) < np.nanmean(closed["first_goal_minute"])
    for sample in (fav, closed):
        first = (sample["first_home"] + sample["first_away"]).sum() / (sample["goals_home"] + sample["goals_away"]).sum()
        assert 0.38 < first < 0.48
        cards = (sample["yellows_first_home"] + sample["yellows_first_away"]).sum() / (sample["yellows_home"] + sample["yellows_away"]).sum()
        assert 0.30 < cards < 0.45
        corners = (sample["corners_first_home"] + sample["corners_first_away"]).sum() / (sample["corners_home"] + sample["corners_away"]).sum()
        assert 0.42 < corners < 0.52


def test_partita_calda_lega_gialli_e_rossi():
    params = ee.load("I1")
    rng = np.random.default_rng(4)
    scores = (rng.poisson(1.3, N), rng.poisson(1.2, N))
    team = ee.TeamInput(1.3, first_share=0.45), ee.TeamInput(1.2, first_share=0.45)

    def ratio(mix):
        s = ee.simulate(np.random.default_rng(5), N, *team, params, scores=scores, mix=mix)
        yellows, reds = s["yellows_home"] + s["yellows_away"], s["reds_home"] + s["reds_away"]
        return yellows[reds > 0].mean() / yellows[reds == 0].mean()

    assert ratio({"corner": 0.0, "cards": 0.3}) > ratio(None) + 0.03
