"""Fase AK, stadio 1b: dizionario tattico e messa in campo per corsie."""

import copy

import pytest

import formation
import tactical_dictionary as td
import tactical_sheets as ts


@pytest.fixture()
def dictionary():
    """Dizionario con beta di prova (0.1 nel verso dichiarato): verifica il cablaggio, non i valori stimati."""
    data = copy.deepcopy(td.load())
    for spec in data["termini"].values():
        for effect in spec["effetti"]:
            effect["beta"] = 0.1 * effect["segno"]
    return data


def _extremes(spec):
    ordered = sorted(spec["punteggio"].items(), key=lambda item: item[1])
    return ordered[0][0], ordered[-1][0]


@pytest.mark.parametrize("term", list(td.load()["termini"]))
def test_changing_one_term_moves_only_its_rates_in_the_declared_direction(dictionary, term):
    spec = dictionary["termini"][term]
    low, high = _extremes(spec)
    if spec.get("testo_libero"):
        low, high = "si chiude e difende", "attacca a testa bassa"
    rates_low, _, warn_low = td.apply_profile({term: low}, dictionary)
    rates_high, _, warn_high = td.apply_profile({term: high}, dictionary)
    assert warn_low == [] and warn_high == []
    moved = {effect["tasso"]: effect["segno"] for effect in spec["effetti"]}
    for rate in dictionary["tassi"]:
        if rate in moved:
            assert (rates_high[rate] - rates_low[rate]) * moved[rate] > 0, (term, rate)
        else:
            assert rates_high[rate] == rates_low[rate] == pytest.approx(1.0), (term, rate)


def test_unknown_terms_and_values_are_reported_never_ignored(dictionary):
    rates, _, warnings = td.apply_profile({"tiki_taka": "sì", "pressing": "altissimo"}, dictionary)
    assert any("tiki_taka" in message for message in warnings) and any("altissimo" in message for message in warnings)
    assert all(value == pytest.approx(1.0) for value in rates.values())


def test_unestimated_effects_are_neutral_and_declared():
    rates, rows, _ = td.apply_profile({"pressing": "alto"})
    if all(effect["beta"] is None for effect in td.load()["termini"]["pressing"]["effetti"]):
        assert rates["recuperi_alti"] == 1.0 and all(row["stato"] == "non stimato" for row in rows)


def test_synonyms_and_sheet_fields_feed_the_dictionary(dictionary):
    sheets, warnings = ts.parse_profiles("PROFILO_TATTICO: Alfa\npossesso: palla a terra | verticalizzazione: alta | blocco: alto | "
                                         "tiki_taka: sì | fonte: https://esempio.it/p\n")
    assert sheets[0].possesso == "palla_a_terra" and sheets[0].verticalizzazione == "alta"
    assert any("tiki_taka" in message for message in warnings)
    terms = td.from_sheet(sheets[0], dictionary)
    assert terms == {"possesso": "palla_a_terra", "verticalizzazione": "alta", "altezza_linea": "alto"}
    assert td.normalize("marcatura", "a uomo", dictionary)[0] == "uomo"


def test_roles_by_line_and_lane():
    players, warnings = formation.roles("4-3-3")
    assert warnings == []
    assert [p["ruolo"] for p in players if p["linea"] == "difesa"] == ["terzino", "centrale", "centrale", "terzino"]
    assert [p["ruolo"] for p in players if p["linea"] == "attacco"] == ["ala", "punta", "ala"]
    assert {p["ruolo"] for p in players if p["linea"] == "centrocampo"} == {"mediano"}
    trequartista, _ = formation.roles("4-2-3-1")
    assert [p["ruolo"] for p in trequartista if p["linea"] == "centrocampo"][-3:] == ["esterno", "trequartista", "esterno"]
    wing_backs, _ = formation.roles("3-5-2")
    assert [p["corsia"] for p in wing_backs if p["linea"] == "difesa"] == ["centro"] * 3
    _, bad = formation.roles("4-4-4")
    assert bad and "non valido" in bad[0]


def test_lane_matchups_decide_where_actions_start():
    same = formation.lane_shares("4-4-2", "4-4-2")
    assert sum(same.values()) == pytest.approx(1.0) and same["sinistra"] == pytest.approx(same["destra"])
    against_back_three = formation.lane_shares("4-3-3", "3-5-2")
    against_back_four = formation.lane_shares("4-3-3", "4-4-2")
    wide = lambda shares: shares["sinistra"] + shares["destra"]      # noqa: E731
    assert wide(against_back_three) > wide(against_back_four)           # fasce meno presidiate → più azioni sulle fasce
    pairs = formation.matchups("4-3-3", "4-4-2")
    assert [(row["corsia_casa"], row["corsia_ospite"]) for row in pairs] == [("sinistra", "destra"), ("centro", "centro"), ("destra", "sinistra")]
