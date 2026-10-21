from parser import MatchInputError, parse_match_input


VALID = """CASA: Inter
Attacco: 1,34 | Difesa: 1.25 | Elo: 1835 | Forma: W-W-D-W-W | xG Fatti: 2.15 | xG Subiti: 0.85 | Corner pro/sub: 5.8/4.2 | Cartellini pro: 1.60

OSPITE: Milan
Attacco: 1.22 | Difesa: 1.10 | Elo: 1765 | Forma: W-W-L-D-W | xG Fatti: 1.85 | xG Subiti: 1.10 | Corner pro/sub: 5.1/4.8 | Cartellini pro: 1.85

ARBITRO: Gialli medi 4.5 | Falli medi 24
"""


COMPLETE_COPY_BLOCK = """CASA: Como | Quota 1: 2.50 | Quota 1T 1: 3.10 | Quota DNB Casa: 1.80
Attacco: 1.25 | Difesa: 0.95 | Elo: 1680 | Forma: W-W-L-W-W | xG Fatti: 1.85 | xG Subiti: 1.10 | Corner pro/sub: 1.15/1.10 | Cartellini pro: 1.10

OSPITE: Roma | Quota 2: 2.70 | Quota 1T 2: 3.30 | Quota DNB Ospite: 1.90
Attacco: 1.45 | Difesa: 0.70 | Elo: 1810 | Forma: W-W-D-W-W | xG Fatti: 2.80 | xG Subiti: 0.60 | Corner pro/sub: 1.20/0.85 | Cartellini pro: 1.15

ARBITRO: Gialli medi 4.30 | Falli medi 22.50

QUOTE_MERCATI_PRINCIPALI:
Quota X: 3.25 | Quota 1X: 1.44 | Quota X2: 1.50 | Quota 12: 1.33 | Quota 1T X: 2.10
Quota Goal: 1.62 | Quota No Goal: 2.20 | Quota Goal 1T: 4.50
Quota Under 1.5: 3.60 | Quota Over 1.5: 1.25 | Quota Over 1.5 1T: 2.45
Quota Under 2.5: 2.20 | Quota Over 2.5: 1.60
Quota Under 3.5: 1.45 | Quota Over 3.5: 2.60
Quota Under 4.5: 1.20 | Quota Over 4.5: 4.50

QUOTE_MULTIGOL_TOTALI:
Quota Multigol Totale 1-2: 2.30 | Quota Multigol Totale 1-3: 1.50 | Quota Multigol Totale 1-4: 1.20 | Quota Multigol Totale 1-5: 1.10
Quota Multigol Totale 2-3: 2.00 | Quota Multigol Totale 2-4: 1.48 | Quota Multigol Totale 2-5: 1.32 | Quota Multigol Totale 2-6: 1.22
Quota Multigol Totale 3-4: 2.70 | Quota Multigol Totale 3-5: 1.85 | Quota Multigol Totale 3-6: 1.60

QUOTE_MULTIGOL_CASA:
Quota Multigol Casa 1-2: 1.65 | Quota Multigol Casa 1-3: 1.35 | Quota Multigol Casa 1-4: 1.18 | Quota Multigol Casa 1-5: 1.08
Quota Multigol Casa 2-3: 2.20 | Quota Multigol Casa 2-4: 1.80 | Quota Multigol Casa 2-5: 1.55 | Quota Multigol Casa 2-6: 1.40
Quota Multigol Casa 3-4: 4.20 | Quota Multigol Casa 3-5: 3.50 | Quota Multigol Casa 3-6: 3.00

QUOTE_MULTIGOL_OSPITE:
Quota Multigol Ospite 1-2: 1.60 | Quota Multigol Ospite 1-3: 1.32 | Quota Multigol Ospite 1-4: 1.15 | Quota Multigol Ospite 1-5: 1.06
Quota Multigol Ospite 2-3: 2.10 | Quota Multigol Ospite 2-4: 1.70 | Quota Multigol Ospite 2-5: 1.48 | Quota Multigol Ospite 2-6: 1.35
Quota Multigol Ospite 3-4: 3.80 | Quota Multigol Ospite 3-5: 3.10 | Quota Multigol Ospite 3-6: 2.70

QUOTE_SOMMA_GOL:
Quota Somma Gol 0: 10.00 | Quota Somma Gol 1: 4.80 | Quota Somma Gol 2: 3.60 | Quota Somma Gol 3: 3.80 | Quota Somma Gol 4: 5.00 | Quota Somma Gol 5+: 6.50

QUOTE_CORNER_E_CARTELLINI:
Quota Over 8.5 Corner: 1.45 | Quota Over 9.5 Corner: 1.80 | Quota Over 10.5 Corner: 2.35 | Quota Over 11.5 Corner: 3.10
Quota Over 3.5 Cartellini: 1.40 | Quota Over 4.5 Cartellini: 1.85 | Quota Over 5.5 Cartellini: 2.70

QUOTE_COMBO:
Quota 1X + Over 1.5: 1.80 | Quota X2 + Over 1.5: 1.85 | Quota X2 + Multigol 1-3: 2.40
"""


def test_parser_preserves_values_and_decimal_comma():
    match = parse_match_input(VALID)
    assert match.home.attack == 1.34
    assert match.away.elo == 1765.0
    assert match.home.corners_against == 4.2
    assert match.warnings == ()


def test_parser_reads_every_quote_from_the_complete_copy_block():
    match = parse_match_input(COMPLETE_COPY_BLOCK)

    assert match.home.name == "Como"
    assert match.away.name == "Roma"
    assert match.referee.yellow_avg == 4.3
    assert match.referee.fouls_avg == 22.5
    assert len(match.odds) == 72
    assert len(match.warnings) == 1
    assert "2.15" in match.warnings[0]
    assert "non coefficienti" in match.warnings[0]
    assert match.odds["1 1T"] == 3.10
    assert match.odds["2 1T"] == 3.30
    assert match.odds["X 1T"] == 2.10
    assert match.odds["Casa DNB"] == 1.80
    assert match.odds["Ospite DNB"] == 1.90
    assert match.odds["Over 1.5 gol 1T"] == 2.45
    assert match.odds["1X + Over 1.5 gol"] == 1.80
    assert match.odds["X2 + Over 1.5 gol"] == 1.85
    assert match.odds["X2 + Multigol 1-3"] == 2.40


def test_parser_reports_secondary_fallbacks():
    text = VALID.replace(" | Corner pro/sub: 5.8/4.2 | Cartellini pro: 1.60", "")
    match = parse_match_input(text, strict=False)
    assert match.home.corners_for == 5.0
    assert match.home.corners_against == 5.0
    assert len(match.warnings) == 2


def test_parser_rejects_missing_required_field():
    try:
        parse_match_input(VALID.replace("xG Fatti: 2.15 | ", ""))
    except MatchInputError as error:
        assert "xG Fatti" in str(error)
    else:
        raise AssertionError("Missing required data must fail explicitly")


def test_strict_parser_requires_every_team_and_referee_field():
    incomplete_blocks = (
        (VALID.replace(" | Corner pro/sub: 5.8/4.2", ""), "Corner pro/sub"),
        (VALID.replace(" | Cartellini pro: 1.60", ""), "Cartellini pro"),
        (VALID.replace("Gialli medi 4.5 | ", ""), "Gialli medi"),
        (VALID.replace(" | Falli medi 24", ""), "Falli medi"),
    )

    for text, missing_field in incomplete_blocks:
        try:
            parse_match_input(text)
        except MatchInputError as error:
            assert missing_field in str(error)
        else:
            raise AssertionError(f"Strict parsing must reject missing {missing_field}")


def test_strict_parser_rejects_malformed_unknown_duplicate_and_invalid_odds():
    invalid_blocks = (
        (VALID.replace("CASA: Inter", "CASA: Inter | Quota X: abc"), "malformata"),
        (VALID.replace("CASA: Inter", "CASA: Inter | Quota MercatoNuovo: 2.0"), "non riconosciuto"),
        (VALID.replace("CASA: Inter", "CASA: Inter | Quota 1: 1.8 | Quota 1: 1.9"), "duplicata"),
        (VALID.replace("CASA: Inter", "CASA: Inter | Quota 1: 1.0"), "maggiore di 1.0"),
    )

    for text, expected_message in invalid_blocks:
        try:
            parse_match_input(text)
        except MatchInputError as error:
            assert expected_message in str(error)
        else:
            raise AssertionError(f"Strict parsing must reject {expected_message}")


def test_parser_rejects_non_finite_and_out_of_domain_metrics():
    invalid_inputs = (
        (VALID.replace("Attacco: 1,34", "Attacco: 0"), "Attacco"),
        (VALID.replace("Difesa: 1.25", "Difesa: 0"), "Difesa"),
        (VALID.replace("xG Fatti: 2.15", "xG Fatti: nan"), "finito"),
        (VALID.replace("Corner pro/sub: 5.8/4.2", "Corner pro/sub: -1/4.2"), "tra 0 e 15"),
        (VALID.replace("Corner pro/sub: 5.8/4.2", "Corner pro/sub: 22/4.2"), "tra 0 e 15"),
        (VALID.replace("Cartellini pro: 1.60", "Cartellini pro: -0.95"), "tra 0 e 10"),
        (VALID.replace("Elo: 1835", "Elo: 2500"), "tra 800 e 2400"),
        (VALID.replace("Gialli medi 4.5", "Gialli medi -4.5"), "0-15 gialli"),
        (
            VALID.replace("Corner pro/sub: 5.8/4.2", "Corner pro/sub: 15/15").replace(
                "Corner pro/sub: 5.1/4.8", "Corner pro/sub: 15/15"
            ),
            "supera 20",
        ),
        (
            VALID.replace("Cartellini pro: 1.60", "Cartellini pro: 5.0").replace(
                "Cartellini pro: 1.85", "Cartellini pro: 5.0"
            ).replace("Gialli medi 4.5", "Gialli medi 12").replace("Falli medi 24", "Falli medi 50"),
            "supera 20",
        ),
    )

    for text, expected_message in invalid_inputs:
        try:
            parse_match_input(text)
        except MatchInputError as error:
            assert expected_message in str(error)
        else:
            raise AssertionError(f"Invalid metric should fail with {expected_message!r}")


def test_parser_reads_optional_bookmaker_quotes_from_team_headers():
    text = VALID.replace(
        "CASA: Inter",
        "CASA: Inter | Quota 1: 1,85 | Quota Over 2.5: 2.10",
    ).replace(
        "OSPITE: Milan",
        "OSPITE: Milan | Quota X: 3.40 | Quota 2: 4.20",
    )
    match = parse_match_input(text, strict=False)
    assert match.odds == {"1": 1.85, "Over 2.5 gol": 2.10, "X": 3.40, "2": 4.20}


def test_parser_rejects_invalid_duplicate_and_unknown_quotes_with_warnings():
    text = VALID.replace(
        "CASA: Inter",
        "CASA: Inter | Quota 1: 1.85 | Quota 1: 1.90 | Quota Casa Over 1.5: 2.00 | Quota Sconosciuta: 5.00 | Quota X: 1.00",
    )
    match = parse_match_input(text, strict=False)
    assert match.odds == {"1": 1.85, "Casa Over 1.5 gol": 2.00}
    assert any("duplicata" in warning for warning in match.warnings)
    assert any("non supportato" in warning for warning in match.warnings)
    assert any("maggiore di 1.0" in warning for warning in match.warnings)


def test_parser_isolates_repeated_team_headers_and_reads_quote_sections():
    text = VALID.replace("CASA: Inter", "CASA: InterCASA: Genoa").replace(
        "ARBITRO: Gialli medi 4.5 | Falli medi 24",
        """ARBITRO: Gialli medi 4.5 | Falli medi 24

QUOTE_MERCATI_PRINCIPALI:
Quota 1: 1.85 | DNB Casa: 1.70 | Over 2.5: 2.10

QUOTE_MULTIGOL_TOTALI_E_SQUADRA:
Multigol Totale 1-3: 1.55 | Multigol Casa 1-2: 1.80 | Multigol Ospite 1-2: 1.90

QUOTE_SOMMA_GOL:
Somma gol 0: 4.00 | Somma gol 5+: 8.00

QUOTE_CORNER_E_CARTELLINI:
Over 8.5 corner: 1.90 | 1 corner: 2.00 | Under 4.5 cartellini: 1.80

QUOTE_COMBO:
1 + Over 1.5: 2.50""",
    )
    match = parse_match_input(text)

    assert match.home.name == "Inter"
    assert match.away.name == "Milan"
    assert match.odds == {
        "1": 1.85,
        "Casa DNB": 1.70,
        "Over 2.5 gol": 2.10,
        "Multigol 1-3": 1.55,
        "Multigol Casa 1-2": 1.80,
        "Multigol Ospite 1-2": 1.90,
        "Somma gol 0": 4.00,
        "Somma gol 5+": 8.00,
        "Over 8.5 corner": 1.90,
        "1 corner": 2.00,
        "Under 4.5 cartellini": 1.80,
        "1 + Over 1.5 gol": 2.50,
    }


def test_parser_reads_unprefixed_quotes_with_multiple_separators():
    text = VALID.replace(
        "ARBITRO: Gialli medi 4.5 | Falli medi 24",
        "ARBITRO: Gialli medi 4.5 | Falli medi 24\n"
        "Quota Multigol Totale 1-2 2.10 | Quota Multigol Casa 1-2: 1.80 | "
        "Quota Somma Gol 0 - 4.00 | Quota Over 8.5 Corner 1.90 | "
        "Quota 1 + Over 1.5 2.50\n"
        "Over 2.5 - 2.10 | DNB Casa 1.70",
    )
    match = parse_match_input(text)

    assert match.odds["Multigol 1-2"] == 2.10
    assert match.odds["Multigol Casa 1-2"] == 1.80
    assert match.odds["Somma gol 0"] == 4.00
    assert match.odds["Over 8.5 corner"] == 1.90
    assert match.odds["1 + Over 1.5 gol"] == 2.50
    assert match.odds["Over 2.5 gol"] == 2.10
    assert match.odds["Casa DNB"] == 1.70


def test_parser_canonicalizes_dynamic_team_multigol_labels():
    text = VALID.replace(
        "ARBITRO: Gialli medi 4.5 | Falli medi 24",
        "ARBITRO: Gialli medi 4.5 | Falli medi 24\n"
        "Quota multigol casa 3 - 4: 2.25 | Quota MULTIGOL ospite 1-4: 2.10",
    )
    match = parse_match_input(text)

    assert match.odds["Multigol Casa 3-4"] == 2.25
    assert match.odds["Multigol Ospite 1-4"] == 2.10


def test_parser_reads_all_extended_multigol_ranges_without_truncation():
    text = VALID.replace(
        "ARBITRO: Gialli medi 4.5 | Falli medi 24",
        "ARBITRO: Gialli medi 4.5 | Falli medi 24\n"
        "Quota Multigol Totale 1-5: 1.80 | Quota Multigol Totale 2-6: 2.10 | "
        "Quota Multigol Totale 3-4: 2.40 | Quota Multigol Totale 3-6: 1.60 | "
        "Quota Multigol Casa 1-4: 1.75 | Quota Multigol Casa 2-5: 2.00 | "
        "Quota Multigol Ospite 2-6: 2.15 | Quota Multigol Ospite 3-5: 2.30",
    )
    match = parse_match_input(text)

    assert set(match.odds) == {
        "Multigol 1-5", "Multigol 2-6", "Multigol 3-4", "Multigol 3-6",
        "Multigol Casa 1-4", "Multigol Casa 2-5",
        "Multigol Ospite 2-6", "Multigol Ospite 3-5",
    }
