"""Giocatori da Understat (fase AL): minuti, npxG, xA, tiri e rigori per 90 con decadimento e shrinkage verso il ruolo.

Dati: le rose partita per partita già in cache (``tools.player_data``, ``data/cache/fase_p``). Per una partita del
giorno D si usano solo le gare con data < D nelle ultime ``finestra_anni`` stagioni, pesate 0.5**(età/emivita).
Ruoli: POR, DIF, CEN, ATT dalla posizione Understat. Il tasso di un giocatore è ridotto verso la media del RUOLO nel
campionato con peso ``n/(n+k)`` (n = minuti pesati, k in ``config/giocatori.json``); i tassi esorbitanti sono
winsorizzati ai percentili del ruolo, con avviso. npxG = xG − xG dei rigori battuti.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from datasources.names import canonical_key

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "giocatori.json"
ROLES = ("POR", "DIF", "CEN", "ATT")
UNDERSTAT_LEAGUES = {"I1": "Serie_A", "E0": "EPL", "SP1": "La_liga", "D1": "Bundesliga", "F1": "Ligue_1"}
RATE_COLUMNS = ("npxg", "xa", "shots")


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def role4(position: str | None) -> str | None:
    """Ruolo da posizione Understat di partita («GK», «DC», «DMC», «AMR», «FW», «Sub») o di stagione («F S»)."""
    first = (position or "").upper().split()[0] if (position or "").split() else ""
    if first in ("", "SUB"):
        return None
    if first == "GK":
        return "POR"
    if first in ("FW", "FWR", "FWL", "AMR", "AML", "F"):
        return "ATT"
    if first in ("DC", "DR", "DL", "D"):
        return "DIF"
    return "CEN"


# --- Tabella giocatore-partita ----------------------------------------------------------------------------------------

def rows_from_matches(matches: Iterable[Mapping[str, Any]], league_code: str) -> pd.DataFrame:
    """Una riga per giocatore e partita, con npxG e rigori (da ``penalties``)."""
    rows = []
    for match in matches:
        when = pd.Timestamp(match["date"]).normalize()
        penalties = {}
        for penalty in match.get("penalties") or []:
            key = str(penalty.get("player_id"))
            entry = penalties.setdefault(key, {"n": 0, "xg": 0.0, "goals": 0})
            entry["n"] += 1
            entry["xg"] += float(penalty.get("xG") or 0.0)
            entry["goals"] += int(penalty.get("result") == "Goal")
        for player in match["players"]:
            side = player["side"]
            pen = penalties.get(str(player["player_id"]), {"n": 0, "xg": 0.0, "goals": 0})
            minutes = float(player.get("time") or 0)
            position = str(player.get("position") or "")
            xg = float(player.get("xG") or 0.0)
            rows.append({
                "league": league_code, "match_id": match["id"], "date": when,
                "team": match["home"] if side == "h" else match["away"],
                "opponent": match["away"] if side == "h" else match["home"], "venue": "home" if side == "h" else "away",
                "player_id": str(player["player_id"]), "player": player["player"], "position": position,
                "role": role4(position), "minutes": minutes, "starter": position.upper() != "SUB" and minutes > 0,
                "xg": xg, "npxg": xg - pen["xg"], "xa": float(player.get("xA") or 0.0), "shots": float(player.get("shots") or 0.0),
                "goals": float(player.get("goals") or 0.0), "pen_taken": float(pen["n"]), "pen_xg": float(pen["xg"]),
                "pen_goals": float(pen["goals"]),
            })
    return pd.DataFrame(rows)


def load_table(leagues: Iterable[str], years: Iterable[int]) -> pd.DataFrame:
    """Tabella giocatore-partita dalla cache locale (``python -m tools.player_data 2025 2026`` per scaricarla)."""
    from tools import player_data

    frames = []
    for code in leagues:
        for year in years:
            matches = player_data.load(UNDERSTAT_LEAGUES[code], year)
            if matches:
                frames.append(rows_from_matches(matches, code))
    return pd.concat(frames, ignore_index=True).sort_values(["date", "match_id"]).reset_index(drop=True) if frames else pd.DataFrame()


# --- Archivio ---------------------------------------------------------------------------------------------------------

@dataclass
class PlayerStore:
    table: pd.DataFrame
    config: dict = field(default_factory=load_config)
    _teams: dict = field(default_factory=dict, init=False, repr=False)
    _roles: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.table):
            self.table = self.table.assign(key=self.table["team"].map(canonical_key))
            for (league, key), group in self.table.groupby(["league", "key"], sort=False):
                self._teams[(league, key)] = (group["date"].to_numpy("datetime64[ns]"), group.sort_values(["date", "match_id"]))

    def team_keys(self, key: str) -> list[str]:
        return sorted({league for league, team in self._teams if team == key})

    def team_rows(self, league: str, key: str, when: pd.Timestamp) -> pd.DataFrame:
        """Righe del giocatore-partita della squadra con data < ``when`` negli ultimi anni di finestra."""
        entry = self._teams.get((league, key))
        if entry is None:
            return pd.DataFrame()
        dates, group = entry
        end = int(np.searchsorted(dates, np.datetime64(when), side="left"))
        rows = group.iloc[:end]
        return rows[rows["date"] >= when - pd.DateOffset(years=self.config["finestra_anni"])]

    def role_stats(self, league: str, when: pd.Timestamp) -> dict[str, dict[str, float]]:
        """Media del RUOLO nel campionato (tassi per 90 pesati) con le gare precedenti il primo del mese."""
        month = pd.Timestamp(when.year, when.month, 1)
        cache_key = (league, month)
        if cache_key not in self._roles:
            data = self.table[(self.table["league"] == league) & (self.table["date"] < month)
                              & (self.table["date"] >= month - pd.DateOffset(years=self.config["finestra_anni"]))]
            stats = {}
            for role in ROLES:
                part = data[data["role"] == role]
                minutes = float(part["minutes"].sum())
                stats[role] = {"minuti": minutes, **{column: (90.0 * float(part[column].sum()) / minutes if minutes else float("nan"))
                                                     for column in RATE_COLUMNS}}
                # percentili dei tassi individuali (winsorizzazione) tra chi ha minuti sufficienti
                per_player = part.groupby("player_id")[["minutes", *RATE_COLUMNS]].sum()
                enough = per_player[per_player["minutes"] >= self.config["winsorizzazione"]["minuti_minimi"]]
                low, high = self.config["winsorizzazione"]["percentili"]
                for column in RATE_COLUMNS:
                    rates = 90.0 * enough[column] / enough["minutes"]
                    stats[role][f"{column}_p"] = ((float(np.percentile(rates, low)), float(np.percentile(rates, high)))
                                                  if len(rates) >= 20 else (float("nan"), float("nan")))
            self._roles[cache_key] = stats
        return self._roles[cache_key]


# --- Statistiche della rosa -------------------------------------------------------------------------------------------

def squad_stats(store: PlayerStore, league: str, key: str, when: pd.Timestamp) -> pd.DataFrame:
    """Rosa con tassi per 90 (shrinkage verso il ruolo), minuti da titolare/subentrato e ruolo. Solo gare < ``when``."""
    rows = store.team_rows(league, key, when)
    if rows.empty:
        return pd.DataFrame()
    cfg = store.config
    age = (when - rows["date"]).dt.days.to_numpy(float)
    rows = rows.assign(w=0.5 ** (age / float(cfg["emivita_giorni"])))
    roles = store.role_stats(league, when)
    modal = (rows[rows["role"].notna()].groupby(["player_id", "role"])["w"].sum().reset_index()
             .sort_values("w", ascending=False).drop_duplicates("player_id").set_index("player_id")["role"])
    result = []
    for player_id, group in rows.groupby("player_id"):
        role = modal.get(player_id)
        guessed = role is None
        role = role or "CEN"
        minutes = float((group["w"] * group["minutes"]).sum())
        record = {"player_id": player_id, "player": group["player"].iloc[-1], "role": role, "ruolo_stimato": guessed,
                  "minuti_pesati": minutes, "partite": int((group["minutes"] > 0).sum()),
                  "ultima": group["date"].max(), "avvisi": []}
        k = float(cfg["k_minuti"][role])
        for column in RATE_COLUMNS:
            reference = roles[role][column]
            raw = 90.0 * float((group["w"] * group[column]).sum()) / minutes if minutes > 0 else float("nan")
            low, high = roles[role][f"{column}_p"]
            if np.isfinite(raw) and np.isfinite(low) and minutes >= cfg["winsorizzazione"]["minuti_minimi"]:
                clipped = min(max(raw, low), high)
                if clipped != raw:
                    record["avvisi"].append(f"{column}/90 {raw:.2f} fuori dai percentili del ruolo {role} ({low:.2f}…{high:.2f}): riportato al limite")
                raw = clipped
            if not np.isfinite(reference):
                record[f"{column}90"] = raw if np.isfinite(raw) else 0.0
            else:
                record[f"{column}90"] = ((minutes * (raw if np.isfinite(raw) else reference) + k * reference) / (minutes + k))
        record["prod90"] = record["npxg90"] + record["xa90"]
        starts = group[group["starter"]]
        subs = group[(~group["starter"]) & (group["minutes"] > 0)]
        record["starts"] = len(starts)
        record["minuti_da_titolare"] = float(np.average(starts["minutes"], weights=starts["w"])) if len(starts) else float("nan")
        record["minuti_da_subentrato"] = float(np.average(subs["minutes"], weights=subs["w"])) if len(subs) else float("nan")
        record["entrate"] = len(subs)
        result.append(record)
    return pd.DataFrame(result)


def penalty_stats(store: PlayerStore, league: str, key: str, when: pd.Timestamp) -> dict[str, Any]:
    """Rigori della squadra e della lega (xG medio, conversione), solo gare precedenti."""
    rows = store.team_rows(league, key, when)
    cfg = store.config["rigori"]
    league_rows = store.table[(store.table["league"] == league) & (store.table["date"] < when)
                              & (store.table["date"] >= when - pd.DateOffset(years=store.config["finestra_anni"]))]
    taken = float(league_rows["pen_taken"].sum())
    conversion = float(league_rows["pen_goals"].sum()) / taken if taken else float("nan")
    xg_each = float(league_rows["pen_xg"].sum()) / taken if taken else float("nan")
    matches = rows["match_id"].nunique()
    league_matches = max(league_rows["match_id"].nunique() * 2, 1)       # partite-squadra
    league_rate = taken / league_matches
    team_rate = float(rows["pen_taken"].sum()) / matches if matches else float("nan")
    k_freq = float(cfg["k_frequenza_partite"])
    rate = (matches * team_rate + k_freq * league_rate) / (matches + k_freq) if matches else league_rate
    by_player = rows.groupby(["player_id"]).agg(player=("player", "last"), n=("pen_taken", "sum"), goals=("pen_goals", "sum"),
                                                last=("date", "max")).reset_index()
    by_player = by_player[by_player["n"] > 0].sort_values(["n", "last"], ascending=False)
    return {"lega": {"rigori": taken, "conversione": conversion, "xg_per_rigore": xg_each, "rigori_per_partita": league_rate},
            "squadra": {"partite": int(matches), "rigori_per_partita": rate},
            "battitori": by_player.to_dict("records")}
