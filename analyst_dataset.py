"""Fase Y, punti 2, 4 e 5: storico proprio («dataset Analista») e verifiche che le fonti gratuite non permettono.

Una voce per partita (chiave data|Casa - Ospite) con: profili tattici delle due squadre alla data della partita
(dalle schede PROFILO_TATTICO), quote, probabilità del modello (mercati principali e per tempo), gol, corner e
gialli attesi, fattori delle regole applicate ed esito completo dal blocco ESITO (anche per tempo, con la fonte).
L'archivio è cumulativo: tabella SQLite ``dataset_analista`` nella cache locale, foglio «Dataset Analista»
dell'Excel della giornata (JSON nel foglio tecnico, ripristinato da «Riprendi da file»). Le probabilità e i
profili di una partita si fissano alla prima analisi; l'esito si aggiunge senza sovrascrivere valori presenti.

- ``verify_rules``: con almeno ``min_partite`` partite con profili ed esiti, per ogni regola dell'Analista
  stima l'effetto (osservato/atteso dove la regola vale, diviso lo stesso rapporto dove non vale) in una metà
  del dataset (per data) e misura l'altra metà, poi il contrario; regola severa su log-verosimiglianza ed ECE.
- ``half_calibration``: con almeno ``min_partite_tempi`` partite con corner e cartellini del primo tempo,
  calibrazione dei mercati per tempo (oggi «non verificabili» con i dati storici gratuiti).
"""

from __future__ import annotations

from datetime import date, datetime
import json
import math
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.stats import nbinom, poisson

from tactical_sheets import TacticalSheet, _applies, load_rules

TABLE = "dataset_analista"
SHEET = "Dataset Analista"
SHEET_COLUMNS = ("ID", "Data", "Competizione", "Partita", "Profilo casa", "Profilo ospite", "Gol attesi", "Esito",
                 "Primo tempo", "Corner", "Corner 1T", "Gialli", "Gialli 1T", "Rossi", "Fonte esito", "Regole applicate")
MAIN_KEYS = ("1", "X", "2", "Over 2.5 gol", "Under 2.5 gol", "Goal", "Over 9.5 corner", "Over 4.5 cartellini")


def record_id(day: date | str, home: str, away: str) -> str:
    return f"{str(day)[:10]}|{home} - {away}"


def stored_probabilities(final: Mapping[str, float]) -> dict[str, float]:
    """Mercati principali più tutti i mercati di corner e cartellini per tempo (verifica del punto 5)."""
    return {key: float(value) for key, value in final.items()
            if key in MAIN_KEYS or ((" corner " in f" {key} " or " cartellini " in f" {key} ") and key.endswith((" 1T", " 2T")))}


def from_result(day: date | str, competition: str, home: str, away: str, result: Mapping[str, Any],
                odds: Mapping[str, float] | None, home_sheet: TacticalSheet | None, away_sheet: TacticalSheet | None,
                effects=None, context: Mapping[str, Any] | None = None) -> dict:
    counts = result.get("count_anchoring") or {}
    return {
        "id": record_id(day, home, away), "data": str(day)[:10], "competizione": competition or "", "casa": home,
        "ospite": away,
        "profilo_casa": home_sheet.to_dict() if home_sheet is not None else None,
        "profilo_ospite": away_sheet.to_dict() if away_sheet is not None else None,
        "quote": {key: float(value) for key, value in (odds or {}).items()},
        "probabilita": stored_probabilities(result["components"]["finale"]),
        "attesi": {"lambda": float(result["model"]["lambda"]), "mu": float(result["model"]["mu"]),
                   "corner": float((counts.get("corner") or {}).get("final_mean") or 0.0) or None,
                   "gialli": float((counts.get("cartellini") or {}).get("final_mean") or 0.0) or None},
        "regole": {"fattori": dict(effects.factors) if effects is not None else {},
                   "analista": list(effects.analyst_notes) if effects is not None else []},
        "contesto": context,
        "esito": None, "aggiornato": datetime.now().isoformat(timespec="seconds"),
    }


def _same_match(record: Mapping[str, Any], home: str, away: str, day: date | None, tolerance: int = 1) -> bool:
    from datasources.names import match_team

    if not (match_team(home, [record["casa"]]) and match_team(away, [record["ospite"]])):
        return False
    return day is None or abs((date.fromisoformat(record["data"]) - day).days) <= tolerance


def upsert(records: Sequence[Mapping[str, Any]], record: Mapping[str, Any]) -> list[dict]:
    """Aggiunge o aggiorna una partita: profili e probabilità della prima analisi restano, l'esito si conserva."""
    out, found = [], False
    for item in records:
        if item["id"] == record["id"] or _same_match(item, record["casa"], record["ospite"],
                                                      date.fromisoformat(record["data"]), tolerance=0):
            merged = dict(record)
            for key in ("profilo_casa", "profilo_ospite"):
                merged[key] = item.get(key) or record.get(key)
            merged["esito"] = item.get("esito") or record.get("esito")
            out.append(merged)
            found = True
        else:
            out.append(dict(item))
    return out if found else [*out, dict(record)]


def attach_outcome(records: Sequence[Mapping[str, Any]], block) -> tuple[list[dict], str]:
    """Esito di un blocco ESITO nella voce della partita (creata se manca); i valori presenti non cambiano."""
    day = block.when.date() if block.when else None
    out, status = [dict(item) for item in records], "aggiunto"
    target = next((item for item in out if _same_match(item, block.home, block.away, day)), None)
    if target is None:
        target = {"id": record_id(day, block.home, block.away), "data": day.isoformat(), "competizione": block.competition,
                  "casa": block.home, "ospite": block.away, "profilo_casa": None, "profilo_ospite": None, "quote": {},
                  "probabilita": {}, "attesi": {}, "regole": {}, "esito": None,
                  "aggiornato": datetime.now().isoformat(timespec="seconds")}
        out.append(target)
        status = "nuova partita (solo esito)"
    current = dict(target.get("esito") or {})
    missing = {key: value for key, value in block.values.items() if key not in current}
    if not missing:
        return out, "già presente"
    current.update(missing)
    current.setdefault("fonte", block.source)
    target["esito"] = current
    target["aggiornato"] = datetime.now().isoformat(timespec="seconds")
    return out, status


# --- Archivio locale -------------------------------------------------------------------------------------

class DatasetStore:
    def __init__(self, cache) -> None:
        self.path = cache.path
        with sqlite3.connect(self.path) as connection:
            connection.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} (id TEXT PRIMARY KEY, data TEXT, json TEXT)")

    def load(self) -> list[dict]:
        with sqlite3.connect(self.path) as connection:
            return [json.loads(row[0]) for row in connection.execute(f"SELECT json FROM {TABLE} ORDER BY data, id")]

    def save(self, records: Iterable[Mapping[str, Any]]) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.executemany(f"INSERT OR REPLACE INTO {TABLE} (id, data, json) VALUES (?, ?, ?)",
                                   [(item["id"], item["data"], json.dumps(item, ensure_ascii=False)) for item in records])


def sheet_row(record: Mapping[str, Any]) -> dict:
    outcome = record.get("esito") or {}

    def pair(key: str) -> str:
        home, away = outcome.get(f"home_{key}"), outcome.get(f"away_{key}")
        return f"{home}-{away}" if home is not None and away is not None else ""

    expected = record.get("attesi") or {}
    return {"ID": record["id"], "Data": record["data"], "Competizione": record.get("competizione", ""),
            "Partita": f"{record['casa']} - {record['ospite']}",
            "Profilo casa": "sì" if record.get("profilo_casa") else "no",
            "Profilo ospite": "sì" if record.get("profilo_ospite") else "no",
            "Gol attesi": f"{expected['lambda']:.2f}-{expected['mu']:.2f}" if expected.get("lambda") else "",
            "Esito": pair("goals"), "Primo tempo": pair("ht_goals"), "Corner": pair("corners"),
            "Corner 1T": pair("corners_1t"), "Gialli": pair("yellows"), "Gialli 1T": pair("yellows_1t"),
            "Rossi": pair("reds"), "Fonte esito": outcome.get("fonte", ""),
            "Regole applicate": "; ".join((record.get("regole") or {}).get("analista") or [])}


# --- Verifiche --------------------------------------------------------------------------------------------

def _ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    index = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return float(sum(abs(p[index == b].mean() - y[index == b].mean()) * (index == b).sum()
                     for b in range(bins) if (index == b).any()) / len(p))


def _strict(before: np.ndarray, after: np.ndarray, ece_before: float, ece_after: float) -> dict:
    difference = after - before
    error = float(difference.std(ddof=1) / math.sqrt(len(difference))) if len(difference) > 1 else float("nan")
    keep = bool(difference.mean() < -2 * error and ece_after <= ece_before + 0.0005)
    worse = bool(difference.mean() > 2 * error or (difference.mean() > 0 and ece_after > ece_before + 0.0005))
    return {"differenza": float(difference.mean()), "due_es": 2 * error, "ece_prima": ece_before, "ece_dopo": ece_after,
            "migliora": keep, "peggiora": worse}


def usable(records: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Partite con i profili di entrambe le squadre, l'esito e i valori attesi."""
    return [record for record in records if record.get("profilo_casa") and record.get("profilo_ospite")
            and (record.get("esito") or {}).get("home_goals") is not None and (record.get("attesi") or {}).get("lambda")]


def _dispersions() -> tuple[float, float]:
    from engine import DEFAULT_COUNT_MODEL

    model = DEFAULT_COUNT_MODEL
    return (model.corner_dispersion, model.card_dispersion) if model.active else (0.0, 0.0)


def _count_logpmf(count: int, mean: float, dispersion: float) -> float:
    if dispersion > 0:
        return float(nbinom.logpmf(count, dispersion, dispersion / (dispersion + mean)))
    return float(poisson.logpmf(count, mean))


def _count_sf(line: float, mean: float, dispersion: float) -> float:
    if dispersion > 0:
        return float(nbinom.sf(math.floor(line), dispersion, dispersion / (dispersion + mean)))
    return float(poisson.sf(math.floor(line), mean))


def verify_rules(records: Sequence[Mapping[str, Any]], settings: Mapping[str, Any] | None = None) -> dict:
    """Verifica delle regole dell'Analista sullo storico proprio (vedi docstring del modulo)."""
    settings = settings or load_rules()
    section = settings.get("regole_analista") or {}
    minimum = int(section.get("min_partite", 150))
    data = sorted(usable(records), key=lambda record: record["data"])
    out = {"partite": len(data), "minimo": minimum, "regole": {}}
    if len(data) < minimum:
        return out
    rules = {rule["id"]: rule for rule in settings["regole"]}
    corner_shape, card_shape = _dispersions()
    low, high = section.get("limiti", (0.95, 1.05))
    halves = (np.arange(len(data)) < len(data) // 2)
    for rule_id in (section.get("regole") or {}):
        rule = rules.get(rule_id)
        if rule is None:
            continue
        sides = []  # (indice partita, lato che attacca, regola applicata)
        for index, record in enumerate(data):
            home, away = TacticalSheet.from_dict(record["profilo_casa"]), TacticalSheet.from_dict(record["profilo_ospite"])
            sides.append((index, "home", _applies(rule, home, away)))
            sides.append((index, "away", _applies(rule, away, home)))
        applied = np.array([flag for _, _, flag in sides])
        result = {"partite": len(data), "casi": int(applied.sum()), "effetto": {}, "verifica": {}}
        for key in rule["effetto"]:
            observed, expected, match_index = [], [], []
            for index, side, _ in sides:
                record, outcome = data[index], data[index]["esito"]
                if key == "gol":
                    observed.append(outcome[f"{side}_goals"])
                    expected.append(record["attesi"]["lambda" if side == "home" else "mu"])
                else:
                    total_key = "corners" if key == "corner" else "yellows"
                    mean_key = "corner" if key == "corner" else "gialli"
                    value, mean = outcome.get(f"home_{total_key}"), record["attesi"].get(mean_key)
                    observed.append(np.nan if value is None or not mean else value + outcome[f"away_{total_key}"])
                    expected.append(mean or np.nan)
                match_index.append(index)
            observed, expected, match_index = np.array(observed, float), np.array(expected, float), np.array(match_index)
            valid = np.isfinite(observed) & np.isfinite(expected) & (expected > 0)

            def estimate(part: np.ndarray) -> float:
                inside, outside = valid & applied & part, valid & ~applied & part
                if inside.sum() < 5 or outside.sum() < 5:
                    return 1.0
                ratio = (observed[inside].sum() / expected[inside].sum()) / (observed[outside].sum() / expected[outside].sum())
                return float(np.clip(ratio, low, high))

            first, second = halves[match_index], ~halves[match_index]
            effect_first, effect_second = estimate(first), estimate(second)
            # Ogni metà è misurata con l'effetto stimato sull'altra (fuori campione).
            factor = np.where(applied, np.where(first, effect_second, effect_first), 1.0)
            line = {"gol": 1.5, "corner": 9.5, "cartellini": 4.5}[key]
            shape = {"gol": 0.0, "corner": corner_shape, "cartellini": card_shape}[key]
            # Gol: per squadra; corner e gialli: totale della partita, una volta (lato casa) con il prodotto dei fattori.
            rows = valid if key == "gol" else valid & np.array([side == "home" for _, side, _ in sides])
            if key != "gol":
                factor = np.where(np.array([side == "home" for _, side, _ in sides]),
                                  factor * np.roll(factor, -1), factor)
            before = np.array([-_count_logpmf(int(o), e, shape) for o, e in zip(observed[rows], expected[rows])])
            after = np.array([-_count_logpmf(int(o), e * f, shape) for o, e, f in zip(observed[rows], expected[rows], factor[rows])])
            p_before = np.array([_count_sf(line, e, shape) for e in expected[rows]])
            p_after = np.array([_count_sf(line, e * f, shape) for e, f in zip(expected[rows], factor[rows])])
            y = (observed[rows] > line).astype(float)
            result["effetto"][key] = round(estimate(np.ones(len(observed), bool)), 4)
            result["verifica"][key] = _strict(before, after, _ece(p_before, y), _ece(p_after, y))
        checks = result["verifica"].values()
        result["proposta"] = ("passa a «verificata»" if checks and all(check["migliora"] for check in checks) else
                              "spegni" if any(check["peggiora"] for check in checks) else "lascia «da verificare»")
        out["regole"][rule_id] = result
    return out


def half_calibration(records: Sequence[Mapping[str, Any]], minimum: int | None = None) -> dict:
    """Calibrazione dei mercati di corner e cartellini per tempo con gli esiti dell'Analista."""
    from performance import settle

    minimum = int(minimum if minimum is not None else (load_rules().get("regole_analista") or {}).get("min_partite_tempi", 100))
    data = [record for record in records if record.get("probabilita")
            and all(key in (record.get("esito") or {}) for key in ("home_corners_1t", "away_corners_1t",
                                                                    "home_yellows_1t", "away_yellows_1t"))]
    out = {"partite": len(data), "minimo": minimum, "mercati": []}
    if len(data) < minimum:
        return out
    keys = sorted({key for record in data for key in record["probabilita"] if key.endswith((" 1T", " 2T"))})
    for key in keys:
        pairs = []
        for record in data:
            outcome = settle(key, record["esito"])
            if outcome is not None and key in record["probabilita"]:
                pairs.append((record["probabilita"][key] / 100.0, outcome))
        if len(pairs) < 20:
            continue
        p, y = np.array([pair[0] for pair in pairs]), np.array([pair[1] for pair in pairs], float)
        clipped = np.clip(p, 1e-6, 1 - 1e-6)
        out["mercati"].append({"Mercato": key, "Partite": len(pairs), "Prevista %": round(100 * p.mean(), 1),
                               "Reale %": round(100 * y.mean(), 1),
                               "Log-loss": round(float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped))), 4),
                               "ECE": round(_ece(p, y, bins=5), 4)})
    return out


def apply_proposal(rule_id: str, verdict: Mapping[str, Any], path=None) -> None:
    """Scrive in ``config/tattica.json`` lo stato proposto (dopo la conferma dell'utente)."""
    from tactical_sheets import CONFIG_PATH

    path = path or CONFIG_PATH
    settings = json.loads(path.read_text(encoding="utf-8"))
    state = settings["regole_analista"]["regole"].setdefault(rule_id, {})
    if verdict["proposta"].startswith("passa"):
        state.update(stato="verificata", effetto={key: value for key, value in verdict["effetto"].items()})
    elif verdict["proposta"] == "spegni":
        state["stato"] = "spenta"
    state["verifica"] = {"data": date.today().isoformat(), "partite": verdict["partite"], "casi": verdict["casi"],
                         **{key: {name: round(value, 6) if isinstance(value, float) else value for name, value in check.items()}
                            for key, check in verdict["verifica"].items()}}
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
