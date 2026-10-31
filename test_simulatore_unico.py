"""Fase AP: Simulatore unico (sorgente per famiglia di mercati) e incroci di stile nel motore a eventi."""

import json
import math

import pytest

import engine
import engine_choice
import event_engine
import tactical_dictionary
from engine import config_from_input, simulate_match
from parser import parse_match_input
from test_parser import VALID
from tools import ap_scegli

PRESSING = {"id": "possesso_contro_pressing", "attacco": "possesso", "difesa": "pressing", "tasso": "falli_fatti",
            "colonna": "falli_subiti", "beta": 0.0176, "attiva": True}
CROSS = {"id": "cross_contro_blocco_basso", "attacco": "fasce_cross", "difesa": "altezza_linea", "tasso": "corner_fasce",
         "colonna": "corner_fasce", "beta": -0.028, "attiva": True}


def test_regola_di_scelta_per_famiglia():
    base = {"ece_prima": 0.02, "ece_dopo": 0.018, "partite": 1000}
    assert ap_scegli.decide({**base, "diff": -0.001, "se": 0.0002})[0] == "eventi"
    assert ap_scegli.decide({**base, "diff": -0.001, "se": 0.0002, "ece_dopo": 0.03})[0] == "attuale"     # ECE peggiore
    assert ap_scegli.decide({**base, "diff": -0.001, "se": 0.0008})[0] == "attuale"                       # dentro l'errore
    source, motive = ap_scegli.decide({**base, "diff": 0.004, "se": 0.0006})
    assert source == "attuale" and "PEGGIORE" in motive


def test_unione_dei_campioni_con_pesi_inversi():
    united = ap_scegli.pool([{"partite": 100, "diff": -1.0, "se": 1.0, "ece_prima": 0.02, "ece_dopo": 0.01},
                             {"partite": 300, "diff": -3.0, "se": 1.0, "ece_prima": 0.04, "ece_dopo": 0.02}])
    assert united["diff"] == pytest.approx(-2.0) and united["se"] == pytest.approx(1 / math.sqrt(2))
    assert united["ece_prima"] == pytest.approx(0.035) and united["partite"] == 400


def test_incrocio_pressing_cambia_i_falli_dell_avversario_e_zero_se_neutro():
    dictionary = tactical_dictionary.load()
    home, away = {"possesso": "palla_a_terra"}, {"pressing": "alto"}
    mult_home, mult_away = event_engine.apply_crossings({}, {}, home, away, [PRESSING], dictionary)
    assert mult_away["falli_fatti"] == pytest.approx(math.exp(0.0176)) and "falli_fatti" not in mult_home
    neutral_home, neutral_away = event_engine.apply_crossings({}, {}, {"possesso": "misto"}, away, [PRESSING], dictionary)
    assert not neutral_home and not neutral_away                                  # punteggio 0: nessun effetto


def test_incroci_accesi_solo_se_attivi():
    data = {"incroci": {"a": dict(PRESSING), "b": {**CROSS, "attiva": False}}}
    assert [item["id"] for item in event_engine.active_crossings(data)] == ["possesso_contro_pressing"]
    assert event_engine.active_crossings({}) == ()


def test_predefinito_invariato_e_incroci_spenti_in_configurazione():
    assert engine.DEFAULT_EVENT_ENGINE.crossings == () and not engine.DEFAULT_EVENT_ENGINE.unified
    assert engine_choice.load_default.__defaults__[0].name == "impostazioni.json"
    saved = json.loads(event_engine.PATH.read_text(encoding="utf-8"))["incroci"]
    assert all(not item["attiva"] for item in saved.values())


def test_preimpostazione_unico_segue_il_file(tmp_path, monkeypatch):
    path = tmp_path / "su.json"
    path.write_text(json.dumps({"famiglie": {"corner": {"sorgente": "eventi"}, "cartellini": {"sorgente": "attuale"}},
                                "incroci_gruppi_tenuti": []}), encoding="utf-8")
    monkeypatch.setattr(engine_choice, "UNIQUE_PATH", path)
    monkeypatch.setattr(engine_choice, "load_unified", lambda p=path: json.loads(p.read_text(encoding="utf-8")))
    settings = engine_choice.preset(engine_choice.UNIQUE, engine.DEFAULT_EVENT_ENGINE)
    assert settings.active and settings.markets == ("corner",) and settings.unified and settings.crossings == ()
    assert engine_choice.choice_of(settings) == engine_choice.UNIQUE
    assert engine_choice.driven(settings, "Over 9.5 corner") and engine_choice.driven(settings, "Goal & Over 9.5 corner")
    assert not engine_choice.driven(settings, "Over 4.5 cartellini") and not engine_choice.driven(settings, "Over 2.5 gol")
    path.write_text(json.dumps({"famiglie": {"corner": {"sorgente": "attuale"}}}), encoding="utf-8")
    off = engine_choice.preset(engine_choice.UNIQUE, engine.DEFAULT_EVENT_ENGINE)
    assert not off.active and engine_choice.choice_of(off) == engine_choice.UNIQUE      # tutto del calcolo attuale


def test_file_reale_coerente_con_le_verifiche():
    data = engine_choice.load_unified()
    families = data["famiglie"]
    assert {"gol", "tempi", "corner", "cartellini", "combo_corner", "combo_altre"} <= set(families)
    assert families["cartellini"]["sorgente"] == "attuale" and families["gol"]["sorgente"] == "attuale"
    for key in ("gol", "tempi", "corner", "cartellini"):
        united = families[key]["unito"]
        source, _ = ap_scegli.decide(united)
        assert source == families[key]["sorgente"]                                # il file riproduce la regola
    rows = engine_choice.unified_table(data)
    assert len(rows) == len(families) and all(row["Sorgente"] and row["Etichetta"] for row in rows)


def test_simulatore_unico_nel_risultato_e_nelle_etichette():
    config = config_from_input(parse_match_input(VALID), simulations=3000, seed=4)
    result = simulate_match(engine_choice.apply(config, engine_choice.UNIQUE))
    motor = result["motore"]
    assert motor["chiave"] == engine_choice.UNIQUE and motor["etichetta"] == "motore: Simulatore unico"
    import taratura

    label = engine_choice.result_label(result, taratura.load(), "Over 9.5 corner", 55.0)
    assert (label == engine_choice.UNIQUE_EVENT_LABEL) == ("corner" in motor["mercati"])
    assert engine_choice.result_label(result, taratura.load(), "Over 2.5 gol", 60.0) != engine_choice.UNIQUE_EVENT_LABEL
    assert sum(m["percentage"] for m in result["markets"]["1x2"].values()) == pytest.approx(100.0, abs=0.3)
