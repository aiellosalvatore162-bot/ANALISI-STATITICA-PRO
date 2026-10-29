"""Combo builder (fase Z): più selezioni della STESSA partita, probabilità congiunta dai campioni simulati.

La congiunta è la frazione delle simulazioni in cui tutte le selezioni sono vere (``result["event_samples"]``, stessi
run di tutte le probabilità della partita); il prodotto delle marginali è mostrato solo come confronto, perché tra
mercati correlati (es. Over 2.5 e GG) è sbagliato.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np


def samples(result: Mapping, key: str) -> np.ndarray:
    packed = (result.get("event_samples") or {}).get(key)
    if packed is None:
        raise KeyError(f"Campioni non disponibili per «{key}»: rianalizza la partita come «Da giocare».")
    return np.unpackbits(packed, count=int(result["sample_size"])).astype(bool)


def available(result: Mapping) -> list[str]:
    return sorted(result.get("event_samples") or {})


def evaluate(result: Mapping, legs: Sequence[str], odds: float | None = None) -> dict:
    """Congiunta, quota equa, marginali, prodotto (solo confronto) e, con la quota del bookmaker, EV."""
    if len(set(legs)) < 2:
        raise ValueError("Servono almeno due selezioni diverse della stessa partita.")
    arrays = [samples(result, leg) for leg in legs]
    joint = float(np.mean(np.logical_and.reduce(arrays)))
    marginals = {leg: float(np.mean(array)) for leg, array in zip(legs, arrays)}
    product = float(np.prod(list(marginals.values())))
    out = {"selezioni": list(legs), "congiunta": joint, "quota_equa": (1.0 / joint) if joint > 0 else None,
           "marginali": marginals, "prodotto": product, "simulazioni": int(result["sample_size"]),
           "quota_bookmaker": odds, "ev": (joint * odds - 1.0) if odds and joint > 0 else None}
    return out
