"""Chiavi del match (fase X): blocco CHIAVI_MATCH tollerante, al massimo 4 duelli, sempre con fonte."""

from claude_bridge import parse_response
from match_keys import MAX_KEYS, parse_keys, swap_text


ANSWER = """Commento iniziale.
CORREZIONI_CLAUDE:
gol_casa: 0.95 | motivo: assenze | fonte: https://x.it/a
confidenza: media
commento: ok

**CHIAVI_MATCH:**
- duello: Politano vs Dimarco | effetto: esterno veloce contro terzino che spinge | mercato: Corner | fonte: https://x.it/1
* Duello: Lobotka - Barella | Effetto: duelli fisici a centrocampo | Mercato: cartellini/gol | Fonte: https://x.it/2
duello: Lukaku vs Bastoni | effetto: spalle alla porta | mercato: gol
duello: Kvara vs Darmian | effetto: dribbling | mercato: punizioni | fonte: https://x.it/4
duello: A vs B | effetto: 1 | mercato: gol | fonte: https://x.it/5
duello: C vs D | effetto: 2 | mercato: gol | fonte: https://x.it/6
duello: E vs F | effetto: 3 | mercato: corner | fonte: https://x.it/7

Testo libero dopo.
"""


def test_keys_are_parsed_tolerantly_with_source_and_market():
    keys, discarded = parse_keys(ANSWER)
    assert len(keys) == MAX_KEYS
    assert keys[0].duel == "Politano vs Dimarco" and keys[0].markets == ("corner",)
    assert keys[1].duel == "Lobotka vs Barella" and keys[1].markets == ("cartellini", "gol")
    assert any("senza fonte" in reason for reason in discarded)
    assert any("mercato mancante" in reason for reason in discarded)
    assert any("oltre le 4" in reason for reason in discarded)
    assert parse_keys("niente chiavi") == ([], [])


def test_keys_do_not_disturb_the_claude_corrections():
    response = parse_response(ANSWER)
    assert set(response.corrections) == {"gol_casa"} and not any("duello" in warning for warning in response.warnings)


def test_swap_text_swaps_goal_keys_and_duel_sides():
    text = "gol_casa: 0.9 | fonte: https://a\ngol_ospite: 1.1 | fonte: https://b\nduello: A vs B | mercato: gol | fonte: https://c"
    swapped = swap_text(text)
    assert swapped.splitlines()[0].startswith("gol_ospite: 0.9") and swapped.splitlines()[1].startswith("gol_casa: 1.1")
    assert "duello: B vs A |" in swapped
