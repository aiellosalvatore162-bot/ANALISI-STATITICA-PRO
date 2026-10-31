"""Fase AN: importazione di dati nuovi, scelta del motore."""
import json
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

import data_import
import engine
import engine_choice
import style_profile
from engine import config_from_input, simulate_match
from parser import parse_match_input
from test_parser import VALID

KNOWN = ["Inter", "Milan", "Napoli", "Juventus"]


@pytest.fixture
def dirs(tmp_path):
    return {"store_dir": tmp_path / "cache", "registry_path": tmp_path / "registro.json", "names_path": tmp_path / "nomi.json"}


def _csv(tmp_path, text, name="dati.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


STYLE = ("squadra,stagione,data_dati,partite,xg,xga,possesso\n"
         "Inter,2025/26,2026-05-25,38,68.5,35.2,55\nMilan,2025/26,2026-05-25,38,60,40,52\n")


def test_importa_csv_di_prova_con_intestazioni_italiane_e_inglesi(tmp_path, dirs):
    english = STYLE.replace("squadra,stagione,data_dati,partite", "team,season,as_of,matches")
    for text in (STYLE, english):
        report = data_import.import_file(_csv(tmp_path, text), source="prova", today=date(2026, 6, 1), known=KNOWN, **dirs)
        assert report.error is None and report.kind == "stile" and report.imported == 2 and report.discarded == 0
    log = data_import.registry(dirs["registry_path"])
    assert log[-1]["fonte"] == "prova" and log[-1]["importate"] == 2 and log[-1]["tipo"] == "stile"
    assert len(data_import.load_rows("stile", dirs["store_dir"])) == 2       # reimportare non duplica


def test_nome_non_abbinato_chiede_la_scelta_e_non_indovina(tmp_path, dirs):
    text = STYLE.replace("Milan", "Inter Milano FC Zzz")
    asked = []

    def chooser(name, suggestion, similar):
        asked.append(name)
        return None                                            # l'utente non sceglie: riga scartata

    report = data_import.import_file(_csv(tmp_path, text), chooser=chooser, today=date(2026, 6, 1), known=KNOWN, **dirs)
    assert asked == ["Inter Milano FC Zzz"] and report.imported == 1 and report.discarded == 1
    assert report.unmatched == ["Inter Milano FC Zzz"]
    chosen = data_import.import_file(_csv(tmp_path, text), chooser=lambda *a: "Milan", today=date(2026, 6, 1), known=KNOWN, **dirs)
    assert chosen.imported == 2


def test_colonna_mancante_e_tipo_non_riconosciuto(tmp_path, dirs):
    missing = data_import.import_file(_csv(tmp_path, "squadra,stagione,partite\nInter,2025/26,38\n"), known=KNOWN, **dirs)
    assert missing.error and "data_dati" in missing.error
    unknown = data_import.import_file(_csv(tmp_path, "a,b\n1,2\n"), known=KNOWN, **dirs)
    assert unknown.error and "non riconosciuto" in unknown.error


def test_dati_duplicati_valori_fuori_scala_e_date_future(tmp_path, dirs):
    text = ("squadra,stagione,data_dati,partite,possesso\n"
            "Inter,2025/26,2026-05-25,38,55\nInter,2025/26,2026-05-25,38,57\n"
            "Milan,2025/26,2026-05-25,38,180\nNapoli,2025/26,2027-01-01,38,50\n")
    report = data_import.import_file(_csv(tmp_path, text), today=date(2026, 6, 1), known=KNOWN, **dirs)
    assert report.duplicates == 1 and report.imported == 1 and report.discarded == 2
    assert any("fuori scala" in r for r in report.reasons) and any("futuro" in r for r in report.reasons)
    assert data_import.load_rows("stile", dirs["store_dir"])[0]["possesso"] == 57       # nei doppioni vale l'ultima riga


def test_nessun_dato_dal_futuro(tmp_path, dirs):
    data_import.import_file(_csv(tmp_path, STYLE), today=date(2026, 6, 1), known=KNOWN, **dirs)
    store = dirs["store_dir"]
    assert data_import.style_row("Inter", "2026-05-25", store) is None          # stesso giorno: non ancora noto
    assert data_import.style_row("Inter", "2026-05-26", store)["xg"] == 68.5
    assert data_import.style_row("Inter", "2026-01-10", store) is None


def _store_with_proxy():
    rows = []
    for i in range(10):
        for team, other, venue in (("Inter", "Milan", "home"), ("Milan", "Inter", "away")):
            rows.append({"league": "I1", "season": "2526", "date": pd.Timestamp("2025-09-01") + pd.Timedelta(days=7 * i),
                         "team": team, "key": team.lower(), "opponent": other, "venue": venue, "gf": 1.0, "ga": 1.0,
                         "xg_for": 1.1, "xg_against": 1.0, "xg_source": "proxy dai tiri", "xg_diff": 0.1})
    return pd.DataFrame(rows)


def test_importato_prevale_sul_proxy_e_dichiara_fonte(tmp_path, dirs, monkeypatch):
    table = _store_with_proxy()
    store = style_profile.StyleStore(table)
    when = pd.Timestamp("2026-08-30")
    base = style_profile.forma_reale(store, "I1", "inter", "home", when)
    assert "proxy" in base.fonte
    data_import.import_file(_csv(tmp_path, STYLE), source="Opta", today=date(2026, 6, 1), known=KNOWN, **dirs)
    monkeypatch.setattr(data_import, "STORE_DIR", dirs["store_dir"])
    imported = style_profile.forma_reale(store, "I1", "inter", "home", when)
    assert "dato importato dal" in imported.fonte and "fonte Opta" in imported.fonte
    assert imported.valore == pytest.approx((68.5 - 35.2) / 38 * 38 / (38 + store.config["shrinkage_k"].get("forma_reale", 8.0)), abs=1e-6)
    # senza dato precedente alla partita resta il proxy dichiarato
    early = style_profile.forma_reale(store, "I1", "inter", "home", pd.Timestamp("2026-03-01"))
    assert "proxy" in early.fonte
    # nessuna correzione sopra correzioni: con l'interruttore spento torna esattamente la stima di partenza
    monkeypatch.setattr(data_import, "ENABLED", False)
    assert style_profile.forma_reale(store, "I1", "inter", "home", when).valore == base.valore


# --- Scelta del motore ----------------------------------------------------------------------------------------------

def test_tre_posizioni_e_motore_dichiarato_nel_risultato():
    config = config_from_input(parse_match_input(VALID), simulations=3000, seed=4)
    names = {}
    for choice in (engine_choice.CURRENT, engine_choice.CORNER, engine_choice.FULL):
        result = simulate_match(engine_choice.apply(config, choice))
        names[choice] = result["motore"]["scelta"]
        assert result["motore"]["chiave"] == choice and result["motore"]["etichetta"] == f"motore: {names[choice]}"
        one = result["markets"]["1x2"]
        assert sum(m["percentage"] for m in one.values()) == pytest.approx(100.0, abs=0.3)
    assert len(set(names.values())) == 3


def test_fase_o_accesa_non_da_errore():
    from timeline import TimelineParams

    config = replace(config_from_input(parse_match_input(VALID), simulations=2000, seed=1),
                     timeline=TimelineParams(active=True, components=("gol_stato",)))
    result = simulate_match(engine_choice.apply(config, engine_choice.CORNER))
    assert result["motore"]["chiave"] == engine_choice.CORNER


def test_libero_ripesa_dixon_coles_sullo_stesso_campione():
    config = config_from_input(parse_match_input(VALID), simulations=6000, seed=2)
    result = simulate_match(engine_choice.apply(config, engine_choice.FULL))
    details = result["event_engine"]
    assert details["modo"] == "libero" and set(details["dixon_coles"]["dopo"]) == {"0-0", "1-0", "0-1", "1-1"}
    ou = result["markets"]["over_under"]
    assert ou["Over_2.5"]["percentage"] + ou["Under_2.5"]["percentage"] == pytest.approx(100.0, abs=0.01)


def test_etichetta_dice_se_manca_la_taratura_del_motore_a_eventi():
    import taratura

    tar = taratura.load()
    attuale = engine_choice.preset(engine_choice.CURRENT, engine.DEFAULT_EVENT_ENGINE)
    completo = engine_choice.preset(engine_choice.FULL, engine.DEFAULT_EVENT_ENGINE)
    corner = engine_choice.preset(engine_choice.CORNER, engine.DEFAULT_EVENT_ENGINE)
    assert engine_choice.label(attuale, tar, "Over 2.5 gol", 60.0) in ("verificata", "poco verificata", "non affidabile")
    assert "nessuna taratura" in engine_choice.label(completo, tar, "Over 2.5 gol", 60.0)
    assert "nessuna taratura" in engine_choice.label(corner, tar, "Over 9.5 corner", 55.0)
    assert "nessuna taratura" not in engine_choice.label(corner, tar, "Over 2.5 gol", 60.0)


def test_predefinito_salvato(tmp_path):
    path = tmp_path / "impostazioni.json"
    assert engine_choice.load_default(path) == engine_choice.CURRENT
    engine_choice.save_default(engine_choice.FULL, path)
    assert engine_choice.load_default(path) == engine_choice.FULL
    engine_choice.save_default("sbagliato", path)
    assert engine_choice.load_default(path) == engine_choice.CURRENT


def test_registro_riporta_il_motore():
    import prediction_log

    config = config_from_input(parse_match_input(VALID), simulations=2000, seed=1)
    result = simulate_match(engine_choice.apply(config, engine_choice.CORNER))
    assert result["motore"]["scelta"] in result["motore"]["etichetta"]
    assert prediction_log.ENGINE_NOTE == "motore: "
