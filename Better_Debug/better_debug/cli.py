from __future__ import annotations

import argparse
import shlex
import sys
from typing import Iterable

from serial.tools import list_ports

from .formats import (
    FormatError,
    NewlineConfig,
    apply_text_escapes,
    parse_base64,
    parse_hex_string,
    parse_i16_list,
    parse_u16_list,
)
from .monitor import MonitorConfig, SerialMonitor


def _list_ports() -> int:
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found")
        return 0
    for p in ports:
        desc = p.description or ""
        hwid = p.hwid or ""
        print(f"{p.device}\t{desc}\t{hwid}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="better_debug", description="Simple serial monitor based on pyserial")
    p.add_argument("--list", action="store_true", help="List available serial ports")
    p.add_argument("--gui", action="store_true", help="Launch cross-platform GUI (requires PySide6)")
    p.add_argument("--port", help="Serial port name, e.g. COM3")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--bytesize", type=int, choices=[5, 6, 7, 8], default=8)
    p.add_argument("--parity", choices=["N", "E", "O", "M", "S"], default="N")
    p.add_argument("--stopbits", type=float, choices=[1, 1.5, 2], default=1)
    p.add_argument("--xonxoff", action="store_true")
    p.add_argument("--rtscts", action="store_true")
    p.add_argument("--dsrdtr", action="store_true")
    p.add_argument("--timeout", type=float, default=0.1)
    p.add_argument("--encoding", default="utf-8")
    p.add_argument("--rx", choices=["text", "hex", "both"], default="both")
    p.add_argument("--timestamp", action="store_true")
    p.add_argument("--log", help="Log RX/TX as HEX into a file")
    p.add_argument("--eol", choices=["none", "lf", "cr", "crlf"], default="crlf")
    p.add_argument("--escapes", action="store_true", help="Interpret \\n, \\r, \\xNN in :text and plain input")
    return p


_HELP = """\
Interactive commands:
  :help
  :quit
  :text <payload>
  :hex <AA 55 01 02>
  :b64 <base64>
  :u16le <n1 n2 ...>    (e.g. :u16le 0x1234 4660)
  :u16be <n1 n2 ...>
  :i16le <n1 n2 ...>
  :i16be <n1 n2 ...>
  :file <path>          (send raw file bytes)
  :eol <none|lf|cr|crlf>
  :encoding <name>
  :rx <text|hex|both>
  :flush
Plain input (no leading ':') is sent as text.
"""


def _tokenize_args(rest: str) -> list[str]:
    rest = rest.strip()
    if not rest:
        return []
    return shlex.split(rest, posix=False)


def _send_text(m: SerialMonitor, text: str, encoding: str, eol: NewlineConfig, escapes: bool) -> None:
    if escapes:
        text = apply_text_escapes(text)
    data = text.encode(encoding, errors="replace") + eol.suffix_bytes()
    m.send(data)


def _send_words(m: SerialMonitor, tokens: Iterable[str], kind: str) -> None:
    if kind == "u16le":
        m.send(parse_u16_list(tokens, "le"))
        return
    if kind == "u16be":
        m.send(parse_u16_list(tokens, "be"))
        return
    if kind == "i16le":
        m.send(parse_i16_list(tokens, "le"))
        return
    if kind == "i16be":
        m.send(parse_i16_list(tokens, "be"))
        return
    raise ValueError(kind)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.gui:
        from .gui import main as gui_main

        return gui_main()

    if args.list:
        return _list_ports()

    if not args.port:
        print("Missing --port. Use --list to see ports.")
        return 2

    eol = NewlineConfig(args.eol)

    cfg = MonitorConfig(
        port=args.port,
        baudrate=args.baud,
        bytesize=args.bytesize,
        parity=args.parity,
        stopbits=args.stopbits,
        xonxoff=args.xonxoff,
        rtscts=args.rtscts,
        dsrdtr=args.dsrdtr,
        timeout=args.timeout,
        encoding=args.encoding,
        rx_mode=args.rx,
        timestamp=args.timestamp,
        log_path=args.log,
    )

    mon = SerialMonitor(cfg)
    try:
        mon.open()
    except Exception as exc:
        print(f"Failed to open {args.port}: {exc}")
        return 1

    mon.start()
    print("Connected. Type :help for commands. Type :quit to exit.")

    current_encoding = args.encoding
    current_rx = args.rx
    current_eol = eol

    try:
        while True:
            try:
                line = sys.stdin.readline()
            except KeyboardInterrupt:
                break
            if not line:
                break
            line = line.rstrip("\r\n")
            if not line:
                continue

            if line.startswith(":"):
                cmdline = line[1:].strip()
                if not cmdline:
                    continue
                parts = cmdline.split(" ", 1)
                cmd = parts[0].lower()
                rest = parts[1] if len(parts) > 1 else ""

                if cmd in ("q", "quit", "exit"):
                    break
                if cmd == "help":
                    print(_HELP)
                    continue
                if cmd == "flush":
                    mon.flush_input()
                    continue
                if cmd == "eol":
                    try:
                        current_eol = NewlineConfig(rest.strip())
                        _ = current_eol.suffix_bytes()
                    except FormatError as exc:
                        print(f"[ERR] {exc}")
                    continue
                if cmd == "encoding":
                    current_encoding = rest.strip() or current_encoding
                    continue
                if cmd == "rx":
                    new_rx = rest.strip().lower()
                    if new_rx not in ("text", "hex", "both"):
                        print("[ERR] rx must be text|hex|both")
                        continue
                    current_rx = new_rx
                    mon.config.rx_mode = new_rx  # type: ignore[assignment]
                    continue
                if cmd == "text":
                    try:
                        _send_text(mon, rest, current_encoding, current_eol, args.escapes)
                    except Exception as exc:
                        print(f"[ERR] {exc}")
                    continue
                if cmd == "hex":
                    try:
                        mon.send(parse_hex_string(rest))
                    except FormatError as exc:
                        print(f"[ERR] {exc}")
                    continue
                if cmd == "b64":
                    try:
                        mon.send(parse_base64(rest))
                    except FormatError as exc:
                        print(f"[ERR] {exc}")
                    continue
                if cmd in ("u16le", "u16be", "i16le", "i16be"):
                    try:
                        toks = _tokenize_args(rest)
                        _send_words(mon, toks, cmd)
                    except FormatError as exc:
                        print(f"[ERR] {exc}")
                    continue
                if cmd == "file":
                    path = rest.strip().strip('"')
                    if not path:
                        print("[ERR] missing file path")
                        continue
                    try:
                        with open(path, "rb") as f:
                            mon.send(f.read())
                    except Exception as exc:
                        print(f"[ERR] {exc}")
                    continue

                print("[ERR] unknown command. Type :help")
                continue

            # Plain input -> text
            try:
                _send_text(mon, line, current_encoding, current_eol, args.escapes)
            except Exception as exc:
                print(f"[ERR] {exc}")

    finally:
        mon.close()

    return 0
