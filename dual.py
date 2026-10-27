"""Doppio pronostico (fase U): Simulatore, Osservatore e Unita sulle stesse partite.

Per ogni partita della pagina Oggi:
- **Simulatore**: la giocata singola più probabile che non sia una trappola (stesso criterio del
  costruttore di multiple: EV sopra ``trappola_ev`` e quota minima per gamba);
- **Osservatore**: la giocata scelta dall'utente tra i mercati con quota, con la sua quota;
- **Unita**: la conferma se coincidono, altrimenti la scelta dell'utente tra le due (default la sua).

Nel registro ogni selezione è una riga sola (l'``ID`` resta data|partita|mercato|selezione): le fonti
stanno in Note come «fonte: simulatore, unita». Le righe dell'osservatore hanno comunque la
``Prob_finale`` del simulatore, così le classifiche sono confrontabili. Solo presentazione e misura:
nessun calcolo del modello.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from multiples import Leg, filter_legs


SOURCES = ("simulatore", "osservatore", "unita")
LABELS = {"simulatore": "Simulatore", "osservatore": "Osservatore", "unita": "Unita"}
_SOURCE_NOTE = re.compile(r"fonte:\s*([a-zà, ]+?)(?:;|$)", re.IGNORECASE)


# --- Scelte della pagina Oggi --------------------------------------------------------------------

def simulator_pick(legs: Iterable[Leg], *, trap_ev: float = -5.0, min_odds: float = 1.0) -> Leg | None:
    """La giocata singola più probabile della partita che non sia una trappola né sotto la quota minima."""
    singles = [leg for leg in legs if leg.kind == "singola"]
    kept = filter_legs(singles, trap_ev=trap_ev, min_odds=min_odds).kept
    return max(kept, key=lambda leg: (leg.probability, leg.odds or 0.0), default=None)


@dataclass(frozen=True)
class Pick:
    selection: str
    probability: float      # probabilità del simulatore, 0-1
    odds: float | None

    def label(self) -> str:
        odds = f" @ {self.odds:.2f}" if self.odds else ""
        return f"{self.selection}{odds} (simulatore {self.probability:.0%})"


@dataclass(frozen=True)
class DualChoice:
    match_id: str
    match: str
    simulator: Pick | None
    observer: Pick | None
    unita: Pick | None

    @property
    def agree(self) -> bool:
        return self.simulator is not None and self.observer is not None and self.simulator.selection == self.observer.selection

    def strong_disagreement(self, threshold: float = 0.45) -> bool:
        """Disaccordo forte: per la scelta dell'osservatore il simulatore dà meno di ``threshold``."""
        return self.observer is not None and not self.agree and self.observer.probability < threshold


def pick_for(selection: str, result: Mapping[str, Any], odds: float | None) -> Pick:
    """Giocata con la probabilità finale del simulatore per quella selezione."""
    value = result["components"]["finale"].get(selection)
    return Pick(selection, float(value) / 100.0 if value is not None else float("nan"), odds)


def observer_options(result: Mapping[str, Any], odds: Mapping[str, float]) -> list[str]:
    """Mercati con quota tra cui l'osservatore sceglie: le selezioni registrabili simulate."""
    from prediction_log import market_of

    final = result["components"]["finale"]
    return [key for key, price in odds.items() if price and float(price) > 1.0 and key in final and market_of(key) is not None]


def sources_by_selection(choice: DualChoice) -> dict[str, tuple[list[str], float | None]]:
    """Selezione -> (fonti, quota presa). Stessa selezione da più fonti = una riga; vale la quota dell'osservatore."""
    merged: dict[str, tuple[list[str], float | None]] = {}
    for source, pick in (("simulatore", choice.simulator), ("osservatore", choice.observer), ("unita", choice.unita)):
        if pick is None:
            continue
        sources, odds = merged.get(pick.selection, ([], None))
        if source == "osservatore" or odds is None:
            odds = pick.odds
        merged[pick.selection] = (sources + [source], odds)
    return merged


def source_note(sources: Sequence[str]) -> str:
    return "fonte: " + ", ".join(sources)


def dual_sheet_rows(choices: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Foglio «Doppio pronostico» dell'Excel della giornata: le tre colonne per partita."""
    rows = []
    for choice in choices:
        row = {"Data": choice.get("date"), "Partita": choice.get("match")}
        for source in SOURCES:
            pick = choice.get(source) or {}
            row[LABELS[source]] = pick.get("selection")
            row[f"Prob. simulatore ({LABELS[source]})"] = pick.get("probability")
            row[f"Quota ({LABELS[source]})"] = pick.get("odds")
        row["Disaccordo forte"] = "sì" if choice.get("strong") else ""
        rows.append(row)
    return rows


def choice_record(choice: DualChoice, day: date, threshold: float) -> dict:
    """Forma salvabile (JSON) della scelta, per la memoria e l'Excel della giornata."""
    def pick(value: Pick | None) -> dict | None:
        return None if value is None else {"selection": value.selection, "probability": round(value.probability, 4),
                                           "odds": value.odds}

    return {"id": f"{choice.match_id}", "date": day.isoformat(), "match": choice.match, "simulatore": pick(choice.simulator),
            "osservatore": pick(choice.observer), "unita": pick(choice.unita),
            "strong": choice.strong_disagreement(threshold)}


# --- Misure della pagina Prestazioni ---------------------------------------------------------------

def sources_of(note: Any) -> list[str]:
    """Fonti indicate in Note («fonte: simulatore, unita»)."""
    match = _SOURCE_NOTE.search(str(note or ""))
    if not match:
        return []
    found = [part.strip().lower().replace("à", "a") for part in match.group(1).split(",")]
    return [source for source in SOURCES if source in found]


def weekend_of(day: Any) -> date | None:
    """Sabato del weekend della giornata: da martedì a lunedì successivo (il lunedì chiude il weekend prima)."""
    if day is None or (isinstance(day, float) and np.isnan(day)) or pd.isna(day):
        return None
    day = pd.Timestamp(day).date()
    shifted = day - timedelta(days=1)                 # lunedì -> domenica precedente
    monday = shifted - timedelta(days=shifted.weekday())
    return monday + timedelta(days=5)


def exploded(frame: pd.DataFrame) -> pd.DataFrame:
    """Una riga per (selezione, fonte) con esito; colonne aggiunte: Fonte, Weekend."""
    rows = []
    for _, row in frame.iterrows():
        for source in sources_of(row.get("Note")):
            rows.append({**row.to_dict(), "Fonte": source, "Weekend": weekend_of(row.get("Data"))})
    columns = [*frame.columns, "Fonte", "Weekend"]
    return pd.DataFrame(rows, columns=columns)


def _summary(group: pd.DataFrame) -> dict:
    settled = group[group["Esito"].notna()]
    odds = settled["Quota_presa"]
    staked = settled[odds.notna()]
    profit = (staked["Quota_presa"] * staked["Esito"] - 1.0).sum() if not staked.empty else np.nan
    probs = settled[settled["Prob_finale"].notna()]
    return {
        "Selezioni": len(group), "Con esito": len(settled),
        "% vinte": float(settled["Esito"].mean()) if len(settled) else np.nan,
        "Attese": float(probs["Prob_finale"].mean()) if len(probs) else np.nan,
        "ROI": float(profit / len(staked)) if len(staked) else np.nan,
        "Brier": float(np.mean((probs["Prob_finale"] - probs["Esito"]) ** 2)) if len(probs) else np.nan,
    }


def leaderboard(frame: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Classifica per fonte (e per «Mercato» o «Weekend»): selezioni, % vinte, attese, ROI a puntata 1, Brier."""
    data = exploded(frame)
    if data.empty:
        return pd.DataFrame(columns=["Fonte", *([by] if by else []), "Selezioni", "Con esito", "% vinte", "Attese", "ROI", "Brier"])
    keys = ["Fonte", by] if by else ["Fonte"]
    rows = [{**dict(zip(keys, key if isinstance(key, tuple) else (key,))), **_summary(group)}
            for key, group in data.groupby(keys, sort=True, dropna=False)]
    table = pd.DataFrame(rows)
    table["Fonte"] = table["Fonte"].map(LABELS)
    return table


def disagreements(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partite in cui simulatore e osservatore hanno scelto diversamente, con esito di entrambe: chi aveva ragione."""
    data = exploded(frame)
    details = []
    if not data.empty:
        for (day, match), group in data.groupby(["Data", "Partita"], sort=True):
            sim = group[group["Fonte"] == "simulatore"]
            obs = group[group["Fonte"] == "osservatore"]
            if sim.empty or obs.empty or sim.iloc[0]["Selezione"] == obs.iloc[0]["Selezione"]:
                continue
            sim_row, obs_row = sim.iloc[0], obs.iloc[0]
            if pd.isna(sim_row["Esito"]) or pd.isna(obs_row["Esito"]):
                continue
            verdict = {(1.0, 0.0): "Simulatore", (0.0, 1.0): "Osservatore", (1.0, 1.0): "Entrambi",
                       (0.0, 0.0): "Nessuno"}[(float(sim_row["Esito"]), float(obs_row["Esito"]))]
            details.append({"Data": day, "Partita": match, "Simulatore": sim_row["Selezione"],
                            "Osservatore": obs_row["Selezione"], "Mercato osservatore": obs_row["Mercato"],
                            "Prob. simulatore per l'osservatore": obs_row["Prob_finale"], "Ha ragione": verdict})
    details = pd.DataFrame(details, columns=["Data", "Partita", "Simulatore", "Osservatore", "Mercato osservatore",
                                             "Prob. simulatore per l'osservatore", "Ha ragione"])
    summary = details["Ha ragione"].value_counts().reindex(["Simulatore", "Osservatore", "Entrambi", "Nessuno"], fill_value=0)
    return summary.rename_axis("Ha ragione").reset_index(name="Volte"), details


def suggestions(frame: pd.DataFrame, *, min_weekends: int = 4, min_selections: int = 5) -> tuple[list[str], int]:
    """Dopo ``min_weekends`` weekend con esiti: per mercato chi rende meglio tra osservatore e simulatore (ROI, poi Brier).

    Restituisce i suggerimenti e il numero di weekend con esiti finora.
    """
    data = exploded(frame)
    settled = data[data["Esito"].notna()] if not data.empty else data
    weekends = int(settled["Weekend"].nunique()) if not settled.empty else 0
    if weekends < min_weekends:
        return [], weekends
    table = leaderboard(frame, "Mercato")
    lines = []
    for market, group in table.groupby("Mercato", sort=True):
        rows = {row["Fonte"]: row for _, row in group.iterrows()}
        sim, obs = rows.get("Simulatore"), rows.get("Osservatore")
        if sim is None or obs is None or min(sim["Con esito"], obs["Con esito"]) < min_selections:
            continue
        if pd.notna(sim["ROI"]) and pd.notna(obs["ROI"]) and sim["ROI"] != obs["ROI"]:
            better, worse = (obs, sim) if obs["ROI"] > sim["ROI"] else (sim, obs)
            measure = f"ROI {better['ROI']:+.1%} contro {worse['ROI']:+.1%}"
        elif pd.notna(sim["Brier"]) and pd.notna(obs["Brier"]) and abs(sim["Brier"] - obs["Brier"]) > 1e-12:
            better, worse = (obs, sim) if obs["Brier"] < sim["Brier"] else (sim, obs)
            measure = f"Brier {better['Brier']:.3f} contro {worse['Brier']:.3f}"
        else:
            continue
        who = "l'osservatore" if better["Fonte"] == "Osservatore" else "il simulatore"
        lines.append(f"{market}: su questo mercato rende meglio {who} ({measure}; "
                     f"{int(better['Con esito'])} e {int(worse['Con esito'])} selezioni con esito).")
    return lines, weekends
