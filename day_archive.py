"""Archivio unico della giornata (fase Z): una voce per partita, fonte unica di verità per tutta l'app.

Ogni voce (chiave data|Casa - Ospite, ``match_memory.match_id``) contiene: dati della partita (evento, competizione,
orario), selezione («selezionata», «da giocare»), quote di ogni fonte e bookmaker (``QuoteMercato``), pagine
incollate (testo grezzo, formato, bookmaker), dati inseriti a mano (fase R, formato di ``manual_data``), conflitti in
attesa di conferma e quote non raccolte. Le funzioni sono pure (lavorano su un ``dict``): la pagina Oggi, la pagina
Partita, «I miei mercati», combo builder, multiple, registro, schedine ed Excel leggono tutti da qui
(``ui_quotes.archive()`` lo tiene in ``st.session_state``).

Precedenza delle quote: un nuovo valore per la stessa selezione e lo stesso bookmaker che differisce da quello
salvato non sovrascrive: va tra i conflitti e cambia solo dopo conferma. Le quote scritte a mano nella pagina
Partita sono una scelta esplicita e si salvano come bookmaker «a mano».
"""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from quotes.model import QuoteMercato, consolidate, now_iso

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "oggi.json"
MANUAL_BOOKMAKER = "a mano"


def limits(path: Path = CONFIG_PATH) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    section = data.get("selezione") or {}
    return int(section.get("max_partite", 8)), int(section.get("max_da_giocare", 5))


def key_for(day: Any, home: str, away: str) -> str:
    from match_memory import match_id

    return match_id(day, home, away)


def new_entry(key: str, *, home: str, away: str, commence: str = "", competition: str = "", sport: str = "",
              event_id: str = "") -> dict:
    return {"key": key, "event_id": event_id, "sport": sport, "competition": competition, "commence": commence,
            "home": home, "away": away, "selected": False, "to_play": False, "quotes": [], "pages": [],
            "manual": {}, "pending": [], "not_collected": []}


def add_match(archive: dict, match) -> str:
    """Partita del giorno (``today.TodayMatch``) nell'archivio; una voce già presente non cambia."""
    key = key_for(match.commence_time.date(), match.home, match.away)
    if key not in archive:
        archive[key] = new_entry(key, home=match.home, away=match.away, commence=match.commence_time.isoformat(),
                                 competition=match.competition, sport=match.sport, event_id=match.event_id)
    return key


def today_match(entry: Mapping):
    from today import TodayMatch

    return TodayMatch(entry.get("event_id", ""), entry.get("sport", ""), entry.get("competition", ""),
                      datetime.fromisoformat(entry["commence"]), entry["home"], entry["away"])


def find(archive: Mapping, home: str, away: str, day: date | None = None) -> str | None:
    """Voce della partita (grafie diverse ammesse); con più voci per le stesse squadre vince la data più vicina."""
    from datasources.names import match_team

    found = [key for key, entry in archive.items()
             if match_team(home, [entry["home"]]) and match_team(away, [entry["away"]])]
    if not found:
        return None
    if day is None or len(found) == 1:
        return found[-1]

    def distance(key: str) -> int:
        commence = archive[key].get("commence")
        return abs((datetime.fromisoformat(commence).date() - day).days) if commence else 10_000

    return min(found, key=distance)


def ensure(archive: dict, home: str, away: str, day: date | None = None, competition: str = "") -> str:
    """Voce esistente o nuova (es. partita aperta nella pagina Partita senza passare da Oggi)."""
    key = find(archive, home, away, day)
    if key is None:
        day = day or date.today()
        key = key_for(day, home, away)
        archive[key] = new_entry(key, home=home, away=away, commence=datetime.combine(day, datetime.min.time()).isoformat(),
                                 competition=competition)
    return key


# --- Selezione ------------------------------------------------------------------------------------------------

def counts(archive: Mapping) -> tuple[int, int, int, int]:
    """(selezionate, massimo, da giocare, massimo)."""
    max_selected, max_play = limits()
    selected = sum(1 for entry in archive.values() if entry.get("selected"))
    play = sum(1 for entry in archive.values() if entry.get("to_play"))
    return selected, max_selected, play, max_play


def counter_text(archive: Mapping) -> str:
    selected, max_selected, play, _ = counts(archive)
    return f"Selezionate {selected}/{max_selected}, Da giocare {play}/{min(selected, limits()[1]) if selected else limits()[1]}"


def set_selection(archive: dict, key: str, *, selected: bool | None = None, to_play: bool | None = None) -> str | None:
    """Aggiorna la selezione nei limiti di ``config/oggi.json``; restituisce l'avviso se un limite blocca il cambio."""
    entry = archive[key]
    max_selected, max_play = limits()
    if selected is False:
        entry["selected"], entry["to_play"] = False, False
        return None
    if (selected or to_play) and not entry.get("selected"):
        if counts(archive)[0] >= max_selected:
            return f"Massimo {max_selected} partite selezionate: togline una prima di aggiungere {entry['home']} - {entry['away']}."
        entry["selected"] = True
    if to_play is True and not entry.get("to_play"):
        if counts(archive)[2] >= max_play:
            return f"Massimo {max_play} partite «Da giocare»: togline una prima di aggiungere {entry['home']} - {entry['away']}."
        entry["to_play"] = True
    elif to_play is False:
        entry["to_play"] = False
    return None


def select_all(archive: dict, keys: Iterable[str]) -> list[str]:
    """Seleziona le partite indicate finché c'è posto; restituisce le escluse per il limite."""
    skipped = []
    for key in keys:
        if not archive[key].get("selected") and set_selection(archive, key, selected=True):
            skipped.append(key)
    return skipped


def deselect_all(archive: dict) -> None:
    for entry in archive.values():
        entry["selected"], entry["to_play"] = False, False


def selected(archive: Mapping) -> list[dict]:
    return sorted((entry for entry in archive.values() if entry.get("selected")), key=lambda entry: entry.get("commence", ""))


def to_play(archive: Mapping) -> list[dict]:
    return [entry for entry in selected(archive) if entry.get("to_play")]


# --- Quote ------------------------------------------------------------------------------------------------------

def quotes_of(entry: Mapping) -> list[QuoteMercato]:
    return [QuoteMercato.from_dict(item) for item in entry.get("quotes", [])]


def _identity(quote: Mapping) -> tuple:
    return (quote.get("mercato") or f"{quote.get('selezione')}|{quote.get('linea') or ''}", quote.get("bookmaker"))


def add_quotes(archive: dict, key: str, quotes: Iterable[QuoteMercato], *, confirm: bool = False) -> dict[str, int]:
    """Quote nuove nell'archivio: uguali = solo ora aggiornata, nuove = aggiunte, diverse = conflitto da confermare
    (o sostituite con ``confirm``). Restituisce i conteggi."""
    entry = archive[key]
    current = {_identity(item): index for index, item in enumerate(entry["quotes"])}
    result = {"aggiunte": 0, "uguali": 0, "conflitti": 0, "sostituite": 0}
    for quote in quotes:
        item = quote.to_dict()
        index = current.get(_identity(item))
        if index is None:
            entry["quotes"].append(item)
            current[_identity(item)] = len(entry["quotes"]) - 1
            result["aggiunte"] += 1
        elif entry["quotes"][index]["quota"] == item["quota"]:
            entry["quotes"][index]["ora_lettura"] = item["ora_lettura"]
            result["uguali"] += 1
        elif confirm:
            entry["quotes"][index] = item
            result["sostituite"] += 1
        else:
            pending = {"attuale": entry["quotes"][index]["quota"], **item}
            if pending not in entry["pending"]:
                entry["pending"].append(pending)
            result["conflitti"] += 1
    return result


def resolve_pending(archive: dict, key: str, accept: bool, indexes: Iterable[int] | None = None) -> int:
    """Conferma (``accept``) o scarta i conflitti indicati (tutti se ``indexes`` è None)."""
    entry = archive[key]
    chosen = set(range(len(entry["pending"])) if indexes is None else indexes)
    kept, done = [], 0
    for index, item in enumerate(entry["pending"]):
        if index not in chosen:
            kept.append(item)
            continue
        done += 1
        if accept:
            quote = QuoteMercato.from_dict(item)
            add_quotes(archive, key, [quote], confirm=True)
    entry["pending"] = kept
    return done


def consolidated(entry: Mapping) -> dict:
    return consolidate(quotes_of(entry))


def engine_odds(entry: Mapping) -> dict[str, float]:
    """Una quota per mercato del catalogo (sharp se c'è, altrimenti mediana): la stessa in tutta l'app."""
    return {market: item.quota for market, item in consolidated(entry).items()}


def sharp_odds(entry: Mapping) -> dict[str, float] | None:
    """Quote di riferimento dell'API per l'ancoraggio dei gol (1X2 e Over/Under 2.5), come nella fase N3."""
    from eurobet import GOAL_ANCHOR_KEYS

    api = [quote for quote in quotes_of(entry) if quote.fonte == "The Odds API" and quote.mercato in GOAL_ANCHOR_KEYS]
    values = {market: item.quota for market, item in consolidate(api).items()}
    return values or None


def record_manual_odds(archive: dict, key: str, odds: Mapping[str, float]) -> int:
    """Quote scritte a mano (pagina Partita): bookmaker «a mano», scelta esplicita quindi senza conflitto."""
    current = engine_odds(archive[key])
    fresh = [QuoteMercato(f"{archive[key]['home']} - {archive[key]['away']}", market, None, market, float(price),
                          MANUAL_BOOKMAKER, "a mano", now_iso())
             for market, price in odds.items() if price and float(price) > 1.0 and abs(current.get(market, 0) - float(price)) > 1e-9]
    add_quotes(archive, key, fresh, confirm=True)
    return len(fresh)


# --- Pagine incollate -------------------------------------------------------------------------------------

def add_page(archive: dict, key: str, *, text: str, title: str, bookmaker: str, page_format: str,
             replace_bookmaker: bool = False) -> None:
    entry = archive[key]
    if replace_bookmaker:
        entry["pages"] = [page for page in entry["pages"] if page["bookmaker"] != bookmaker]
    page = {"text": text, "title": title, "bookmaker": bookmaker, "format": page_format, "read_at": now_iso()}
    if not any(item["text"] == text and item["bookmaker"] == bookmaker for item in entry["pages"]):
        entry["pages"].append(page)


_PASTES: dict[str, Any] = {}


def eurobet_text(entry: Mapping) -> str:
    return "\n\n".join(page["text"] for page in entry.get("pages", []) if page.get("format") == "eurobet")


def eurobet_paste(entry: Mapping):
    """``EurobetPaste`` delle pagine Eurobet della partita (EV, ancoraggio di corner e cartellini, Combo Builder)."""
    from eurobet import parse_eurobet

    text = eurobet_text(entry)
    if not text.strip():
        return None
    digest = hashlib.sha1(text.encode()).hexdigest()
    if digest not in _PASTES:
        _PASTES[digest] = parse_eurobet(text)
    return _PASTES[digest]


def set_eurobet_text(archive: dict, key: str, text: str) -> None:
    """Incolla della scheda partita: sostituisce le pagine e le quote Eurobet incollate di quella partita."""
    from quotes.adapters.eurobet import BOOKMAKER, from_text

    entry = archive[key]
    entry["pages"] = [page for page in entry["pages"] if page.get("format") != "eurobet"]
    entry["quotes"] = [item for item in entry["quotes"] if not (item["bookmaker"] == BOOKMAKER and item["fonte"] == "incollata")]
    entry["pending"] = [item for item in entry["pending"] if item.get("bookmaker") != BOOKMAKER]
    if text.strip():
        add_page(archive, key, text=text, title=f"{entry['home']} - {entry['away']}", bookmaker=BOOKMAKER, page_format="eurobet")
        quotes, _ = from_text(text, f"{entry['home']} - {entry['away']}")
        add_quotes(archive, key, quotes, confirm=True)


# --- Excel della giornata ---------------------------------------------------------------------------------

def items(archive: Mapping) -> list[dict]:
    return [{"id": key, **entry} for key, entry in archive.items()]


def restore(archive: dict, rows: Iterable[Mapping]) -> None:
    for row in rows:
        entry = {key: value for key, value in row.items() if key != "id"}
        archive[row["id"]] = {**new_entry(row["id"], home=entry.get("home", ""), away=entry.get("away", "")), **entry}


SHEET_COLUMNS = ("Partita", "Competizione", "Ora", "Selezionata", "Da giocare", "Mercato", "Selezione", "Linea", "Quota",
                 "Bookmaker", "Fonte", "Letta")


def sheet_rows(archive: Mapping) -> list[dict]:
    rows = []
    for entry in archive.values():
        base = {"Partita": f"{entry['home']} - {entry['away']}", "Competizione": entry.get("competition", ""),
                "Ora": entry.get("commence", "")[:16].replace("T", " "), "Selezionata": "sì" if entry.get("selected") else "",
                "Da giocare": "sì" if entry.get("to_play") else ""}
        quotes = entry.get("quotes") or [{}]
        for quote in quotes:
            rows.append({**base, "Mercato": quote.get("mercato") or ("non simulato" if quote else ""),
                         "Selezione": quote.get("selezione", ""), "Linea": quote.get("linea") or "",
                         "Quota": quote.get("quota"), "Bookmaker": quote.get("bookmaker", ""),
                         "Fonte": quote.get("fonte", ""), "Letta": quote.get("ora_lettura", "")})
    return rows
