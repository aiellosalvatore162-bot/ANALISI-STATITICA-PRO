"""Fase AO, stadio 3: peso delle fasce e dello scontro esterno contro terzino su cross, corner da cross e tiri di testa da cross.

Dati: StatsBomb Open Data 2015/16 (posizioni iniziali ``statsbomb_formazioni_*``, eventi ``statsbomb_dettaglio_*``, cross per
squadra-partita ``stili_statsbomb``). Per ogni squadra-partita: giocatori larghi in attacco L (esterni, ali, quinti) e scontro
S = L − larghi difensivi dell'avversario (terzini, esterni, quinti), come ``formation.wide_players`` per i moduli dell'app.
Modelli (quasi-Poisson, errori robusti per partita), per y = cross, corner da cross, tiri di testa da cross:

    log E[y] = log(media del campionato) + log(concessi dall'avversario, senza la partita / media) + a + b·casa
               + β_fasce·(L − L̄) + β_scontro·(S − S̄)

Le stime entrano nel motore così come sono (``config/motore_eventi.json`` → ``corsie``), con l'intervallo al 95%.

    python -m tools.ao_corsie [--salva]
"""

from __future__ import annotations

import argparse
from datetime import date
import gzip
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import formation
from tools.ao_giocatori import quasi_poisson

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "minuto"
OUT = ROOT / "docs" / "backtest" / "AO_corsie.md"
OUTCOMES = ("cross", "corner_da_cross", "testa_da_cross")


def team_rows() -> pd.DataFrame:
    crosses = {(row["match"], row["team"]): row["crosses"]
               for row in json.load(gzip.open(CACHE / "stili_statsbomb.json.gz", "rt", encoding="utf-8"))}
    rows = []
    for path in sorted(CACHE.glob("statsbomb_formazioni_*_*.json.gz")):
        if "parziale" in path.name:
            continue
        season = path.name.replace("statsbomb_formazioni_", "").replace(".json.gz", "")
        detail = {match["id"]: match for match in
                  json.load(gzip.open(CACHE / f"statsbomb_dettaglio_{season}.json.gz", "rt", encoding="utf-8"))}
        for match in json.load(gzip.open(path, "rt", encoding="utf-8")):
            events = detail.get(match["id"])
            positions = match["posizioni"]
            if events is None or len(positions) != 2 or any(len(p) != 11 for p in positions.values()):
                continue
            for side, team, other in (("h", match["home"], match["away"]), ("a", match["away"], match["home"])):
                if (match["id"], team) not in crosses or team not in positions or other not in positions:
                    continue
                own, opp = formation.wide_from_positions(positions[team]), formation.wide_from_positions(positions[other])
                rows.append({
                    "season": season, "match": match["id"], "team": team, "opponent": other, "home": float(side == "h"),
                    "larghi": own["attacco"], "scontro": own["attacco"] - opp["difesa"],
                    "cross": float(crosses[(match["id"], team)]),
                    "corner_da_cross": float(sum(c["s"] == side and c["o"] == "cross" for c in events["corners"])),
                    "testa_da_cross": float(sum(s["s"] == side and s.get("b") == "Head" and s.get("cross") for s in events["shots"])),
                })
    frame = pd.DataFrame(rows)
    for column in OUTCOMES:
        by_opp = frame.groupby(["season", "opponent"])[column]
        frame[f"conc_{column}"] = (by_opp.transform("sum") - frame[column]) / (by_opp.transform("count") - 1)
        frame[f"lega_{column}"] = frame.groupby("season")[column].transform("mean")
    return frame


def estimate(frame: pd.DataFrame) -> dict[str, Any]:
    means = {"larghi": float(frame["larghi"].mean()), "scontro": float(frame["scontro"].mean())}
    x = np.column_stack([np.ones(len(frame)), frame["home"], frame["larghi"] - means["larghi"], frame["scontro"] - means["scontro"]])
    names = ("intercetta", "casa", "fasce", "scontro")
    result: dict[str, Any] = {"squadre_partita": int(len(frame)), "partite": int(frame["match"].nunique()),
                              "media_larghi": round(means["larghi"], 4), "media_scontro": round(means["scontro"], 4),
                              "distribuzione_larghi": frame["larghi"].value_counts().sort_index().to_dict()}
    for column in OUTCOMES:
        ok = frame[f"conc_{column}"] > 0
        part = frame[ok]
        offset = np.log(part[f"lega_{column}"]) + np.log(part[f"conc_{column}"] / part[f"lega_{column}"])
        beta, se = quasi_poisson(x[ok.to_numpy()], part[column].to_numpy(float), offset.to_numpy(), part["match"].to_numpy())
        result[column] = {name: {"stima": round(float(b), 4), "se": round(float(s), 4),
                                 "ic95": [round(float(b - 1.96 * s), 4), round(float(b + 1.96 * s), 4)]}
                          for name, b, s in zip(names, beta, se)}
        result[column]["media"] = round(float(part[column].mean()), 4)
    return result


def render(result: dict[str, Any]) -> str:
    lines = ["# Fase AO – moduli e corsie nel motore a eventi", "",
             f"Data: StatsBomb Open Data 2015/16, {result['squadre_partita']} squadre-partita ({result['partite']} partite). "
             f"Giocatori larghi in attacco (media {result['media_larghi']:.2f}; distribuzione {result['distribuzione_larghi']}), "
             f"scontro = larghi propri − larghi difensivi dell'avversario (media {result['media_scontro']:.2f}). "
             "Quasi-Poisson con offset (media del campionato × concessi dall'avversario senza la partita), errori robusti per partita.", ""]
    for column in OUTCOMES:
        lines += [f"## {column} (media {result[column]['media']:.2f} per squadra-partita)", "",
                  "| termine | stima | e.s. | IC 95% |", "|---|---|---|---|"]
        for name in ("intercetta", "casa", "fasce", "scontro"):
            item = result[column][name]
            lines.append(f"| {name} | {item['stima']:+.4f} | {item['se']:.4f} | {item['ic95'][0]:+.4f} … {item['ic95'][1]:+.4f} |")
        lines.append("")
    lines += ["«fasce» = effetto sul logaritmo per ogni giocatore largo in più; «scontro» = per ogni larghi in più rispetto a chi "
              "copre la fascia avversaria. Nel motore: cross, corner da cross e tiri di testa da cross × exp(fasce·ΔL + scontro·ΔS); "
              "il totale dei corner resta quello del motore attuale (vincolo di coerenza), le corsie spostano la parte da cross.", ""]
    return "\n".join(lines)


def save(result: dict[str, Any], path: Path = ROOT / "config" / "motore_eventi.json") -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["corsie"] = {
        "attive": True, "data": date.today().isoformat(), "partite": result["partite"],
        "fonte": "Data: StatsBomb Open Data 2015/16, python -m tools.ao_corsie",
        "media_larghi": result["media_larghi"], "media_scontro": result["media_scontro"],
        **{column: {name: result[column][name] for name in ("fasce", "scontro")} for column in OUTCOMES},
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    args = parser.parse_args()
    result = estimate(team_rows())
    OUT.write_text(render(result), encoding="utf-8")
    print(render(result))
    if args.salva:
        save(result)


if __name__ == "__main__":
    main()
