"""Screenshot della dashboard con Playwright (solo sviluppo, non serve all'app).

Avvia l'app in modalità headless, inserisce una partita d'esempio con quote,
esegue la simulazione e salva ogni tab in desktop e mobile, tema chiaro e
scuro, in ``docs/screenshot/``. Uso: ``python -m tools.screenshots``; con
``--oggi`` la pagina «Oggi» della demo ``tools/demo_oggi.py`` (quote registrate,
dati reali delle fonti gratuite) in desktop chiaro e scuro (richiede ``pip install playwright`` e ``python -m playwright install chromium``).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "screenshot"
TABS = ("Panoramica", "Gol", "Corner e cartellini", "Risultati esatti", "Claude", "Registro", "Prestazioni")
SLUGS = ("panoramica", "gol", "corner-cartellini", "risultati-esatti", "claude", "registro", "prestazioni")
DEVICES = {"desktop": {"width": 1366, "height": 900}, "mobile": {"width": 390, "height": 844}}
BLOCK = """CASA: Inter
Attacco: 1.34 | Difesa: 1.25 | Elo: 1835 | Forma: W-W-D-W-W | xG Fatti: 2.15 | xG Subiti: 0.85 | Corner pro/sub: 5.8/4.2 | Cartellini pro: 1.60

OSPITE: Milan
Attacco: 1.22 | Difesa: 1.10 | Elo: 1765 | Forma: W-W-L-D-W | xG Fatti: 1.85 | xG Subiti: 1.10 | Corner pro/sub: 5.1/4.8 | Cartellini pro: 1.85

ARBITRO: Gialli medi 4.5 | Falli medi 24

QUOTE_MERCATI_PRINCIPALI:
Quota 1: 2.05 | Quota X: 3.50 | Quota 2: 3.60 | Quota Over 2.5: 1.75 | Quota Under 2.5: 2.10
"""


def _wait_for_server(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/_stcore/health", timeout=2) as response:
                if response.read() == b"ok":
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("L'app non si è avviata in tempo.")


def _wait_idle(page, timeout: float = 120_000) -> None:
    """Attende che Streamlit finisca di eseguire lo script (niente indicatore «Running»)."""
    page.wait_for_timeout(600)
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"stStatusWidget\"]') || "
        "!document.querySelector('[data-testid=\"stStatusWidget\"]').innerText.includes('Running')",
        timeout=timeout,
    )
    page.wait_for_timeout(500)


def _settle(page, rounds: int = 20) -> None:
    """Attende che l'altezza della pagina resti uguale per tre controlli di fila (rerun finiti)."""
    _wait_idle(page)
    last, stable = -1, 0
    for _ in range(rounds):
        height = page.evaluate("() => document.querySelector('[data-testid=\"stMain\"]').scrollHeight")
        stable = stable + 1 if height == last else 0
        if stable >= 2:
            return
        last = height
        page.wait_for_timeout(700)


def _prepare(page) -> None:
    page.get_by_role("textbox", name="Blocco CASA / OSPITE / ARBITRO").fill(BLOCK)
    page.keyboard.press("Control+Enter")
    _wait_idle(page)
    page.get_by_role("spinbutton", name="Simulazioni Monte Carlo").fill("50000")
    page.keyboard.press("Enter")
    _wait_idle(page)
    page.get_by_role("button", name="Esegui simulazione").click()
    _wait_idle(page)


def _choose_group(page) -> None:
    box = page.get_by_role("combobox", name="Risultati del gruppo")
    for score in ("1-0", "2-0", "2-1", "1-1"):
        box.click()
        page.keyboard.type(score)
        page.get_by_role("option", name=score, exact=True).click()
        _wait_idle(page)
    page.keyboard.press("Escape")
    page.get_by_role("spinbutton", name="Quota offerta (es. Eurobet) per questa combinazione").fill("1.60")
    page.keyboard.press("Enter")
    _wait_idle(page)


def capture(url: str, only: set[str] | None = None) -> list[Path]:
    from playwright.sync_api import sync_playwright

    OUTPUT.mkdir(parents=True, exist_ok=True)
    saved = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for theme in ("light", "dark"):
            for device, viewport in DEVICES.items():
                context = browser.new_context(viewport=viewport, color_scheme=theme, device_scale_factor=1,
                                              is_mobile=device == "mobile", has_touch=device == "mobile")
                page = context.new_page()
                page.goto(url, wait_until="networkidle")
                _wait_idle(page)
                _prepare(page)
                for tab, slug in zip(TABS, SLUGS):
                    if only and slug not in only:
                        continue
                    page.get_by_role("tab", name=tab, exact=True).click()
                    _wait_idle(page)
                    if slug == "risultati-esatti":
                        _choose_group(page)
                    if slug == "prestazioni":
                        page.locator("input[type=file][accept*=xlsx]").set_input_files(str(ROOT / "tests" / "fixtures" / "registro_esempio.xlsx"))
                        _wait_idle(page)
                    _settle(page)
                    path = OUTPUT / f"{slug}_{device}_{'chiaro' if theme == 'light' else 'scuro'}.png"
                    # La pagina di Streamlit scorre dentro il contenitore principale: si allunga la vista per catturarla
                    # tutta e si ritaglia dalla barra delle tab in giù (l'input sta sopra).
                    height = page.evaluate("() => document.querySelector('[data-testid=\"stMain\"]').scrollHeight")
                    page.set_viewport_size({"width": viewport["width"], "height": min(int(height) + 40, 12000)})
                    page.wait_for_timeout(600)
                    top = page.get_by_role("tab", name="Panoramica", exact=True).bounding_box()["y"] - 12
                    full = page.evaluate("() => document.documentElement.scrollHeight")
                    page.screenshot(path=str(path), full_page=True,
                                    clip={"x": 0, "y": top, "width": viewport["width"], "height": max(200, full - top)})
                    page.set_viewport_size(viewport)
                    saved.append(path)
                context.close()
        browser.close()
    return saved


def capture_oggi(url: str) -> list[Path]:
    """Pagina «Oggi» (layout per computer): cerca le partite, «Analizza tutte», multipla lunga."""
    from playwright.sync_api import sync_playwright

    OUTPUT.mkdir(parents=True, exist_ok=True)
    saved = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for theme in ("light", "dark"):
            viewport = {"width": 1600, "height": 1000}
            context = browser.new_context(viewport=viewport, color_scheme=theme, device_scale_factor=1)
            page = context.new_page()
            page.goto(url, wait_until="networkidle")
            _wait_idle(page)
            page.get_by_role("button", name="Cerca le partite del giorno (gratis)").click()
            _wait_idle(page)
            confirm = page.get_by_text("Confermo la spesa di")
            if confirm.count():  # con le quote già in cache il costo è 0 e non c'è conferma
                confirm.first.click()
                _wait_idle(page)
            page.get_by_role("button", name="Analizza tutte").click()
            # La prima volta i dati delle squadre si scaricano tutti: può volerci qualche minuto.
            page.get_by_text("Costruttore di multiple").wait_for(timeout=1_200_000)
            _wait_idle(page, timeout=600_000)
            page.get_by_role("tab", name="Multipla lunga (12-13)").click()
            _settle(page)
            height = page.evaluate("() => document.querySelector('[data-testid=\"stMain\"]').scrollHeight")
            page.set_viewport_size({"width": viewport["width"], "height": min(int(height) + 40, 14000)})
            page.wait_for_timeout(800)
            path = OUTPUT / f"oggi_desktop_{'chiaro' if theme == 'light' else 'scuro'}.png"
            page.screenshot(path=str(path), full_page=True)
            saved.append(path)
            context.close()
        browser.close()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8591)
    parser.add_argument("--solo", nargs="*", help="Solo queste tab (slug), es. panoramica gol")
    parser.add_argument("--oggi", action="store_true", help="Solo la pagina «Oggi» della demo con quote registrate")
    args = parser.parse_args()
    env = {**os.environ, "SIMULPRO_CACHE_DB": str(ROOT / "data" / "cache" / "screenshot.sqlite")}
    entry = ROOT / "tools" / "demo_oggi.py" if args.oggi else ROOT / "streamlit_app.py"
    server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(entry), "--server.headless", "true",
                               "--server.port", str(args.port), "--browser.gatherUsageStats", "false"],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f"http://localhost:{args.port}"
        _wait_for_server(url)
        for path in (capture_oggi(url) if args.oggi else capture(url, set(args.solo) if args.solo else None)):
            print(path.relative_to(ROOT))
    finally:
        server.terminate()
        server.wait(timeout=20)


if __name__ == "__main__":
    main()
