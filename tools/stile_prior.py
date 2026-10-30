"""Prior dei profili qualitativi (fase AH): mediana del parametro misurato per categoria del profilo dell'Analista.

Per ogni squadra con un profilo salvato (``PROFILO_TATTICO`` nelle schede tattiche del giorno, foglio «Schede tattiche» di un
Excel della giornata) e con dati misurati (archivio di stile della fase AD) si prende il valore del parametro collegato
(``config/stile_prior.json``, ``mappa``) e per ogni categoria si calcola la mediana. Una categoria con meno di
``campione_minimo_categoria`` squadre resta ``null``: nessun valore inventato (allora vale il dato, o la media del campionato).

    python -m tools.stile_prior --file Giornata.xlsx --campionato I1 [--salva]
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

import match_context
import style_profile

CONFIG_PATH = match_context.PRIOR_PATH


def estimate(sheets: Iterable[Mapping[str, Any]], store, league: str, when, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Prior per categoria dalle squadre con profilo e dati; ``null`` sotto il campione minimo."""
    config = dict(config or match_context.load_prior())
    minimum = int(config["campione_minimo_categoria"])
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    used = 0
    for row in sheets:
        team = row.get("team") or row.get("Squadra")
        if not team:
            continue
        profile = style_profile.get_style_params(team, when, True, store, league)
        if not profile.get("parametri"):
            continue
        used += 1
        for name, spec in config["mappa"].items():
            category, item = row.get(name), profile["parametri"].get(spec["parametro"]) or {}
            if category is not None and item.get("valore") is not None and item.get("campione", 0) >= 5:
                values[name][str(category)].append(float(item["valore"]))
    prior = {name: {category: (round(median(values[name][category]), 4) if len(values[name][category]) >= minimum else None)
                    for category in spec["categorie"]} for name, spec in config["mappa"].items()}
    counts = {name: {category: len(values[name][category]) for category in spec["categorie"]} for name, spec in config["mappa"].items()}
    return {"prior": prior, "campioni": counts, "squadre": used}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", required=True, help="Excel della giornata con il foglio «Schede tattiche»")
    parser.add_argument("--campionato", required=True, help="codice football-data, es. I1")
    parser.add_argument("--salva", action="store_true")
    args = parser.parse_args()
    from match_memory import read_day_workbook

    day = read_day_workbook(Path(args.file).read_bytes())
    store = style_profile.load_store(args.campionato, date.today())
    if store is None:
        raise SystemExit("Archivio di stile non disponibile per questo campionato.")
    result = estimate(day.tactical_rows, store, args.campionato, date.today())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.salva:
        config = match_context.load_prior()
        config["prior"] = result["prior"]
        config["stimato"] = {"data": date.today().isoformat(), "squadre": result["squadre"], "campioni": result["campioni"]}
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
