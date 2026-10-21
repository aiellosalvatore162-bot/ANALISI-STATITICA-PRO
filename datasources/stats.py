"""Statistiche per squadra (casa/trasferta, pesate per recenza) e per arbitro.

I valori che finiscono nel blocco del parser restano sulla scala usata nella
taratura del motore (medie su tutte le gare): la media casa/trasferta della
squadra viene moltiplicata per il rapporto tra media generale e media
casa/trasferta della lega, così il vantaggio casa non è contato due volte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd

from datasources.names import match_team


# Proxy xG dai tiri in porta (stesso coefficiente della taratura, tools/dataset.py).
SHOT_XG_PER_SHOT_ON_TARGET = 0.308
REFEREE_PRIOR_MATCHES = 10
REFEREE_RELIABLE_MATCHES = 10


@dataclass(frozen=True)
class FieldValue:
    """Un valore con la sua provenienza; ``value=None`` significa campo mancante."""

    value: float | str | None
    source: str
    updated: datetime | None = None
    last_match: date | None = None
    note: str = ""
    level: str = "ok"  # ok | avviso | mancante

    @property
    def missing(self) -> bool:
        return self.value is None


def missing(note: str, source: str = "—") -> FieldValue:
    return FieldValue(None, source, note=note, level="mancante")


def recency_weights(count: int, half_life: float) -> np.ndarray:
    """Pesi in ordine cronologico: l'ultima partita pesa 1, ``half_life`` partite prima 0.5."""
    ages = np.arange(count - 1, -1, -1, dtype=float)
    return 0.5 ** (ages / max(half_life, 1e-9))


def weighted_mean(values: pd.Series, half_life: float) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return float("nan")
    return float(np.average(values.to_numpy(float), weights=recency_weights(len(values), half_life)))


def team_match_rows(matches: pd.DataFrame) -> pd.DataFrame:
    """Una riga per squadra e partita (formato lungo) dai CSV football-data."""
    if matches.empty:
        return pd.DataFrame()

    def side(prefix: str, other: str, venue: str) -> pd.DataFrame:
        return pd.DataFrame({
            "league": matches["league"], "date": matches["date"], "venue": venue,
            "team": matches[f"{prefix}_team"], "opponent": matches[f"{other}_team"],
            "goals_for": matches[f"{prefix}_goals"], "goals_against": matches[f"{other}_goals"],
            "ht_goals_for": matches[f"{prefix}_ht_goals"], "ht_goals_against": matches[f"{other}_ht_goals"],
            "corners_for": matches[f"{prefix}_corners"], "corners_against": matches[f"{other}_corners"],
            "yellows_for": matches[f"{prefix}_yellows"], "fouls_for": matches[f"{prefix}_fouls"],
            "xg_real_for": matches[f"{prefix}_xg_real"], "xg_real_against": matches[f"{other}_xg_real"],
            "sot_for": matches[f"{prefix}_sot"], "sot_against": matches[f"{other}_sot"],
            "shots_for": matches[f"{prefix}_shots"],
        })

    rows = pd.concat([side("home", "away", "home"), side("away", "home", "away")], ignore_index=True)
    return rows.sort_values(["team", "date"]).reset_index(drop=True)


def _result(row) -> str:
    return "W" if row.goals_for > row.goals_against else "D" if row.goals_for == row.goals_against else "L"


@dataclass
class TeamProfile:
    team: str
    venue: str
    fields: dict[str, FieldValue]
    extra: dict[str, FieldValue]
    last_match: date | None
    warnings: list[str]


def team_profile(
    team: str,
    rows: pd.DataFrame,
    understat_rows: pd.DataFrame | None,
    *,
    as_of: date,
    venue: str,
    matches: int = 10,
    half_life: float = 5.0,
    footballdata_updated: datetime | None = None,
    understat_updated: datetime | None = None,
) -> TeamProfile:
    """Statistiche della squadra nelle ultime ``matches`` gare in casa o in trasferta prima di ``as_of``."""
    warnings: list[str] = []
    before = rows[rows["date"] < pd.Timestamp(as_of)] if not rows.empty else rows
    name = match_team(team, before["team"].unique()) if not before.empty else None
    if name is None:
        note = f"«{team}» non trovata nei CSV football-data.co.uk dei campionati coperti."
        empty = {key: missing(note) for key in ("attack", "defense", "form", "xg_for", "xg_against",
                                                 "corners_for", "corners_against", "cards_for")}
        return TeamProfile(team, venue, empty, {}, None, [note])

    league_rows = before[before["league"] == before.loc[before["team"] == name, "league"].iloc[-1]]
    team_rows = league_rows[league_rows["team"] == name]
    venue_rows = team_rows[team_rows["venue"] == venue].tail(matches)
    last_match = venue_rows["date"].max().date() if not venue_rows.empty else None
    venue_label = "casa" if venue == "home" else "trasferta"
    if len(venue_rows) < matches:
        warnings.append(f"{name}: solo {len(venue_rows)} partite in {venue_label} disponibili (richieste {matches}).")

    league_venue = league_rows[league_rows["venue"] == venue]

    def scale(column: str) -> float:
        overall = pd.to_numeric(league_rows[column], errors="coerce").mean()
        specific = pd.to_numeric(league_venue[column], errors="coerce").mean()
        return float(overall / specific) if specific and np.isfinite(specific) else 1.0

    def stat(column: str, label: str, normalize: bool = True, digits: int = 2) -> FieldValue:
        if len(venue_rows) < 3:
            return missing(f"meno di 3 partite in {venue_label}", "football-data.co.uk")
        value = weighted_mean(venue_rows[column], half_life)
        if not np.isfinite(value):
            return missing(f"{label} non presente nei CSV", "football-data.co.uk")
        factor = scale(column) if normalize else 1.0
        note = f"{len(venue_rows)} gare in {venue_label}, pesate per recenza"
        if normalize:
            note += f"; riportato alla media generale della lega (×{factor:.3f})"
        return FieldValue(round(value * factor, digits), "football-data.co.uk", footballdata_updated, last_match, note)

    fields: dict[str, FieldValue] = {}
    if len(venue_rows) >= 3:
        goals_for = weighted_mean(venue_rows["goals_for"], half_life)
        goals_against = weighted_mean(venue_rows["goals_against"], half_life)
        league_for = league_venue["goals_for"].mean()
        league_against = league_venue["goals_against"].mean()
        note = f"{len(venue_rows)} gare in {venue_label}, rapporto con la media {venue_label} della lega"
        fields["attack"] = FieldValue(round(float(np.clip(goals_for / league_for, 0.2, 3.0)), 2),
                                      "football-data.co.uk", footballdata_updated, last_match, note)
        fields["defense"] = (
            FieldValue(round(float(np.clip(league_against / goals_against, 0.2, 3.0)), 2),
                       "football-data.co.uk", footballdata_updated, last_match, note)
            if goals_against > 0 else
            FieldValue(3.0, "football-data.co.uk", footballdata_updated, last_match,
                       note + "; nessun gol subito: valore al massimo consentito (3.0)", "avviso")
        )
    else:
        fields["attack"] = fields["defense"] = missing(f"meno di 3 partite in {venue_label}", "football-data.co.uk")

    recent = team_rows.tail(5)
    fields["form"] = (
        FieldValue("-".join(_result(row) for row in recent.itertuples()), "football-data.co.uk",
                   footballdata_updated, recent["date"].max().date(), "ultime 5 di campionato, dalla più vecchia")
        if not recent.empty else missing("nessuna partita di campionato", "football-data.co.uk")
    )

    fields["xg_for"], fields["xg_against"] = _xg_fields(
        name, venue, venue_rows, understat_rows, as_of, matches, half_life, understat_updated,
        footballdata_updated, last_match, warnings,
    )
    fields["corners_for"] = stat("corners_for", "corner", digits=1)
    fields["corners_against"] = stat("corners_against", "corner", digits=1)
    fields["cards_for"] = stat("yellows_for", "gialli")

    extra = {
        "goals_for": stat("goals_for", "gol", normalize=False),
        "goals_against": stat("goals_against", "gol", normalize=False),
        "ht_goals_for": stat("ht_goals_for", "gol primo tempo", normalize=False),
        "ht_goals_against": stat("ht_goals_against", "gol primo tempo", normalize=False),
        "fouls_for": stat("fouls_for", "falli", normalize=False, digits=1),
    }
    if understat_rows is not None and not understat_rows.empty:
        us_name = match_team(team, understat_rows["team"].unique())
        if us_name is not None:
            us_venue = understat_rows[(understat_rows["team"] == us_name) & (understat_rows["venue"] == venue)
                                      & (understat_rows["date"] < pd.Timestamp(as_of))].tail(matches)
            for key, label in (("ppda", "PPDA"), ("deep", "deep completions")):
                value = weighted_mean(us_venue[key], half_life)
                if np.isfinite(value):
                    extra[key] = FieldValue(round(value, 2), "Understat", understat_updated,
                                            us_venue["date"].max().date(), f"{len(us_venue)} gare in {venue_label}")
    return TeamProfile(name, venue, fields, extra, last_match, warnings)


def _xg_fields(name, venue, venue_rows, understat_rows, as_of, matches, half_life, understat_updated,
               footballdata_updated, last_match, warnings) -> tuple[FieldValue, FieldValue]:
    venue_label = "casa" if venue == "home" else "trasferta"
    if understat_rows is not None and not understat_rows.empty:
        us_name = match_team(name, understat_rows["team"].unique())
        if us_name is not None:
            league = understat_rows[understat_rows["date"] < pd.Timestamp(as_of)]
            us_venue = league[(league["team"] == us_name) & (league["venue"] == venue)].tail(matches)
            if len(us_venue) >= 3:
                result = []
                for column in ("xg_for", "xg_against"):
                    factor = float(league[column].mean() / league.loc[league["venue"] == venue, column].mean())
                    value = weighted_mean(us_venue[column], half_life) * factor
                    result.append(FieldValue(
                        round(value, 2), "Understat", understat_updated, us_venue["date"].max().date(),
                        f"{len(us_venue)} gare in {venue_label}, pesate per recenza; riportato alla media "
                        f"generale della lega (×{factor:.3f})",
                    ))
                return result[0], result[1]
    real = venue_rows[["xg_real_for", "xg_real_against"]].dropna()
    if len(real) >= 3:
        return tuple(
            FieldValue(round(weighted_mean(real[column], half_life), 2), "football-data.co.uk (xG)",
                       footballdata_updated, last_match, f"{len(real)} gare in {venue_label}; Understat non disponibile",
                       "avviso")
            for column in ("xg_real_for", "xg_real_against")
        )
    proxy = venue_rows[["sot_for", "sot_against"]].dropna()
    if len(proxy) >= 3:
        warnings.append(f"{name}: xG stimati dai tiri in porta (Understat e xG football-data non disponibili).")
        return tuple(
            FieldValue(round(weighted_mean(proxy[column], half_life) * SHOT_XG_PER_SHOT_ON_TARGET, 2),
                       "football-data.co.uk (stima dai tiri)", footballdata_updated, last_match,
                       f"{SHOT_XG_PER_SHOT_ON_TARGET} × tiri in porta", "avviso")
            for column in ("sot_for", "sot_against")
        )
    return missing("xG non disponibili"), missing("xG non disponibili")


@dataclass
class RefereeProfile:
    name: str | None
    yellow: FieldValue
    fouls: FieldValue
    competitions: dict[str, dict]
    warnings: list[str]


def referee_profile(
    name: str | None,
    matches: pd.DataFrame,
    *,
    as_of: date,
    footballdata_updated: datetime | None = None,
    prior_matches: int = REFEREE_PRIOR_MATCHES,
) -> RefereeProfile:
    """Gialli e falli medi dell'arbitro nel campionato, avvicinati alla media della competizione.

    Valore = (n·media arbitro + k·media competizione) / (n + k) con k=``prior_matches``:
    con poche partite pesa soprattutto la media della competizione.
    """
    data = matches[matches["date"] < pd.Timestamp(as_of)] if not matches.empty else matches
    warnings: list[str] = []
    if data.empty:
        note = "nessuna partita di riferimento per la competizione"
        return RefereeProfile(name, missing(note), missing(note), {}, [note])
    data = data.assign(yellows=data["home_yellows"] + data["away_yellows"], fouls=data["home_fouls"] + data["away_fouls"])
    competition_yellow, competition_fouls = float(data["yellows"].mean()), float(data["fouls"].mean())
    last = data["date"].max().date()
    cups = {"partite": 0, "nota": "coppe europee: nessuna fonte gratuita con gli arbitri (FBref bloccata)"}

    referees = data["referee"].dropna().unique() if "referee" in data else []
    found = match_team(name, referees, cutoff=0.9) if name and len(referees) else None
    if found is None:
        reason = ("arbitro non indicato" if not name else
                  f"arbitro «{name}» non presente nei dati (football-data.co.uk ha gli arbitri solo per la Premier League)")
        note = f"{reason}: media della competizione ({len(data)} partite)"
        warnings.append(note)
        return RefereeProfile(
            name,
            FieldValue(round(competition_yellow, 2), "football-data.co.uk (media competizione)", footballdata_updated, last, note, "avviso"),
            FieldValue(round(competition_fouls, 1), "football-data.co.uk (media competizione)", footballdata_updated, last, note, "avviso"),
            {"campionato": {"partite": 0}, "coppe_europee": cups},
            warnings,
        )

    own = data[data["referee"] == found]
    count = len(own)
    weight = count / (count + prior_matches)
    yellow = weight * own["yellows"].mean() + (1 - weight) * competition_yellow
    fouls = weight * own["fouls"].mean() + (1 - weight) * competition_fouls
    level = "avviso" if count < REFEREE_RELIABLE_MATCHES else "ok"
    note = (f"{found}: {count} partite di campionato (media grezza {own['yellows'].mean():.2f} gialli, "
            f"{own['fouls'].mean():.1f} falli), avvicinata alla media della competizione con peso {1 - weight:.0%}")
    if count < REFEREE_RELIABLE_MATCHES:
        warnings.append(f"Arbitro {found}: solo {count} partite, dato poco affidabile.")
        note += " · poco affidabile (meno di 10 partite)"
    last_own = own["date"].max().date()
    return RefereeProfile(
        found,
        FieldValue(round(float(yellow), 2), "football-data.co.uk", footballdata_updated, last_own, note, level),
        FieldValue(round(float(fouls), 1), "football-data.co.uk", footballdata_updated, last_own, note, level),
        {"campionato": {"partite": count, "gialli_medi": float(own["yellows"].mean()), "falli_medi": float(own["fouls"].mean())},
         "coppe_europee": cups},
        warnings,
    )
