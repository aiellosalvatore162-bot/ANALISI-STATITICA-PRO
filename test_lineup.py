"""Fase AL: giocatori Understat, formazione attesa, assenti pesati, rigorista, performando; niente doppia conta con P e AD."""

from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import absences
import engine
import lineup as lu
import players as pl
from parser import parse_match_input
from test_engine import VALID

WHEN = pd.Timestamp("2026-03-01")
GK, STAR, BACKUP = "p_gk", "p_star", "p_backup"


def _player(side, pid, name, position, minutes, xg=0.0, xa=0.0, goals=0.0, shots=0.0):
    return {"side": side, "player_id": pid, "player": name, "position": position, "time": str(minutes), "goals": str(goals),
            "xG": str(xg), "xA": str(xa), "shots": str(shots), "roster_in": "0", "roster_out": "0", "positionOrder": "1"}


def _squad(side, team_tag, star_plays=True, star_xg=0.6):
    """11 titolari (portiere, 4 difensori, 4 centrocampisti, 2 attaccanti con STAR) e 3 della panchina."""
    out = [_player(side, GK + team_tag, f"Portiere {team_tag}", "GK", 90)]
    for i in range(4):
        out.append(_player(side, f"d{i}{team_tag}", f"Difensore {i} {team_tag}", "DC", 90, xg=0.02, xa=0.03))
    for i in range(4):
        out.append(_player(side, f"c{i}{team_tag}", f"Centrale {i} {team_tag}", "DMC", 85, xg=0.06, xa=0.08))
    out.append(_player(side, STAR, "Bomber Rossi", "FW", 90 if star_plays else 0, xg=star_xg if star_plays else 0.0, xa=0.1,
                       goals=1.0 if star_plays and star_xg > 0.5 else 0.0))
    out.append(_player(side, "f2" + team_tag, f"Punta {team_tag}", "FW", 90, xg=0.15, xa=0.05))
    out.append(_player(side, BACKUP, "Riserva Verdi", "Sub", 20, xg=0.08, xa=0.02))
    out.append(_player(side, "b1" + team_tag, f"Panchinaro 1 {team_tag}", "Sub", 15, xg=0.03, xa=0.02))
    return out


def fake_matches(n=12, absent_last=False):
    matches = []
    for i in range(n):
        last = i == n - 1
        matches.append({"id": str(i), "date": (pd.Timestamp("2026-01-01") + pd.Timedelta(days=7 * i)).strftime("%Y-%m-%d %H:%M:%S"),
                        "home": "Alfa FC", "away": "Beta FC", "home_goals": 2, "away_goals": 1,
                        "players": _squad("h", "A", star_plays=not (absent_last and last)) + _squad("a", "B"),
                        "penalties": [{"side": "h", "player_id": STAR, "player": "Bomber Rossi", "xG": "0.76",
                                       "result": "Goal" if i % 3 else "Missed"}] if i % 2 == 0 else []})
    return matches


@pytest.fixture()
def store():
    table = pl.rows_from_matches(fake_matches(), "I1")
    return pl.PlayerStore(table, config={**pl.load_config(), "fattore_attacco": {"limiti": None, "esponente": 1.0}})


KEY = pl.canonical_key("Alfa FC")


def test_roles_and_npxg_from_penalties(store):
    assert [pl.role4(code) for code in ("GK", "DC", "DMC", "AMR", "FW", "Sub", "F S")] == ["POR", "DIF", "CEN", "ATT", "ATT", None, "ATT"]
    star = store.table[(store.table["player_id"] == STAR) & (store.table["match_id"] == "0")].iloc[0]
    assert star["xg"] == pytest.approx(0.6) and star["npxg"] == pytest.approx(0.6 - 0.76)   # il rigore non è npxG


def test_rates_shrink_towards_the_role_average(store):
    when = WHEN
    squad = pl.squad_stats(store, "I1", KEY, when).set_index("player_id")
    role = store.role_stats("I1", when)["ATT"]
    star = squad.loc[STAR]
    k = store.config["k_minuti"]["ATT"]
    age = (when - store.team_rows("I1", KEY, when).query("player_id == @STAR")["date"]).dt.days.to_numpy(float)
    weights = 0.5 ** (age / store.config["emivita_giorni"])
    minutes = float((weights * 90).sum())
    assert star["minuti_pesati"] == pytest.approx(minutes)
    rows = store.team_rows("I1", KEY, when).query("player_id == @STAR")
    raw = 90.0 * float((weights * rows["xa"]).sum()) / minutes
    assert star["xa90"] == pytest.approx((minutes * raw + k * role["xa"]) / (minutes + k), rel=1e-6)
    # il peso del giocatore è n/(n+k): con pochi minuti si sta più vicini al ruolo
    short = pl.PlayerStore(pl.rows_from_matches(fake_matches(2), "I1"), config=store.config)
    assert pl.squad_stats(short, "I1", KEY, WHEN).set_index("player_id").loc[STAR]["minuti_pesati"] < minutes


def test_absent_star_is_weighted_not_counted(store):
    base = lu.team_lineup(store, "I1", KEY, WHEN)
    gone = lu.team_lineup(store, "I1", KEY, WHEN, absent=[{"nome": "Bomber Rossi", "fonte": "https://x.it", "motivo": "infortunio"}])
    assert base["fattore_attacco"]["valore"] == pytest.approx(1.0)
    assert 0.80 < gone["fattore_attacco"]["valore"] < 1.0
    absent = gone["assenti"][0]
    assert absent["giocatore"] == "Bomber Rossi" and absent["fonte"] == "https://x.it" and absent["in_xi_tipo"]
    assert absent["quota_persa"] == pytest.approx(1.0 - gone["fattore_attacco"]["valore"], abs=1e-6)   # un solo assente: stesso valore
    assert "Bomber Rossi" not in [row["giocatore"] for row in gone["xi"]] and len(gone["xi"]) == 11
    assert "Riserva Verdi" in [row["giocatore"] for row in gone["xi"] + gone["panchina"]]
    # un assente che non gioca quasi mai pesa quasi zero (PESATO, non contato)
    bench = lu.team_lineup(store, "I1", KEY, WHEN, absent=[{"nome": "Panchinaro 1 A", "fonte": "https://x.it"}])
    assert bench["fattore_attacco"]["valore"] == pytest.approx(1.0, abs=0.01)
    unknown = lu.team_lineup(store, "I1", KEY, WHEN, absent=[{"nome": "Sconosciuto Zeta", "fonte": "https://x.it"}])
    assert any("non trovato" in message for message in unknown["avvisi"]) and unknown["fattore_attacco"]["valore"] == pytest.approx(1.0)


def test_minutes_and_origin_are_visible(store):
    side = lu.team_lineup(store, "I1", KEY, WHEN)
    assert "XI tipo" in side["origine_formazione"]
    assert sum(row["minuti_attesi"] for row in side["xi"] + side["panchina"]) == pytest.approx(990.0, abs=1.0)
    assert all(row["origine"] for row in side["xi"]) and side["xi"][0]["minuti_attesi"] > 80
    confirmed = lu.team_lineup(store, "I1", KEY, WHEN, confirmed=[row["giocatore"] for row in side["xi"]][:10] + ["Riserva Verdi"],
                               source="https://report.it")
    assert "formazione indicata (https://report.it)" == confirmed["origine_formazione"]


def test_penalty_taker_absent_uses_substitute_or_the_league_average(store):
    present = lu.team_lineup(store, "I1", KEY, WHEN)["rigorista"]
    assert present["rigorista"] == "Bomber Rossi" and present["stato"] == "in campo"
    stats = pl.penalty_stats(store, "I1", KEY, WHEN)
    k = store.config["rigori"]["k_conversione"]
    taker = stats["battitori"][0]
    assert present["conversione"] == pytest.approx(round((taker["goals"] + k * stats["lega"]["conversione"]) / (taker["n"] + k), 3))
    gone = lu.team_lineup(store, "I1", KEY, WHEN, absent=[{"nome": "Bomber Rossi", "fonte": "https://x.it"}])["rigorista"]
    assert gone["stato"] == "assente" and gone["sostituto"] is None
    assert gone["conversione"] == pytest.approx(round(stats["lega"]["conversione"], 3))      # nessun sostituto: media del campionato
    assert "media del campionato" in gone["nota"]


def test_performing_is_shrunk_hard_and_labelled(store):
    side = lu.team_lineup(store, "I1", KEY, WHEN)
    star = next(row for row in side["performando"]["giocatori"] if row["giocatore"] == "Bomber Rossi")
    raw, xg = star["differenza_grezza"], star["npxg"]
    k = store.config["performando"]["k_xg"]
    assert star["differenza_ridimensionata"] == pytest.approx(round(raw * xg / (xg + k), 2), abs=0.011)
    assert abs(star["differenza_ridimensionata"]) <= abs(raw)
    assert star["etichetta"] in ("sopra l'xG", "sotto l'xG", "in linea")


def test_winsorization_warns_on_exorbitant_rates():
    matches = fake_matches()
    for match in matches:
        for player in match["players"]:
            if player["player_id"] == "f2A":
                player["xG"] = "3.5"        # tasso esorbitante per un attaccante
    store = pl.PlayerStore(pl.rows_from_matches(matches, "I1"))
    squad = pl.squad_stats(store, "I1", KEY, WHEN)
    row = squad[squad["player_id"] == "f2A"].iloc[0]
    assert any("fuori dai percentili" in message for message in row["avvisi"]) or row["npxg90"] < 3.5


# --- Motore: niente doppia conta con P e con la forma reale della AD ----------------------------------------------------

def _config(**changes):
    return replace(engine.config_from_input(parse_match_input(VALID), simulations=2000), **changes)


def test_engine_applies_lineup_before_anchoring_and_reports_it_in_the_ledger():
    base = engine.expected_goals(_config())
    lineup = {"home": {"attack": 0.9, "defense": 1.0}, "away": {"attack": 1.0, "defense": 1.1}}
    lam, mu, ledger = engine.expected_goals(_config(lineup=lineup))
    assert lam == pytest.approx(base[0] * 0.9 * 1.1) and mu == pytest.approx(base[1])
    assert ledger["formazione"]["usata"] and "formazione" not in base[2]
    # i fattori neutri (esponente 0, pesi di ruolo non stimabili) non cambiano nulla
    neutral = {"home": {"attack": 1.0, "defense": 1.0}, "away": {"attack": 1.0, "defense": 1.0}}
    assert engine.expected_goals(_config(lineup=neutral))[:2] == pytest.approx(base[:2])


def test_lineup_and_real_form_are_independent_multipliers():
    style = {"home": {"forma_reale": 0.4, "n_gare": 8}, "away": {"forma_reale": -0.2, "n_gare": 8}}
    model = engine.StyleModelParams(True, 0.3, 6.0)
    lineup = {"home": {"attack": 0.95, "defense": 1.0}, "away": {"attack": 1.0, "defense": 1.0}}
    only_style = engine.expected_goals(_config(style=style, style_model=model))
    both = engine.expected_goals(_config(style=style, style_model=model, lineup=lineup))
    assert both[0] == pytest.approx(only_style[0] * 0.95) and both[1] == pytest.approx(only_style[1])
    assert "forma_reale" in both[2] and "formazione" in both[2]


def test_absences_of_phase_p_are_off_when_lineup_moves_the_goals(monkeypatch, tmp_path):
    monkeypatch.setattr(absences, "_lineup_replaces_absences", lambda: True)
    assert absences.is_active() is False
    # con il fattore della formazione a esponente 0 le assenze della P non sono sostituite
    config = json.loads((Path(absences.__file__).parent / "config" / "giocatori.json").read_text(encoding="utf-8"))
    assert config["sostituisce_assenze_P"] is True and float(config["fattore_attacco"]["esponente"]) >= 0.0


def test_lineup_params_for_the_engine_and_unknown_teams(store):
    data = lu.get_lineup_params("Alfa FC", "Beta FC", WHEN, store, league="I1",
                                report={"casa": {"assenti": [{"nome": "Bomber Rossi", "fonte": "https://x.it"}]}})
    assert data["motore"]["home"]["attack"] < 1.0 and data["motore"]["away"]["attack"] == pytest.approx(1.0)
    assert data["casa"]["fattore_attacco"]["fonte"] and data["casa"]["rigorista"]["fonte"]
    missing = lu.get_lineup_params("Alfa FC", "Sconosciuta", WHEN, store)
    assert missing["motore"] is None and any("Understat" in message for message in missing["avvisi"])


def test_report_lines_formation_and_absences_are_parsed():
    import claude_bridge as bridge

    names = ", ".join(f"Giocatore {i}" for i in range(11))
    response = bridge.parse_response("CORREZIONI_CLAUDE:\nassenti_casa: Mario Rossi | fonte: https://a.it\n"
                                     f"formazione_ospite: {names} | fonte: https://b.it\nformazione_casa: solo uno | fonte: https://b.it\n"
                                     "confidenza: media")
    report = lu.report_from_response(response)
    assert report["casa"]["assenti"][0] == {"nome": "Mario Rossi", "fonte": "https://a.it", "motivo": "assente (report)"}
    assert len(report["ospite"]["formazione"]) == 11 and report["ospite"]["fonte"] == "https://b.it"
    assert any("formazione_casa" in warning for warning in response.warnings)
