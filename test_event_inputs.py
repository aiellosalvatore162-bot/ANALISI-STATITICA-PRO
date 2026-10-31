"""Fase AO: tutti i dati nel motore a eventi (formazione, corsie, stile, arbitro) e test di buon senso calcistico."""

import numpy as np
import pytest

import event_engine as ee
import event_inputs as ei
import formation

N = 20_000
NEUTRAL = {"POR": 0.0, "DIF": 0.0, "CEN": 0.0}


def _lineup(home_shots=1.0, home_quality=1.0, home_missing=None, away_missing=None):
    def side(shots, quality, missing):
        return {"disponibile": True, "eventi": {"rapporto_tiri": shots, "rapporto_qualita": quality,
                                                 "quota_minuti_mancanti": missing or dict(NEUTRAL)}}
    return {"casa": side(home_shots, home_quality, home_missing), "ospite": side(1.0, 1.0, away_missing)}


def _team(goals, scales=None, goal_factor=1.0, **extra):
    return ee.TeamInput(goals * goal_factor, **(scales or {}), **extra)


def _shots(sample, side="home"):
    return sample[f"shots_{side}"].sum(axis=1)


def test_lineup_scales_use_estimated_coefficients():
    cfg = ei._load(ei.PLAYERS_PATH)["motore_eventi"]
    center = dict(cfg["media_mancanti"])          # reparti mancanti nella media: nessun effetto difensivo
    scales, goals, rows = ei.lineup_scales(_lineup(0.8, 0.9, dict(center), dict(center)))
    assert scales["home"]["shot_scale"] == pytest.approx(0.8 ** cfg["tiri"]["attacco"]["stima"])
    assert scales["home"]["quality_scale"] == pytest.approx(0.9 ** cfg["qualita"]["attacco"]["stima"])
    assert goals["home"]["attack"] == pytest.approx(scales["home"]["shot_scale"] * scales["home"]["quality_scale"])
    assert scales["away"] == pytest.approx({"shot_scale": 1.0, "quality_scale": 1.0})
    assert any("IC 95%" in row["fonte"] for row in rows)


def test_lineup_missing_is_declared_neutral():
    scales, goals, rows = ei.lineup_scales(None)
    assert goals is None and scales == {"home": {}, "away": {}}
    assert rows[0]["effetto"] == "nessuno"


def test_team_without_two_strikers_shoots_less_and_worse():
    """Buon senso: senza i due attaccanti (meno tiri e npxG/tiro nell'XI atteso) la squadra tira meno e peggio."""
    params = ee.load("E0")
    scales, goals, _ = ei.lineup_scales(_lineup(0.75, 0.85))
    base = ee.simulate(np.random.default_rng(1), N, _team(1.5), _team(1.2), params)
    weak = ee.simulate(np.random.default_rng(1), N, _team(1.5, scales["home"], goals["home"]["attack"]), _team(1.2), params)
    assert _shots(weak).mean() < _shots(base).mean() * 0.95
    assert weak["xg_home"].mean() / _shots(weak).mean() < base["xg_home"].mean() / _shots(base).mean()


def test_wide_players_match_statsbomb_positions():
    assert formation.wide_players("4-4-2") == {"attacco": 2.0, "difesa": 4.0}
    assert formation.wide_players("3-4-3") == {"attacco": 4.0, "difesa": 2.0}
    assert formation.wide_players("5-3-2") == {"attacco": 2.0, "difesa": 2.0}
    assert formation.wide_players("4-2-3-1") == {"attacco": 2.0, "difesa": 2.0}
    assert formation.wide_from_positions(["Right Back", "Left Back", "Right Midfield", "Left Midfield"]) == \
        formation.wide_players("4-4-2")


def test_lanes_follow_estimates_and_declare_missing_module():
    out, rows = ei.lane_scales(None, "4-4-2")
    assert out == {"home": {}, "away": {}} and "modulo mancante" in rows[0]["fonte"]
    cfg = ei._load(ei.EVENTS_PATH).get("corsie")
    if not cfg:
        pytest.skip("corsie non stimate")
    wide, narrow = ei.lane_scales("3-4-3", "4-3-3")[0]["home"], ei.lane_scales("5-3-2", "4-3-3")[0]["home"]
    sign = np.sign(cfg["corner_da_cross"]["fasce"]["stima"])
    assert np.sign(np.log(wide["corner_cross_scale"] / narrow["corner_cross_scale"])) == sign


def test_wide_module_more_crosses_and_corners_when_estimated_positive():
    """Buon senso: con l'effetto stimato positivo, un modulo con esterni alti produce più corner da cross."""
    cfg = ei._load(ei.EVENTS_PATH).get("corsie")
    if not cfg or cfg["corner_da_cross"]["fasce"]["stima"] <= 0:
        pytest.skip("effetto delle fasce sui corner non positivo: dichiarato nella scheda")
    params = ee.load("E0")
    lanes = {module: ei.lane_scales(module, "4-4-2")[0]["home"] for module in ("3-4-3", "5-3-2")}
    corners = {}
    for module, extra in lanes.items():
        sample = ee.simulate(np.random.default_rng(2), N, _team(1.4, type_scale=extra["type_scale"],
                                                                corner_cross_scale=extra["corner_cross_scale"]), _team(1.2), params)
        corners[module] = sample["corners_by_origin_home"][:, ee.CORNER_ORIGINS.index("cross")].mean()
    assert corners["3-4-3"] > corners["5-3-2"]


def test_strict_referee_more_yellows():
    """Buon senso: arbitro severo (molti falli e gialli fischiati) → più gialli nel motore a eventi."""
    params = ee.load("E0")
    strict = ee.RefereeInput(matches=60, fouls=25.0, yellows=4.6, league_fouls=21.5, league_yellows=3.6)
    soft = ee.RefereeInput(matches=60, fouls=18.0, yellows=2.8, league_fouls=21.5, league_yellows=3.6)
    runs = {name: ee.simulate(np.random.default_rng(3), N, _team(1.4), _team(1.2), params, referee=ref)
            for name, ref in (("severo", strict), ("morbido", soft))}
    total = {name: (s["yellows_home"] + s["yellows_away"]).mean() for name, s in runs.items()}
    fouls = {name: (s["fouls_home"] + s["fouls_away"]).mean() for name, s in runs.items()}
    assert total["severo"] > total["morbido"] and fouls["severo"] > fouls["morbido"]


def test_high_press_more_fouls():
    """Buon senso: pressing alto (beta stimato sui falli fatti) → più falli; i recuperi alti non sono stimabili (dichiarato)."""
    params = ee.load("E0")
    high = ee.simulate(np.random.default_rng(4), N, _team(1.4, profile={"pressing": "alto"}),
                       _team(1.2, profile={"possesso": "palla_a_terra"}), params)
    low = ee.simulate(np.random.default_rng(4), N, _team(1.4, profile={"pressing": "basso"}),
                      _team(1.2, profile={"possesso": "palla_a_terra"}), params)
    assert high["fouls_home"].mean() > low["fouls_home"].mean()
    _, rows = ei.style_terms({}, {}, {})
    assert any(row["dato"] == "stile: recuperi_alti" and ei.MISSING in row["fonte"] for row in rows)


def test_style_priority_imported_over_measured_over_sheet():
    style = {"parametri": {"ppda": {"valore": 14.0}, "quota_tiri": {"valore": 0.6}}}
    cuts = {"ppda": (9.0, 12.0), "quota_tiri": (0.45, 0.55)}
    terms, rows = ei.style_terms(style, {"ppda": 7.5}, {"pressing": "basso", "marcatura": "uomo"}, cuts)
    assert terms["pressing"] == "alto"                     # importato (PPDA basso) prevale su misura e scheda
    assert terms["possesso"] == "palla_a_terra"            # misurato (proxy quota di tiri)
    assert terms["marcatura"] == "uomo"                    # solo scheda: qualitativo, dichiarato
    assert any("NON usata" in row["fonte"] for row in rows)
    terms, _ = ei.style_terms(style, {}, {}, cuts)
    assert terms["pressing"] == "basso"                    # PPDA 14 = terzile alto = pressing basso


def test_referee_without_history_is_declared():
    data, rows = ei.referee({"nome": "X", "partite": 0})
    assert data is None and "senza storico" in rows[0]["fonte"]
    data, _ = ei.referee({"nome": "Y", "partite": 30, "falli_medi": 24.0, "gialli_medi": 4.0,
                          "media_falli_competizione": 21.5, "media_gialli_competizione": 3.6})
    assert data["matches"] == 30 and ee.RefereeInput(**data).factors((20.8, 80.7))[0] > 1.0


def test_build_combines_everything():
    out = ei.build(lineup=_lineup(0.9, 1.0), sheets={"home": {"pressing": "alto"}}, modules={"home": "4-3-3", "away": "4-4-2"},
                   referee_extra=None)
    assert out["home"]["profile"]["pressing"] == "alto" and out["home"]["module"] == "4-3-3"
    assert out["home"]["shot_scale"] < 1.0 and out["formazione"]["home"]["attack"] < 1.0
    assert out["arbitro"] is None and any(row["dato"] == "arbitro" for row in out["schede"])
