import numpy as np

import engine
from engine import _event_catalog, config_from_input, simulate_match, smart_combo
from parser import parse_match_input

from test_parser import COMPLETE_COPY_BLOCK, VALID


def test_simulation_is_reproducible_and_auditable():
    match = parse_match_input(VALID)
    config = config_from_input(match, simulations=3000, seed=11)
    first = simulate_match(config)
    second = simulate_match(config)
    assert first == second
    assert first["model"]["simulation_count"] == 3000
    assert first["model"]["formula_ledger"]["weights"]["xg"] == 0.20
    assert set(first["markets"]["1x2"]) == {"1", "X", "2"}
    assert set(first["markets"]["first_half_1x2"]) == {"1", "X", "2"}
    assert set(first["markets"]["first_half_goal_no_goal"]) == {"Goal", "No_Goal"}
    assert set(first["markets"]["multigol"]) == {"1-2", "1-3", "2-4", "2-5"}
    assert "Over_10.5" in first["markets"]["corners"]
    assert "Under_6.5" in first["markets"]["cards"]


def test_probabilities_use_the_declared_sample_size():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=2000, seed=3))
    assert sum(item["count"] for item in result["markets"]["1x2"].values()) == 2000
    assert result["summary"]["modal_score"]["share_pct"] > 0
    score_distribution = result["dashboard"]["exact_score_distribution"]
    assert score_distribution["labels"] == [*(str(value) for value in range(8)), "8+"]
    assert abs(sum(map(sum, score_distribution["probabilities_pct"])) - 100.0) < 0.01
    goal_distribution = result["dashboard"]["goals_distribution"]
    assert goal_distribution["goals"][-1] == "8+"
    assert abs(sum(goal_distribution["home"]) - 100.0) < 0.01
    assert abs(sum(goal_distribution["away"]) - 100.0) < 0.01
    for market in result["markets"]["1x2"].values():
        low, high = market["confidence_interval_95"]
        assert 0 <= low <= high <= 100
        assert 0 <= market["reliability_pct"] <= 100
        assert market["fair_odds"] > 1.0


def test_score_derived_markets_are_coherent_for_every_simulation():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=4000, seed=17))
    markets = result["markets"]
    simulation_count = result["model"]["simulation_count"]

    assert sum(markets["1x2"][key]["count"] for key in ("1", "X", "2")) == simulation_count
    assert markets["double_chance"]["1X"]["count"] + markets["double_chance"]["X2"]["count"] >= simulation_count
    assert markets["goal_no_goal"]["Goal"]["count"] + markets["goal_no_goal"]["No_Goal"]["count"] == simulation_count
    assert markets["over_under"]["Over_2.5"]["count"] + markets["over_under"]["Under_2.5"]["count"] == simulation_count
    assert sum(markets["goal_sums"][str(value)]["count"] for value in range(5)) + markets["goal_sums"]["5+"]["count"] == simulation_count
    assert markets["multigol_complete"]["2-3"]["count"] <= markets["over_under"]["Over_1.5"]["count"]


def test_exact_score_two_one_activates_all_dependent_markets():
    one = lambda value: np.array([value])
    events = _event_catalog(one(2), one(1), one(1), one(0), one(1), one(1), one(4), one(3), one(2), one(1))

    assert events["1"][0]
    assert not events["X2"][0]
    assert events["Casa DNB"][0]
    assert events["Over 2.5 gol"][0]
    assert events["Goal"][0]
    assert events["Multigol 2-3"][0]
    assert events["Multigol Casa 1-2"][0]
    assert events["Somma gol 3"][0]


def test_team_multigol_ranges_are_dynamic_and_reach_financial_analysis():
    config = config_from_input(parse_match_input(VALID), simulations=3000, seed=21)
    config = config.__class__(
        **{
            **config.__dict__,
            "odds": {
                "Multigol Casa 1-4": 1.75,
                "Multigol Ospite 3-4": 2.40,
            },
        }
    )
    result = simulate_match(config)

    assert {"Casa 1-4", "Ospite 3-4"}.issubset(result["markets"]["team_multigol"])
    financial = {row["market"]: row for row in result["financial"]["markets"]}
    assert {"Multigol Casa 1-4", "Multigol Ospite 3-4"} == set(financial)
    for row in financial.values():
        assert row["fair_odds"] is not None
        assert len(row["confidence_interval_95"]) == 2
        assert "recommended_quarter_kelly_pct" in row


def test_complete_market_catalog_exposes_all_requested_families():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=2000, seed=9))
    markets = result["markets"]
    assert set(markets["double_chance"]) == {"1X", "X2", "12"}
    assert set(markets["second_half_1x2"]) == {"1", "X", "2"}
    assert set(markets["second_half_double_chance"]) == {"1X", "X2", "12"}
    assert set(markets["over_under"]) == {
        "Over_0.5", "Under_0.5", "Over_1.5", "Under_1.5",
        "Over_2.5", "Under_2.5", "Over_3.5", "Under_3.5",
        "Over_4.5", "Under_4.5",
    }
    assert set(markets["multigol_complete"]) == {
        "1-2", "1-3", "1-4", "1-5", "2-3", "2-4", "2-5", "2-6",
        "3-4", "3-5", "3-6",
    }
    assert set(markets["goal_sums"]) == {"0", "1", "2", "3", "4", "5+"}
    assert len(markets["combos"]) >= 10
    assert set(markets["corner_1x2"]) == {"1", "X", "2"}
    assert set(markets["card_1x2"]) == {"1", "X", "2"}


def test_financial_analysis_and_smart_combo_use_joint_samples():
    match = parse_match_input(VALID)
    config = config_from_input(match, simulations=5000, seed=4)
    config = config.__class__(
        **{**config.__dict__, "odds": {"1X": 1.35, "Over 1.5 gol": 1.30, "Over 8.5 corner": 1.90, "Over 4.5 cartellini": 1.80}}
    )
    result = simulate_match(config)
    assert result["financial"]["quotes_provided"] == 4
    assert result["financial"]["best_value"] is not None
    best = result["financial"]["best_value"]
    assert best["recommended_stake_pct"] == best["recommended_quarter_kelly_pct"]
    assert best["kelly_fraction"] == 0.25
    assert len(best["confidence_interval_95"]) == 2
    assert result["smart_combo"]["recommendation"] is not None
    combo = result["smart_combo"]["recommendation"]
    assert len(combo["legs"]) == 2
    assert combo["recommended_stake_pct"] >= 0
    assert 0 <= combo["reliability_pct"] <= 100


def test_quotes_from_parsed_input_reach_value_bet_analysis():
    text = VALID.replace("CASA: Inter", "CASA: Inter | Quota 1: 1.85").replace(
        "OSPITE: Milan", "OSPITE: Milan | Quota X: 3.40 | Quota 2: 4.20"
    )
    result = simulate_match(config_from_input(parse_match_input(text), simulations=2000, seed=5))
    assert {row["market"] for row in result["financial"]["markets"]} == {"1", "X", "2"}
    assert all("recommended_stake_pct" in row for row in result["financial"]["markets"])


def test_complete_copy_block_quotes_reach_market_and_financial_analysis():
    match = parse_match_input(COMPLETE_COPY_BLOCK)
    result = simulate_match(config_from_input(match, simulations=3000, seed=59))
    financial_markets = {row["market"] for row in result["financial"]["markets"]}

    assert len(match.odds) == 72
    assert len(financial_markets) == 72
    assert "Casa DNB" in financial_markets
    assert "Ospite DNB" in financial_markets
    assert "Over 1.5 gol 1T" in financial_markets
    assert "1X + Over 1.5 gol" in financial_markets
    assert "X2 + Over 1.5 gol" in financial_markets
    assert "X2 + Multigol 1-3" in financial_markets
    assert set(match.odds) == financial_markets


def test_dnb_financial_settlement_exposes_push_probability():
    config = config_from_input(parse_match_input(VALID), simulations=4000, seed=6)
    config = config.__class__(**{**config.__dict__, "odds": {"Casa DNB": 1.70}})
    result = simulate_match(config)
    row = result["financial"]["markets"][0]
    assert row["market"] == "Casa DNB"
    assert row["push_probability_pct"] > 0
    assert 0 <= row["loss_probability_pct"] <= 100
    expected_fair_odds = 1.0 + row["loss_probability_pct"] / row["simulated_probability_pct"]
    assert row["fair_odds"] == round(expected_fair_odds, 3)
    assert row["settlement_fair_odds"] == row["fair_odds"]
    expected_edge = (
        row["simulated_probability_pct"] * 100.0
        / (100.0 - row["push_probability_pct"])
        - row["implied_probability_pct"]
    )
    assert row["edge_pct"] == round(expected_edge, 2)


def test_smart_combo_does_not_treat_dnb_push_as_a_binary_loss():
    events = {
        "Casa DNB": np.array([True] * 9 + [False]),
        "Over 1.5 gol": np.array([True] * 8 + [False, False]),
    }

    result = smart_combo(events, {"Casa DNB": 2.0, "Over 1.5 gol": 2.0})

    assert result["recommendation"] is None
    assert result["status"] == "insufficient_quotes"


def test_report_is_consistent_with_returned_probabilities():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=3000, seed=2))
    report = result["statistical_report"]
    p1 = result["markets"]["1x2"]["1"]["percentage"]
    assert f"{p1:.2f}%" in report
    assert f"λ={result['model']['lambda']:.3f}" in report


def test_simulation_samples_the_dixon_coles_score_distribution(monkeypatch):
    forced_distribution = np.zeros((3, 2))
    forced_distribution[2, 1] = 1.0
    monkeypatch.setattr(engine, "dixon_coles_matrix", lambda *_args, **_kwargs: forced_distribution)

    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=100, seed=7))

    assert result["summary"]["modal_score"] == {
        "home": 2,
        "away": 1,
        "share_pct": 100.0,
        "conditional_share_pct": 100.0,
    }
    assert result["markets"]["1x2"]["1"]["percentage"] == 100.0


def test_fixed_score_follows_favorite_sign_and_derived_markets(monkeypatch):
    forced_distribution = np.zeros((4, 2))
    forced_distribution[1, 1] = 0.40
    forced_distribution[2, 1] = 0.35
    forced_distribution[3, 1] = 0.25
    monkeypatch.setattr(engine, "dixon_coles_matrix", lambda *_args, **_kwargs: forced_distribution)
    config = config_from_input(parse_match_input(VALID), simulations=20_000, seed=13)

    result = simulate_match(config)
    summary = result["summary"]
    score_markets = result["fixed_score_scenario"]["markets"]

    assert summary["most_likely_exact_score"]["home"] == 1
    assert summary["most_likely_exact_score"]["away"] == 1
    assert summary["favorite_sign"] == "1"
    assert summary["modal_score"]["home"] == 2
    assert summary["modal_score"]["away"] == 1
    assert score_markets["1"] == 100.0
    assert score_markets["Over 2.5 gol"] == 100.0
    assert score_markets["Goal"] == 100.0
    assert score_markets["Multigol 2-3"] == 100.0
    assert score_markets["Somma gol 3"] == 100.0


def test_conditional_scenarios_keep_markets_tied_to_the_selected_sign():
    simulations = 4000
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=simulations, seed=31))
    scenarios = result["conditional_scenarios"]

    assert sum(scenario["sample_count"] for scenario in scenarios.values()) == simulations
    assert scenarios["1"]["sample_count"] == result["markets"]["1x2"]["1"]["count"]
    assert scenarios["1"]["markets"]["1"] == 100.0
    assert scenarios["1"]["markets"]["X"] == 0.0
    assert scenarios["1"]["markets"]["2"] == 0.0
    assert scenarios["1"]["markets"]["1X"] == 100.0
    assert scenarios["2"]["markets"]["X2"] == 100.0


def test_corner_mean_uses_for_and_opponent_conceded_averages():
    config = config_from_input(parse_match_input(VALID), simulations=12_000, seed=33)
    config = config.__class__(
        **{
            **config.__dict__,
            "home": config.home.__class__(**{**config.home.__dict__, "corners_for": 6.0, "corners_against": 4.0}),
            "away": config.away.__class__(**{**config.away.__dict__, "corners_for": 5.0, "corners_against": 7.0}),
        }
    )

    result = simulate_match(config)

    assert abs(result["markets"]["corners"]["mean"] - 11.0) < 0.12


def test_zero_card_inputs_do_not_create_artificial_cards():
    config = config_from_input(parse_match_input(VALID), simulations=2000, seed=47)
    config = config.__class__(
        **{
            **config.__dict__,
            "home": config.home.__class__(**{**config.home.__dict__, "cards_for": 0.0}),
            "away": config.away.__class__(**{**config.away.__dict__, "cards_for": 0.0}),
            "referee_yellow_avg": 0.0,
        }
    )

    result = simulate_match(config)

    assert result["markets"]["cards"]["mean"] == 0.0
    assert result["markets"]["cards"]["Over_2.5"]["percentage"] == 0.0
    assert result["markets"]["card_1x2"]["X"]["percentage"] == 100.0
