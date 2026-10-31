"""Fase AP, punto 2: sorgente di ogni famiglia di mercati nel «Simulatore unico» → ``config/simulatore_unico.json``.

Usa solo risultati già misurati: primo banco AK (1.454 partite), campione nuovo AK (2.672), AO (563, tutti i dati) e, per gli
incroci di stile, ``tools.ap_check``. Per ogni famiglia le differenze di log-loss (motore a eventi − calcolo attuale) dei
campioni si uniscono con pesi 1/e.s.² (campioni indipendenti). Regola fissata prima: motore a eventi SOLO se la differenza unita è
sotto zero di oltre 2 errori standard ED l'ECE unita (pesata per partite) non peggiora; altrimenti resta il calcolo attuale tarato
dalla fase AM. Corner e cartellini sono blocchi indivisibili (totali, 1X2 e per squadra dallo stesso campione).

    python -m tools.ap_scegli [--salva]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "simulatore_unico.json"
GOAL_MODEL = ROOT / "config" / "goal_model.json"
AO = ROOT / "data" / "cache" / "ao_check" / "riepilogo.json"
AP = ROOT / "data" / "cache" / "ap_check" / "riepilogo.json"
FAMILIES = {
    "gol": ("1X2, gol, multigol, GG/NG", "gol"),
    "tempi": ("Primo e secondo tempo", "tempi"),
    "corner": ("Corner (totali, 1X2, per squadra)", "corner"),
    "cartellini": ("Cartellini (totali, 1X2, per squadra)", "cartellini"),
}


def samples(group: str) -> list[dict]:
    """Un dict per campione disponibile: nome, partite, diff, se, ece_prima, ece_dopo."""
    out = []
    section = json.loads(GOAL_MODEL.read_text(encoding="utf-8"))["motore_eventi"]
    for name, key in (("AK primo banco", "verifica"), ("AK campione nuovo", "verifica_nuova")):
        item = section.get(key, {}).get("gruppi", {}).get(group)
        if item:
            out.append({"campione": name, "partite": section[key]["partite"], "diff": item["differenza"],
                        "se": item["errore_standard"], "ece_prima": item["ece_prima"], "ece_dopo": item["ece_dopo"]})
    ao = json.loads(AO.read_text(encoding="utf-8"))
    if group in ao["gruppi"]:
        item = ao["gruppi"][group]
        out.append({"campione": "AO (tutti i dati)", "partite": ao["partite"], "diff": item["diff"], "se": item["e2"] / 2,
                    "ece_prima": item["ece"][0], "ece_dopo": item["ece"][1]})
    return [s for s in out if s["se"] > 0]


def pool(items: list[dict]) -> dict:
    weights = [1.0 / s["se"] ** 2 for s in items]
    total = sum(weights)
    games = sum(s["partite"] for s in items)
    return {"diff": sum(w * s["diff"] for w, s in zip(weights, items)) / total, "se": 1.0 / math.sqrt(total), "partite": games,
            "ece_prima": sum(s["partite"] * s["ece_prima"] for s in items) / games,
            "ece_dopo": sum(s["partite"] * s["ece_dopo"] for s in items) / games}


def decide(united: dict) -> tuple[str, str]:
    better = united["diff"] < -2 * united["se"]
    ece_ok = united["ece_dopo"] <= united["ece_prima"]
    if better and ece_ok:
        return "eventi", "log-loss giù di oltre 2 e.s. ed ECE non peggiore"
    if united["diff"] > 2 * united["se"]:
        return "attuale", "il motore a eventi è PEGGIORE di oltre 2 e.s."
    why = "differenza dentro l'errore statistico" if not better else "ECE peggiore"
    return "attuale", why + ": resta il calcolo tarato dalla AM"


def build() -> dict:
    families = {}
    for key, (label, group) in FAMILIES.items():
        items = samples(group)
        united = pool(items)
        source, motive = decide(united)
        families[key] = {"nome": label, "sorgente": source, "motivo": motive, "campioni": items,
                         "unito": {k: round(v, 5) for k, v in united.items()}}
    combo = pool(samples("combo"))
    corner_events = families["corner"]["sorgente"] == "eventi"
    families["combo_corner"] = {
        "nome": "Combo con i corner", "sorgente": "eventi" if corner_events else "attuale",
        "motivo": ("stesso campione dei corner (un solo campione per partita)" if corner_events else "come i corner"),
        "campioni": samples("combo"), "unito": {k: round(v, 5) for k, v in combo.items()},
        "nota": "Tutte le combo (con e senza corner) unite: informativo. Le combo con i corner seguono i corner."}
    families["combo_altre"] = {"nome": "Combo senza corner", "sorgente": "attuale",
                               "motivo": "gol e cartellini restano del calcolo attuale: stessa distribuzione", "campioni": [],
                               "unito": {}}
    crossings = []
    if AP.exists():
        ap = json.loads(AP.read_text(encoding="utf-8"))
        for group, item in ap["gruppi"].items():
            if item.get("tieni"):
                crossings.append(group)
    return {"nota": "Fase AP: sorgente per famiglia di mercati nel Simulatore unico. Si rigenera con "
                    "`python -m tools.ap_scegli --salva`. Predefinito dell'app invariato.",
            "regola": "motore a eventi solo se differenza unita < −2 e.s. ED ECE non peggiore; altrimenti calcolo attuale (AM)",
            "famiglie": families, "incroci_gruppi_tenuti": crossings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    args = parser.parse_args()
    data = build()
    for key, item in data["famiglie"].items():
        u = item["unito"]
        print(f"{key:14} {item['sorgente']:8} " + (f"diff {u['diff']:+.5f} ± {2 * u['se']:.5f} (2 e.s.), ECE {u['ece_prima']:.4f} → "
              f"{u['ece_dopo']:.4f}" if u else "") + f" | {item['motivo']}")
    print("incroci tenuti per:", data["incroci_gruppi_tenuti"] or "nessuno")
    if args.salva:
        CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
