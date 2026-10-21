"""Compilazione automatica del blocco di input del parser a partire dalle fonti.

Il blocco prodotto è nel formato attuale del parser; sotto ogni riga c'è un
commento ``# Fonti: ...`` (ignorato dal parser) con fonte e date di ogni
valore. I campi che nessuna fonte fornisce restano assenti: il parser li
segnalerà come mancanti e l'interfaccia li evidenzia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import re

import pandas as pd

from datasources.cache import SourceCache
from datasources.clubelo import ClubElo
from datasources.names import display_name, match_team
from datasources.sources import (
    COMPETITIONS, CUP_COMPETITIONS, FootballDataCoUk, FootballDataOrg, Understat, football_data_org_key,
    season_start,
)
from datasources.stats import FieldValue, RefereeProfile, TeamProfile, missing, referee_profile, team_match_rows, team_profile
from tools.dataset import elo_table


DEFAULT_MAX_AGE = timedelta(hours=24)
TEAM_FIELDS = (
    ("attack", "Attacco"), ("defense", "Difesa"), ("elo", "Elo"), ("form", "Forma"),
    ("xg_for", "xG Fatti"), ("xg_against", "xG Subiti"), ("corners", "Corner pro/sub"), ("cards_for", "Cartellini pro"),
)
ODDS_FIELDS = (("1", "Quota 1"), ("X", "Quota X"), ("2", "Quota 2"),
               ("Over 2.5 gol", "Quota Over 2.5"), ("Under 2.5 gol", "Quota Under 2.5"))


@dataclass
class MatchSheet:
    home: str
    away: str
    match_date: date
    competition: str | None
    home_fields: dict[str, FieldValue]
    away_fields: dict[str, FieldValue]
    referee_fields: dict[str, FieldValue]
    odds: dict[str, FieldValue] = field(default_factory=dict)
    extras: dict[str, dict[str, FieldValue]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    origin: str = "fonti automatiche"


def _date(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.astimezone().strftime("%d/%m/%Y %H:%M")
    return value.strftime("%d/%m/%Y")


def _format(key: str, value) -> str:
    if key == "elo":
        return f"{float(value):.0f}"
    if isinstance(value, str):
        return value
    return f"{float(value):.2f}".rstrip("0").rstrip(".") if key != "corners" else value


class DataProvider:
    """Accesso unico alle fonti con soglia di aggiornamento configurabile.

    ``max_age``: età massima dei dati di squadre e arbitri prima di un nuovo
    download (24 ore). ``refresh()`` la azzera per forzare il download.
    """

    def __init__(self, cache: SourceCache | None = None, *, max_age: timedelta = DEFAULT_MAX_AGE,
                 matches: int = 10, half_life: float = 5.0, today: date | None = None,
                 football_data_key: str | None = None) -> None:
        self.cache = cache or SourceCache()
        self.max_age = max_age
        self.matches = matches
        self.half_life = half_life
        self.today = today or date.today()
        self.clubelo = ClubElo(self.cache)
        self.understat = Understat(self.cache)
        self.footballdata = FootballDataCoUk(self.cache)
        self.footballdata_org = FootballDataOrg(self.cache, football_data_key if football_data_key is not None else football_data_org_key())
        self.warnings: list[str] = []

    def refresh(self) -> None:
        self.max_age = timedelta(0)

    # --- Fonti -------------------------------------------------------------------------

    def league_matches(self, competition: str):
        code = COMPETITIONS[competition]["footballdata"]
        frame = self.footballdata.recent(code, self.today, self.max_age)
        self.warnings.extend(frame.warnings)
        return frame

    def understat_matches(self, competition: str):
        start = season_start(self.today)
        frames = [self.understat.league(COMPETITIONS[competition]["understat"], season, self.max_age if season == start else timedelta(days=30))
                  for season in (start, start - 1)]
        for frame in frames:
            self.warnings.extend(frame.warnings)
        data = pd.concat([frame.data for frame in frames if not frame.data.empty], ignore_index=True) if any(
            not frame.data.empty for frame in frames) else pd.DataFrame()
        if not data.empty:
            data = data.sort_values(["team", "date"]).reset_index(drop=True)
        updated = max((frame.updated for frame in frames if frame.updated), default=None)
        return data, updated

    def competition_of(self, team: str) -> str | None:
        """Campionato nazionale (tra quelli coperti) in cui gioca la squadra nella stagione in corso."""
        for competition, codes in COMPETITIONS.items():
            frame = self.footballdata.season(codes["footballdata"], season_start(self.today), self.max_age)
            if not frame.data.empty and match_team(team, pd.concat([frame.data["home_team"], frame.data["away_team"]]).unique()):
                return competition
        return None

    def fixtures(self) -> pd.DataFrame:
        """Prossime partite dei campionati coperti (football-data.co.uk) e coppe (football-data.org)."""
        frame = self.footballdata.fixtures(min(self.max_age, timedelta(hours=6)))
        self.warnings.extend(frame.warnings)
        codes = {codes["footballdata"]: name for name, codes in COMPETITIONS.items()}
        fixtures = frame.data[frame.data["league"].isin(codes)].assign(competition=lambda df: df["league"].map(codes)) \
            if not frame.data.empty else pd.DataFrame()
        cups = []
        for name, code in CUP_COMPETITIONS.items():
            cup = self.footballdata_org.matches(code, self.today, self.today + timedelta(days=14), min(self.max_age, timedelta(hours=6)))
            self.warnings.extend(cup.warnings)
            if not cup.data.empty:
                cups.append(cup.data.assign(competition=name))
        return pd.concat([fixtures, *cups], ignore_index=True) if cups else fixtures

    # --- Costruzione della scheda --------------------------------------------------------

    def build(self, home: str, away: str, *, match_date: date | None = None, competition: str | None = None,
              referee: str | None = None, odds: dict[str, float] | None = None) -> MatchSheet:
        self.warnings = []
        match_date = match_date or self.today
        leagues = {side: self.competition_of(team) for side, team in (("home", home), ("away", away))}
        profiles: dict[str, TeamProfile] = {}
        updated: dict[str, datetime | None] = {}
        league_rows: dict[str, pd.DataFrame] = {}
        for side, team in (("home", home), ("away", away)):
            league = leagues[side]
            if league is None:
                note = f"«{team}» non trovata nei campionati coperti ({', '.join(COMPETITIONS)})."
                self.warnings.append(note)
                profiles[side] = TeamProfile(team, side, {key: missing(note) for key, _ in TEAM_FIELDS if key not in ("elo", "corners")}
                                             | {"corners_for": missing(note), "corners_against": missing(note)}, {}, None, [])
                continue
            matches = self.league_matches(league)
            understat, us_updated = self.understat_matches(league)
            league_rows[league] = matches.data
            updated[side] = matches.updated
            profiles[side] = team_profile(
                team, team_match_rows(matches.data), understat, as_of=match_date, venue=side,
                matches=self.matches, half_life=self.half_life,
                footballdata_updated=matches.updated, understat_updated=us_updated,
            )
            self.warnings.extend(profiles[side].warnings)

        elo = self._elo(home, away, match_date, leagues)
        sheet_fields = {}
        for side in ("home", "away"):
            fields = dict(profiles[side].fields)
            fields["elo"] = elo[side]
            fields["corners"] = _pair(fields.pop("corners_for"), fields.pop("corners_against"))
            sheet_fields[side] = fields
            self._freshness(profiles[side], elo[side])

        if leagues["home"] and leagues["away"] and leagues["home"] != leagues["away"]:
            self.warnings.append(
                f"Campionati diversi ({leagues['home']} / {leagues['away']}): Attacco, Difesa, xG, corner e cartellini "
                "sono relativi al proprio campionato nazionale; il confronto tra campionati è affidato all'Elo ClubElo."
            )
        referee_data = pd.concat([league_rows[league] for league in {leagues["home"], leagues["away"]} if league in league_rows],
                                 ignore_index=True) if league_rows else pd.DataFrame()
        ref = referee_profile(referee, referee_data, as_of=match_date,
                              footballdata_updated=max((value for value in updated.values() if value), default=None))
        self.warnings.extend(ref.warnings)

        sheet = MatchSheet(
            home=profiles["home"].team if leagues["home"] else display_name(home),
            away=profiles["away"].team if leagues["away"] else display_name(away),
            match_date=match_date,
            competition=competition or (leagues["home"] if leagues["home"] == leagues["away"] else None),
            home_fields=sheet_fields["home"], away_fields=sheet_fields["away"],
            referee_fields={"yellow": ref.yellow, "fouls": ref.fouls},
            extras={"home": profiles["home"].extra, "away": profiles["away"].extra},
        )
        sheet.odds = self._odds(sheet, odds)
        sheet.warnings = list(dict.fromkeys(self.warnings + self.clubelo.warnings))
        return sheet

    def _elo(self, home: str, away: str, match_date: date, leagues: dict) -> dict[str, FieldValue]:
        ratings = {side: self.clubelo.rating(team, match_date, self.max_age) for side, team in (("home", home), ("away", away))}
        if all(ratings.values()):
            return {
                side: FieldValue(rating.value, "ClubElo", rating.updated, rating.as_of,
                                 f"Elo pre-partita (punto dello storico del {_date(rating.as_of)}), {rating.url}",
                                 "avviso" if rating.warning else "ok")
                for side, rating in ratings.items()
            }
        # Ripiego: Elo calcolato dai risultati, solo se entrambe giocano nello stesso campionato
        # (scale diverse non sono confrontabili).
        if leagues["home"] and leagues["home"] == leagues["away"]:
            code = COMPETITIONS[leagues["home"]]["footballdata"]
            start = season_start(self.today)
            seasons = [self.footballdata.season(code, start - offset, self.max_age if offset == 0 else timedelta(days=30)).data
                       for offset in range(5, -1, -1)]
            table = elo_table(pd.concat([frame for frame in seasons if not frame.empty], ignore_index=True), pd.Timestamp(match_date))
            result = {}
            for side, team in (("home", home), ("away", away)):
                name = match_team(team, table)
                result[side] = (FieldValue(round(table[name][0], 1), "Elo calcolato dai risultati (ripiego)", None, table[name][1].date(),
                                           "ClubElo non disponibile: Elo calcolato da football-data.co.uk (6 stagioni)", "avviso")
                                if name else missing("ClubElo non disponibile e squadra non trovata nei risultati"))
            self.warnings.append("ClubElo non disponibile: uso l'Elo calcolato dai risultati (ripiego).")
            return result
        note = "ClubElo non disponibile per entrambe le squadre: inserire l'Elo a mano"
        self.warnings.append(note)
        return {side: (FieldValue(r.value, "ClubElo", r.updated, r.as_of, "l'altra squadra non ha l'Elo: confronto non possibile", "avviso")
                       if r else missing(note)) for side, r in ratings.items()}

    def _freshness(self, profile: TeamProfile, elo: FieldValue) -> None:
        """Avvisa se ClubElo conosce una partita più recente dell'ultima inclusa nelle statistiche."""
        rating_latest = None
        if elo.source == "ClubElo" and not elo.missing:
            slug_page = self.clubelo.slug_for(profile.team)
            rating = self.clubelo.rating(profile.team, self.today + timedelta(days=1), self.max_age) if slug_page else None
            rating_latest = rating.latest_match if rating else None
        included = [value.last_match for value in profile.fields.values() if value.last_match]
        latest_included = max(included) if included else None
        if rating_latest and latest_included and rating_latest > latest_included:
            self.warnings.append(
                f"{profile.team}: ultima partita giocata il {_date(rating_latest)} (secondo ClubElo) non presente nelle "
                f"statistiche (ultima inclusa {_date(latest_included)}): può essere una gara di coppa o un dato non ancora aggiornato."
            )

    def _odds(self, sheet: MatchSheet, odds: dict[str, float] | None) -> dict[str, FieldValue]:
        if odds:
            return {key: FieldValue(value, "inserita dall'utente") for key, value in odds.items()}
        fixtures = self.footballdata.fixtures(min(self.max_age, timedelta(hours=6)))
        if fixtures.data.empty:
            return {}
        data = fixtures.data
        home = match_team(sheet.home, data["home_team"].unique())
        away = match_team(sheet.away, data["away_team"].unique())
        row = data[(data["home_team"] == home) & (data["away_team"] == away)]
        if home is None or away is None or row.empty:
            return {}
        row = row.iloc[0]
        columns = {"1": "odds_home", "X": "odds_draw", "2": "odds_away", "Over 2.5 gol": "odds_over25", "Under 2.5 gol": "odds_under25"}
        return {key: FieldValue(float(row[column]), "football-data.co.uk (media bookmaker pre-partita)", fixtures.updated, row["date"].date())
                for key, column in columns.items() if column in row and pd.notna(row[column])}


def _pair(first: FieldValue, second: FieldValue) -> FieldValue:
    if first.missing or second.missing:
        return missing(first.note if first.missing else second.note, first.source)
    return FieldValue(f"{first.value:.1f}/{second.value:.1f}", first.source, first.updated, first.last_match,
                      first.note, "avviso" if "avviso" in (first.level, second.level) else "ok")


def _sources_comment(fields: dict[str, FieldValue], labels) -> str:
    parts = []
    for key, label in labels:
        value = fields.get(key)
        if value is None:
            continue
        if value.missing:
            parts.append(f"{label} MANCANTE ({value.note})")
        else:
            parts.append(f"{label} {value.source} (agg. {_date(value.updated)}, ultima partita {_date(value.last_match)})")
    return "# Fonti: " + " · ".join(parts)


def render_block(sheet: MatchSheet) -> str:
    """Blocco nel formato del parser; i campi mancanti sono omessi e annotati nel commento."""
    lines = [f"# Scheda compilata da {sheet.origin} per la partita del {_date(sheet.match_date)}"
             + (f" ({sheet.competition})" if sheet.competition else "")]
    for label, name, fields in (("CASA", sheet.home, sheet.home_fields), ("OSPITE", sheet.away, sheet.away_fields)):
        values = [f"{text}: {_format(key, fields[key].value)}" for key, text in TEAM_FIELDS
                  if key in fields and not fields[key].missing]
        lines += [f"{label}: {name}", " | ".join(values), _sources_comment(fields, TEAM_FIELDS), ""]
    referee = sheet.referee_fields
    parts = []
    if not referee["yellow"].missing:
        parts.append(f"Gialli medi {referee['yellow'].value:.2f}")
    if not referee["fouls"].missing:
        parts.append(f"Falli medi {referee['fouls'].value:.1f}")
    lines += [f"ARBITRO: {' | '.join(parts)}", _sources_comment(referee, (("yellow", "Gialli medi"), ("fouls", "Falli medi")))]
    if sheet.odds:
        quotes = [f"{label}: {sheet.odds[key].value:.2f}" for key, label in ODDS_FIELDS if key in sheet.odds]
        source = next(iter(sheet.odds.values()))
        lines += ["", "QUOTE_MERCATI_PRINCIPALI:", " | ".join(quotes),
                  f"# Fonti: quote {source.source} (agg. {_date(source.updated)})"]
    return "\n".join(lines) + "\n"


def provenance_rows(sheet: MatchSheet) -> list[dict]:
    """Tabella con valore, fonte, data di aggiornamento e ultima partita inclusa."""
    rows = []
    for subject, fields, labels in (
        (sheet.home, sheet.home_fields, TEAM_FIELDS), (sheet.away, sheet.away_fields, TEAM_FIELDS),
        ("Arbitro", sheet.referee_fields, (("yellow", "Gialli medi"), ("fouls", "Falli medi"))),
        ("Quote", sheet.odds, ODDS_FIELDS),
    ):
        for key, label in labels:
            if key not in fields:
                continue
            value = fields[key]
            rows.append({
                "Soggetto": subject, "Campo": label,
                "Valore": "" if value.missing else _format(key, value.value) if key in dict(TEAM_FIELDS) else str(value.value),
                "Fonte": value.source, "Aggiornato": _date(value.updated),
                "Ultima partita inclusa": _date(value.last_match), "Nota": value.note,
                "Stato": {"ok": "ok", "avviso": "da verificare", "mancante": "MANCANTE"}[value.level],
            })
    for side, subject in (("home", sheet.home), ("away", sheet.away)):
        for key, value in sheet.extras.get(side, {}).items():
            if value.missing:
                continue
            rows.append({
                "Soggetto": subject, "Campo": f"(info) {EXTRA_LABELS.get(key, key)}", "Valore": str(value.value),
                "Fonte": value.source, "Aggiornato": _date(value.updated),
                "Ultima partita inclusa": _date(value.last_match), "Nota": value.note, "Stato": "informativo",
            })
    return rows


EXTRA_LABELS = {
    "goals_for": "Gol fatti", "goals_against": "Gol subiti", "ht_goals_for": "Gol fatti 1° tempo",
    "ht_goals_against": "Gol subiti 1° tempo", "fouls_for": "Falli commessi", "ppda": "PPDA", "deep": "Deep completions",
}


# --- Controllo di plausibilità ------------------------------------------------------------

_NUMBER = r"[-+]?\d+(?:[.,]\d+)?"
_RANGES = {
    "Attacco": (0.3, 2.5, 0.2, 3.0), "Difesa": (0.3, 2.5, 0.2, 3.0), "Elo": (1200, 2200, 800, 2400),
    "xG Fatti": (0.3, 3.5, 0.0, 10.0), "xG Subiti": (0.3, 3.5, 0.0, 10.0), "Cartellini pro": (0.5, 4.0, 0.0, 10.0),
}


def plausibility_warnings(text: str) -> list[str]:
    """Avvisi su campi mancanti o valori fuori scala, prima ancora del parser."""
    warnings: list[str] = []
    sections = re.split(r"^(CASA|OSPITE)\s*:", text, flags=re.M | re.I)
    teams = {sections[index].upper(): sections[index + 1] for index in range(1, len(sections) - 1, 2)}
    for label in ("CASA", "OSPITE"):
        body = teams.get(label)
        if body is None:
            warnings.append(f"{label}: sezione mancante.")
            continue
        body = re.split(r"^(?:OSPITE|ARBITRO|QUOTE_)", body, flags=re.M | re.I)[0]
        body = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
        for field, (low, high, hard_low, hard_high) in _RANGES.items():
            match = re.search(rf"{re.escape(field)}\s*:\s*({_NUMBER})", body, re.I)
            if not match:
                warnings.append(f"{label}: {field} mancante.")
                continue
            value = float(match.group(1).replace(",", "."))
            if not hard_low <= value <= hard_high:
                warnings.append(f"{label}: {field} {value:g} fuori dal range accettato ({hard_low:g}-{hard_high:g}).")
            elif not low <= value <= high:
                hint = f" (forse {value / 10:g}?)" if field.startswith("xG") and value > 5 else ""
                warnings.append(f"{label}: {field} {value:g} insolito (atteso {low:g}-{high:g}){hint}.")
        if not re.search(r"Forma\s*:\s*[WDL](?:-[WDL]){0,4}\b", body, re.I):
            warnings.append(f"{label}: Forma mancante o non nel formato W-D-L.")
        corners = re.search(rf"Corner pro/sub\s*:\s*({_NUMBER})\s*/\s*({_NUMBER})", body, re.I)
        if not corners:
            warnings.append(f"{label}: Corner pro/sub mancante.")
        else:
            for value in (float(group.replace(",", ".")) for group in corners.groups()):
                if not 1.5 <= value <= 10.0:
                    warnings.append(f"{label}: Corner {value:g} per partita insolito (atteso 1.5-10).")
    referee = re.search(r"^ARBITRO\s*:(.*)$", text, re.M | re.I)
    if not referee:
        warnings.append("ARBITRO: riga mancante.")
    else:
        yellow = re.search(rf"Gialli medi\s*({_NUMBER})", referee.group(1), re.I)
        fouls = re.search(rf"Falli medi\s*({_NUMBER})", referee.group(1), re.I)
        if not yellow:
            warnings.append("ARBITRO: Gialli medi mancante.")
        elif not 1.0 <= float(yellow.group(1).replace(",", ".")) <= 8.0:
            warnings.append(f"ARBITRO: Gialli medi {yellow.group(1)} insolito (atteso 1-8 per partita).")
        if not fouls:
            warnings.append("ARBITRO: Falli medi mancante.")
        elif not 10.0 <= float(fouls.group(1).replace(",", ".")) <= 40.0:
            warnings.append(f"ARBITRO: Falli medi {fouls.group(1)} insolito (atteso 10-40 per partita).")
    for match in re.finditer(rf"Quota\s+([^:|\n]+?)\s*:\s*({_NUMBER})", text, re.I):
        odd = float(match.group(2).replace(",", "."))
        if odd < 1.01:
            warnings.append(f"Quota {match.group(1).strip()} {odd:g}: sotto 1.01, non valida.")
        elif odd > 200:
            warnings.append(f"Quota {match.group(1).strip()} {odd:g}: insolitamente alta.")
    return warnings
