"""Test della dashboard (fase J): solo presentazione, escape dei testi esterni, contrasto e numeri coerenti."""

import re

import pytest

import dashboard
import engine
from parser import parse_match_input
from test_parser import VALID


@pytest.fixture(scope="module")
def result():
    config = engine.config_from_input(parse_match_input(VALID), simulations=30_000, seed=4)
    return engine.simulate_match(engine.MatchConfig(**{**config.__dict__, "odds": {"1": 1.9, "X": 3.6, "2": 4.4, "Over 2.5 gol": 1.7}}))


def test_formats_use_one_decimal_for_percentages_and_two_for_odds():
    assert dashboard.pct(48.04) == "48.0%" and dashboard.pct(None) == "—"
    assert dashboard.odd(1.856) == "1.86" and dashboard.out_of_ten(66) == 7


def test_external_text_is_escaped(result):
    hostile = '<img src=x onerror="alert(1)">'
    data = {**result, "input": {**result["input"], "home": {**result["input"]["home"], "name": hostile}}}
    for html in (dashboard.scoreboard(data), dashboard.outcome_card(data), dashboard.heatmap(data), dashboard.badge(hostile)):
        assert "<img" not in html and "&lt;img" in html
    assert "<script" not in dashboard.card("<script>x</script>", "ball", "1", "<b>frase</b>")
    assert "<script" not in "".join(dashboard.theme_css(theme) for theme in ("light", "dark", None)).lower()


def test_text_tokens_meet_wcag_aa():
    for tokens in (dashboard.LIGHT, dashboard.DARK):
        for text in ("ink", "ink-2", "muted", "good-ink", "bad-ink", "tab-on"):
            for background in ("surface", "surface-2", "page"):
                assert dashboard.contrast(tokens[text], tokens[background]) >= 4.5, (text, background)
        assert dashboard.contrast(tokens["pitch-ink"], tokens["pitch"]) >= 4.5
        # Testo sopra i segmenti 1X2: 19 px grassetto (testo grande, soglia 3:1).
        for name in ("home", "draw", "away"):
            assert dashboard.contrast(tokens[name], dashboard.readable_ink(tokens[name])) >= 3.0


def test_cards_show_the_engine_numbers(result):
    one = result["markets"]["1x2"]["1"]["percentage"]
    assert dashboard.pct(one) in dashboard.outcome_card(result)
    over = result["markets"]["over_under"]["Over_2.5"]["percentage"]
    assert dashboard.pct(over) in dashboard.goals_card(result)
    board = dashboard.scoreboard(result)
    score = result["summary"]["most_likely_exact_score"]
    assert f'{score["home"]} - {score["away"]}' in board and "Ancorato al mercato" in board
    assert f'{result["markets"]["corners"]["mean"]:.1f}' in dashboard.corners_card(result)
    assert f'{result["markets"]["cards"]["mean"]:.1f}' in dashboard.cards_card(result)


def test_value_lights_always_have_text(result):
    states = dashboard.value_states(result)
    assert {state["market"] for state in states} == {"1", "X", "2", "Over 2.5 gol"}
    for state in states:
        expected = "green" if state["ev"] > 0 else ("red" if state["ev"] <= 0 else "grey")
        assert state["color"] in ("green", "grey", "red") and state["verdict"]
        if state["color"] != "grey":
            assert state["color"] == expected
    html = dashboard.value_card(result)
    assert all(state["verdict"].split(" · ")[0] in html for state in states)
    empty = {**result, "financial": {**result["financial"], "markets": []}}
    assert "Semaforo spento" in dashboard.value_card(empty)


def test_solid_picks_are_plausible_and_sorted(result):
    picks = dashboard.solid_picks(result)
    assert picks and len(picks) <= 4
    assert [pick["probability"] for pick in picks] == sorted((pick["probability"] for pick in picks), reverse=True)
    assert all(55 <= pick["probability"] <= 85 for pick in picks)
    assert len({pick["family"] for pick in picks}) == len(picks)


def test_heatmap_marks_groups_and_recommended_line(result):
    html = dashboard.heatmap(result, ["1-0", "1-1"], ["2-1"])
    assert html.count('class="min"') + html.count('class="min mine"') == 2
    assert 'class="mine"' in html
    assert len(re.findall(r"<td ", html)) == 36
    line = dashboard.recommended_line({"Over_8.5": {"percentage": 66.0}, "Over_9.5": {"percentage": 52.0}, "mean": 9.8})
    assert line == ("Over 8.5", 66.0)
    assert dashboard.recommended_line({"Over_8.5": {"percentage": 95.0}, "Over_12.5": {"percentage": 48.0}}) == ("Over 12.5", 48.0)


def test_team_badges_use_colors_and_initials():
    assert dashboard.initials("Inter") == "INT" and dashboard.initials("Real Madrid") == "RM" and dashboard.initials("AC Milan") == "MIL"
    assert dashboard.team_colors("Inter")[0] == "#0068a8"
    assert dashboard.team_colors("Squadra Sconosciuta") == dashboard.team_colors("Squadra Sconosciuta")
    assert 'title="Inter"' in dashboard.badge("Inter")


def test_in_brief_uses_only_computed_numbers(result):
    sentences = dashboard.brief_sentences(result)
    assert 3 <= len(sentences) <= 4
    model, finale = result["model"], result["components"]["finale"]
    assert f'{model["lambda"] + model["mu"]:.1f} gol' in sentences[0]
    assert dashboard.pct(finale["Over 9.5 corner"]) in sentences[2] and dashboard.pct(finale["Over 4.5 cartellini"]) in sentences[2]
    picks = dashboard.solid_picks(result, limit=2)
    assert all(pick["market"] in sentences[3] for pick in picks)
    assert dashboard._side(60) == "sopra la linea" and dashboard._side(40) == "sotto la linea" and dashboard._side(50) == "vicini alla linea"
    html = dashboard.in_brief(result)
    assert html.count("<li>") == len(sentences) and "In breve" in html


def test_in_brief_balanced_match_and_escaping(result):
    markets = {**result["markets"], "1x2": {"1": {"percentage": 36.0}, "X": {"percentage": 30.0}, "2": {"percentage": 34.0}}}
    hostile = {**result, "markets": markets, "input": {**result["input"], "home": {**result["input"]["home"], "name": "<b>X</b>"}}}
    assert dashboard.brief_sentences(hostile)[1].startswith("Partita equilibrata")
    assert "<b>X</b>" not in dashboard.in_brief(hostile)


def test_missing_values_are_shown_as_dash():
    import numpy as np
    import pandas as pd

    frame = pd.DataFrame({"a": [1.5, np.nan], "b": [None, "testo"], "c": [0.2025, 0.0]})
    shown = dashboard.missing_as_dash(frame)
    assert shown.loc[1, "a"] == "—" and shown.loc[0, "b"] == "—" and shown.loc[1, "b"] == "testo"
    assert shown.loc[0, "a"] == "1.5" and shown.loc[0, "c"] == "0.2025"
