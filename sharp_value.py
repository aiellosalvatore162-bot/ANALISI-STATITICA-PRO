"""Fase Y, punto 0b: quote Eurobet contro il prezzo equo del riferimento sharp (The Odds API: Pinnacle o mediana).

Prezzo equo sharp = 1 / probabilità senza margine (Shin, come l'ancoraggio) dell'1X2 e dell'Over/Under 2.5 di
riferimento; doppie chance e DNB si ricavano dalle stesse probabilità. Scarto = quota Eurobet / quota equa − 1:
positivo = Eurobet paga sopra il prezzo equo. Nel registro la nota «eurobet_vs_sharp: +x%» permette di misurare
nel tempo rendimento e CLV di queste giocate (pagina Prestazioni).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Mapping

import pandas as pd

from engine import remove_margin

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "oggi.json"
NOTE = "eurobet_vs_sharp: "
_NOTE = re.compile(r"eurobet_vs_sharp:\s*([+-]?\d+(?:[.,]\d+)?)%")


def threshold_pct(path: Path = CONFIG_PATH) -> float:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return float((data.get("eurobet_vs_sharp") or {}).get("soglia_pct", 3.0))


def fair_probabilities(sharp: Mapping[str, float]) -> dict[str, float]:
    """Probabilità senza margine delle selezioni ricavabili dalle quote sharp (1X2 e Over/Under 2.5)."""
    out: dict[str, float] = {}
    if all(float(sharp.get(key) or 0) > 1.0 for key in ("1", "X", "2")):
        home, draw, away = remove_margin([sharp["1"], sharp["X"], sharp["2"]], "shin")
        out |= {"1": home, "X": draw, "2": away, "1X": home + draw, "X2": draw + away, "12": home + away,
                # DNB: vinta con probabilità p/(p_casa + p_ospite) se non è pareggio (rimborso).
                "Casa DNB": home / (home + away), "Ospite DNB": away / (home + away)}
    if all(float(sharp.get(key) or 0) > 1.0 for key in ("Over 2.5 gol", "Under 2.5 gol")):
        over, under = remove_margin([sharp["Over 2.5 gol"], sharp["Under 2.5 gol"]], "shin")
        out |= {"Over 2.5 gol": over, "Under 2.5 gol": under}
    return out


def compare(eurobet: Mapping[str, float], sharp: Mapping[str, float] | None) -> list[dict]:
    """Una riga per selezione con quota Eurobet e prezzo equo sharp: scarto in percentuale."""
    fair = fair_probabilities(sharp or {})
    rows = []
    for selection, probability in fair.items():
        price = eurobet.get(selection)
        if not price or float(price) <= 1.0 or probability <= 0:
            continue
        fair_odds = 1.0 / probability
        rows.append({"Selezione": selection, "Quota Eurobet": round(float(price), 2), "Quota equa sharp": round(fair_odds, 3),
                     "Scarto %": round((float(price) / fair_odds - 1.0) * 100.0, 1)})
    return rows


def describe(row: Mapping) -> str:
    gap = row["Scarto %"]
    return f"Eurobet paga {abs(gap):.1f}% {'sopra' if gap >= 0 else 'sotto'} la quota equa sharp"


def above(rows: list[dict], threshold: float | None = None) -> list[dict]:
    limit = threshold_pct() if threshold is None else threshold
    return sorted((row for row in rows if row["Scarto %"] >= limit), key=lambda row: -row["Scarto %"])


def note(gap_pct: float) -> str:
    return f"{NOTE}{gap_pct:+.1f}%"


def notes_for(eurobet: Mapping[str, float], sharp: Mapping[str, float] | None) -> dict[str, str]:
    """Nota del registro per ogni selezione confrontabile."""
    return {row["Selezione"]: note(row["Scarto %"]) for row in compare(eurobet, sharp)}


def performance_table(frame: pd.DataFrame, threshold: float | None = None) -> pd.DataFrame:
    """Registro: giocate con la nota, divise tra sopra soglia e sotto; rendimento e CLV medi."""
    limit = threshold_pct() if threshold is None else threshold
    gaps = frame["Note"].fillna("").astype(str).map(lambda text: _NOTE.search(text))
    rows = frame[gaps.notna()].copy()
    if rows.empty:
        return pd.DataFrame()
    rows["scarto"] = gaps[gaps.notna()].map(lambda found: float(found.group(1).replace(",", ".")))
    out = []
    for label, part in (("sopra soglia", rows[rows["scarto"] >= limit]), ("sotto soglia", rows[rows["scarto"] < limit])):
        settled = part[part["Esito"].notna() & part["Quota_presa"].notna()]
        profit = (settled["Esito"] * settled["Quota_presa"] - 1.0) if not settled.empty else pd.Series(dtype=float)
        clv = part[part["Quota_presa"].notna() & part["Quota_chiusura"].notna()]
        out.append({"Gruppo": f"{label} (≥ {limit:g}%)" if label.startswith("sopra") else label, "Selezioni": len(part),
                    "Con esito": len(settled), "Rendimento medio": float(profit.mean()) if len(profit) else None,
                    "CLV medio": float((clv["Quota_presa"] / clv["Quota_chiusura"] - 1.0).mean()) if len(clv) else None})
    return pd.DataFrame(out)
