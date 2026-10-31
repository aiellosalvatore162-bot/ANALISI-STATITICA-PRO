"""Fase AN, parte B: importazione di dati nuovi (stile, giocatori, formazioni, arbitri, quote) da CSV.

Logica pura (nessuna interfaccia): riconoscimento del tipo dalle intestazioni (italiano o inglese), validazione, abbinamento dei
nomi squadra a quelli dell'app senza mai scegliere in caso di dubbio, scrittura nella cache (``data/cache/importati``) e registro
delle importazioni (``data/import/registro.json``). Consultazione per il motore: ``style_row`` (solo righe con ``data_dati``
PRIMA della partita: nessun dato dal futuro). Comando: ``python -m tools.importa_dati <file>``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

from datasources.names import canonical_key, display_name, match_team

ROOT = Path(__file__).resolve().parent
STORE_DIR = ROOT / "data" / "cache" / "importati"
REGISTRY_PATH = ROOT / "data" / "import" / "registro.json"
NAMES_PATH = ROOT / "data" / "import" / "nomi.json"
ENABLED = True   # interruttore per il confronto con/senza dato importato (tools/confronto_dati)


@dataclass(frozen=True)
class Kind:
    name: str
    label: str
    key: tuple[str, ...]
    required: tuple[str, ...]
    team_columns: tuple[str, ...]
    aliases: Mapping[str, tuple[str, ...]]     # colonna canonica -> nomi accettati (italiani e inglesi)
    numeric: Mapping[str, tuple[float, float]] = field(default_factory=dict)   # colonna -> (minimo, massimo)
    dates: tuple[str, ...] = ()
    used_by_engine: tuple[str, ...] = ()       # colonne che il motore legge davvero (le altre: solo consultazione)


KINDS: dict[str, Kind] = {
    "stile": Kind(
        "stile", "Stile squadra", ("squadra", "stagione"), ("squadra", "stagione", "data_dati", "partite"), ("squadra",),
        {"squadra": ("squadra", "team", "club"), "stagione": ("stagione", "season"), "campionato": ("campionato", "league", "competition"),
         "data_dati": ("data_dati", "aggiornato_al", "as_of", "data", "date"), "partite": ("partite", "matches", "games", "mp"),
         "possesso": ("possesso", "possession", "poss"), "passaggi": ("passaggi", "passes"), "pressioni": ("pressioni", "pressures"),
         "ppda": ("ppda",), "tiri_area": ("tiri_area", "shots_box", "tiri_in_area"), "tiri_fuori_area": ("tiri_fuori_area", "shots_outside"),
         "corner": ("corner", "corners"), "falli": ("falli", "fouls"), "xg": ("xg", "xg_for", "xg_fatti"),
         "xga": ("xga", "xg_against", "xg_subiti"), "tiri_transizione": ("tiri_transizione", "transition_shots"),
         "quota_xg_palle_inattive": ("quota_xg_palle_inattive", "set_piece_xg_share"), "cross": ("cross", "crosses")},
        {"possesso": (0, 100), "ppda": (0, 60), "partite": (1, 80), "passaggi": (0, 2000), "pressioni": (0, 1000),
         "xg": (0, 200), "xga": (0, 200), "tiri_area": (0, 40), "tiri_fuori_area": (0, 40), "corner": (0, 30), "falli": (0, 60),
         "quota_xg_palle_inattive": (0, 1)},
        ("data_dati",), ("xg", "xga", "partite", "tiri_transizione", "quota_xg_palle_inattive", "cross")),
    "giocatori": Kind(
        "giocatori", "Giocatori", ("giocatore", "squadra", "stagione"),
        ("giocatore", "squadra", "stagione", "minuti", "ruolo", "data_dati"), ("squadra",),
        {"giocatore": ("giocatore", "player", "nome"), "squadra": ("squadra", "team", "club"), "stagione": ("stagione", "season"),
         "ruolo": ("ruolo", "role", "position", "pos"), "minuti": ("minuti", "minutes", "min"), "xg": ("xg",), "xa": ("xa",),
         "tiri": ("tiri", "shots"), "data_dati": ("data_dati", "aggiornato_al", "as_of", "data", "date")},
        {"minuti": (0, 6000), "xg": (0, 60), "xa": (0, 60), "tiri": (0, 600)}, ("data_dati",), ()),
    "formazioni": Kind(
        "formazioni", "Formazioni e assenti", ("data", "squadra"), ("data", "squadra"), ("squadra",),
        {"data": ("data", "date"), "squadra": ("squadra", "team", "club"), "formazione": ("formazione", "lineup", "titolari"),
         "assenti": ("assenti", "absent", "unavailable", "indisponibili")}, {}, ("data",), ()),
    "arbitri": Kind(
        "arbitri", "Arbitri", ("arbitro", "stagione"), ("arbitro", "partite", "gialli", "data_dati"), (),
        {"arbitro": ("arbitro", "referee"), "stagione": ("stagione", "season"), "partite": ("partite", "matches", "games"),
         "falli": ("falli", "fouls"), "gialli": ("gialli", "yellows", "yellow_cards"), "rossi": ("rossi", "reds", "red_cards"),
         "data_dati": ("data_dati", "aggiornato_al", "as_of", "data", "date")},
        {"partite": (1, 500), "falli": (0, 100000), "gialli": (0, 3000), "rossi": (0, 300)}, ("data_dati",), ()),
    "quote": Kind(
        "quote", "Quote", ("data", "casa", "ospite", "mercato", "bookmaker", "tipo"), ("data", "casa", "ospite", "mercato", "quota"),
        ("casa", "ospite"),
        {"data": ("data", "date"), "casa": ("casa", "home", "home_team"), "ospite": ("ospite", "away", "away_team"),
         "mercato": ("mercato", "market", "selezione", "selection"), "quota": ("quota", "odds", "price"),
         "bookmaker": ("bookmaker", "book"), "tipo": ("tipo", "type")},
        {"quota": (1.0001, 1000)}, ("data",), ()),
}


def norm_header(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _canonical_columns(kind: Kind, columns: Iterable[str]) -> dict[str, str]:
    lookup = {norm_header(alias): canon for canon, aliases in kind.aliases.items() for alias in aliases}
    found: dict[str, str] = {}
    for column in columns:
        canon = lookup.get(norm_header(column))
        if canon and canon not in found:
            found[canon] = column
    return found


def detect_kind(columns: Sequence[str]) -> tuple[Kind | None, list[str]]:
    """Il tipo con più colonne obbligatorie presenti (a parità di punteggio nessun tipo: ambiguo). Ritorna (tipo, mancanti)."""
    scored = []
    for kind in KINDS.values():
        present = _canonical_columns(kind, columns)
        missing = [name for name in kind.required if name not in present]
        scored.append((len(kind.required) - len(missing), -len(missing), kind, missing))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = scored[0]
    if best[0] == 0 or (len(scored) > 1 and scored[1][0] == best[0] and scored[1][3] == [] and best[3] == []):
        return None, []
    return best[2], best[3]


def parse_date(value: Any) -> date | None:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# --- Nomi squadra ---------------------------------------------------------------------------------------------------

def known_teams() -> list[str]:
    """Squadre note all'app: alias dei nomi e squadre nei CSV in cache."""
    from datasources.names import TEAM_ALIASES

    teams = {row[0] for row in TEAM_ALIASES}
    for path in sorted((ROOT / "data" / "cache").glob("*_*.csv"))[:60]:
        try:
            frame = pd.read_csv(path, usecols=lambda c: c in ("HomeTeam", "AwayTeam"), encoding="latin-1")
        except (ValueError, OSError):
            continue
        for column in frame.columns:
            teams.update(str(name) for name in frame[column].dropna().unique())
    return sorted(teams)


def load_name_map(path: Path = NAMES_PATH) -> dict[str, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_name_map(mapping: Mapping[str, str], path: Path = NAMES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(mapping.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def resolve_team(name: str, known: Sequence[str], saved: Mapping[str, str]) -> tuple[str | None, str | None]:
    """(nome dell'app, suggerimento). Si abbina da solo SOLO con scelta già salvata o nome canonico identico; altrimenti
    ritorna (None, suggerimento) e l'utente deve scegliere: nessun abbinamento automatico dubbio."""
    if name in saved:
        return saved[name], None
    key = canonical_key(name)
    exact = sorted({team for team in known if canonical_key(team) == key})
    if len(exact) == 1:
        return display_name(exact[0]), None
    return None, match_team(name, known)


def similar_names(name: str, known: Sequence[str], count: int = 5) -> list[str]:
    from difflib import SequenceMatcher

    key = canonical_key(name)
    scored = sorted(((SequenceMatcher(None, key, canonical_key(team)).ratio(), team) for team in known), reverse=True)
    return [team for _, team in scored[:count]]


# --- Importazione ---------------------------------------------------------------------------------------------------

@dataclass
class Report:
    kind: str
    file: str
    source: str
    imported: int = 0
    discarded: int = 0
    duplicates: int = 0
    reasons: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    leagues: list[str] = field(default_factory=list)
    error: str | None = None


def read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, sep=None, engine="python", dtype=str, encoding=encoding, keep_default_na=False)
        except UnicodeDecodeError:
            continue
    raise ValueError("file non leggibile")


def prepare(frame: pd.DataFrame, kind: Kind, today: date | None = None, known: Sequence[str] | None = None,
            saved: Mapping[str, str] | None = None, names_path: Path | None = None) -> tuple[list[dict], Report, dict[str, str | None]]:
    """Righe valide (nomi ancora da abbinare), rapporto e nomi squadra non abbinati (nome → suggerimento).

    Scarta: valori fuori scala, date non valide o future, campi obbligatori vuoti, doppioni nello stesso file (vince l'ultima)."""
    today = today or date.today()
    report = Report(kind.name, "", "")
    columns = _canonical_columns(kind, frame.columns)
    missing = [name for name in kind.required if name not in columns]
    if missing:
        report.error = f"colonne mancanti: {', '.join(missing)}"
        return [], report, {}
    rows: dict[tuple, dict] = {}
    for position, raw in enumerate(frame.to_dict("records"), start=2):
        row = {canon: str(raw[column]).strip() for canon, column in columns.items()}
        problem = None
        for name in kind.required:
            if row.get(name, "") == "":
                problem = f"riga {position}: campo «{name}» vuoto"
        for name in kind.dates:
            if problem is None and name in row and row[name] != "":
                parsed = parse_date(row[name])
                if parsed is None:
                    problem = f"riga {position}: data «{row[name]}» non valida"
                elif parsed > today and name == "data_dati":
                    problem = f"riga {position}: data_dati {parsed:%d/%m/%Y} nel futuro"
                else:
                    row[name] = parsed.isoformat()
        for name, (low, high) in kind.numeric.items():
            if problem is None and row.get(name, "") != "":
                try:
                    value = float(row[name].replace(",", "."))
                except ValueError:
                    problem = f"riga {position}: «{name}» = «{row[name]}» non è un numero"
                else:
                    if not low <= value <= high:
                        problem = f"riga {position}: «{name}» = {value:g} fuori scala ({low:g}…{high:g})"
                    row[name] = value
            elif row.get(name, "") == "":
                row.pop(name, None)
        if problem:
            report.discarded += 1
            report.reasons.append(problem)
            continue
        key = tuple(row.get(name, "") for name in kind.key)
        if key in rows:
            report.duplicates += 1
            report.reasons.append(f"riga {position}: doppione di una riga precedente, vale questa")
        rows[key] = row
    known = list(known) if known is not None else known_teams()
    saved = dict(saved) if saved is not None else load_name_map(names_path or NAMES_PATH)
    unmatched: dict[str, str | None] = {}
    for row in rows.values():
        for column in kind.team_columns:
            name = row[column]
            resolved, suggestion = resolve_team(name, known, saved)
            if resolved is None:
                unmatched[name] = suggestion
    return list(rows.values()), report, unmatched


def commit(rows: list[dict], kind: Kind, report: Report, mapping: Mapping[str, str], *, file: str, source: str,
           store_dir: Path = STORE_DIR, registry_path: Path = REGISTRY_PATH, today: date | None = None,
           known: Sequence[str] | None = None, names_path: Path | None = None) -> Report:
    """Applica l'abbinamento dei nomi (le righe con nomi senza scelta sono scartate), scrive nella cache e nel registro."""
    today = today or date.today()
    known = list(known) if known is not None else known_teams()
    saved = {**load_name_map(names_path or NAMES_PATH), **mapping}
    kept = []
    for row in rows:
        row = dict(row)
        ok = True
        for column in kind.team_columns:
            resolved, _ = resolve_team(row[column], known, saved)
            if resolved is None:
                ok = False
                report.reasons.append(f"nome squadra non abbinato: «{row[column]}»")
                if row[column] not in report.unmatched:
                    report.unmatched.append(row[column])
            else:
                row[column] = resolved
        if ok:
            row["_fonte"], row["_importato"] = source, today.isoformat()
            kept.append(row)
        else:
            report.discarded += 1
    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_dir / f"{kind.name}.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    index = {tuple(row.get(name, "") for name in kind.key): row for row in existing}
    for row in kept:
        index[tuple(row.get(name, "") for name in kind.key)] = row       # la stessa chiave si aggiorna: importare due volte non duplica
    path.write_text(json.dumps(list(index.values()), ensure_ascii=False) + "\n", encoding="utf-8")
    report.file, report.source, report.imported = file, source, len(kept)
    report.teams = sorted({row[c] for row in kept for c in kind.team_columns})
    report.leagues = sorted({row["campionato"] for row in kept if row.get("campionato")})
    log = _read_registry(registry_path)
    log.append({"data": today.isoformat(), "file": file, "tipo": kind.name, "fonte": source, "importate": report.imported,
                "scartate": report.discarded, "doppioni": report.duplicates, "squadre": len(report.teams),
                "campionati": report.leagues, "motivi": report.reasons[:20]})
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if mapping:
        save_name_map(saved, names_path or NAMES_PATH)
    return report


def _read_registry(path: Path = REGISTRY_PATH) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def registry(path: Path = REGISTRY_PATH) -> list[dict]:
    return _read_registry(path)


def import_file(path: Path, *, source: str | None = None, chooser: Callable[[str, str | None, list[str]], str | None] | None = None,
                mapping: Mapping[str, str] | None = None, store_dir: Path = STORE_DIR, registry_path: Path = REGISTRY_PATH,
                today: date | None = None, known: Sequence[str] | None = None, names_path: Path | None = None) -> Report:
    """Importazione completa. ``chooser(nome, suggerimento, simili)`` sceglie il nome dell'app (o None per scartare)."""
    frame = read_csv(path)
    kind, missing = detect_kind(list(frame.columns))
    if kind is None:
        return Report("?", path.name, source or path.name, error="tipo di file non riconosciuto dalle intestazioni")
    rows, report, unmatched = prepare(frame, kind, today, known, names_path=names_path)
    report.file, report.source = path.name, source or path.name
    if report.error:
        return report
    chosen = dict(mapping or {})
    for name, suggestion in unmatched.items():
        if name in chosen:
            continue
        if chooser is not None:
            answer = chooser(name, suggestion, similar_names(name, known or known_teams()))
            if answer:
                chosen[name] = answer
    return commit(rows, kind, report, chosen, file=path.name, source=source or path.name, store_dir=store_dir,
                  registry_path=registry_path, today=today, known=known, names_path=names_path)


# --- Consultazione (motore) -------------------------------------------------------------------------------------------

def load_rows(kind: str, store_dir: Path | None = None) -> list[dict]:
    try:
        return json.loads(((store_dir or STORE_DIR) / f"{kind}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def style_row(team: str, when: Any, store_dir: Path | None = None) -> dict | None:
    """Riga di stile importata più recente per la squadra con ``data_dati`` STRETTAMENTE prima di ``when`` (nessun dato dal futuro)."""
    key = canonical_key(team)
    limit = pd.Timestamp(when).date().isoformat()
    rows = [row for row in load_rows("stile", store_dir) if canonical_key(row["squadra"]) == key and row["data_dati"] < limit]
    return max(rows, key=lambda row: (row["data_dati"], row["stagione"])) if rows else None


def provenance(row: Mapping[str, Any]) -> str:
    imported = date.fromisoformat(row["_importato"]).strftime("%d/%m/%Y")
    return f"dato importato dal {imported}, fonte {row['_fonte']}"
