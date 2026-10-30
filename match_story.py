"""Fase AK, stadio 15: «Vedi come andrà» — come si sviluppa la partita analizzata, dai percorsi del motore a eventi.

Per fasce di 15 minuti: tiri, gol attesi, corner, gialli e rossi per squadra; probabilità di un gol in ogni tratto di
5 minuti; minuto e squadra del primo gol; frasi in italiano. Sempre con l'indicazione del motore attivo:

- motore a eventi acceso (anche solo per alcuni mercati): l'andamento viene dagli STESSI percorsi della simulazione
  (``result["event_engine"]["andamento"]``);
- motore a eventi spento: si fa girare il motore a eventi sulla stessa ``MatchConfig`` solo per disegnare l'andamento
  (illustrativo, dichiarato): le probabilità dei mercati restano quelle del motore attuale.

Solo presentazione dei percorsi: nessun numero nuovo entra nelle probabilità, nell'EV o nel registro.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import engine

ILLUSTRATIVE_SIMULATIONS = 20_000
GROUP_NAMES = {"tempi": "gol del primo e secondo tempo", "corner": "corner", "cartellini": "cartellini"}


def engine_label(settings: engine.EventEngineParams) -> str:
    """Quale motore produce le probabilità, in italiano."""
    if not settings.active or not settings.markets:
        return ("Motore attivo: motore attuale (punteggi Dixon-Coles, corner e cartellini dalle medie). Il motore a eventi è "
                "spento per i mercati: l'andamento qui sotto è solo illustrativo e non cambia le probabilità.")
    used = [GROUP_NAMES[group] for group in engine.EVENT_ENGINE_GROUPS if group in settings.markets]
    others = [GROUP_NAMES[group] for group in engine.EVENT_ENGINE_GROUPS if group not in settings.markets]
    text = f"Motore attivo: motore a eventi per {', '.join(used)}"
    if others:
        text += f"; {', '.join(others)} dal motore attuale"
    return text + " (stessi punteggi Dixon-Coles). L'andamento viene dagli stessi percorsi della simulazione."


def illustrative_run(config: engine.MatchConfig, simulations: int = ILLUSTRATIVE_SIMULATIONS) -> dict[str, Any]:
    """Motore a eventi sulla stessa configurazione, solo per l'andamento (nessun arresto anticipato)."""
    settings = replace(config.event_engine, active=True, minimum=simulations, batch=simulations,
                       pilot=min(config.event_engine.pilot, simulations))
    result = engine.simulate_match(replace(config, simulations=simulations, keep_samples=False, event_engine=settings))
    return result["event_engine"]


def story(result: dict, config: engine.MatchConfig | None, cached: dict | None = None) -> dict[str, Any]:
    """Andamento della partita: dal risultato se il motore a eventi era acceso, altrimenti da ``cached`` (una
    ``illustrative_run`` già fatta) o da una nuova esecuzione illustrativa. Errore spiegato se non si può calcolare."""
    details = result.get("event_engine") or {}
    settings = config.event_engine if config is not None else engine.EventEngineParams()
    out = {"motore": engine_label(settings), "illustrativo": not details.get("active"), "errore": None}
    if details.get("active") and details.get("andamento"):
        source = details
    elif cached is not None:
        source = cached
    elif config is None:
        out["errore"] = "Configurazione della partita non disponibile: riesegui la simulazione."
        return out
    elif config.timeline.active:
        out["errore"] = "Il motore minuto per minuto (fase O) è acceso: non si può usare insieme al motore a eventi."
        return out
    else:
        source = illustrative_run(config)
    out.update({"andamento": source["andamento"], "parametri": source.get("parametri"), "dettagli": source})
    out["frasi"] = sentences(source["andamento"], result)
    return out


def _names(result: dict) -> tuple[str, str]:
    teams = result.get("input") or {}
    return ((teams.get("home") or {}).get("name") or "Casa", (teams.get("away") or {}).get("name") or "Ospite")


def _pct(value: float) -> str:
    return f"{100 * value:.0f}%"


def sentences(timeline: dict, result: dict) -> list[str]:
    """Poche frasi in italiano sull'andamento."""
    home, away = _names(result)
    rows = timeline["fasce"]
    first = {band: p for band, p in timeline["primo_gol"].items() if band != "nessun gol"}
    best = max(first, key=first.get)
    low, high = best.split("-")
    lines = [f"Primo gol: più probabile tra il {low}' e il {high}' ({_pct(first[best])}); segna per prima {home} nel "
             f"{_pct(timeline['primo_gol_casa'])} delle partite, {away} nel {_pct(timeline['primo_gol_ospite'])}, nessun gol "
             f"nel {_pct(timeline['primo_gol']['nessun gol'])}."]
    goals = [row["goals_home"] + row["goals_away"] for row in rows]
    peak = rows[max(range(len(rows)), key=goals.__getitem__)]["fascia"]
    total_goals = sum(goals)
    first_half = sum(goals[:3]) / total_goals if total_goals else 0.0
    lines.append(f"Gol: {total_goals:.2f} attesi, {_pct(first_half)} nel primo tempo; la fascia con più gol attesi è "
                 f"{peak}'.")
    shots = (sum(row["shots_home"] for row in rows), sum(row["shots_away"] for row in rows))
    corners = (sum(row["corners_home"] for row in rows), sum(row["corners_away"] for row in rows))
    corner_bands = [row["corners_home"] + row["corners_away"] for row in rows]
    trend = ("più nel finale" if corner_bands[-1] > corner_bands[0] * 1.05 else
             "più a inizio partita" if corner_bands[-1] < corner_bands[0] * 0.95 else "distribuiti in modo uniforme")
    lines.append(f"Tiri: {home} {shots[0]:.1f}, {away} {shots[1]:.1f}. Corner: {home} {corners[0]:.1f}, {away} {corners[1]:.1f}, "
                 f"{trend}.")
    yellows = [row["yellows_home"] + row["yellows_away"] for row in rows]
    late = sum(yellows[4:]) / sum(yellows) if sum(yellows) else 0.0
    lines.append(f"Gialli: {sum(yellows):.1f} mostrati in media, {_pct(late)} dopo il 60'. Almeno un'espulsione nel "
                 f"{_pct(timeline['almeno_un_rosso'])} delle partite.")
    return lines


def band_table(timeline: dict, result: dict) -> list[dict[str, Any]]:
    """Righe della tabella per fascia, con intestazioni in italiano."""
    home, away = _names(result)
    return [{"Minuti": f"{row['fascia']}'", f"Tiri {home}": round(row["shots_home"], 2), f"Tiri {away}": round(row["shots_away"], 2),
             f"Gol attesi {home}": round(row["goals_home"], 2), f"Gol attesi {away}": round(row["goals_away"], 2),
             f"Corner {home}": round(row["corners_home"], 2), f"Corner {away}": round(row["corners_away"], 2),
             f"Gialli {home}": round(row["yellows_home"], 2), f"Gialli {away}": round(row["yellows_away"], 2),
             "Rossi": round(row["reds_home"] + row["reds_away"], 3)}
            for row in timeline["fasce"]]


def goal_moments(timeline: dict) -> list[dict[str, Any]]:
    """Probabilità di almeno un gol in ogni tratto di 5 minuti."""
    steps = timeline["gol_nel_passo"]
    width = (steps["minuto"][1] - steps["minuto"][0]) if len(steps["minuto"]) > 1 else 5
    return [{"Minuti": f"{minute}-{minute + width}'", "Probabilità di un gol": round(100 * p, 1)}
            for minute, p in zip(steps["minuto"], steps["probabilita"])]


def first_goal_rows(timeline: dict) -> list[dict[str, Any]]:
    return [{"Primo gol": band if band == "nessun gol" else f"{band}'", "Probabilità": f"{100 * p:.1f}%"}
            for band, p in timeline["primo_gol"].items()]
