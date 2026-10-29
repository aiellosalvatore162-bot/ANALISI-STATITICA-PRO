"""Fase V: misura dei tempi di «Analizza tutte» su una giornata fissa di 13 partite in 4 campionati.

Stesso percorso della pagina Oggi (``today.analyze`` con ``DataProvider.build`` e la simulazione), senza quote
The Odds API (nessun credito): le partite si simulano con il solo modello. Due passate sulla stessa cache SQLite:
«cache vuota» (database nuovo, tutto dalla rete) e «cache calda» (stesso database, subito dopo).

- ``--offline``: nessuna rete, solo il database indicato con ``--db`` (già riempito da una passata in linea);
  utile per ripetere la cache calda senza toccare le fonti.
- ``--output docs/bench/oggi_prima.md``: tabella per fase (secondi, richieste HTTP, hit di cache) e tempi per
  partita.

Uso: ``python -m tools.bench_oggi --output docs/bench/oggi_prima.md``.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import time

GIORNATA = (  # partite giocate il 24-26/10/2026: dati «alla data della partita», lista fissa per prima/dopo
    ("Serie A", "2026-10-24", "Napoli", "Roma"), ("Serie A", "2026-10-24", "Lazio", "Parma"),
    ("Serie A", "2026-10-25", "Inter", "Fiorentina"), ("Serie A", "2026-10-25", "Genoa", "Venezia"),
    ("Premier League", "2026-10-24", "Arsenal", "Everton"), ("Premier League", "2026-10-24", "Chelsea", "Tottenham"),
    ("Premier League", "2026-10-25", "Liverpool", "Brighton"),
    ("La Liga", "2026-10-25", "Barcelona", "Real Madrid"), ("La Liga", "2026-10-24", "Valencia", "Villarreal"),
    ("La Liga", "2026-10-25", "Celta", "Betis"),
    ("Bundesliga", "2026-10-24", "Dortmund", "Ein Frankfurt"), ("Bundesliga", "2026-10-25", "Freiburg", "Bayern Munich"),
    ("Bundesliga", "2026-10-25", "Hoffenheim", "Leverkusen"),
)


def _offline_opener(url, headers, timeout):
    raise ConnectionError("modalità offline: nessuna rete")


def _without_clubelo(url, headers, timeout):
    """ClubElo escluso senza contattarlo (oggi risponde 403 Cloudflare): misura il resto del percorso."""
    from datasources.cache import _requests_opener

    if "clubelo.com" in url:
        raise ConnectionError("ClubElo escluso dalla misura")
    return _requests_opener(url, headers, timeout)


def run(db: Path, *, offline: bool, simulations: int, limit: int | None = None, clubelo: bool = True) -> dict:
    from datasources.builder import DataProvider
    from datasources.cache import SourceCache
    from timing import fase, registra
    from today import TodayMatch, analyze

    from datasources.cache import MIN_INTERVAL

    opener = _offline_opener if offline else (None if clubelo else _without_clubelo)
    cache = SourceCache(db, opener=opener, min_interval=None if clubelo else {**MIN_INTERVAL, "clubelo": 0.0})
    provider = DataProvider(cache, football_data_key="")
    per_match = []
    with registra() as registro:
        start = time.perf_counter()
        for index, (competition, day, home, away) in enumerate(GIORNATA[:limit]):
            match = TodayMatch(f"bench{index}", "", competition,
                               datetime.fromisoformat(f"{day}T15:00").replace(tzinfo=timezone.utc), home, away)
            began = time.perf_counter()
            analysis = analyze(match, provider.build, {}, simulations=simulations, competition=competition)
            per_match.append({"Partita": f"{home} - {away}", "Secondi": round(time.perf_counter() - began, 2),
                              "Esito": "simulata" if analysis.ok else f"saltata: {analysis.skipped}"})
        with fase("totale"):
            pass
        total = time.perf_counter() - start
    return {"totale": total, "fasi": registro.rows(), "partite": per_match}


def render(label: str, result: dict) -> list[str]:
    lines = [f"### {label}: {result['totale']:.1f} s per {len(result['partite'])} partite", "",
             "| Fase | Secondi | Richieste HTTP | Hit di cache |", "|---|---|---|---|"]
    for row in result["fasi"]:
        if row["Fase"] == "totale":
            continue
        lines.append(f"| {row['Fase']} | {row['Secondi']:.2f} | {row['Richieste HTTP'] if row['Richieste HTTP'] is not None else ''} | "
                     f"{row['Hit di cache'] if row['Hit di cache'] is not None else ''} |")
    lines += ["", "| Partita | Secondi | Esito |", "|---|---|---|"]
    lines += [f"| {row['Partita']} | {row['Secondi']:.2f} | {row['Esito']} |" for row in result["partite"]]
    return lines + [""]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, help="database della cache (default: nuovo file temporaneo)")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--simulazioni", type=int, default=30_000)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--titolo", default="Analizza tutte")
    parser.add_argument("--partite", type=int, help="solo le prime N partite della giornata")
    parser.add_argument("--senza-clubelo", action="store_true", help="ClubElo escluso senza richieste (risponde 403)")
    args = parser.parse_args()
    db = args.db or Path(tempfile.mkdtemp(prefix="bench_oggi_")) / "cache.sqlite"
    sections = []
    if not args.offline:
        sections.append(("Cache vuota", run(db, offline=False, simulations=args.simulazioni, limit=args.partite,
                                            clubelo=not args.senza_clubelo)))
    sections.append(("Cache calda" + (" (offline)" if args.offline else ""), run(db, offline=args.offline,
                                                                                 simulations=args.simulazioni, limit=args.partite,
                                                                                 clubelo=not args.senza_clubelo)))
    lines = [f"## {args.titolo} · {date.today():%d/%m/%Y}", "",
             f"Comando: `python -m tools.bench_oggi{' --offline' if args.offline else ''}`. Giornata fissa di "
             f"{len(GIORNATA[:args.partite])} partite (Serie A, Premier League, La Liga, Bundesliga, 24-26/10/2026), "
             f"{args.simulazioni:,} simulazioni per partita, nessuna quota The Odds API. Database: `{db}`.".replace(",", "."),
             ""]
    for label, result in sections:
        lines += render(label, result)
    markdown = "\n".join(lines)
    print(markdown)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
