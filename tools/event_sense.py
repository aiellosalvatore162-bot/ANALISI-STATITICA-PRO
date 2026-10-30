"""Fase AK, stadi 12-13: realismo e buon senso calcistico del motore a eventi acceso, su partite tipo.

Per ogni scenario (favorita netta, partita equilibrata, partita chiusa, arbitro severo, arbitro permissivo) si simula la stessa
partita con il motore attuale e con il motore a eventi (stessi punteggi Dixon-Coles, stesse medie finali per il vincolo di
coerenza) e si confrontano mercati e percorsi: chi è sotto spinge (più tiri e corner), chi è avanti gestisce, le espulsioni
cambiano la partita, l'arbitro severo dà più gialli e più seconde gialle. Uso:
``python -m tools.event_sense [--simulazioni 40000] [--output docs/backtest/AK_buon_senso.md]``.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

import engine

# Quote 1X2 e Over/Under 2.5 di chiusura tipiche (Serie A) e medie di corner/gialli delle squadre.
SCENARIOS: dict[str, dict[str, Any]] = {
    "favorita netta": {"odds": {"1": 1.28, "X": 6.0, "2": 11.0, "Over 2.5 gol": 1.62, "Under 2.5 gol": 2.30},
                       "corners": (7.0, 3.5, 3.8, 6.2), "cards": (1.6, 2.4), "referee": (4.4, 26.0)},
    "equilibrata": {"odds": {"1": 2.60, "X": 3.20, "2": 2.85, "Over 2.5 gol": 1.95, "Under 2.5 gol": 1.88},
                    "corners": (5.2, 4.9, 4.8, 5.1), "cards": (2.1, 2.2), "referee": (4.4, 26.0)},
    "chiusa": {"odds": {"1": 2.75, "X": 2.90, "2": 2.95, "Over 2.5 gol": 2.60, "Under 2.5 gol": 1.50},
               "corners": (4.6, 4.8, 4.5, 4.9), "cards": (2.4, 2.5), "referee": (4.4, 26.0)},
    "arbitro severo": {"odds": {"1": 2.60, "X": 3.20, "2": 2.85, "Over 2.5 gol": 1.95, "Under 2.5 gol": 1.88},
                       "corners": (5.2, 4.9, 4.8, 5.1), "cards": (2.1, 2.2), "referee": (6.0, 30.0)},
    "arbitro permissivo": {"odds": {"1": 2.60, "X": 3.20, "2": 2.85, "Over 2.5 gol": 1.95, "Under 2.5 gol": 1.88},
                           "corners": (5.2, 4.9, 4.8, 5.1), "cards": (2.1, 2.2), "referee": (3.2, 22.0)},
}
MARKETS = ("1", "X", "2", "Over 2.5 gol", "X 1T", "Over 0.5 gol 1T", "Over 1.5 gol 2T", "Over 9.5 corner", "1 corner",
           "Casa Over 4.5 corner", "Over 4.5 cartellini", "Over 1.5 cartellini 1T", "Ospite Over 1.5 cartellini",
           "Over 2.5 gol + Over 9.5 corner", "1 + Over 4.5 cartellini")


def scenario_config(name: str, simulations: int = 40_000, seed: int = 7, active: bool = False) -> engine.MatchConfig:
    spec = SCENARIOS[name]
    home_for, home_against, away_for, away_against = spec["corners"]

    def team(label, corners_for, corners_against, cards):
        base = engine.DEFAULT_GOAL_PARAMS.base_goals
        return engine.TeamParams(name=label, attack=1.0, defense=1.0, elo=1700.0, form="W-D-L-W-D", xg_for=base,
                                 xg_against=base, corners_for=corners_for, corners_against=corners_against, cards_for=cards)

    config = engine.MatchConfig(home=team("Casa", home_for, home_against, spec["cards"][0]),
                                away=team("Ospite", away_for, away_against, spec["cards"][1]),
                                referee_yellow_avg=spec["referee"][0], referee_fouls_avg=spec["referee"][1],
                                simulations=simulations, seed=seed, odds=dict(spec["odds"]), league="I1", keep_samples=True)
    return replace(config, event_engine=replace(config.event_engine, active=active))


def _bits(result: dict, key: str) -> np.ndarray:
    first, second = (key.split(" + ") + [None])[:2]
    size = result["sample_size"]
    mask = np.unpackbits(result["event_samples"][first])[:size].astype(bool)
    if second:
        mask &= np.unpackbits(result["event_samples"][second])[:size].astype(bool)
    return mask


def paths(sample: dict[str, np.ndarray]) -> dict[str, float]:
    """Misure di buon senso sui percorsi del motore a eventi."""
    gh, ga, fh, fa = sample["goals_home"], sample["goals_away"], sample["first_home"], sample["first_away"]
    ch, ca = sample["corners_home"], sample["corners_away"]
    yellows = sample["yellows_home"] + sample["yellows_away"]
    reds = sample["reds_home"] + sample["reds_away"]
    behind_home, ahead_home = fh < fa, fh > fa
    second_corners_home = ch - sample["corners_first_home"]
    out = {
        "corner da tiro (quota)": float((sample["corners_by_origin_home"][:, 0] + sample["corners_by_origin_away"][:, 0]).sum()
                                        / max((ch + ca).sum(), 1)),
        "corner casa 2T se sotto all'intervallo": float(second_corners_home[behind_home].mean()) if behind_home.any() else np.nan,
        "corner casa 2T se pari all'intervallo": float(second_corners_home[fh == fa].mean()),
        "corner casa 2T se avanti all'intervallo": float(second_corners_home[ahead_home].mean()) if ahead_home.any() else np.nan,
        "correlazione diff. gol / diff. corner": float(np.corrcoef(gh - ga, ch - ca)[0, 1]),
        "correlazione gol totali / corner totali": float(np.corrcoef(gh + ga, ch + ca)[0, 1]),
        "correlazione |diff. gol| / gialli": float(np.corrcoef(np.abs(gh - ga), yellows)[0, 1]),
        "quota gialli nel 1T": float((sample["yellows_first_home"] + sample["yellows_first_away"]).sum() / max(yellows.sum(), 1)),
        "quota corner nel 1T": float((sample["corners_first_home"] + sample["corners_first_away"]).sum() / max((ch + ca).sum(), 1)),
        "quota gol nel 1T": float((fh + fa).sum() / max((gh + ga).sum(), 1)),
        "minuto medio del primo gol": float(np.nanmean(sample["first_goal_minute"])),
        "partite con un rosso (%)": float(np.mean(reds > 0) * 100),
        "gialli medi con un rosso / senza": float(yellows[reds > 0].mean() / max(yellows[reds == 0].mean(), 1e-9)),
        "falli medi": float((sample["fouls_home"] + sample["fouls_away"]).mean()),
    }
    # Espulsione presto (prima del 30'): tiri della squadra in 10 rispetto alla media.
    early = sample["first_red_minute_home"] < 30
    if early.sum() >= 30:
        shots = sample["shots_home"].sum(axis=1)
        out["tiri casa con rosso prima del 30' / media"] = float(shots[early].mean() / shots.mean())
        corners_away = sample["corners_away"]
        out["corner ospite con rosso casa prima del 30' / media"] = float(corners_away[early].mean() / corners_away.mean())
    return out


def run(simulations: int = 40_000) -> dict[str, dict[str, Any]]:
    results = {}
    for name in SCENARIOS:
        off = engine.simulate_match(scenario_config(name, simulations))
        on = engine.simulate_match(scenario_config(name, simulations, active=True))
        results[name] = {
            "mercati": {key: (float(_bits(off, key).mean() * 100), float(_bits(on, key).mean() * 100)) for key in MARKETS},
            "medie": {"corner": (off["markets"]["corners"]["mean"], on["markets"]["corners"]["mean"]),
                      "punti cartellino": (off["markets"]["cards"]["mean"], on["markets"]["cards"]["mean"])},
            "percorsi": paths(on["event_engine_sample"]),
            "simulazioni": (off["sample_size"], on["sample_size"]),
            "avvisi": on["event_engine"]["warnings"],
        }
    return results


def report(results: dict[str, dict[str, Any]]) -> str:
    names = list(results)
    lines = ["## Motore a eventi: realismo e buon senso (fase AK, stadi 12-13)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.event_sense`. Serie A, partite tipo con quote di chiusura "
             "inventate ma plausibili; stessi punteggi Dixon-Coles e stesse medie finali nei due motori (vincolo di coerenza). "
             "Le misure sui percorsi esistono solo col motore a eventi: nel motore attuale corner e cartellini sono "
             "indipendenti dal punteggio (correlazioni 0 per costruzione).", "",
             "### Mercati (%): motore attuale → motore a eventi", "",
             "| Mercato | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for key in MARKETS:
        lines.append(f"| {key} | " + " | ".join(f"{results[n]['mercati'][key][0]:.1f} → {results[n]['mercati'][key][1]:.1f}"
                                                for n in names) + " |")
    for key in ("corner", "punti cartellino"):
        lines.append(f"| media {key} | " + " | ".join(f"{results[n]['medie'][key][0]:.2f} → {results[n]['medie'][key][1]:.2f}"
                                                     for n in names) + " |")
    lines.append("| simulazioni | " + " | ".join(f"{results[n]['simulazioni'][0]:,} → {results[n]['simulazioni'][1]:,}".replace(",", ".")
                                                for n in names) + " |")
    lines += ["", "### Percorsi del motore a eventi", "", "| Misura | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    keys = list(dict.fromkeys(key for n in names for key in results[n]["percorsi"]))
    for key in keys:
        lines.append(f"| {key} | " + " | ".join(f"{results[n]['percorsi'].get(key, float('nan')):.3f}" for n in names) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--simulazioni", type=int, default=40_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    markdown = report(run(args.simulazioni))
    print(markdown)
    if args.output:
        args.output.write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    main()
