"""Dizionario tattico (fase AK): dai termini del profilo ai tassi del motore a eventi.

Ogni termine di ``config/dizionario_tattico.json`` ha i valori ammessi con un punteggio (−1…+1) e gli effetti sui tassi:
moltiplicatore del tasso = exp(Σ beta·punteggio). beta viene da ``tools.stima_motore`` (dati StatsBomb / football-data); finché
è ``null`` l'effetto è 1 e la riga dice «non stimato». Un termine o un valore non riconosciuto è SEMPRE segnalato.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

PATH = Path(__file__).resolve().parent / "config" / "dizionario_tattico.json"
_AGGRESSIVE = ("attacc", "spinge", "alza", "aggressiv", "offensiv", "forza", "in avanti")
_PASSIVE = ("chiude", "abbass", "difend", "gestisce", "rallent", "conserva", "addormenta")


def load(path: Path = PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(term: str, value: Any, dictionary: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(valore canonico, avviso). Il testo libero delle reazioni si legge con le parole chiave della fase Q."""
    spec = dictionary["termini"][term]
    text = str(value).strip().lower()
    if spec.get("testo_libero"):
        if any(word in text for word in _AGGRESSIVE):
            return "aggressiva", None
        if any(word in text for word in _PASSIVE):
            return "passiva", None
        return ("neutra", None) if text in ("", "neutra", "-", "—") or text in spec["punteggio"] else (
            "neutra", f"{term}: «{value}» non riconosciuto (né aggressivo né passivo), letto come neutro e segnalato.")
    text = spec.get("sinonimi", {}).get(text, text).replace(" ", "_")
    if text in spec["punteggio"]:
        return text, None
    return None, f"{term}: valore «{value}» non ammesso ({'/'.join(spec['punteggio'])}), segnalato e non usato."


def from_sheet(sheet: Mapping[str, Any] | Any, dictionary: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Termini del dizionario da una scheda tattica (``TacticalSheet`` o dict): {termine: valore grezzo}."""
    dictionary = dictionary or load()
    get = sheet.get if isinstance(sheet, Mapping) else (lambda key, default=None: getattr(sheet, key, default))
    terms = {}
    for term, spec in dictionary["termini"].items():
        value = get(spec["campo_scheda"], None)
        if value not in (None, ""):
            terms[term] = value
    return terms


def apply_profile(profile: Mapping[str, Any], dictionary: Mapping[str, Any] | None = None) -> tuple[dict[str, float], list[dict], list[str]]:
    """(moltiplicatori per tasso, righe di spiegazione, avvisi). Tassi non toccati = 1."""
    dictionary = dictionary or load()
    logs = {rate: 0.0 for rate in dictionary["tassi"]}
    rows, warnings = [], []
    for term, raw in profile.items():
        if term not in dictionary["termini"]:
            warnings.append(f"termine «{term}» non riconosciuto dal dizionario tattico: segnalato e non usato.")
            continue
        value, warning = normalize(term, raw, dictionary)
        if warning:
            warnings.append(warning)
        if value is None:
            continue
        score = float(dictionary["termini"][term]["punteggio"][value])
        for effect in dictionary["termini"][term]["effetti"]:
            beta = effect.get("beta")
            reason = f" · {effect['motivo']}" if effect.get("motivo") else ""
            if beta is None:
                rows.append({"termine": term, "valore": value, "tasso": effect["tasso"], "moltiplicatore": 1.0,
                             "stato": "non stimato" + reason})
                continue
            logs[effect["tasso"]] += float(beta) * score
            rows.append({"termine": term, "valore": value, "tasso": effect["tasso"], "moltiplicatore": math.exp(float(beta) * score),
                         "stato": f"stimato (n={effect.get('n', 0)}, {effect.get('fonte') or 'fonte non indicata'}){reason}"})
    return {rate: math.exp(value) for rate, value in logs.items()}, rows, warnings
