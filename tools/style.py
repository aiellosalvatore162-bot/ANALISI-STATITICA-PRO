"""Archetipi di stile: k-means sui profili completi dei 5 campionati top.

Il numero di gruppi è quello con la silhouette più alta tra 2 e 8; ogni gruppo
riceve un nome leggibile dai suoi tratti più marcati. Il risultato va in
``config/style_archetypes.json`` (versionato) e l'app assegna ogni squadra al
gruppo più vicino.

Uso: ``python -m tools.style [--aggiorna]`` (``--aggiorna`` riscarica i dati).
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json

import numpy as np

from datasources.builder import DataProvider
from datasources.sources import COMPETITIONS
from datasources.style import ARCHETYPES_PATH, EXCLUDED_METRICS, archetype_name, kmeans, silhouette

K_RANGE = range(2, 9)
# Raggruppamento solo su metriche di comportamento: xG, tiri e corner misurano soprattutto
# la forza della squadra (con loro la silhouette separa solo forti/deboli) e la quota di
# gol nel primo tempo è un risultato molto rumoroso. Restano nel radar e nelle descrizioni.
CLUSTER_FEATURES = ("pressing", "block_height", "build_up", "transitions", "set_pieces", "fouls", "cards")


def collect_profiles(provider: DataProvider) -> list:
    profiles = []
    for competition, codes in COMPETITIONS.items():
        if codes["understat"]:
            profiles += list(provider.style_profiles(competition).values())
    return [profile for profile in profiles if not profile.partial]


def build_archetypes(profiles: list) -> dict:
    features = [key for key in CLUSTER_FEATURES if all(key in profile.z for profile in profiles)]
    points = np.array([[profile.z[key] for key in features] for profile in profiles])
    scores = {}
    fits = {}
    for k in K_RANGE:
        labels, centroids, _ = kmeans(points, k)
        scores[k] = silhouette(points, labels)
        fits[k] = (labels, centroids)
    best_k = max(scores, key=scores.get)
    labels, centroids = fits[best_k]
    groups, names = [], set()
    for index, centroid in enumerate(centroids):
        centroid_map = {key: round(float(value), 3) for key, value in zip(features, centroid)}
        name = archetype_name(centroid_map)
        while name in names:
            name += " (variante)"
        names.add(name)
        members = [profile for profile, label in zip(profiles, labels) if label == index]
        groups.append({
            "name": name,
            "centroid": centroid_map,
            "size": len(members),
            "examples": sorted(f"{profile.team} ({profile.league})" for profile in members)[:8],
        })
    return {
        "generato_il": date.today().isoformat(),
        "metodo": f"k-means (k-means++, 25 ripartenze) su z-score per campionato delle metriche di comportamento; "
                  f"k scelto per silhouette massima tra {K_RANGE.start} e {K_RANGE.stop - 1}",
        "squadre": len(profiles),
        "k": best_k,
        "silhouette": {str(k): round(value, 4) for k, value in scores.items()},
        "features": features,
        "metriche_escluse": EXCLUDED_METRICS,
        "groups": groups,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aggiorna", action="store_true", help="Riscarica i dati ignorando la cache")
    args = parser.parse_args()
    provider = DataProvider(max_age=timedelta(hours=24))
    if args.aggiorna:
        provider.refresh()
    result = build_archetypes(collect_profiles(provider))
    ARCHETYPES_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("k", "silhouette", "squadre")}, ensure_ascii=False))
    for group in result["groups"]:
        print(f"- {group['name']} ({group['size']}): {', '.join(group['examples'][:5])}")


if __name__ == "__main__":
    main()
