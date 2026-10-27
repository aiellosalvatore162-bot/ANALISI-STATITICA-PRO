"""Fase O: motore minuto per minuto (blocchi di 5 minuti), solo simulazioni e dati sintetici."""

from dataclasses import replace
import time

import numpy as np
import pandas as pd
import pytest

import engine
import timeline
from tools import minute_model


PARAMS = timeline.TimelineParams(
    goal_weights=(0.66, 0.65, 0.66, 0.76, 0.8, 0.8, 0.8, 0.81, 2.18, 1.27, 1.0, 1.01, 0.94, 0.95, 0.94, 0.86, 0.89, 2.02),
    state={-2: (1.12, 1.46, 1.52, 1.49), -1: (1.16, 1.3, 1.31, 1.41), 0: (1.0,) * 4, 1: (0.57, 0.61, 0.64, 0.66),
           2: (0.45, 0.41, 0.42, 0.43)},
    fewer_players=0.63, more_players=1.78, corner_gamma=0.77, card_level=(0.88, 1.0, 1.01, 1.23),
)
INPUTS = dict(lambda_=1.6, mu=1.1, first_share_home=0.45, first_share_away=0.44, corner_home=5.4, corner_away=4.4,
              corner_dispersion=50.0, yellow_mean=4.4, card_dispersion=13.0, red_mean=0.25, card_share=0.48)
N = 100_000


def run(components, scores=None, seed=1):
    return timeline.sample(np.random.default_rng(seed), N, params=PARAMS.with_components(components), scores=scores, **INPUTS)


def dc_scores(seed=2):
    matrix = engine.dixon_coles_matrix(INPUTS["lambda_"], INPUTS["mu"], -0.1, max_goals=12)
    index = np.random.default_rng(seed).choice(matrix.size, size=N, p=(matrix / matrix.sum()).ravel())
    return np.unravel_index(index, matrix.shape)


def test_goal_rules_keep_the_calibrated_means_and_first_half_share():
    out = run(("gol_stato", "espulsioni"))
    assert out["goals_home"].mean() == pytest.approx(1.6, rel=0.02) and out["goals_away"].mean() == pytest.approx(1.1, rel=0.02)
    assert out["first_home"].sum() / out["goals_home"].sum() == pytest.approx(0.45, abs=0.02)
    assert out["corners_home"].mean() + out["corners_away"].mean() == pytest.approx(9.8, rel=0.02)
    assert out["yellows"].mean() == pytest.approx(4.4, rel=0.02)
    assert (out["reds_home"] + out["reds_away"]).mean() == pytest.approx(0.25, rel=0.05)


def test_without_goal_rules_the_dixon_coles_scores_are_kept():
    home, away = dc_scores()
    out = run(("corner_pressione",), scores=(home, away))
    assert np.array_equal(out["goals_home"], home) and np.array_equal(out["goals_away"], away)
    assert out["first_home"].sum() / home.sum() == pytest.approx(0.45, abs=0.01)
    with pytest.raises(ValueError, match="punteggi finali"):
        run(("corner_pressione",))


def test_score_state_changes_the_second_half():
    on, off = run(("gol_stato",)), run(("espulsioni",), seed=3)
    def ratio(out):
        second = out["goals_home"] - out["first_home"]
        leading = out["first_home"] > out["first_away"]
        level = out["first_home"] == out["first_away"]
        return second[leading].mean() / second[level].mean()
    assert ratio(on) < 0.85 and ratio(off) == pytest.approx(1.0, abs=0.06)


def test_a_red_card_lowers_the_attack_of_the_team_with_ten():
    out = run(("espulsioni",), seed=4)
    sent_off = out["reds_home"] > 0
    assert out["goals_home"][sent_off].mean() < out["goals_home"][~sent_off].mean() * 0.95
    assert out["goals_away"][sent_off].mean() > out["goals_away"][~sent_off].mean()


def test_corners_follow_offensive_pressure_and_cards_the_balance():
    home, away = dc_scores(5)
    on = run(("corner_pressione", "cartellini_tempo"), scores=(home, away), seed=6)
    off = run(("corner_pressione",), scores=(home, away), seed=6)
    trailing, leading = home < away, home > away
    assert on["corners_home"][trailing].mean() > on["corners_home"][leading].mean() + 0.2
    assert on["yellows"].mean() == pytest.approx(off["yellows"].mean(), rel=0.02)
    draw = home == away
    assert on["yellows"][draw].mean() > on["yellows"][~draw].mean()
    plain = run(("espulsioni",), seed=7)   # senza corner_pressione: corner indipendenti dal punteggio
    behind = plain["goals_home"] < plain["goals_away"]
    assert plain["corners_home"][behind].mean() == pytest.approx(plain["corners_home"][~behind].mean(), rel=0.03)


def test_engine_option_is_off_by_default_and_fast_when_on():
    team = lambda name, elo: engine.TeamParams(name, 1.2, 1.0, elo, "W-D-W-L-W", 1.6, 1.1, 5.5, 4.5, 2.0)
    config = engine.MatchConfig(team("A", 1850), team("B", 1750), 4.4, 24.0, odds={"1": 1.9, "X": 3.6, "2": 4.2},
                                simulations=100_000)
    plain = engine.simulate_match(replace(config, timeline=timeline.TimelineParams()))
    assert plain["timeline"] == {"active": False}
    loaded = timeline.load(engine.GOAL_MODEL_PATH)
    full = replace(loaded if loaded.goal_weights != (1.0,) * 18 else PARAMS, active=True, components=timeline.COMPONENTS)
    start = time.time()
    result = engine.simulate_match(replace(config, timeline=full))
    assert time.time() - start < 6.0
    assert result["timeline"]["active"] and result["model"]["lambda"] == plain["model"]["lambda"]
    goals = result["dashboard"]["goals_distribution"]["home"]
    mean = sum(index * value for index, value in enumerate(goals)) / 100
    assert mean == pytest.approx(result["model"]["lambda"], rel=0.03)


def test_block_mapping_and_state_estimation_on_synthetic_minutes():
    assert minute_model.block_of(1) == 0 and minute_model.block_of(45) == 8 and minute_model.block_of(46) == 9
    assert minute_model.block_of(93) == 17 and minute_model.band_of(31) == 1 and minute_model.band_of(90) == 3
    rng = np.random.default_rng(9)
    rows = []
    for team_match in range(3000):
        base = rng.uniform(0.01, 0.03)
        state = 0
        for minute in range(1, 91):
            multiplier = 1.4 if state < 0 else 0.6 if state > 0 else 1.0
            count = rng.poisson(base * multiplier * 8)
            rows.append({"team_match": team_match, "match": team_match, "minute": minute, "block": minute_model.block_of(minute),
                         "band": minute_model.band_of(minute), "state": state, "advantage": 0, "xg": count})
            if rng.random() < 0.02:
                state = int(np.clip(state + rng.choice([-1, 1]), -2, 2))
    fitted = minute_model.fit_state_model(pd.DataFrame(rows), "xg", shrink=1.0, with_advantage=False)
    assert np.mean(fitted["stato"]["-1"]) == pytest.approx(1.4, abs=0.12)
    assert np.mean(fitted["stato"]["1"]) == pytest.approx(0.6, abs=0.08)
