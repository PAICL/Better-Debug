from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

import serial
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


def _now_prefix(enable: bool) -> str:
    if not enable:
        return ""
    t = time.localtime()
    ms = int((time.time() % 1) * 1000)
    return time.strftime("%H:%M:%S", t) + f".{ms:03d} "


_BRACKET_TOKEN_RE = re.compile(r"^\[(?P<token>[^\]]{1,64})\]")
_TIME_TOKEN_RE = re.compile(r"^\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$")


def _extract_tag(line: str) -> str | None:
    """Extract stream tag from a line prefix.

    Supports patterns:
      [debug]message
      [00:11:22][debug]message   -> returns 'debug' (skips timestamp-like token)

    Returns None if no suitable tag is found.
    """
    s = line.lstrip()
    tokens: list[str] = []
    while True:
        m = _BRACKET_TOKEN_RE.match(s)
        if not m:
            break
        token = m.group("token").strip()
        tokens.append(token)
        s = s[m.end() :].lstrip()

    if not tokens:
        return None

    # Pick the first non-timestamp token.
    for token in tokens:
        if _TIME_TOKEN_RE.fullmatch(token):
            continue
        # Only tags whose first character is an ASCII letter are eligible.
        if token and ("A" <= token[0] <= "Z" or "a" <= token[0] <= "z"):
            return token
        return None
    return None


@dataclass
class GuiSerialConfig:
    port: str
    baud: int
    bytesize: int
    parity: str
    stopbits: float
    xonxoff: bool
    rtscts: bool
    dsrdtr: bool
    timeout: float
    encoding: str


def main() -> int:
    try:
        from PySide6 import QtCore, QtWidgets
    except Exception:
        print("PySide6 is not installed. Install with: pip install -r requirements-gui.txt")
        return 2

    class SerialReader(QtCore.QObject):
        rx = QtCore.Signal(bytes)
        err = QtCore.Signal(str)
        opened = QtCore.Signal(str)
        closed = QtCore.Signal()

        def __init__(self) -> None:
            super().__init__()
            self._ser: Optional[serial.Serial] = None
            self._stop = threading.Event()
            self._thread: Optional[threading.Thread] = None

        def is_open(self) -> bool:
            return bool(self._ser and self._ser.is_open)

        def open(self, cfg: GuiSerialConfig) -> None:
            if self.is_open():
                return
            try:
                self._ser = serial.Serial(
                    port=cfg.port,
                    baudrate=cfg.baud,
                    bytesize=cfg.bytesize,
                    parity=cfg.parity,
                    stopbits=cfg.stopbits,
                    xonxoff=cfg.xonxoff,
                    rtscts=cfg.rtscts,
                    dsrdtr=cfg.dsrdtr,
                    timeout=cfg.timeout,
                )
            except Exception as exc:
                self.err.emit(f"Failed to open {cfg.port}: {exc}")
                self._ser = None
                return

            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="qt-serial-reader", daemon=True)
            self._thread.start()
            self.opened.emit(cfg.port)

        def close(self) -> None:
            self._stop.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
            self._ser = None
            self.closed.emit()

        def flush_input(self) -> None:
            if self._ser:
                try:
                    self._ser.reset_input_buffer()
                except Exception as exc:
                    self.err.emit(f"Flush failed: {exc}")

        def send(self, payload: bytes) -> None:
            if not self.is_open() or not self._ser:
                self.err.emit("Serial port not open")
                return
            try:
                if payload:
                    self._ser.write(payload)
                    self._ser.flush()
            except Exception as exc:
                self.err.emit(f"Write failed: {exc}")

        def _loop(self) -> None:
            assert self._ser is not None
            while not self._stop.is_set():
                try:
                    chunk = self._ser.read(4096)
                except Exception as exc:
                    self.err.emit(f"Read failed: {exc}")
                    break
                if chunk:
                    self.rx.emit(chunk)

    class MainWindow(QtWidgets.QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Better Debug (Serial)")
            self.setMinimumWidth(200)

            self.reader = SerialReader()

            self._log_fp = None

            self._left_default_width = 240
            self._left_width = self._left_default_width
            self._left_hidden = False
            self._hide_threshold_width = 480

            # Give the splitter handles a visible style.
            self.setStyleSheet(
                "QSplitter::handle { background: palette(mid); }"
                "QSplitter::handle:horizontal { width: 6px; }"
                "QSplitter::handle:vertical { height: 6px; }"
            )

            central = QtWidgets.QWidget(self)
            self.setCentralWidget(central)

            self.port_cb = QtWidgets.QComboBox()
            self.refresh_btn = QtWidgets.QPushButton("Refresh")
            self.baud_cb = QtWidgets.QComboBox()
            self.baud_cb.setEditable(True)
            for b in [
                9600,
                19200,
                38400,
                57600,
                115200,
                230400,
                460800,
                921600,
                2000000,
                3000000,
            ]:
                self.baud_cb.addItem(str(b))
            self.baud_cb.setCurrentText("115200")

            self.open_btn = QtWidgets.QPushButton("Open")
            self.close_btn = QtWidgets.QPushButton("Close")
            self.close_btn.setEnabled(False)

            self.encoding_cb = QtWidgets.QComboBox()
            self.encoding_cb.setEditable(True)
            for enc in [
                "utf-8",
                "gbk",
                "gb2312",
                "ascii",
                "latin-1",
                "utf-16",
                "utf-16le",
                "utf-16be",
            ]:
                self.encoding_cb.addItem(enc)
            self.encoding_cb.setCurrentText("ascii")
            self.eol_cb = QtWidgets.QComboBox()
            self.eol_cb.addItems(["none", "lf", "cr", "crlf"])
            self.eol_cb.setCurrentText("crlf")

            self.rx_mode_cb = QtWidgets.QComboBox()
            self.rx_mode_cb.addItems(["both", "text", "hex"])
            # Default to text to avoid surprising HEX output.
            self.rx_mode_cb.setCurrentText("text")

            self.xonxoff_ck = QtWidgets.QCheckBox("XON/XOFF")
            self.rtscts_ck = QtWidgets.QCheckBox("RTS/CTS")
            self.dsrdtr_ck = QtWidgets.QCheckBox("DSR/DTR")
            self.escapes_ck = QtWidgets.QCheckBox("Escapes (\\n \\r \\xNN)")
            self.timestamp_ck = QtWidgets.QCheckBox("Timestamp")

            self.log_path_edit = QtWidgets.QLineEdit("")
            self.log_browse_btn = QtWidgets.QPushButton("Browse")

            self.rx_view = QtWidgets.QPlainTextEdit()
            self.rx_view.setReadOnly(True)

            # RX tabs (browser-like): [ALL] + dynamic tags
            self.rx_tabs = QtWidgets.QTabWidget()
            self.rx_tabs.setDocumentMode(True)
            self.rx_tabs.setMovable(False)
            self._rx_editors: dict[str, QtWidgets.QPlainTextEdit] = {}
            self._ensure_rx_tab("ALL")

            # For tag routing & optional timestamp prefixing we process complete lines.
            self._rx_line_buffer = ""

            self.send_mode_cb = QtWidgets.QComboBox()
            self.send_mode_cb.addItems([
                "text",
                "hex",
                "base64",
                "u16le",
                "u16be",
                "i16le",
                "i16be",
                "file",
            ])
            self.tx_edit = QtWidgets.QPlainTextEdit()
            self.tx_edit.setMinimumHeight(40)
            self.tx_edit.setMaximumHeight(10000)
            self.tx_edit.setPlaceholderText("Enter payload...\n(text mode supports multi-line)")
            self.send_btn = QtWidgets.QPushButton("Send")
            self.flush_btn = QtWidgets.QPushButton("Flush RX")

            # Left parameter panel (default width 120, user-resizable)
            self.left_panel = QtWidgets.QWidget()
            self.left_panel.setMinimumWidth(0)
            left_layout = QtWidgets.QVBoxLayout(self.left_panel)
            left_layout.setContentsMargins(6, 6, 6, 6)
            left_layout.setSpacing(6)

            left_layout.addWidget(QtWidgets.QLabel("Port"))
            left_layout.addWidget(self.port_cb)
            left_layout.addWidget(self.refresh_btn)

            left_layout.addWidget(QtWidgets.QLabel("Baud"))
            left_layout.addWidget(self.baud_cb)

            left_layout.addWidget(self.open_btn)
            left_layout.addWidget(self.close_btn)

            left_layout.addWidget(QtWidgets.QLabel("Encoding"))
            left_layout.addWidget(self.encoding_cb)

            left_layout.addWidget(QtWidgets.QLabel("EOL"))
            left_layout.addWidget(self.eol_cb)

            left_layout.addWidget(QtWidgets.QLabel("RX"))
            left_layout.addWidget(self.rx_mode_cb)

            # Toggle-like parameters should be checkboxes (square button on the left)
            left_layout.addWidget(self.xonxoff_ck)
            left_layout.addWidget(self.rtscts_ck)
            left_layout.addWidget(self.dsrdtr_ck)
            left_layout.addWidget(self.escapes_ck)
            left_layout.addWidget(self.timestamp_ck)

            left_layout.addWidget(self.flush_btn)

            left_layout.addWidget(QtWidgets.QLabel("Log"))
            left_layout.addWidget(self.log_path_edit)
            left_layout.addWidget(self.log_browse_btn)
            left_layout.addStretch(1)

            # Right panel: RX tabs + resizable TX editor area
            right_panel = QtWidgets.QWidget()
            right_layout = QtWidgets.QVBoxLayout(right_panel)
            right_layout.setContentsMargins(6, 6, 6, 6)
            right_layout.setSpacing(6)

            tx_panel = QtWidgets.QWidget()
            tx_layout = QtWidgets.QVBoxLayout(tx_panel)
            tx_layout.setContentsMargins(0, 0, 0, 0)
            tx_layout.setSpacing(6)

            tx_row = QtWidgets.QHBoxLayout()
            tx_row.setContentsMargins(0, 0, 0, 0)
            tx_row.addWidget(QtWidgets.QLabel("Send as"))
            tx_row.addWidget(self.send_mode_cb)
            tx_row.addStretch(1)
            tx_row.addWidget(self.send_btn)
            tx_layout.addLayout(tx_row)
            tx_layout.addWidget(self.tx_edit, 1)

            self.right_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
            self.right_splitter.setChildrenCollapsible(False)
            self.right_splitter.addWidget(self.rx_tabs)
            self.right_splitter.addWidget(tx_panel)
            self.right_splitter.setStretchFactor(0, 1)
            self.right_splitter.setStretchFactor(1, 0)
            right_layout.addWidget(self.right_splitter, 1)

            # Splitter: left parameter panel + right I/O panel
            self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
            self.splitter.setChildrenCollapsible(True)
            self.splitter.addWidget(self.left_panel)
            self.splitter.addWidget(right_panel)
            self.splitter.setStretchFactor(0, 0)
            self.splitter.setStretchFactor(1, 1)
            self.splitter.splitterMoved.connect(self.on_splitter_moved)

            layout = QtWidgets.QVBoxLayout(central)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self._build_toolbar(), 0)

            self.pages = QtWidgets.QStackedWidget()
            self.pages.addWidget(self.splitter)
            self.pages.addWidget(self._build_settings_page())
            layout.addWidget(self.pages, 1)

            self.status = self.statusBar()

            self.refresh_btn.clicked.connect(self.refresh_ports)
            self.open_btn.clicked.connect(self.on_open)
            self.close_btn.clicked.connect(self.on_close)
            self.send_btn.clicked.connect(self.on_send)
            self.flush_btn.clicked.connect(self.reader.flush_input)
            self.log_browse_btn.clicked.connect(self.browse_log)

            self.reader.rx.connect(self.on_rx)
            self.reader.err.connect(self.on_err)
            self.reader.opened.connect(self.on_opened)
            self.reader.closed.connect(self.on_closed)

            self.refresh_ports()

            # Apply initial left width
            self._apply_splitter_sizes()

            # Apply initial TX editor height (default 120)
            self._apply_right_splitter_sizes(120)

            # Apply initial settings (font/color/theme)
            self._apply_settings_to_all_views()

            # Restore persisted settings (or fall back to defaults)
            self._load_settings()

            # Ensure hide/show rule is applied based on current size
            self._auto_hide_left_panel_if_needed()

        def closeEvent(self, event):  # type: ignore[override]
            try:
                self._save_settings()
            except Exception:
                # Never block app close due to settings persistence
                pass
            super().closeEvent(event)

        def resizeEvent(self, event):  # type: ignore[override]
            super().resizeEvent(event)
            self._auto_hide_left_panel_if_needed()

        def on_splitter_moved(self, _pos: int, _index: int) -> None:
            sizes = self.splitter.sizes()
            if len(sizes) >= 2 and sizes[0] > 0:
                self._left_width = sizes[0]

        def _available_splitter_width(self) -> int:
            # Prefer splitter width; during early init it may be 0.
            w = int(self.splitter.width()) if hasattr(self, "splitter") else 0
            return max(w, 0)

        def _apply_splitter_sizes(self) -> None:
            total = self._available_splitter_width()
            if total <= 0:
                # Fall back to a reasonable default during first show
                self.splitter.setSizes([self._left_width, 1])
                return

            left = max(0, self._left_width)
            right = max(0, total - left)
            self.splitter.setSizes([left, right])

        def _apply_right_splitter_sizes(self, tx_height: int) -> None:
            total = int(self.right_splitter.height())
            if total <= 0:
                self.right_splitter.setSizes([1, tx_height])
                return
            tx_h = max(60, int(tx_height))
            rx_h = max(0, total - tx_h)
            self.right_splitter.setSizes([rx_h, tx_h])

        def _auto_hide_left_panel_if_needed(self) -> None:
            win_w = int(self.width())
            total = self._available_splitter_width()
            if total <= 0:
                return

            if win_w <= self._hide_threshold_width:
                if not self._left_hidden:
                    sizes = self.splitter.sizes()
                    if len(sizes) >= 2 and sizes[0] > 0:
                        self._left_width = sizes[0]
                    self._left_hidden = True
                # hide left panel
                self.splitter.setSizes([0, total])
                return

            # win_w > threshold: show left panel and keep its width constant while resizing
            if self._left_hidden:
                self._left_hidden = False
                if self._left_width <= 0:
                    self._left_width = self._left_default_width

            self._apply_splitter_sizes()

        def _build_toolbar(self):
            from PySide6 import QtWidgets, QtGui

            bar = QtWidgets.QToolBar()
            bar.setMovable(False)

            # Use standard icons to avoid external assets.
            serial_icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)
            settings_icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogDetailedView)

            self.act_serial = QtGui.QAction(serial_icon, "Serial", self)
            self.act_serial.setCheckable(True)
            self.act_settings = QtGui.QAction(settings_icon, "Settings", self)
            self.act_settings.setCheckable(True)

            group = QtGui.QActionGroup(self)
            group.setExclusive(True)
            group.addAction(self.act_serial)
            group.addAction(self.act_settings)
            self.act_serial.setChecked(True)

            self.act_serial.triggered.connect(lambda: self.pages.setCurrentIndex(0))
            self.act_settings.triggered.connect(lambda: self.pages.setCurrentIndex(1))

            bar.addAction(self.act_serial)
            bar.addSeparator()
            spacer = QtWidgets.QWidget()
            spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
            bar.addWidget(spacer)
            bar.addAction(self.act_settings)
            return bar

        def _build_settings_page(self):
            from PySide6 import QtWidgets

            w = QtWidgets.QWidget()
            layout = QtWidgets.QFormLayout(w)
            layout.setContentsMargins(12, 12, 12, 12)

            self.style_cb = QtWidgets.QComboBox()
            self.style_cb.addItems(["System", "Fusion"])

            self.font_cb = QtWidgets.QFontComboBox()
            self.font_size_sp = QtWidgets.QSpinBox()
            self.font_size_sp.setRange(6, 48)
            self.font_size_sp.setValue(10)

            self.text_color_btn = QtWidgets.QPushButton("Choose...")
            self._text_color = None

            layout.addRow("Style", self.style_cb)
            layout.addRow("Font", self.font_cb)
            layout.addRow("Font size", self.font_size_sp)
            layout.addRow("Text color", self.text_color_btn)

            self.style_cb.currentTextChanged.connect(self.on_style_changed)
            self.font_cb.currentFontChanged.connect(lambda _f: self._apply_settings_to_all_views())
            self.font_size_sp.valueChanged.connect(lambda _v: self._apply_settings_to_all_views())
            self.text_color_btn.clicked.connect(self.on_choose_text_color)
            return w

        def _settings(self):
            # QSettings backend is platform-specific:
            # - Windows: registry
            # - macOS: plist
            # - Linux: ini under ~/.config
            from PySide6 import QtCore

            return QtCore.QSettings("BetterDebug", "BetterDebug")

        def _save_settings(self) -> None:
            s = self._settings()
            s.beginGroup("window")
            s.setValue("geometry", self.saveGeometry())
            s.setValue("page", int(self.pages.currentIndex()))
            s.setValue("left_width", int(self._left_width))
            s.setValue("left_hidden", bool(self._left_hidden))
            s.setValue("splitter_sizes", self.splitter.sizes())
            s.setValue("right_splitter_sizes", self.right_splitter.sizes())
            s.endGroup()

            s.beginGroup("serial")
            # Store port device string (userData)
            s.setValue("port", self.port_cb.currentData() or "")
            s.setValue("baud", self.baud_cb.currentText().strip())
            s.setValue("encoding", self.encoding_cb.currentText().strip())
            s.setValue("eol", self.eol_cb.currentText())
            s.setValue("rx_mode", self.rx_mode_cb.currentText())
            s.setValue("xonxoff", bool(self.xonxoff_ck.isChecked()))
            s.setValue("rtscts", bool(self.rtscts_ck.isChecked()))
            s.setValue("dsrdtr", bool(self.dsrdtr_ck.isChecked()))
            s.setValue("escapes", bool(self.escapes_ck.isChecked()))
            s.setValue("timestamp", bool(self.timestamp_ck.isChecked()))
            s.setValue("log_path", self.log_path_edit.text())
            s.endGroup()

            s.beginGroup("appearance")
            s.setValue("style", self.style_cb.currentText() if hasattr(self, "style_cb") else "System")
            s.setValue("font_family", self.font_cb.currentFont().family() if hasattr(self, "font_cb") else "")
            s.setValue("font_size", int(self.font_size_sp.value()) if hasattr(self, "font_size_sp") else 10)
            s.setValue("text_color", self._text_color.name() if getattr(self, "_text_color", None) is not None else "")
            s.endGroup()

        def _load_settings(self) -> None:
            from PySide6 import QtGui

            s = self._settings()

            def _read_bool(group: str, key: str, default: bool) -> bool:
                """Read a bool from QSettings robustly.

                QSettings may return bool/int/str depending on platform/backend.
                """
                try:
                    v = s.value(key, default)
                except Exception:
                    return default
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(v)
                if v is None:
                    return default
                # QString may arrive as Python str
                text = str(v).strip().lower()
                if text in ("1", "true", "yes", "y", "on"):
                    return True
                if text in ("0", "false", "no", "n", "off", ""):
                    return False
                return default

            s.beginGroup("appearance")
            style = str(s.value("style", "System"))
            font_family = str(s.value("font_family", ""))
            try:
                font_size = int(s.value("font_size", 10))
            except Exception:
                font_size = 10
            text_color = str(s.value("text_color", ""))
            s.endGroup()

            # Apply appearance first
            if hasattr(self, "style_cb"):
                idx = self.style_cb.findText(style)
                if idx >= 0:
                    self.style_cb.setCurrentIndex(idx)
                else:
                    self.style_cb.setCurrentText(style)
                self.on_style_changed(self.style_cb.currentText())

            if hasattr(self, "font_cb") and font_family:
                self.font_cb.setCurrentFont(QtGui.QFont(font_family))
            if hasattr(self, "font_size_sp"):
                self.font_size_sp.setValue(font_size)
            if text_color:
                c = QtGui.QColor(text_color)
                if c.isValid():
                    self._text_color = c
            self._apply_settings_to_all_views()

            s.beginGroup("serial")
            saved_port = str(s.value("port", ""))
            saved_baud = str(s.value("baud", self.baud_cb.currentText()))
            saved_encoding = str(s.value("encoding", self.encoding_cb.currentText()))
            saved_eol = str(s.value("eol", self.eol_cb.currentText()))
            saved_rx = str(s.value("rx_mode", self.rx_mode_cb.currentText()))
            self.xonxoff_ck.setChecked(_read_bool("serial", "xonxoff", self.xonxoff_ck.isChecked()))
            self.rtscts_ck.setChecked(_read_bool("serial", "rtscts", self.rtscts_ck.isChecked()))
            self.dsrdtr_ck.setChecked(_read_bool("serial", "dsrdtr", self.dsrdtr_ck.isChecked()))
            self.escapes_ck.setChecked(_read_bool("serial", "escapes", self.escapes_ck.isChecked()))
            self.timestamp_ck.setChecked(_read_bool("serial", "timestamp", self.timestamp_ck.isChecked()))
            self.log_path_edit.setText(str(s.value("log_path", self.log_path_edit.text())))
            s.endGroup()

            # Refresh ports and re-select saved port if present
            self.refresh_ports()
            if saved_port:
                for i in range(self.port_cb.count()):
                    if self.port_cb.itemData(i) == saved_port:
                        self.port_cb.setCurrentIndex(i)
                        break

            if saved_baud:
                self.baud_cb.setCurrentText(saved_baud)
            if saved_encoding:
                self.encoding_cb.setCurrentText(saved_encoding)
            if saved_eol:
                self.eol_cb.setCurrentText(saved_eol)
            if saved_rx:
                self.rx_mode_cb.setCurrentText(saved_rx)

            s.beginGroup("window")
            geom = s.value("geometry")
            if geom is not None:
                try:
                    self.restoreGeometry(geom)
                except Exception:
                    pass

            try:
                self.pages.setCurrentIndex(int(s.value("page", 0)))
            except Exception:
                self.pages.setCurrentIndex(0)

            try:
                self._left_width = int(s.value("left_width", self._left_default_width))
            except Exception:
                self._left_width = self._left_default_width

            # Restore splitters if possible; otherwise fall back to our stored left width
            splitter_sizes = s.value("splitter_sizes")
            if isinstance(splitter_sizes, list) and len(splitter_sizes) >= 2:
                try:
                    self.splitter.setSizes([int(splitter_sizes[0]), int(splitter_sizes[1])])
                except Exception:
                    self._apply_splitter_sizes()
            else:
                self._apply_splitter_sizes()

            right_sizes = s.value("right_splitter_sizes")
            if isinstance(right_sizes, list) and len(right_sizes) >= 2:
                try:
                    self.right_splitter.setSizes([int(right_sizes[0]), int(right_sizes[1])])
                except Exception:
                    self._apply_right_splitter_sizes(120)
            s.endGroup()

        def on_style_changed(self, name: str) -> None:
            from PySide6 import QtWidgets

            if name == "Fusion":
                QtWidgets.QApplication.setStyle("Fusion")
            else:
                # System default
                QtWidgets.QApplication.setStyle(QtWidgets.QApplication.style().objectName())

        def on_choose_text_color(self) -> None:
            from PySide6 import QtWidgets

            color = QtWidgets.QColorDialog.getColor(parent=self)
            if not color.isValid():
                return
            self._text_color = color
            self._apply_settings_to_all_views()

        def _apply_settings_to_all_views(self) -> None:
            from PySide6 import QtGui

            font = QtGui.QFont(self.font_cb.currentFont()) if hasattr(self, "font_cb") else None
            size = int(self.font_size_sp.value()) if hasattr(self, "font_size_sp") else None
            if font and size:
                font.setPointSize(size)

            color_css = ""
            if getattr(self, "_text_color", None) is not None:
                c = self._text_color
                color_css = f"color: {c.name()};"

            # Apply to all RX editors and TX editor
            for ed in getattr(self, "_rx_editors", {}).values():
                if font:
                    ed.setFont(font)
                if color_css:
                    ed.setStyleSheet(color_css)

            if hasattr(self, "tx_edit"):
                if font:
                    self.tx_edit.setFont(font)
                if color_css:
                    self.tx_edit.setStyleSheet(color_css)

        def _ensure_rx_tab(self, tag: str) -> None:
            # tag is without brackets
            label = f"[{tag}]"
            if label in self._rx_editors:
                return
            ed = QtWidgets.QPlainTextEdit()
            ed.setReadOnly(True)
            self._rx_editors[label] = ed
            self.rx_tabs.addTab(ed, label)
            self._apply_settings_to_all_views()

        def browse_log(self) -> None:
            from PySide6 import QtWidgets

            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select log file", "serial.log", "Log (*.log);;All (*.*)")
            if path:
                self.log_path_edit.setText(path)

        def refresh_ports(self) -> None:
            self.port_cb.clear()
            for p in list_ports.comports():
                label = p.device
                if p.description:
                    label += f"  ({p.description})"
                self.port_cb.addItem(label, userData=p.device)

        def _cfg(self) -> GuiSerialConfig:
            port = self.port_cb.currentData()
            if not port:
                raise ValueError("No port selected")
            try:
                baud = int(self.baud_cb.currentText().strip())
            except ValueError:
                raise ValueError("Invalid baud")
            return GuiSerialConfig(
                port=port,
                baud=baud,
                bytesize=8,
                parity="N",
                stopbits=1,
                xonxoff=self.xonxoff_ck.isChecked(),
                rtscts=self.rtscts_ck.isChecked(),
                dsrdtr=self.dsrdtr_ck.isChecked(),
                timeout=0.1,
                encoding=self.encoding_cb.currentText().strip() or "ascii",
            )

        def _open_log(self) -> None:
            path = self.log_path_edit.text().strip()
            if not path:
                self._log_fp = None
                return
            try:
                self._log_fp = open(path, "a", encoding="utf-8")
            except Exception as exc:
                self._log_fp = None
                self.on_err(f"Open log failed: {exc}")

        def _log(self, direction: str, data: bytes) -> None:
            if not self._log_fp:
                return
            prefix = _now_prefix(self.timestamp_ck.isChecked())
            self._log_fp.write(f"{prefix}{direction} {data.hex(' ').upper()}\n")
            self._log_fp.flush()

        def on_open(self) -> None:
            try:
                cfg = self._cfg()
            except Exception as exc:
                self.on_err(str(exc))
                return
            self._open_log()
            self.reader.open(cfg)

        def on_close(self) -> None:
            self.reader.close()
            if self._log_fp:
                try:
                    self._log_fp.close()
                except Exception:
                    pass
                self._log_fp = None

        def on_opened(self, port: str) -> None:
            self.status.showMessage(f"Opened {port}")
            self.open_btn.setEnabled(False)
            self.close_btn.setEnabled(True)

        def on_closed(self) -> None:
            self.status.showMessage("Closed")
            self.open_btn.setEnabled(True)
            self.close_btn.setEnabled(False)

        def on_err(self, msg: str) -> None:
            self.status.showMessage(msg)

        def on_rx(self, data: bytes) -> None:
            self._log("RX", data)
            mode = self.rx_mode_cb.currentText()
            if mode in ("hex", "both"):
                # HEX goes to ALL
                all_ed = self._rx_editors.get("[ALL]")
                if all_ed:
                    # Keep HEX output chunk-based (each chunk on its own line).
                    prefix = _now_prefix(self.timestamp_ck.isChecked())
                    self._append_text(all_ed, prefix + data.hex(" ").upper() + "\n")
            if mode in ("text", "both"):
                enc = self.encoding_cb.currentText().strip() or "utf-8"
                try:
                    text = data.decode(enc, errors="replace")
                except LookupError:
                    text = data.decode("utf-8", errors="replace")

                all_ed = self._rx_editors.get("[ALL]")
                if not all_ed:
                    return

                # 1) ALL view should behave like a mature serial tool: stream output,
                #    i.e. do NOT insert an extra newline per received chunk.
                if not self.timestamp_ck.isChecked():
                    self._append_text(all_ed, text)
                else:
                    # If timestamp is enabled, prefix at line starts.
                    self._rx_line_buffer += text
                    self._drain_rx_lines_for_all_and_tags()

                # 2) Tag tabs: only route complete lines (typical debug logs are line-based).
                #    This avoids creating artifacts for streams with no newlines like "IPIPIP...".
                if self.timestamp_ck.isChecked():
                    # already drained above
                    return
                self._rx_line_buffer += text
                self._drain_rx_lines_for_tags_only()

        def _append_text(self, editor, text: str) -> None:
            """Append raw text to an editor without forcing an extra newline."""
            from PySide6 import QtGui

            cursor = editor.textCursor()
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
            cursor.insertText(text)
            editor.setTextCursor(cursor)
            editor.ensureCursorVisible()

        def _drain_rx_lines_for_all_and_tags(self) -> None:
            """Drain complete lines from buffer and write to ALL + tag tabs with timestamp prefixes."""
            all_ed = self._rx_editors.get("[ALL]")
            if not all_ed:
                return

            while True:
                idx = self._rx_line_buffer.find("\n")
                if idx == -1:
                    break
                raw_line = self._rx_line_buffer[: idx + 1]
                self._rx_line_buffer = self._rx_line_buffer[idx + 1 :]

                # Preserve the original content for tag extraction (no GUI timestamp).
                line_no_eol = raw_line.rstrip("\r\n")
                prefix = _now_prefix(True)
                out = prefix + line_no_eol + "\n"
                self._append_text(all_ed, out)

                tag = _extract_tag(line_no_eol)
                if tag:
                    self._ensure_rx_tab(tag)
                    tag_ed = self._rx_editors.get(f"[{tag}]")
                    if tag_ed:
                        self._append_text(tag_ed, out)

        def _drain_rx_lines_for_tags_only(self) -> None:
            """Drain complete lines from buffer and route them to tag tabs (no timestamp prefix)."""
            while True:
                idx = self._rx_line_buffer.find("\n")
                if idx == -1:
                    break
                raw_line = self._rx_line_buffer[: idx + 1]
                self._rx_line_buffer = self._rx_line_buffer[idx + 1 :]

                line_no_eol = raw_line.rstrip("\r\n")
                tag = _extract_tag(line_no_eol)
                if not tag:
                    continue
                self._ensure_rx_tab(tag)
                tag_ed = self._rx_editors.get(f"[{tag}]")
                if tag_ed:
                    self._append_text(tag_ed, raw_line)

        def on_send(self) -> None:
            mode = self.send_mode_cb.currentText()
            payload_text = self.tx_edit.toPlainText()
            enc = self.encoding_cb.currentText().strip() or "utf-8"
            eol = NewlineConfig(self.eol_cb.currentText())

            try:
                if mode == "text":
                    text = payload_text
                    if self.escapes_ck.isChecked():
                        text = apply_text_escapes(text)
                    # Send the full text content. If non-empty, append EOL once.
                    data = text.encode(enc, errors="replace")
                    if data:
                        data += eol.suffix_bytes()
                elif mode == "hex":
                    data = parse_hex_string(payload_text)
                elif mode == "base64":
                    data = parse_base64(payload_text)
                elif mode in ("u16le", "u16be", "i16le", "i16be"):
                    tokens = [t for t in payload_text.split() if t]
                    if mode == "u16le":
                        data = parse_u16_list(tokens, "le")
                    elif mode == "u16be":
                        data = parse_u16_list(tokens, "be")
                    elif mode == "i16le":
                        data = parse_i16_list(tokens, "le")
                    else:
                        data = parse_i16_list(tokens, "be")
                elif mode == "file":
                    from PySide6 import QtWidgets

                    path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select file", "", "All (*.*)")
                    if not path:
                        return
                    with open(path, "rb") as f:
                        data = f.read()
                else:
                    self.on_err("Unknown send mode")
                    return
            except FormatError as exc:
                self.on_err(str(exc))
                return
            except Exception as exc:
                self.on_err(str(exc))
                return

            self.reader.send(data)
            self._log("TX", data)
            self.status.showMessage(f"Sent {len(data)} bytes")

    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
