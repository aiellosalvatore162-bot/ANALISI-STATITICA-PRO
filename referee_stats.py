"""Arbitri per il motore a eventi (fase AK): quanto pesa l'arbitro su falli e gialli e con che shrinkage.

Modello a effetti casuali a una via sul totale della partita, centrato sulla media di campionato e stagione:
y = media + effetto arbitro + rumore. Con la scomposizione della varianza (ANOVA, metodo dei momenti) si ricavano
la varianza tra arbitri (tau²), quella dentro l'arbitro (sigma²) e lo shrinkage k = sigma²/tau²: il valore di un
arbitro con n partite è media + n/(n+k)·(media arbitro − media). La verifica fuori campione predice ogni stagione
con le sole stagioni precedenti (errore quadratico rispetto alla sola media di campionato).

Fonti: football-data.co.uk (arbitri solo per Premier League e Scozia) e StatsBomb Open Data 2015/16 (5 campionati).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

MIN_REFEREE_MATCHES = 5


def centered(matches: pd.DataFrame, column: str) -> pd.DataFrame:
    """Righe con arbitro e valore, ``y`` = valore meno la media di campionato e stagione."""
    data = matches.dropna(subset=["referee", column]).copy()
    data["referee"] = data["referee"].astype(str).str.strip()
    data["y"] = data[column] - data.groupby(["league", "season"])[column].transform("mean")
    return data


def variance_components(data: pd.DataFrame) -> dict:
    """tau², sigma², k e quota della varianza dovuta all'arbitro da ``y`` già centrato (ANOVA a una via)."""
    groups = data.groupby("referee")["y"]
    sizes, means = groups.size(), groups.mean()
    keep = sizes[sizes >= MIN_REFEREE_MATCHES].index
    data = data[data["referee"].isin(keep)]
    sizes, means = sizes[keep], means[keep]
    total, referees = len(data), len(keep)
    if referees < 3 or total - referees < 10:
        return {"partite": int(total), "arbitri": int(referees), "stimabile": False}
    grand = float(data["y"].mean())
    within = float(((data["y"] - data["referee"].map(means)) ** 2).sum() / (total - referees))
    between = float((sizes * (means - grand) ** 2).sum() / (referees - 1))
    n0 = (total - float((sizes ** 2).sum()) / total) / (referees - 1)
    tau2 = max((between - within) / n0, 0.0)
    return {"partite": int(total), "arbitri": int(referees), "stimabile": True, "sigma2": within, "tau2": tau2,
            "sd_arbitro": math.sqrt(tau2), "k": (within / tau2) if tau2 > 0 else None,
            "quota_varianza_arbitro": tau2 / (tau2 + within)}


def shrunk_effect(history: pd.DataFrame, referee: str, k: float | None) -> float:
    """Effetto atteso dell'arbitro (scarto dalla media) dalle partite passate in ``history`` (``y`` centrato)."""
    own = history.loc[history["referee"] == referee, "y"]
    if own.empty or k is None:
        return 0.0
    return float(len(own) / (len(own) + k) * own.mean())


def out_of_sample(data: pd.DataFrame, k: float | None) -> dict:
    """Ogni stagione predetta con le sole precedenti: errore quadratico medio con e senza arbitro."""
    seasons = sorted(data["season"].unique())
    base, model, count = 0.0, 0.0, 0
    for season in seasons[1:]:
        past, now = data[data["season"] < season], data[data["season"] == season]
        effects = {name: shrunk_effect(past, name, k) for name in now["referee"].unique()}
        prediction = now["referee"].map(effects).to_numpy(float)
        base += float((now["y"] ** 2).sum())
        model += float(((now["y"] - prediction) ** 2).sum())
        count += len(now)
    if not count:
        return {"partite": 0}
    return {"partite": count, "mse_media": base / count, "mse_arbitro": model / count,
            "miglioramento_pct": 100.0 * (1 - model / base) if base else 0.0}


def estimate(matches: pd.DataFrame, columns: dict[str, str]) -> dict:
    """Per campionato e per quantità (``columns``: nome → colonna): componenti di varianza e verifica fuori campione."""
    result = {}
    for league, rows in matches.groupby("league"):
        result[str(league)] = {}
        for name, column in columns.items():
            data = centered(rows, column)
            parts = variance_components(data)
            if parts.get("stimabile") and data["season"].nunique() > 1:
                parts["fuori_campione"] = out_of_sample(data, parts.get("k"))
            parts["media"] = float(rows[column].mean())
            result[str(league)][name] = parts
    return result


def cards_per_foul(matches: pd.DataFrame) -> dict:
    """Quanta parte dell'effetto arbitro sui gialli passa dai falli: correlazione tra gli effetti medi."""
    data = matches.dropna(subset=["referee", "fouls", "yellows"])
    fouls = centered(data, "fouls").groupby("referee")["y"].agg(["mean", "size"])
    yellows = centered(data, "yellows").groupby("referee")["y"].mean()
    fouls = fouls[fouls["size"] >= 15]
    if len(fouls) < 5:
        return {"arbitri": int(len(fouls))}
    correlation = float(np.corrcoef(fouls["mean"], yellows[fouls.index])[0, 1])
    return {"arbitri": int(len(fouls)), "correlazione_effetti_falli_gialli": correlation,
            "gialli_per_fallo": float(data["yellows"].sum() / data["fouls"].sum())}
