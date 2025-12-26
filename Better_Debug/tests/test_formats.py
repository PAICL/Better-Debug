import pytest

from better_debug.formats import (
    FormatError,
    apply_text_escapes,
    parse_hex_string,
    parse_i16_list,
    parse_u16_list,
)


def test_parse_hex_string_compact():
    assert parse_hex_string("AA55") == bytes([0xAA, 0x55])


def test_parse_hex_string_spaced():
    assert parse_hex_string("aa 55 01") == bytes([0xAA, 0x55, 0x01])


def test_parse_hex_string_with_0x_tokens():
    assert parse_hex_string("0xAA,0x55") == bytes([0xAA, 0x55])


def test_parse_hex_string_odd_length_raises():
    with pytest.raises(FormatError):
        parse_hex_string("A")


def test_parse_u16_le():
    assert parse_u16_list(["0x1234"], "le") == bytes([0x34, 0x12])


def test_parse_u16_be():
    assert parse_u16_list(["0x1234"], "be") == bytes([0x12, 0x34])


def test_parse_i16_le_negative_one():
    assert parse_i16_list(["-1"], "le") == bytes([0xFF, 0xFF])


def test_apply_text_escapes():
    assert apply_text_escapes("hi\\r\\n") == "hi\r\n"
    assert apply_text_escapes("\\x41") == "A"
