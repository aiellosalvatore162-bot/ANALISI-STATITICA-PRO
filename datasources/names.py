"""Corrispondenza dei nomi squadra tra le fonti (e i nomi italiani dell'utente).

Ogni riga di ``TEAM_ALIASES`` elenca il nome canonico seguito dalle varianti
usate da football-data.co.uk, Understat, ClubElo (slug) e in italiano. Le
squadre con lo stesso nome ovunque non servono: basta la normalizzazione.
``match_team`` non indovina mai tra candidati ugualmente simili.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata
from typing import Iterable


TEAM_ALIASES: tuple[tuple[str, ...], ...] = (
    # Inghilterra
    ("Manchester City", "Man City", "ManCity"),
    ("Manchester United", "Man United", "Man Utd", "ManUnited"),
    ("Newcastle United", "Newcastle"),
    ("Nottingham Forest", "Nott'm Forest", "Forest"),
    ("Tottenham", "Tottenham Hotspur", "Spurs"),
    ("Wolverhampton", "Wolves", "Wolverhampton Wanderers"),
    ("Sheffield United", "Sheffield Utd", "SheffieldUnited"),
    # Italia
    ("AC Milan", "Milan"),
    ("Inter", "Internazionale", "Inter Milan", "FC Internazionale"),
    ("Parma", "Parma Calcio 1913"),
    # Spagna
    ("Athletic Bilbao", "Ath Bilbao", "Athletic Club", "Bilbao"),
    ("Atletico Madrid", "Ath Madrid", "Atletico", "Atlético Madrid"),
    ("Real Betis", "Betis"),
    ("Celta Vigo", "Celta"),
    ("Espanyol", "Espanol"),
    ("Deportivo La Coruna", "La Coruna", "Deportivo"),
    ("Racing Santander", "Santander", "Racing"),
    ("Rayo Vallecano", "Vallecano", "RayoVallecano"),
    ("Real Sociedad", "Sociedad"),
    ("Barcelona", "Barcellona"),
    ("Sevilla", "Siviglia"),
    # Germania
    ("Bayer Leverkusen", "Leverkusen"),
    ("Bayern Munich", "Bayern", "Bayern Monaco", "Bayern München"),
    ("Borussia Dortmund", "Dortmund"),
    ("Borussia Monchengladbach", "Borussia M.Gladbach", "M'gladbach", "Gladbach"),
    ("Eintracht Frankfurt", "Ein Frankfurt", "Frankfurt"),
    ("FC Koln", "FC Cologne", "Koeln", "Koln", "Colonia"),
    ("Hamburger SV", "Hamburg", "Amburgo"),
    ("Mainz", "Mainz 05", "Magonza"),
    ("RB Leipzig", "RasenBallsport Leipzig", "RBLeipzig", "Leipzig", "Lipsia"),
    ("VfB Stuttgart", "Stuttgart", "Stoccarda"),
    ("Werder Bremen", "Werder", "Brema"),
    # Francia
    ("Paris Saint Germain", "Paris SG", "ParisSG", "PSG", "Paris Saint-Germain"),
    ("Marseille", "Marsiglia"),
    ("Lyon", "Lione"),
    ("Lille", "Lilla"),
    ("Nice", "Nizza"),
    # Coppe europee
    ("AEK Athens", "AEK", "AEK Atene"),
    ("Bodo/Glimt", "Bodoe/Glimt", "BodoeGlimt", "Bodø/Glimt", "Bodo Glimt"),
    ("Slovan Bratislava", "SlovanBratislava"),
    ("PSV Eindhoven", "PSV"),
    ("Porto", "FC Porto"),
    ("Sporting CP", "Sporting", "Sporting Lisbona"),
)

_STOP_TOKENS = {"fc", "ac", "as", "ssc", "cf", "afc", "sc", "sv", "vfb", "vfl", "fsv", "tsg", "rc", "ud", "cd",
                "rcd", "club", "calcio", "bc", "1913", "1907", "05", "04"}
_SPECIAL = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "ß": "ss", "'": "", "’": "", ".": " ", "/": " ", "-": " "})


def normalize(name: str) -> str:
    """Forma compatta senza accenti, punteggiatura e sigle societarie."""
    text = unicodedata.normalize("NFKD", str(name).translate(_SPECIAL))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", text) if token and token not in _STOP_TOKENS]
    return "".join(tokens) or re.sub(r"[^a-z0-9]", "", text)


_CANONICAL = {normalize(variant): normalize(row[0]) for row in TEAM_ALIASES for variant in row}
_DISPLAY = {normalize(row[0]): row[0] for row in TEAM_ALIASES}


def canonical_key(name: str) -> str:
    key = normalize(name)
    return _CANONICAL.get(key, key)


def display_name(name: str) -> str:
    """Nome canonico leggibile (es. "Man City" -> "Manchester City")."""
    return _DISPLAY.get(canonical_key(name), str(name).strip())


def match_team(query: str, candidates: Iterable[str], *, cutoff: float = 0.84) -> str | None:
    """Il candidato che indica la stessa squadra di ``query``, oppure ``None``.

    Prova nell'ordine: chiave canonica uguale, contenimento univoco, somiglianza
    univoca sopra ``cutoff``. In caso di pari merito non sceglie.
    """
    candidates = [str(candidate) for candidate in candidates if str(candidate).strip()]
    target = canonical_key(query)
    if not target:
        return None
    keyed = [(candidate, canonical_key(candidate)) for candidate in candidates]
    exact = [candidate for candidate, key in keyed if key == target]
    if exact:
        return exact[0]
    contained = [candidate for candidate, key in keyed if len(key) >= 4 and len(target) >= 4 and (key in target or target in key)]
    if len(contained) == 1:
        return contained[0]
    scored = sorted(((SequenceMatcher(None, target, key).ratio(), candidate) for candidate, key in keyed), reverse=True)
    if scored and scored[0][0] >= cutoff and (len(scored) == 1 or scored[0][0] - scored[1][0] > 0.03):
        return scored[0][1]
    return None
