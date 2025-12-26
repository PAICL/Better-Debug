from __future__ import annotations

import base64
import re
import struct
from dataclasses import dataclass
from typing import Iterable


_HEX_CLEAN_RE = re.compile(r"[^0-9a-fA-F]")


class FormatError(ValueError):
    pass


def parse_int(token: str) -> int:
    token = token.strip()
    if not token:
        raise FormatError("empty integer")
    try:
        return int(token, 0)
    except ValueError as exc:
        raise FormatError(f"invalid integer: {token!r}") from exc


def parse_hex_string(text: str) -> bytes:
    """Parse a hex string like 'AA55', 'AA 55', '0xAA,0x55', 'AA:55'."""
    raw = text.strip()
    if not raw:
        return b""

    # Support sequences like: 0xAA 0x55
    if "0x" in raw.lower():
        tokens = re.split(r"[\s,;:]+", raw)
        out = bytearray()
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            value = parse_int(token)
            if not (0 <= value <= 0xFF):
                raise FormatError(f"byte out of range: {token!r}")
            out.append(value)
        return bytes(out)

    cleaned = _HEX_CLEAN_RE.sub("", raw)
    if len(cleaned) % 2 != 0:
        raise FormatError("hex string must have even number of digits")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise FormatError(f"invalid hex: {text!r}") from exc


def parse_u16_list(tokens: Iterable[str], endian: str) -> bytes:
    if endian not in ("le", "be"):
        raise ValueError("endian must be 'le' or 'be'")
    fmt = "<H" if endian == "le" else ">H"
    out = bytearray()
    for token in tokens:
        value = parse_int(token)
        if not (0 <= value <= 0xFFFF):
            raise FormatError(f"u16 out of range: {token!r}")
        out.extend(struct.pack(fmt, value))
    return bytes(out)


def parse_i16_list(tokens: Iterable[str], endian: str) -> bytes:
    if endian not in ("le", "be"):
        raise ValueError("endian must be 'le' or 'be'")
    fmt = "<h" if endian == "le" else ">h"
    out = bytearray()
    for token in tokens:
        value = parse_int(token)
        if not (-0x8000 <= value <= 0x7FFF):
            raise FormatError(f"i16 out of range: {token!r}")
        out.extend(struct.pack(fmt, value))
    return bytes(out)


def parse_base64(text: str) -> bytes:
    raw = text.strip()
    if not raw:
        return b""
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as exc:  # pragma: no cover
        raise FormatError("invalid base64") from exc


def apply_text_escapes(text: str) -> str:
    """Interpret common backslash escapes like \\n, \\r, \\t, \\xNN."""
    # unicode_escape gives a reasonable UX for terminal input.
    # It will also interpret \\uXXXX sequences into unicode characters.
    try:
        return bytes(text, "utf-8").decode("unicode_escape")
    except Exception as exc:
        raise FormatError("invalid escape sequence") from exc


@dataclass
class NewlineConfig:
    mode: str  # none|lf|cr|crlf

    def suffix_bytes(self) -> bytes:
        mode = self.mode.lower()
        if mode in ("none", ""):
            return b""
        if mode == "lf":
            return b"\n"
        if mode == "cr":
            return b"\r"
        if mode == "crlf":
            return b"\r\n"
        raise FormatError(f"unknown eol: {self.mode!r}")
