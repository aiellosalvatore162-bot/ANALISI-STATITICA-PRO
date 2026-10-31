"""Fase AO, stadio 4: soglie dei terzili di stile (StatsBomb 2015/16) per portare i valori importati agli stessi livelli su cui
sono stimati i beta del dizionario tattico (``tools.stima_motore``: terzili di stagione delle medie di squadra).

- possesso: quota di passaggi della squadra sulla partita (≈ possesso), media di squadra per stagione;
- cross: cross per partita, media di squadra per stagione.

Le soglie sono la media sulle stagioni-campionato dei terzili 33,3/66,7 → ``config/motore_eventi.json`` → ``soglie_stile``.
Difesa a uomo/zona, recuperi alti e reazioni per squadra non hanno un indicatore nei dati aperti: restano neutri (dichiarato).

    python -m tools.ao_stile [--salva]
"""

from __future__ import annotations

import argparse
from datetime import date
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "cache" / "minuto" / "stili_statsbomb.json.gz"


def cuts() -> dict:
    rows = pd.DataFrame(json.load(gzip.open(SOURCE, "rt", encoding="utf-8")))
    rows = rows[(rows["passes"] > 0) & (rows["opp_passes"] > 0)]
    rows = rows.assign(possesso=rows["passes"] / (rows["passes"] + rows["opp_passes"]))
    teams = rows.groupby(["season", "team"])[["possesso", "crosses"]].mean()
    out = {}
    for column, name in (("possesso", "possesso"), ("crosses", "cross")):
        per_season = teams.groupby(level="season")[column].apply(lambda v: np.percentile(v, [100 / 3, 200 / 3]))
        out[name] = [round(float(np.mean([p[0] for p in per_season])), 4), round(float(np.mean([p[1] for p in per_season])), 4)]
    return {"data": date.today().isoformat(), "fonte": "Data: StatsBomb Open Data 2015/16, python -m tools.ao_stile",
            "squadre_stagione": int(len(teams)), **out}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    args = parser.parse_args()
    result = cuts()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.salva:
        path = ROOT / "config" / "motore_eventi.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["soglie_stile"] = result
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
