"""Stima del proxy xG dai tiri (fase AD): xG ≈ a·tiri in porta + b·altri tiri, coefficienti sui 5 grandi campionati.

Le partite di football-data.co.uk (tiri, tiri in porta) sono abbinate a Understat (xG vero) per data e squadra.
Si stima su alcune stagioni e si misura fuori campione (R², errore quadratico medio). Se R² < ``MIN_R2`` il proxy
NON viene usato (``usabile: false``) e per quei campionati si usano solo i gol. Scrive ``config/proxy_xg.json``.

    python -m tools.proxy_xg [--salva]
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from datasources.cache import SourceCache
from datasources.names import canonical_key
from datasources.sources import COMPETITIONS, Understat
from tools import dataset

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "proxy_xg.json"
MIN_R2 = 0.5
TOP5 = {"I1": "Serie A", "E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga", "F1": "Ligue 1"}
SEASONS = ("2324", "2425", "2526")          # 2324-2425 stima, 2526 verifica fuori campione
FIT, TEST = ("2324", "2425"), ("2526",)


def _long(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for side, other in (("home", "away"), ("away", "home")):
        part = raw[["league", "season", "date", f"{side}_team", f"{side}_shots", f"{side}_sot", f"{side}_goals"]].copy()
        part.columns = ["league", "season", "date", "team", "shots", "sot", "goals"]
        part["venue"] = side
        rows.append(part)
    return pd.concat(rows, ignore_index=True)


def matched_table(cache: SourceCache | None = None) -> pd.DataFrame:
    """Una riga per squadra e partita con tiri (football-data) e xG vero (Understat)."""
    cache = cache or SourceCache()
    understat = Understat(cache)
    raw = dataset.load_raw(tuple(TOP5), SEASONS)
    shots = _long(raw)
    shots["key"] = shots["team"].map(canonical_key)
    frames = []
    for code, competition in TOP5.items():
        for season in SEASONS:
            start = 2000 + int(season[:2])
            frame = understat.league(COMPETITIONS[competition]["understat"], start, timedelta(days=3650)).data
            if frame.empty:
                continue
            frame = frame.assign(league=code, season=season, key=frame["team"].map(canonical_key))
            frames.append(frame[["league", "season", "date", "key", "venue", "xg_for", "goals_for"]])
    xg = pd.concat(frames, ignore_index=True)
    merged = shots.merge(xg, on=["league", "season", "key", "venue"], suffixes=("", "_u"))
    merged = merged[(pd.to_datetime(merged["date"]) - pd.to_datetime(merged["date_u"])).abs() <= pd.Timedelta(days=1)]
    merged = merged.drop_duplicates(["league", "season", "team", "date"])
    return merged.dropna(subset=["shots", "sot", "xg_for"])


def _design(data: pd.DataFrame) -> np.ndarray:
    return np.column_stack([data["sot"], np.clip(data["shots"] - data["sot"], 0.0, None)])


def fit(table: pd.DataFrame) -> dict:
    train = table[table["season"].isin(FIT)]
    test = table[table["season"].isin(TEST)]
    coefficients, _ = nnls(_design(train), train["xg_for"].to_numpy(float))

    def score(data: pd.DataFrame) -> dict:
        prediction = _design(data) @ coefficients
        actual = data["xg_for"].to_numpy(float)
        residual = float(np.sum((actual - prediction) ** 2))
        total = float(np.sum((actual - actual.mean()) ** 2))
        return {"partite": int(len(data)), "r2": round(1.0 - residual / total, 4),
                "errore_quadratico_medio": round(float(np.sqrt(residual / len(data))), 4)}

    train_score, test_score = score(train), score(test)
    return {
        "modello": "xG proxy = a·tiri in porta + b·altri tiri (minimi quadrati non negativi, senza intercetta)",
        "a_tiri_in_porta": round(float(coefficients[0]), 5), "b_altri_tiri": round(float(coefficients[1]), 5),
        "stima_su": {"campionati": list(TOP5.values()), "stagioni": list(FIT), **train_score},
        "verifica_fuori_campione": {"stagioni": list(TEST), **test_score},
        "r2_minimo": MIN_R2, "usabile": bool(test_score["r2"] >= MIN_R2),
        "data": date.today().isoformat(), "fonte": "football-data.co.uk (tiri) + Understat (xG)",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--salva", action="store_true")
    args = parser.parse_args()
    table = matched_table()
    result = fit(table)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.salva:
        CONFIG_PATH.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
