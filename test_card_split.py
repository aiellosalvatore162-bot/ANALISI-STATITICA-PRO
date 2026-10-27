"""Fase T: divisione dei cartellini tra le squadre (solo dati sintetici e simulazioni, nessuna rete)."""

from dataclasses import replace
import math

import numpy as np
import pandas as pd
import pytest

import engine
import today
from parser import parse_match_input


ACTIVE = engine.CardSplitParams(active=True, rate_weight=0.14, provoked_weight=0.40, underdog_weight=0.71, balance=0.153)


def config(**kwargs):
    home = engine.TeamParams("Casa", 1.3, 1.1, 1900, "W-W-W-D-W", 1.9, 0.9, 6.0, 4.0, 1.6, cards_provoked=2.3)
    away = engine.TeamParams("Ospite", 0.9, 0.9, 1650, "L-D-L-L-D", 1.0, 1.6, 4.0, 6.0, 2.3, cards_provoked=1.7)
    return engine.MatchConfig(home, away, 4.6, 25.0, simulations=60_000, **kwargs)


def test_inactive_split_is_the_original_division():
    result = engine.simulate_match(config(card_split=engine.CardSplitParams()))
    assert result["card_split"]["active"] is False
    assert result["card_split"]["p"] == pytest.approx(1.6 / (1.6 + 2.3))


def test_joint_distribution_matches_the_simulation():
    cfg = config(card_split=ACTIVE)
    result = engine.simulate_match(cfg)
    p = result["card_split"]["p"]
    points = engine.card_points_joint(engine.card_total_mean(cfg), p, cfg.count_model, cfg.card_rule, balance=ACTIVE.balance)
    assert points.sum() == pytest.approx(1.0)
    analytic = {key: float(value[0]) * 100 for key, value in engine.card_split_markets(points).items()}
    final = result["components"]["finale"]
    for key in ("1 cartellini", "X cartellini", "2 cartellini", "Casa Over 1.5 cartellini", "Ospite Over 2.5 cartellini"):
        assert final[key] == pytest.approx(analytic[key], abs=1.0), key


def test_underdog_and_provoked_move_the_share_the_right_way():
    cfg = config(card_split=ACTIVE)
    favourite_home, _ = engine.card_split_logit(cfg, underdog=-0.5)    # casa favorita: P(2) − P(1) < 0
    underdog_home, _ = engine.card_split_logit(cfg, underdog=0.4)
    assert underdog_home > favourite_home                               # la sfavorita prende più cartellini
    no_provoked = replace(cfg, home=replace(cfg.home, cards_provoked=None))
    logit, used = engine.card_split_logit(no_provoked, underdog=0.0)
    assert used["provocati"] == "non disponibili: termine escluso"
    with_provoked, _ = engine.card_split_logit(cfg, underdog=0.0)
    assert with_provoked < logit       # l'ospite provoca meno gialli (1.7) di quanti ne provoca la casa (2.3)


def test_balance_makes_equal_splits_more_likely():
    binomial = np.exp(engine.split_log_pmf([6], [0.5]))[0]
    balanced = np.exp(engine.split_log_pmf([6], [0.5], balance=0.15))[0]
    assert balanced[3] > binomial[3] and balanced[:7].sum() == pytest.approx(1.0)


def test_market_anchoring_with_card_odds_and_model_only_warning():
    cfg = config(card_split=ACTIVE)
    plain = engine.simulate_match(cfg)["card_split"]
    assert not plain["anchored"] and plain["reason"].startswith("Non ancorato")
    odds = {"1 cartellini": 9.0, "X cartellini": 6.0, "2 cartellini": 1.22}   # P(2) ≈ 0.78 contro 0.60 del modello
    anchored = engine.simulate_match(replace(cfg, odds=odds))["card_split"]
    assert anchored["anchored"] and anchored["p"] < anchored["p_model"]      # il mercato vede l'ospite più ammonito
    shift = anchored["market_shift"]
    expected = 1 / (1 + math.exp(-(math.log(anchored["p_model"] / (1 - anchored["p_model"])) + 0.8 * shift)))
    assert anchored["p"] == pytest.approx(expected)
    assert set(anchored["targets"]) == {"1 cartellini", "X cartellini", "2 cartellini"}
    lines = {**odds, "Casa Over 1.5 cartellini": 2.0, "Casa Under 1.5 cartellini": 1.75}
    assert "Casa Over 1.5 cartellini" in engine.simulate_match(replace(cfg, odds=lines))["card_split"]["targets"]


def test_strong_disagreement_on_counts_has_no_green_light():
    # Peso del mercato nullo: la divisione resta quella del modello e lo scarto col bookmaker resta grande.
    cfg = config(card_split=replace(ACTIVE, market_weight=0.0), odds={"1 cartellini": 1.25, "X cartellini": 6.0, "2 cartellini": 9.0,
                                          "Over 9.5 corner": 1.9, "Under 9.5 corner": 1.9})
    result = engine.simulate_match(cfg)
    flagged = result["count_disagreements"]
    assert "1 cartellini" in flagged and abs(flagged["1 cartellini"]["gap"]) > 10
    row = next(row for row in result["financial"]["markets"] if row["market"] == "1 cartellini")
    assert row["count_disagreement"] and row["suspicious_value"] and not row["is_value"]
    assert all(bet["market"] not in flagged for bet in result["financial"]["value_bets"])
    gaps = engine.count_market_gaps(result["components"]["finale"], cfg.odds)
    assert set(gaps) >= {"Over 9.5 corner", "Under 9.5 corner", "X cartellini"}


def test_parser_reads_the_optional_provoked_field():
    team = ("Attacco: 1.2 | Difesa: 1.1 | Elo: 1850 | Forma: W-W-D-W-L | xG Fatti: 1.8 | xG Subiti: 1.0 | "
            "Corner pro/sub: 5.5/4.0 | Cartellini pro: 2.0")
    block = f"CASA: A\n{team} | Cartellini provocati: 2.4\nOSPITE: B\n{team}\nARBITRO: Gialli medi 4.2 | Falli medi 24\n"
    parsed = parse_match_input(block)
    assert parsed.home.cards_provoked == 2.4 and parsed.away.cards_provoked is None and parsed.home.cards_for == 2.0
    assert engine.config_from_input(parsed).home.cards_provoked == 2.4
    with pytest.raises(Exception, match="Cartellini provocati"):
        parse_match_input(block.replace("provocati: 2.4", "provocati: 14"))


def test_team_card_markets_need_a_passed_verification():
    assert today.team_card_market("1 cartellini") and today.team_card_market("Ospite Over 1.5 cartellini")
    assert not today.team_card_market("Over 4.5 cartellini")
    settings = {"cartellini_squadra": {"ece_massimo": 0.03}}
    good = {"attiva": True, "ece_fuori_campione": {"1X2 cartellini": 0.01, "Casa Over 1.5": 0.028, "media": 0.02}}
    bad = {"attiva": True, "ece_fuori_campione": {"1X2 cartellini": 0.063, "media": 0.03}}
    assert today.team_cards_status(settings, good)[0]
    allowed, why = today.team_cards_status(settings, bad)
    assert not allowed and "1X2 cartellini" in why
    assert not today.team_cards_status(settings, {"attiva": False})[0]


def test_split_fit_recovers_known_weights_on_synthetic_data():
    from tools.card_split import SplitParams, fit, split_nll

    rng = np.random.default_rng(3)
    n = 4000
    data = pd.DataFrame({
        "home_cards_for": rng.uniform(1.2, 3.0, n), "away_cards_for": rng.uniform(1.2, 3.0, n),
        "home_provoked": rng.uniform(1.2, 3.0, n), "away_provoked": rng.uniform(1.2, 3.0, n),
        "home_rate_shrunk": 2.0, "away_rate_shrunk": 2.0, "referee_yellow_avg": 4.5,
        "market_home": 0.45, "market_away": 0.30, "home_elo": 1700, "away_elo": 1700,
    })
    truth = SplitParams(rate_weight=0.6, provoked_weight=0.5)
    p = 1 / (1 + np.exp(-(0.6 * np.log(data["home_cards_for"] / data["away_cards_for"])
                          + 0.5 * np.log(data["away_provoked"] / data["home_provoked"]))))
    totals = rng.poisson(4.5, n)
    data["home_yellows"] = rng.binomial(totals, p)
    data["away_yellows"] = totals - data["home_yellows"]
    fitted = fit(SplitParams(), ("rate_weight", "provoked_weight"), data)
    assert fitted.rate_weight == pytest.approx(0.6, abs=0.12) and fitted.provoked_weight == pytest.approx(0.5, abs=0.12)
    assert split_nll(fitted, data) <= split_nll(SplitParams(), data)
