"""Dashboard a tema calcio: HTML/CSS delle schede, solo presentazione (nessun calcolo del modello).

Ogni funzione restituisce HTML statico, senza JavaScript. Tutti i testi che
vengono da dati esterni (nomi delle squadre, mercati, note) passano da
``esc``. I numeri arrivano già calcolati dal risultato di ``simulate_match``.

Colori dei dati (validati con lo script della skill dataviz, tema chiaro e
scuro): Casa blu e Ospite arancio superano tutti i controlli; il Pareggio è un
grigio neutro voluto, sempre accompagnato dall'etichetta di testo. Il semaforo
del valore usa i colori di stato con icona e testo, mai il solo colore.
"""

from __future__ import annotations

import html
from typing import Iterable, Mapping, Sequence

GOOGLE_FONTS = "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600;700&display=swap"

GLOSSARY = {
    "EV": "Valore atteso: quanto rende in media 1 € puntato a quella quota secondo il modello. Positivo = conveniente.",
    "CLV": "Closing Line Value: quota presa / quota di chiusura − 1. Positivo = hai battuto il mercato prima del fischio.",
    "Brier": "Errore medio al quadrato tra probabilità e risultato (0 = perfetto). Più basso è meglio.",
    "Ancoraggio": "I gol attesi del modello sono avvicinati a quelli impliciti nelle quote 1X2 e Over/Under 2.5.",
    "Confidenza": "Quanto è netto il favorito (probabilità del segno più probabile). Non misura se il modello ha ragione.",
    "Quota equa": "La quota senza margine del bookmaker: 1 / probabilità.",
}

LIGHT = {
    "page": "#eef3ef", "surface": "#ffffff", "surface-2": "#f5f8f5", "ink": "#0b1a12", "ink-2": "#33463a",
    "muted": "#55675c", "border": "rgba(11,26,18,.14)", "pitch": "#14532d", "pitch-2": "#1d6b3c",
    "pitch-ink": "#f4faf5", "field-line": "rgba(20,83,45,.07)", "home": "#2a78d6", "away": "#eb6834", "draw": "#7c8580",
    "good": "#0ca30c", "good-ink": "#006300", "bad": "#d03b3b", "bad-ink": "#a32020", "neutral": "#7c8580",
    "accent": "#b45309", "track": "#e3eae4", "fifty": "#0b1a12", "tab-on": "#14532d",
}
DARK = {
    "page": "#07120c", "surface": "#10221a", "surface-2": "#163024", "ink": "#eef5ef", "ink-2": "#cbd8ce",
    "muted": "#a3b5a8", "border": "rgba(255,255,255,.13)", "pitch": "#0d3a22", "pitch-2": "#145230",
    "pitch-ink": "#f4faf5", "field-line": "rgba(255,255,255,.05)", "home": "#3987e5", "away": "#d95926", "draw": "#8d9690",
    "good": "#0ca30c", "good-ink": "#4cd04c", "bad": "#e66767", "bad-ink": "#ff9a9a", "neutral": "#8d9690",
    "accent": "#f2b544", "track": "#24392c", "fifty": "#eef5ef", "tab-on": "#4cd04c",
}
# Mappa di calore dei risultati esatti: un solo tono (blu), dal fondo della scheda al pieno.
HEAT = {"light": ("#ffffff", "#1c5cab"), "dark": ("#10221a", "#5598e7")}

# Colori sociali (prima, seconda); niente stemmi. Le squadre non in elenco ricevono colori neutri stabili.
TEAM_COLORS = {
    "inter": ("#0068a8", "#111111"), "milan": ("#d7141a", "#111111"), "juventus": ("#111111", "#ffffff"),
    "napoli": ("#1b8fd2", "#ffffff"), "roma": ("#8e1f2f", "#f0bc42"), "lazio": ("#87d8f7", "#ffffff"),
    "atalanta": ("#1e71b8", "#111111"), "fiorentina": ("#6a2c91", "#ffffff"), "bologna": ("#a21c26", "#1a2f48"),
    "torino": ("#8a1e03", "#ffffff"), "genoa": ("#a51d2d", "#002d62"), "udinese": ("#111111", "#ffffff"),
    "como": ("#1f4e8c", "#ffffff"), "parma": ("#fcd116", "#1b3e8f"), "cagliari": ("#a6192e", "#002350"),
    "lecce": ("#f6d200", "#c8102e"), "monza": ("#e2001a", "#ffffff"), "venezia": ("#ff7f00", "#0b6e34"),
    "sassuolo": ("#00a752", "#111111"), "verona": ("#fdd400", "#002f6c"), "empoli": ("#005fa9", "#ffffff"),
    "frosinone": ("#ffd700", "#0047ab"), "cremonese": ("#cc0000", "#9c9c9c"), "pisa": ("#111111", "#0b3d91"),
    "sampdoria": ("#1b5497", "#ffffff"), "real madrid": ("#ffffff", "#febe10"), "barcellona": ("#a50044", "#004d98"),
    "barcelona": ("#a50044", "#004d98"), "atletico": ("#cb3524", "#272e61"), "manchester city": ("#6cabdd", "#1c2c5b"),
    "city": ("#6cabdd", "#1c2c5b"), "manchester united": ("#da291c", "#111111"), "liverpool": ("#c8102e", "#00b2a9"),
    "arsenal": ("#ef0107", "#ffffff"), "chelsea": ("#034694", "#ffffff"), "tottenham": ("#ffffff", "#132257"),
    "bayern": ("#dc052d", "#ffffff"), "dortmund": ("#fde100", "#111111"), "psg": ("#004170", "#da291c"),
    "paris": ("#004170", "#da291c"), "benfica": ("#e83030", "#ffffff"), "porto": ("#00428c", "#ffffff"),
    "sporting": ("#008057", "#ffffff"), "ajax": ("#d2122e", "#ffffff"), "psv": ("#ed1c24", "#ffffff"),
    "bodo": ("#ffd100", "#111111"), "bodø": ("#ffd100", "#111111"),
}
_STOP = {"fc", "ac", "as", "ssc", "cf", "afc", "sc", "us", "ss", "calcio", "club", "de", "del", "la", "1909", "1907"}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}%"


def odd(value: float | None) -> str:
    return "—" if value is None else f"{float(value):.2f}"


def out_of_ten(percentage: float) -> int:
    return int(round(float(percentage) / 10.0))


def term(label: str, key: str | None = None) -> str:
    """Etichetta con tooltip del glossario."""
    tip = GLOSSARY.get(key or label)
    return f'<abbr class="term" title="{esc(tip)}">{esc(label)}</abbr>' if tip else esc(label)


# --- Tema ---------------------------------------------------------------------------------------

def _tokens(values: Mapping[str, str]) -> str:
    """Token CSS più il colore del testo leggibile sopra i colori dei dati (Casa, Pareggio, Ospite)."""
    derived = {f"{name}-on": readable_ink(values[name]) for name in ("home", "draw", "away")}
    return " ".join(f"--{name}: {value};" for name, value in {**values, **derived}.items())


def theme_css(theme: str | None) -> str:
    """CSS dell'app. ``theme`` = tema Streamlit noto ("light"/"dark"), altrimenti segue il sistema."""
    if theme in ("light", "dark"):
        tokens = f":root {{ {_tokens(DARK if theme == 'dark' else LIGHT)} }}"
    else:
        tokens = f":root {{ {_tokens(LIGHT)} }} @media (prefers-color-scheme: dark) {{ :root {{ {_tokens(DARK)} }} }}"
    return f"""<style>
@import url('{GOOGLE_FONTS}');
{tokens}
html, body, [class*="css"], .stApp {{ font-family: 'Barlow', system-ui, sans-serif; }}
.stApp {{ background: var(--page); color: var(--ink); }}
h1, h2, h3 {{ font-family: 'Barlow Condensed', 'Barlow', sans-serif !important; letter-spacing: .01em; color: var(--ink); }}
p, li, label, [data-testid="stCaptionContainer"] {{ color: var(--ink-2); }}
[data-testid="stCaptionContainer"] {{ opacity: 1 !important; }}
[data-testid="stCaptionContainer"] {{ opacity: 1 !important; }}
[data-testid="stCaptionContainer"] p {{ color: var(--muted); }}
.block-container {{ max-width: 1280px; padding-top: 1rem; padding-bottom: 4rem; }}
.stButton > button, .stDownloadButton > button {{ min-height: 44px; border-radius: 8px; font-weight: 600; }}
.stButton > button[kind="primary"] {{ background: var(--pitch-2); border-color: var(--pitch-2); color: var(--pitch-ink); }}
.stButton > button[kind="primary"] p {{ color: var(--pitch-ink) !important; font-size: 1.05rem; }}
[data-baseweb="tab-list"] {{ gap: .25rem; flex-wrap: wrap; border-bottom: 2px solid var(--border); }}
[data-baseweb="tab"] {{ min-height: 44px; padding: 0 .8rem; font-family: 'Barlow Condensed', sans-serif; font-size: 1.05rem; font-weight: 600; }}
[aria-selected="true"][data-baseweb="tab"] {{ color: var(--tab-on) !important; }}
abbr.term {{ text-decoration: underline dotted; text-underline-offset: 3px; cursor: help; }}
.hero {{ position: relative; overflow: hidden; border-radius: 14px; padding: 18px 22px; margin: 0 0 14px;
  color: var(--pitch-ink); background-color: var(--pitch);
  background-image:
    radial-gradient(circle at 50% 50%, transparent 46px, rgba(255,255,255,.22) 47px, rgba(255,255,255,.22) 49px, transparent 50px),
    linear-gradient(90deg, transparent calc(50% - 1px), rgba(255,255,255,.22) calc(50% - 1px), rgba(255,255,255,.22) calc(50% + 1px), transparent calc(50% + 1px)),
    repeating-linear-gradient(90deg, rgba(255,255,255,.035) 0 60px, transparent 60px 120px); }}
.hero h1 {{ color: var(--pitch-ink) !important; margin: 0 !important; font-size: 2.1rem !important; }}
.hero p {{ color: rgba(244,250,245,.88); margin: .2rem 0 0; font-size: .95rem; }}
.hero .kicker {{ font: 600 .78rem 'Barlow', sans-serif; letter-spacing: .12em; text-transform: uppercase; color: rgba(244,250,245,.8); }}
.dash-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 14px; margin: 6px 0 14px; align-items: start; }}
.dash-grid.wide {{ grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); }}
.card {{ position: relative; background-color: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 16px 18px 14px; color: var(--ink); overflow: hidden;
  background-image:
    radial-gradient(circle at 100% 50%, transparent 54px, var(--field-line) 55px, var(--field-line) 57px, transparent 58px),
    linear-gradient(90deg, transparent calc(100% - 2px), var(--field-line) calc(100% - 2px)),
    linear-gradient(0deg, transparent calc(100% - 2px), var(--field-line) calc(100% - 2px)); }}
.card .head {{ display: flex; align-items: center; gap: 8px; color: var(--ink-2); font: 700 1.02rem 'Barlow Condensed', sans-serif;
  letter-spacing: .06em; text-transform: uppercase; }}
.card .head svg {{ width: 22px; height: 22px; flex: none; }}
.card .big {{ font: 700 2.6rem/1.05 'Barlow Condensed', sans-serif; color: var(--ink); margin: 8px 0 2px; }}
.card .big small {{ font-size: 1rem; color: var(--muted); font-weight: 600; margin-left: 6px; }}
.card .say {{ font-size: 1rem; line-height: 1.4; color: var(--ink); margin: 6px 0 10px; }}
.card .note {{ font-size: .82rem; color: var(--muted); margin-top: 8px; }}
.pill {{ display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 4px 10px; font: 700 .74rem 'Barlow', sans-serif;
  letter-spacing: .06em; text-transform: uppercase; border: 1px solid var(--border); background: var(--surface-2); color: var(--ink); }}
.pill.on {{ border-color: var(--good); }} .pill.off {{ border-color: var(--neutral); }}
.pill .dot {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; }}
.board {{ background: var(--pitch); color: var(--pitch-ink); border-radius: 14px; padding: 16px 18px; border: 1px solid var(--border);
  background-image: linear-gradient(90deg, transparent calc(50% - 1px), rgba(255,255,255,.16) calc(50% - 1px), rgba(255,255,255,.16) calc(50% + 1px), transparent calc(50% + 1px)); }}
.board .row {{ display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 10px; }}
.board .team {{ display: flex; align-items: center; gap: 10px; min-width: 0; }}
.board .team.away {{ flex-direction: row-reverse; text-align: right; }}
.board .name {{ font: 700 1.35rem/1.1 'Barlow Condensed', sans-serif; overflow-wrap: anywhere; }}
.board .xg {{ font-size: .85rem; color: rgba(244,250,245,.85); }}
.board .score {{ font: 700 2.8rem/1 'Barlow Condensed', sans-serif; background: rgba(0,0,0,.28); border-radius: 10px; padding: 6px 14px;
  font-variant-numeric: tabular-nums; letter-spacing: .04em; }}
.board .under {{ display: flex; flex-wrap: wrap; gap: 8px 16px; justify-content: space-between; margin-top: 12px; font-size: .9rem; color: rgba(244,250,245,.92); }}
.board .pill {{ background: rgba(0,0,0,.25); color: var(--pitch-ink); border-color: rgba(255,255,255,.35); }}
.badge {{ width: 46px; height: 46px; border-radius: 50%; display: grid; place-items: center; flex: none;
  font: 700 1rem 'Barlow Condensed', sans-serif; letter-spacing: .03em; border: 3px solid; box-shadow: 0 0 0 2px rgba(255,255,255,.55); }}
.split {{ display: flex; height: 38px; border-radius: 8px; overflow: hidden; gap: 2px; background: var(--surface); }}
.split > div {{ display: flex; align-items: center; justify-content: center; min-width: 34px; color: #fff;
  font: 700 1.2rem 'Barlow Condensed', sans-serif; white-space: nowrap; }}
.split .s1 {{ background: var(--home); color: var(--home-on); }} .split .sx {{ background: var(--draw); color: var(--draw-on); }}
.split .s2 {{ background: var(--away); color: var(--away-on); }}
.split-legend {{ display: flex; justify-content: space-between; gap: 8px; font-size: .86rem; color: var(--ink-2); margin-top: 6px; }}
.split-legend b {{ color: var(--ink); }}
.bars {{ display: grid; gap: 7px; margin-top: 6px; }}
.bar {{ display: grid; grid-template-columns: minmax(84px, 34%) 1fr 54px; align-items: center; gap: 8px; font-size: .9rem; }}
.bar .label {{ color: var(--ink); font-weight: 600; overflow-wrap: anywhere; }}
.bar .track {{ position: relative; height: 14px; background: var(--track); border-radius: 4px; }}
.bar .fill {{ position: absolute; inset: 0 auto 0 0; background: var(--home); border-radius: 0 4px 4px 0; }}
.bar .fill.alt {{ background: var(--away); }}
.bar .fifty {{ position: absolute; top: -3px; bottom: -3px; left: 50%; width: 2px; background: var(--fifty); opacity: .55; }}
.bar .value {{ text-align: right; font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; }}
.bar.chosen .label::after {{ content: "  ◆ consigliata"; color: var(--accent); font-size: .78rem; font-weight: 700; }}
.lights {{ display: grid; gap: 8px; }}
.light {{ display: grid; grid-template-columns: 22px 1fr; gap: 2px 8px; align-items: center; padding: 8px 10px; border-radius: 10px;
  background: var(--surface-2); border: 1px solid var(--border); }}
.light .lamp {{ width: 16px; height: 16px; border-radius: 50%; box-shadow: 0 0 0 3px rgba(0,0,0,.08); }}
.light.green .lamp {{ background: var(--good); }} .light.grey .lamp {{ background: var(--neutral); }} .light.red .lamp {{ background: var(--bad); }}
.light .what {{ font-weight: 600; color: var(--ink); overflow-wrap: anywhere; }}
.light .verdict {{ grid-column: 2; font-weight: 700; font-size: .9rem; }}
.light.green .verdict {{ color: var(--good-ink); }} .light.red .verdict {{ color: var(--bad-ink); }} .light.grey .verdict {{ color: var(--ink-2); }}
.brief {{ margin-bottom: 14px; border-left: 5px solid var(--pitch-2); }}
.brief-list {{ margin: 8px 0 0 1.1rem; padding: 0; display: grid; gap: 6px; }}
.brief-list li {{ color: var(--ink); font-size: 1.02rem; line-height: 1.45; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: .86rem; color: var(--ink-2); margin: 4px 0 12px; }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.legend i {{ width: 14px; height: 14px; border-radius: 3px; display: inline-block; }}
.picks {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
.pick {{ background: var(--surface-2); border: 1px solid var(--border); border-left: 5px solid var(--pitch-2); border-radius: 10px; padding: 10px 12px; }}
.pick .family {{ font: 700 .78rem 'Barlow', sans-serif; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }}
.pick .market {{ font: 700 1.25rem 'Barlow Condensed', sans-serif; color: var(--ink); }}
.pick .prob {{ font-weight: 700; color: var(--ink); }}
.heat {{ width: 100%; border-collapse: separate; border-spacing: 3px; table-layout: fixed; font-variant-numeric: tabular-nums; }}
.heat th {{ font: 700 .9rem 'Barlow Condensed', sans-serif; color: var(--ink-2); padding: 2px; }}
.heat td {{ text-align: center; border-radius: 6px; padding: 8px 2px; font-size: .86rem; font-weight: 600; background: var(--hl); color: var(--fl); }}
.heat td.min {{ outline: 2px dashed var(--ink); outline-offset: -3px; }}
.heat td.mine {{ outline: 3px solid var(--accent); outline-offset: -3px; }}
.heat td.mine::before {{ content: "★ "; }}
.heat caption {{ caption-side: bottom; text-align: left; font-size: .82rem; color: var(--muted); padding-top: 6px; }}
.axis-note {{ font-size: .82rem; color: var(--muted); }}
@media (prefers-color-scheme: dark) {{ .heat td {{ background: var(--hd); color: var(--fd); }} }}
{".heat td { background: var(--hd); color: var(--fd); }" if theme == "dark" else ""}
{".heat td { background: var(--hl) !important; color: var(--fl) !important; }" if theme == "light" else ""}
.score-card {{ background: var(--surface); border: 1px solid var(--border); border-top: 3px solid var(--pitch-2); border-radius: 12px;
  padding: 14px 16px; margin-bottom: 12px; color: var(--ink); }}
.score-card .eyebrow {{ color: var(--muted); font: 700 .74rem 'Barlow', sans-serif; letter-spacing: .08em; text-transform: uppercase; }}
.score-card .market {{ color: var(--ink); font: 700 1.1rem 'Barlow Condensed', sans-serif; margin: 4px 0 6px; }}
.score-card .prob {{ color: var(--ink); font: 700 2rem/1 'Barlow Condensed', sans-serif; }}
.score-card .meta, .score-card .confidence, .score-card .sources {{ color: var(--ink-2); font-size: .82rem; line-height: 1.5; margin-top: 6px; }}
.score-card .vbadge {{ display: inline-block; border-radius: 6px; padding: 4px 8px; margin-top: 8px; font: 700 .76rem 'Barlow', sans-serif;
  border: 1px solid var(--border); background: var(--surface-2); }}
.score-card .positive {{ color: var(--good-ink); border-color: var(--good); }} .score-card .negative {{ color: var(--bad-ink); border-color: var(--bad); }}
.score-card .neutral, .score-card .suspicious {{ color: var(--ink); border-color: var(--accent); }}
.score-card.suspicious-card {{ border-color: var(--accent); }}
.section-kicker {{ color: var(--ink-2); font: 700 .9rem 'Barlow Condensed', sans-serif; letter-spacing: .08em; text-transform: uppercase; margin: 16px 0 8px; }}
.input-card-title {{ color: var(--ink); font: 700 1.2rem 'Barlow Condensed', sans-serif; margin-bottom: 2px; }}
.input-card-subtitle {{ color: var(--ink-2); font-size: .9rem; margin-bottom: 10px; }}
@media (max-width: 640px) {{
  .dash-grid, .dash-grid.wide {{ grid-template-columns: 1fr; }}
  .card .big {{ font-size: 2.2rem; }}
  .board .name {{ font-size: 1.1rem; }} .board .score {{ font-size: 2.1rem; padding: 4px 8px; }}
  .badge {{ width: 38px; height: 38px; font-size: .85rem; }}
  .bar {{ grid-template-columns: minmax(70px, 38%) 1fr 50px; font-size: .85rem; }}
  .heat td {{ padding: 6px 0; font-size: .74rem; }}
  .hero h1 {{ font-size: 1.7rem !important; }}
}}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; transition: none !important; }} }}
</style>"""


# --- Icone (SVG disegnate a mano, nessun logo) --------------------------------------------------

ICONS = {
    "ball": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>'
            '<path d="M12 7l4 3-1.5 4.5h-5L8 10z" fill="currentColor"/><path d="M12 7V3M16 10l3.5-1.5M14.5 14.5l2.5 3.5M9.5 14.5L7 18M8 10L4.5 8.5" '
            'stroke="currentColor" stroke-width="1.6" fill="none"/></svg>',
    "goal": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 19V6h18v13" fill="none" stroke="currentColor" stroke-width="2.2"/>'
            '<path d="M6 6v13M9 6v13M12 6v13M15 6v13M18 6v13M3 9.5h18M3 13h18M3 16.5h18" stroke="currentColor" stroke-width=".8" opacity=".6"/></svg>',
    "flag": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 21V3" stroke="currentColor" stroke-width="2.2"/>'
            '<path d="M6 4l12 4-12 4z" fill="#eb6834" stroke="currentColor" stroke-width="1.2"/><path d="M3 21h9" stroke="currentColor" stroke-width="2"/></svg>',
    "cards": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="10" height="14" rx="2" fill="#f6c000" stroke="currentColor" stroke-width="1"/>'
             '<rect x="11" y="3" width="10" height="14" rx="2" fill="#d03b3b" stroke="currentColor" stroke-width="1" transform="rotate(10 16 10)"/></svg>',
    "clock": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="8" fill="none" stroke="currentColor" stroke-width="2"/>'
             '<path d="M12 13V8M12 13h4M10 2h4" stroke="currentColor" stroke-width="2"/><path d="M12 5a8 8 0 0 1 0 16z" fill="currentColor" opacity=".25"/></svg>',
    "value": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="2" width="10" height="20" rx="3" fill="none" stroke="currentColor" stroke-width="2"/>'
             '<circle cx="12" cy="7" r="2" fill="#d03b3b"/><circle cx="12" cy="12" r="2" fill="#8d9690"/><circle cx="12" cy="17" r="2" fill="#0ca30c"/></svg>',
    "grid": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3h18v18H3zM9 3v18M15 3v18M3 9h18M3 15h18" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>',
    "split": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="8" width="20" height="8" rx="2" fill="none" stroke="currentColor" stroke-width="2"/>'
             '<path d="M10 8v8M15 8v8" stroke="currentColor" stroke-width="2"/></svg>',
}


# --- Squadre --------------------------------------------------------------------------------

def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable_ink(background: str) -> str:
    return "#111111" if contrast(background, "#111111") >= contrast(background, "#ffffff") else "#ffffff"


def team_colors(name: str) -> tuple[str, str]:
    key = " ".join(str(name).lower().split())
    if key in TEAM_COLORS:
        return TEAM_COLORS[key]
    for alias, colors in TEAM_COLORS.items():
        if alias in key.split() or (len(alias) > 4 and alias in key):
            return colors
    neutral = ("#2f5d46", "#c9d6cd"), ("#3b4b6b", "#d9dee8"), ("#5b3b52", "#e6d8e1"), ("#4d4a2f", "#e3e0c9")
    return neutral[sum(map(ord, key)) % len(neutral)]


def initials(name: str) -> str:
    words = [word for word in str(name).replace("-", " ").split() if word.lower() not in _STOP]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(word[0] for word in words[:3]).upper()


def badge(name: str) -> str:
    primary, secondary = team_colors(name)
    return (f'<span class="badge" style="background:{primary};color:{readable_ink(primary)};border-color:{secondary}" '
            f'title="{esc(name)}" aria-hidden="true">{esc(initials(name))}</span>')


# --- Mattoni comuni -------------------------------------------------------------------------

def card(title: str, icon: str, big: str, sentence: str, body: str = "", note: str = "", big_small: str = "") -> str:
    small = f"<small>{esc(big_small)}</small>" if big_small else ""
    note_html = f'<div class="note">{note}</div>' if note else ""
    return (f'<section class="card"><div class="head">{ICONS.get(icon, "")}<span>{esc(title)}</span></div>'
            f'<div class="big">{esc(big)}{small}</div><div class="say">{esc(sentence)}</div>{body}{note_html}</section>')


def grid(cards: Iterable[str], wide: bool = False) -> str:
    return f'<div class="dash-grid{" wide" if wide else ""}">{"".join(cards)}</div>'


def bars(rows: Sequence[tuple[str, float]], *, pick: str | None = None, alt: bool = False) -> str:
    """Barre orizzontali 0-100% con la linea del 50%."""
    items = []
    for label, value in rows:
        width = max(0.0, min(100.0, float(value)))
        items.append(f'<div class="bar{" chosen" if label == pick else ""}"><span class="label">{esc(label)}</span>'
                     f'<span class="track" role="img" aria-label="{esc(label)} {pct(value)}"><span class="fill{" alt" if alt else ""}" '
                     f'style="width:{width:.1f}%"></span><span class="fifty"></span></span><span class="value">{pct(value)}</span></div>')
    return f'<div class="bars">{"".join(items)}</div><div class="axis-note">La linea verticale segna il 50%.</div>'


def split_bar(home: str, away: str, one: float, draw: float, two: float, *, home_label: str = "1", away_label: str = "2") -> str:
    """Barra unica divisa in tre: Casa (blu), Pareggio (grigio), Ospite (arancio), con etichette di testo."""
    def segment(css: str, value: float, label: str) -> str:
        text = pct(value) if value >= 9 else ""
        return f'<div class="{css}" style="flex:{max(float(value), 0.5):.2f}" title="{esc(label)} {pct(value)}">{text}</div>'

    return (f'<div class="split" role="img" aria-label="{esc(home)} {pct(one)}, pareggio {pct(draw)}, {esc(away)} {pct(two)}">'
            f'{segment("s1", one, home)}{segment("sx", draw, "Pareggio")}{segment("s2", two, away)}</div>'
            f'<div class="split-legend"><span><b>{esc(home_label)}</b> {esc(home)} {pct(one)}</span><span><b>X</b> {pct(draw)}</span>'
            f'<span>{esc(away)} {pct(two)} <b>{esc(away_label)}</b></span></div>')


def legend() -> str:
    return ('<div class="legend" aria-label="Legenda dei colori">'
            '<span><i style="background:var(--home)"></i>Casa / Over</span>'
            '<span><i style="background:var(--draw)"></i>Pareggio</span>'
            '<span><i style="background:var(--away)"></i>Ospite</span>'
            '<span><i style="background:var(--good)"></i>Conviene (EV positivo)</span>'
            '<span><i style="background:var(--neutral)"></i>Nessuna quota o da verificare</span>'
            '<span><i style="background:var(--bad)"></i>Non conviene</span></div>')


def anchoring_badge(result: Mapping) -> str:
    active = bool((result.get("market_anchoring") or {}).get("active"))
    text = "Ancorato al mercato" if active else "Solo modello"
    tip = GLOSSARY["Ancoraggio"] if active else "Nessuna quota 1X2 o Over/Under 2.5: probabilità dal solo modello statistico."
    return f'<span class="pill {"on" if active else "off"}" title="{esc(tip)}"><span class="dot" style="background:var(--{"good" if active else "neutral"})"></span>{esc(text)}</span>'


def team_names(result: Mapping) -> tuple[str, str]:
    return str(result["input"]["home"]["name"]), str(result["input"]["away"]["name"])


# --- Schede ---------------------------------------------------------------------------------

def confidence_label(favorite_pct: float) -> str:
    if favorite_pct >= 60:
        return "netto"
    if favorite_pct >= 45:
        return "medio"
    return "aperto"


def scoreboard(result: Mapping) -> str:
    home, away = team_names(result)
    model, summary = result["model"], result["summary"]
    score = summary["most_likely_exact_score"]
    favorite = summary["favorite_sign"]
    favorite_pct = summary["favorite_sign_probability_pct"]
    favorite_text = {"1": home, "X": "Pareggio", "2": away}[favorite]
    return (
        '<section class="board" aria-label="Tabellone partita"><div class="row">'
        f'<div class="team">{badge(home)}<div><div class="name">{esc(home)}</div><div class="xg">Gol attesi {model["lambda"]:.2f}</div></div></div>'
        f'<div class="score" title="Risultato esatto più probabile">{score["home"]} - {score["away"]}</div>'
        f'<div class="team away">{badge(away)}<div><div class="name">{esc(away)}</div><div class="xg">Gol attesi {model["mu"]:.2f}</div></div></div>'
        '</div><div class="under">'
        f'<span>Risultato più probabile: <b>{score["home"]}-{score["away"]}</b> ({pct(score["share_pct"])} delle partite simulate)</span>'
        f'<span>{term("Confidenza")}: <b>{esc(confidence_label(favorite_pct))}</b> · favorito {esc(favorite_text)} {pct(favorite_pct)}</span>'
        f'{anchoring_badge(result)}</div></section>'
    )


def outcome_card(result: Mapping) -> str:
    home, away = team_names(result)
    one_x_two = {key: result["markets"]["1x2"][key]["percentage"] for key in ("1", "X", "2")}
    favorite = max(one_x_two, key=one_x_two.get)
    count = out_of_ten(one_x_two[favorite])
    sentence = {"1": f"{home} vince in circa {count} partite su 10.", "X": f"Il pareggio è l'esito più probabile: circa {count} partite su 10.",
                "2": f"{away} vince in circa {count} partite su 10."}[favorite]
    return card("Esito finale 1X2", "split", pct(one_x_two[favorite]), sentence,
                split_bar(home, away, one_x_two["1"], one_x_two["X"], one_x_two["2"]),
                big_small={"1": f"vittoria {home}", "X": "pareggio", "2": f"vittoria {away}"}[favorite])


def goals_card(result: Mapping) -> str:
    over_under = result["markets"]["over_under"]
    over25 = over_under["Over_2.5"]["percentage"]
    rows = [(f"Over {line}", over_under[f"Over_{line}"]["percentage"]) for line in ("0.5", "1.5", "2.5", "3.5", "4.5")]
    return card("Gol", "ball", pct(over25), f"Almeno 3 gol (Over 2.5) in circa {out_of_ten(over25)} partite su 10.",
                bars(rows), big_small="Over 2.5", note=f"Under 2.5: {pct(over_under['Under_2.5']['percentage'])}")


def team_goals_card(result: Mapping) -> str:
    home, away = team_names(result)
    finale = result["components"]["finale"]
    rows = [(f"{home} segna", finale["Casa segna"]), (f"{away} segna", finale["Ospite segna"]),
            (f"{home} 2+ gol", finale["Casa Over 1.5 gol"]), (f"{away} 2+ gol", finale["Ospite Over 1.5 gol"]),
            ("Goal (segnano entrambe)", finale["Goal"])]
    two_plus = finale["Casa Over 1.5 gol"]
    return card("Gol per squadra", "goal", pct(finale["Goal"]),
                f"{home} segna almeno 2 gol in circa {out_of_ten(two_plus)} partite su 10.", bars(rows), big_small="Goal")


def multigol_card(result: Mapping) -> str:
    multigol = result["markets"]["multigol"]
    rows = [(f"Multigol {key}", value["percentage"]) for key, value in multigol.items()]
    best = max(rows, key=lambda row: row[1])
    return card("Multigol", "ball", pct(best[1]), f"{best[0]}: il totale gol cade in questa fascia in circa "
                f"{out_of_ten(best[1])} partite su 10.", bars(rows), big_small=best[0])


def first_half_card(result: Mapping) -> str:
    home, away = team_names(result)
    first = {key: result["markets"]["first_half_1x2"][key]["percentage"] for key in ("1", "X", "2")}
    half = result["markets"]["first_half_over_under"]
    over05 = half["Over_0.5"]["percentage"]
    body = split_bar(home, away, first["1"], first["X"], first["2"]) + bars(
        [("Over 0.5 1° tempo", over05), ("Over 1.5 1° tempo", half["Over_1.5"]["percentage"])])
    return card("Primo tempo", "clock", pct(over05), f"Si segna almeno un gol nel primo tempo in circa {out_of_ten(over05)} partite su 10.",
                body, big_small="Over 0.5 1T")


def recommended_line(lines: Mapping[str, Mapping]) -> tuple[str, float] | None:
    """La linea più probabile tra quelle non scontate (55-80%), altrimenti la più vicina al 50%. Solo lettura."""
    options = [(key.replace("_", " "), float(value["percentage"])) for key, value in lines.items() if key != "mean"]
    useful = [option for option in options if 55.0 <= option[1] <= 80.0]
    if useful:
        return max(useful, key=lambda option: option[1])
    return min(options, key=lambda option: abs(option[1] - 50.0)) if options else None


def corners_card(result: Mapping) -> str:
    corners = result["markets"]["corners"]
    rows = [(key.replace("_", " "), value["percentage"]) for key, value in corners.items() if key.startswith("Over")]
    line = recommended_line(corners)
    sentence = f"Attesi circa {corners['mean']:.1f} corner." + (f" {line[0]} succede in circa {out_of_ten(line[1])} partite su 10." if line else "")
    return card("Corner", "flag", f"{corners['mean']:.1f}", sentence, bars(rows, pick=line[0] if line else None),
                big_small="corner attesi", note=f"Soglia consigliata: <b>{esc(line[0])}</b> ({pct(line[1])}): la più probabile tra le linee non scontate (55-80%)." if line else "")


def cards_card(result: Mapping) -> str:
    cards = result["markets"]["cards"]
    model = result["model"]
    rows = [(key.replace("_", " "), value["percentage"]) for key, value in cards.items() if key.startswith("Over")]
    line = recommended_line(cards)
    sentence = (f"Attesi circa {cards['mean']:.1f} punti cartellino ({model.get('card_yellow_mean', 0):.1f} gialli e "
                f"{model.get('card_red_mean', 0):.2f} rossi).")
    note = f"Regola: {esc(model.get('card_rule', ''))}."
    if line:
        note = f"Soglia consigliata: <b>{esc(line[0])}</b> ({pct(line[1])}). " + note
    return card("Cartellini", "cards", f"{cards['mean']:.1f}", sentence, bars(rows, pick=line[0] if line else None, alt=True),
                big_small="punti attesi", note=note)


def value_states(result: Mapping) -> list[dict]:
    """Semaforo per ogni quota inserita, dai valori già calcolati da ``financial_analysis``."""
    states = []
    for row in result["financial"]["markets"]:
        ev = float(row["ev_pct"])
        if ev > 0 and not row.get("value_excluded") and not row.get("suspicious_value"):
            color, verdict = "green", f"Conviene · EV {ev:+.1f}%"
        elif ev > 0:
            reason = "valore sospetto, verifica i dati" if row.get("suspicious_value") else "valore non segnalato su questo mercato"
            color, verdict = "grey", f"Da verificare · EV {ev:+.1f}% ({reason})"
        else:
            color, verdict = "red", f"Non conviene · EV {ev:+.1f}%"
        states.append({"market": row["market"], "odds": row["odds"], "probability": row["simulated_probability_pct"],
                       "fair_odds": row.get("fair_odds"), "ev": ev, "color": color, "verdict": verdict})
    return sorted(states, key=lambda state: -state["ev"])


def value_card(result: Mapping, limit: int = 6) -> str:
    states = value_states(result)
    if not states:
        body = ('<div class="lights"><div class="light grey"><span class="lamp"></span><span class="what">Nessuna quota inserita</span>'
                '<span class="verdict">Semaforo spento</span></div></div>')
        return card("Valore", "value", "—", "Inserisci le quote del bookmaker per sapere se una giocata conviene.", body)
    items = "".join(
        f'<div class="light {state["color"]}"><span class="lamp" aria-hidden="true"></span>'
        f'<span class="what">{esc(state["market"])} @ {odd(state["odds"])} · prob. {pct(state["probability"])} · '
        f'{term("quota equa", "Quota equa")} {odd(state["fair_odds"])}</span><span class="verdict">{esc(state["verdict"])}</span></div>'
        for state in states[:limit])
    green = sum(state["color"] == "green" for state in states)
    sentence = (f"{green} quote su {len(states)} convengono secondo il modello." if green
                else f"Nessuna delle {len(states)} quote inserite conviene secondo il modello.")
    return card("Valore", "value", f"{green}/{len(states)}", sentence, f'<div class="lights">{items}</div>',
                big_small="quote con EV positivo", note=f"{term('EV')}: guadagno medio per 1 € puntato. Il colore è sempre accompagnato dal testo.")


SOLID_FAMILIES = {
    "Doppia chance": ("1X", "X2", "12"),
    "Gol": ("Over 1.5 gol", "Over 2.5 gol", "Under 2.5 gol", "Under 3.5 gol"),
    "Goal / No Goal": ("Goal", "No Goal"),
    "Multigol": ("Multigol 1-3", "Multigol 2-4", "Multigol 1-4", "Multigol 2-5"),
    "Corner": tuple(f"{side} {line} corner" for side in ("Over", "Under") for line in ("7.5", "8.5", "9.5", "10.5", "11.5")),
    "Cartellini": tuple(f"{side} {line} cartellini" for side in ("Over", "Under") for line in ("2.5", "3.5", "4.5", "5.5")),
}


def solid_picks(result: Mapping, limit: int = 4, low: float = 55.0, high: float = 85.0) -> list[dict]:
    """Per famiglia, la giocata più probabile tra quelle non scontate; le famiglie più solide prima."""
    finale = result["components"]["finale"]
    financial = {row["market"]: row for row in result["financial"]["markets"]}
    picks = []
    for family, markets in SOLID_FAMILIES.items():
        options = [(market, float(finale[market])) for market in markets if market in finale and low <= finale[market] <= high]
        if not options:
            continue
        market, probability = max(options, key=lambda option: option[1])
        picks.append({"family": family, "market": market, "probability": probability, "fair_odds": 100.0 / probability,
                      "odds": financial.get(market, {}).get("odds"), "ev": financial.get(market, {}).get("ev_pct")})
    return sorted(picks, key=lambda pick: -pick["probability"])[:limit]


def solid_picks_box(result: Mapping) -> str:
    picks = solid_picks(result)
    if not picks:
        return card("Le giocate più solide", "ball", "—", "Nessuna giocata tra il 55% e l'85% di probabilità in questa partita.")
    items = []
    for item in picks:
        value = (f" · quota {odd(item['odds'])} · EV {float(item['ev']):+.1f}%" if item["odds"] else " · nessuna quota inserita")
        items.append(f'<div class="pick"><div class="family">{esc(item["family"])}</div><div class="market">{esc(item["market"])}</div>'
                     f'<div><span class="prob">{pct(item["probability"])}</span> · circa {out_of_ten(item["probability"])} su 10 · '
                     f'{term("quota equa", "Quota equa")} {odd(item["fair_odds"])}{esc(value)}</div></div>')
    return (f'<section class="card"><div class="head">{ICONS["ball"]}<span>Le giocate più solide di questa partita</span></div>'
            f'<div class="say">Le più probabili tra quelle non scontate (55-85%). Solide non vuol dire convenienti: guarda il semaforo del valore.</div>'
            f'<div class="picks">{"".join(items)}</div></section>')


def keys_card(keys: Sequence) -> str:
    """Chiavi del match: duelli con il mercato collegato (solo informazione, non cambiano le probabilità)."""
    items = [f'<div class="pick"><div class="family">{esc(", ".join(key.markets))}</div>'
             f'<div class="market">{esc(key.duel)}</div><div>{esc(key.effect)}</div></div>' for key in keys]
    return (f'<section class="card"><div class="head">{ICONS["ball"]}<span>Chiavi del match</span></div>'
            f'<div class="say">Duelli da guardare e mercato collegato, dal report dell\'Analista o dalla risposta di Claude. '
            f'Sono informazioni: non cambiano le probabilità.</div><div class="picks">{"".join(items)}</div></section>')


# --- Risultati esatti ----------------------------------------------------------------------------

def _blend(surface: str, full: str, alpha: float) -> str:
    first = [int(surface[index:index + 2], 16) for index in (1, 3, 5)]
    second = [int(full[index:index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(f"{round(a + (b - a) * alpha):02x}" for a, b in zip(first, second))


def heatmap(result: Mapping, minimum: Iterable[str] = (), mine: Iterable[str] = (), max_goals: int = 5) -> str:
    """Griglia gol casa × gol ospite; tratteggio = gruppo minimo, bordo pieno e ★ = il mio gruppo."""
    home, away = team_names(result)
    distribution = result["exact_scores"]["finale"]
    minimum, mine = set(minimum), set(mine)
    top = max([value for value in distribution.values()] or [1.0])
    header = "".join(f"<th scope='col'>{goals}</th>" for goals in range(max_goals + 1))
    rows = []
    for home_goals in range(max_goals + 1):
        cells = []
        for away_goals in range(max_goals + 1):
            score = f"{home_goals}-{away_goals}"
            value = float(distribution.get(score, 0.0))
            alpha = 0.06 + 0.94 * (value / top) ** 0.8 if value > 0 else 0.0
            style = []
            for mode, (surface, full) in HEAT.items():
                background = _blend(surface, full, alpha)
                suffix = "l" if mode == "light" else "d"
                style.append(f"--h{suffix}:{background};--f{suffix}:{readable_ink(background)}")
            classes = " ".join(name for name, member in (("min", score in minimum), ("mine", score in mine)) if member)
            cells.append(f'<td class="{classes}" style="{";".join(style)}" title="{score}: {pct(value)}">{pct(value) if value >= 0.05 else "·"}</td>')
        rows.append(f"<tr><th scope='row'>{home_goals}</th>{''.join(cells)}</tr>")
    shown = sum(float(distribution.get(f"{h}-{a}", 0.0)) for h in range(max_goals + 1) for a in range(max_goals + 1))
    return (f'<table class="heat" aria-label="Probabilità dei risultati esatti"><caption>Righe: gol {esc(home)} · colonne: gol {esc(away)}. '
            f'Più scuro = più probabile. Tratteggio = gruppo minimo · ★ e bordo pieno = il mio gruppo. Fuori griglia: {pct(max(0.0, 100 - shown))}.</caption>'
            f"<thead><tr><th>{esc(initials(home))} \\ {esc(initials(away))}</th>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>")


def hero() -> str:
    return ('<header class="hero"><div class="kicker">Simulpro · Match Lab</div><h1>Simulatore partite</h1>'
            '<p>Inserisci la partita, premi «Esegui simulazione» e leggi le schede: ogni numero ha accanto cosa significa.</p></header>')


def missing_as_dash(frame):
    """Tabella per la visualizzazione: «—» al posto di None/NaN, numeri senza zeri inutili."""
    import pandas as pd

    def cell(value):
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            return "—"
        if isinstance(value, float):
            return f"{value:g}" if abs(value) >= 1e-4 or value == 0 else f"{value:.2e}"
        return value

    return frame.astype(object).map(cell)


# --- In breve ---------------------------------------------------------------------------------
# Frasi solo dai numeri già calcolati. Riferimento per «sopra/sotto» = la linea più giocata del mercato
# (2.5 gol, 9.5 corner, 4.5 punti cartellino): sopra se l'Over supera il 55%, sotto se resta sotto il 45%.
REFERENCE_LINES = {"gol": ("Over 2.5 gol", 2.5), "corner": ("Over 9.5 corner", 9.5), "cartellini": ("Over 4.5 cartellini", 4.5)}


def _side(over_pct: float) -> str:
    return "sopra la linea" if over_pct >= 55 else "sotto la linea" if over_pct <= 45 else "vicini alla linea"


def brief_sentences(result: Mapping) -> list[str]:
    home, away = team_names(result)
    finale = result["components"]["finale"]
    model = result["model"]
    one, draw, two = (result["markets"]["1x2"][key]["percentage"] for key in ("1", "X", "2"))
    sentences = []

    total = float(model["lambda"]) + float(model["mu"])
    over = finale[REFERENCE_LINES["gol"][0]]
    pace = "alto" if over >= 58 else "basso" if over <= 42 else "nella media"
    sentences.append(f"Ritmo gol {pace}: attesi {total:.1f} gol in tutto ({home} {float(model['lambda']):.1f}, "
                     f"{away} {float(model['mu']):.1f}); almeno 3 gol in circa {out_of_ten(over)} partite su 10.")

    favorite, favorite_pct = max((("1", one), ("X", draw), ("2", two)), key=lambda item: item[1])
    if abs(one - two) < 8:
        sentences.append(f"Partita equilibrata: {home} {pct(one)}, pareggio {pct(draw)}, {away} {pct(two)}.")
    elif favorite == "X":
        sentences.append(f"Il pareggio è l'esito più probabile ({pct(draw)}), ma nessun risultato domina.")
    else:
        team = home if favorite == "1" else away
        strength = "netta favorita" if favorite_pct >= 60 else "favorita" if favorite_pct >= 45 else "leggermente avanti"
        sentences.append(f"{team} {strength}: vince in circa {out_of_ten(favorite_pct)} partite su 10 ({pct(favorite_pct)}).")

    corners = result["markets"]["corners"]["mean"]
    corner_over = finale[REFERENCE_LINES["corner"][0]]
    cards = result["markets"]["cards"]["mean"]
    card_over = finale[REFERENCE_LINES["cartellini"][0]]
    sentences.append(f"Corner {_side(corner_over)} classica di 9.5 (attesi {corners:.1f}, Over 9.5 al {pct(corner_over)}); "
                     f"cartellini {_side(card_over)} di 4.5 punti (attesi {cards:.1f}, Over 4.5 al {pct(card_over)}).")

    picks = solid_picks(result, limit=2)
    if picks:
        names = " e ".join(f"{pick['market']} ({pct(pick['probability'])})" for pick in picks)
        sentences.append(f"Giocate più solide: {names}. Solide non vuol dire convenienti: guarda il semaforo del valore.")
    else:
        sentences.append("Nessuna giocata tra il 55% e l'85%: partita difficile da leggere.")
    return sentences


def in_brief(result: Mapping) -> str:
    items = "".join(f"<li>{esc(sentence)}</li>" for sentence in brief_sentences(result))
    return (f'<section class="card brief"><div class="head">{ICONS["ball"]}<span>In breve</span></div>'
            f'<ul class="brief-list">{items}</ul></section>')
