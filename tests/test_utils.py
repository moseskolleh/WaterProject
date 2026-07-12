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
