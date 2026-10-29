"""Cronometro per fase del flusso dati di «Analizza tutte» (fase V).

- ``fase("simulazione")``: contesto che somma i secondi della fase nel registratore attivo;
- ``SourceCache.get`` registra da solo, per fonte, le richieste HTTP, gli hit di cache e i secondi passati in
  rete e in pausa (``MIN_INTERVAL``).

Il registratore è per thread (``registra()`` lo attiva e lo restituisce); senza registratore attivo non si
misura nulla, quindi il resto dell'app non cambia. Thread-safe: più thread possono scrivere nello stesso.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
import threading
import time
from typing import Iterator


@dataclass
class Registro:
    seconds: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    requests: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cache_hits: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    parents: set[str] = field(default_factory=set)   # fasi che contengono altre fasi: non entrano nella somma
    network_seconds: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    pause_seconds: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, phase: str, seconds: float) -> None:
        with self._lock:
            self.seconds[phase] += seconds

    def http(self, source: str, *, hit: bool, network: float = 0.0, pause: float = 0.0, error: bool = False) -> None:
        with self._lock:
            if hit:
                self.cache_hits[source] += 1
            else:
                self.requests[source] += 1
                self.errors[source] += int(error)
                self.network_seconds[source] += network
                self.pause_seconds[source] += pause

    def sources(self) -> list[dict]:
        """Per fonte: richieste HTTP fatte, hit di cache, errori, secondi (rete e pause)."""
        return [{"Fonte": source, "Richieste HTTP": self.requests.get(source, 0), "Hit di cache": self.cache_hits.get(source, 0),
                 "Errori": self.errors.get(source, 0),
                 "Secondi": round(self.network_seconds.get(source, 0.0) + self.pause_seconds.get(source, 0.0), 2)}
                for source in sorted(set(self.requests) | set(self.cache_hits))]

    def breakdown(self, total: float) -> list[dict]:
        """Fasi che sommano al totale: le fasi «foglia» (senza quelle che ne contengono altre), una riga «altro» per
        il resto e il totale dell'ultimo giro."""
        leaves = {name: value for name, value in self.seconds.items() if name not in self.parents}
        rows = [{"Fase": name, "Secondi": round(value, 2)} for name, value in leaves.items()]
        rest = total - sum(leaves.values())
        rows.append({"Fase": "altro (cicli, tabelle)", "Secondi": round(max(rest, 0.0), 2)})
        rows.append({"Fase": "TOTALE", "Secondi": round(total, 2)})
        return rows

    def rows(self) -> list[dict]:
        """Tabella fase/secondi/richieste HTTP/hit di cache: prima le fasi, poi le fonti."""
        rows = [{"Fase": name, "Secondi": round(value, 2), "Richieste HTTP": None, "Hit di cache": None}
                for name, value in self.seconds.items()]
        for source in sorted(set(self.requests) | set(self.cache_hits)):
            rows.append({"Fase": f"fonte: {source}",
                         "Secondi": round(self.network_seconds.get(source, 0.0) + self.pause_seconds.get(source, 0.0), 2),
                         "Richieste HTTP": self.requests.get(source, 0), "Hit di cache": self.cache_hits.get(source, 0)})
        return rows


_local = threading.local()
_shared: list[Registro | None] = [None]   # visibile anche ai thread del pool, finché la registrazione è attiva


def attivo() -> Registro | None:
    return getattr(_local, "registro", None) or _shared[0]


@contextmanager
def registra() -> Iterator[Registro]:
    """Attiva un registratore per il blocco (anche per i thread avviati dentro il blocco)."""
    registro, previous = Registro(), _shared[0]
    _local.registro, _shared[0] = registro, registro
    try:
        yield registro
    finally:
        _local.registro, _shared[0] = None, previous


@contextmanager
def fase(name: str, *, contiene_fasi: bool = False) -> Iterator[None]:
    """Cronometra la fase; ``contiene_fasi`` per quelle che racchiudono altre fasi (non contano due volte nel totale)."""
    start = time.perf_counter()
    try:
        yield
    finally:
        registro = attivo()
        if registro is not None:
            registro.add(name, time.perf_counter() - start)
            if contiene_fasi:
                registro.parents.add(name)
