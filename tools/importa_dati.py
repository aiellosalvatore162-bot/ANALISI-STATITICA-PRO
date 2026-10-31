"""Fase AN: importa un CSV di dati nuovi (stile, giocatori, formazioni, arbitri, quote) nella cache dell'app.

Uso: ``python -m tools.importa_dati <file> [--fonte NOME] [--scegli "Nome nel file=Nome app"]... [--non-interattivo]``.
I nomi squadra non abbinati vengono elencati e si chiede di scegliere: nessun abbinamento dubbio è fatto in automatico.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import data_import


def ask(name: str, suggestion: str | None, similar: list[str]) -> str | None:
    print(f"\nNome squadra non abbinato: «{name}»")
    options = [suggestion, *[s for s in similar if s != suggestion]] if suggestion else list(similar)
    for position, option in enumerate(options[:6], start=1):
        print(f"  {position}) {option}{'  (suggerito)' if option == suggestion else ''}")
    answer = input("Numero, nome esatto dell'app, oppure invio per scartare le righe: ").strip()
    if not answer:
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(options[:6]):
        return options[int(answer) - 1]
    return answer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--fonte", help="nome della fonte (default: nome del file)")
    parser.add_argument("--scegli", action="append", default=[], help='abbinamento già deciso: "Nome nel file=Nome app"')
    parser.add_argument("--non-interattivo", action="store_true", help="i nomi non abbinati vengono scartati senza domande")
    args = parser.parse_args(argv)
    mapping = dict(item.split("=", 1) for item in args.scegli if "=" in item)
    chooser = None if args.non_interattivo or not sys.stdin.isatty() else ask
    report = data_import.import_file(args.file, source=args.fonte, chooser=chooser, mapping=mapping)
    if report.error:
        print(f"Importazione non riuscita: {report.error}")
        return 1
    print(f"\nTipo: {report.kind} · fonte: {report.source}")
    print(f"Righe importate: {report.imported} · scartate: {report.discarded} · doppioni nel file: {report.duplicates}")
    if report.unmatched:
        print("Nomi non abbinati (righe scartate): " + ", ".join(report.unmatched))
    for reason in report.reasons[:15]:
        print("  -", reason)
    print("\nControllo rapido consigliato (non lanciato da solo; 1 stagione, 3 campionati, ~minuti):")
    print(f"  python -m tools.confronto_dati --tipo {report.kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
