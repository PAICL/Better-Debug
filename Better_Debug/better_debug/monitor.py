from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal, Optional

import serial


RxMode = Literal["text", "hex", "both"]


@dataclass
class MonitorConfig:
    port: str
    baudrate: int
    bytesize: int
    parity: str
    stopbits: float
    xonxoff: bool
    rtscts: bool
    dsrdtr: bool
    timeout: float
    encoding: str
    rx_mode: RxMode
    timestamp: bool
    log_path: Optional[str]


class SerialMonitor:
    def __init__(self, config: MonitorConfig):
        self.config = config
        self._ser: Optional[serial.Serial] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._log_lock = threading.Lock()
        self._log_fp = open(config.log_path, "a", encoding="utf-8") if config.log_path else None

    def open(self) -> None:
        if self._ser and self._ser.is_open:
            return
        self._ser = serial.Serial(
            port=self.config.port,
            baudrate=self.config.baudrate,
            bytesize=self.config.bytesize,
            parity=self.config.parity,
            stopbits=self.config.stopbits,
            xonxoff=self.config.xonxoff,
            rtscts=self.config.rtscts,
            dsrdtr=self.config.dsrdtr,
            timeout=self.config.timeout,
        )

    def start(self) -> None:
        if not self._ser or not self._ser.is_open:
            self.open()
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader_loop, name="serial-reader", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
        if self._log_fp:
            try:
                self._log_fp.close()
            except Exception:
                pass

    def flush_input(self) -> None:
        if self._ser:
            self._ser.reset_input_buffer()

    def send(self, payload: bytes) -> None:
        if not self._ser or not self._ser.is_open:
            raise RuntimeError("serial port not open")
        if not payload:
            return
        self._ser.write(payload)
        self._ser.flush()
        self._log("TX", payload)

    def _now_prefix(self) -> str:
        if not self.config.timestamp:
            return ""
        t = time.localtime()
        ms = int((time.time() % 1) * 1000)
        return time.strftime("%H:%M:%S", t) + f".{ms:03d} "

    def _log(self, direction: str, data: bytes) -> None:
        if not self._log_fp:
            return
        line = f"{self._now_prefix()}{direction} {data.hex(' ').upper()}\n"
        with self._log_lock:
            self._log_fp.write(line)
            self._log_fp.flush()

    def _emit(self, data: bytes) -> None:
        prefix = self._now_prefix()
        mode = self.config.rx_mode
        if mode in ("hex", "both"):
            print(prefix + "RX " + data.hex(" ").upper(), flush=True)
        if mode in ("text", "both"):
            try:
                text = data.decode(self.config.encoding, errors="replace")
            except LookupError:
                text = data.decode("utf-8", errors="replace")
            # Avoid double newlines from print
            end = "" if text.endswith("\n") else "\n"
            print(prefix + "RX " + text, end=end, flush=True)

    def _reader_loop(self) -> None:
        assert self._ser is not None
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(4096)
            except Exception as exc:
                print(f"[ERR] read failed: {exc}")
                break
            if not chunk:
                continue
            self._log("RX", chunk)
            self._emit(chunk)
