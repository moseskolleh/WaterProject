from groundwater.utils import (
    fmt_num,
    ordinal,
    parse_depth_interval,
    parse_number,
    round_sig,
)


def test_parse_number_leading_zeros():
    assert parse_number("078.7") == 78.7
    assert parse_number("0708958") == 708958.0
    assert parse_number("052.1") == 52.1


def test_parse_number_units_and_commas():
    assert parse_number("80m") == 80.0
    assert parse_number("19.28M") == 19.28
    assert parse_number("2,933lts/hr") == 2933.0
    assert parse_number('6.5"') == 6.5


def test_parse_number_empty():
    assert parse_number("") is None
    assert parse_number(None) is None
    assert parse_number("n/a") is None
    assert parse_number(float("nan")) is None


def test_parse_depth_interval():
    assert parse_depth_interval("0-5") == (0.0, 5.0)
    assert parse_depth_interval("5 - 10") == (5.0, 10.0)
    assert parse_depth_interval("12 to 18 m") == (12.0, 18.0)
    assert parse_depth_interval("65-70") == (65.0, 70.0)
    assert parse_depth_interval("plain text") is None
    # the hyphen is a range separator, never a minus sign
    assert parse_depth_interval("0-5")[0] >= 0


def test_round_and_format():
    assert round_sig(2102.804, 4) == 2103.0
    assert round_sig(0.0123456, 3) == 0.0123
    assert fmt_num(832.14, 4) == "832.1"
    assert fmt_num(None) == "n/a"
    assert fmt_num(80.0) == "80"


def test_ordinal():
    assert ordinal(1) == "1st"
    assert ordinal(2) == "2nd"
    assert ordinal(3) == "3rd"
    assert ordinal(11) == "11th"
    assert ordinal(22) == "22nd"


def test_a_config_override_that_cannot_apply_says_so(tmp_path):
    """A mis-keyed override used to vanish; a quoted number used to arrive as
    a string and fail three pages later."""
    import warnings

    from groundwater.config import Config

    path = tmp_path / "config.yaml"
    path.write_text(
        "pumping:\n  safety_factor: '2.0'\n  design_period_days: 180\n"
        "design:\n  safety_factor: 3.0\nbanana:\n  x: 1\n",
        encoding="utf-8",
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = Config.load(path)
    messages = [str(w.message) for w in caught]
    assert any("safety_factor" in m and "design" in m for m in messages)
    assert any("banana" in m for m in messages)
    assert cfg.pumping.safety_factor == 2.0 and isinstance(cfg.pumping.safety_factor, float)
    assert cfg.pumping.design_period_days == 180
    assert Config.load(tmp_path / "missing.yaml").pumping.safety_factor == Config().pumping.safety_factor


def test_a_decimal_comma_is_a_decimal_point():
    """'1,5' used to parse as 15 and '078,7' as 787 - a silent tenfold error
    in an electrode spacing or a resistivity from a crew that writes decimal
    commas. A comma is a thousands separator only when exactly three digits
    follow it and end the number."""
    from groundwater.utils import parse_number

    for text, expected in (
        ("1,5", 1.5), ("078,7", 78.7), ("3,1416", 3.1416), ("2,933", 2933.0),
        ("2,933lts/hr", 2933.0), ("1.234,5", 1234.5), ("12,345,678", 12345678.0),
        ("19.28M", 19.28), ("0708958", 708958.0), ("-0,5", -0.5), ("1 234", 1.0),
    ):
        assert parse_number(text) == expected, text
