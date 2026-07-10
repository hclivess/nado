#!/usr/bin/env python3
"""
NADO Desktop Wallet — a professional, dark-themed PySide6 wallet for the NADO blockchain.

Self-contained single-file GUI. It does NOT touch any consensus code: every txid,
signature and proof-of-work is produced by the repo's own modules (signatures,
ops.transaction_ops, ops.mining_ops, ...), so the wallet can never desync from the
chain by reimplementing crypto. All node I/O goes over plain HTTP via `requests`.

Launch:
    python pyside_wallet.py
    python pyside_wallet.py --host 127.0.0.1 --port 9173

Optional dependency: PySide6 (see requirements.txt). The node itself does not need it.

----------------------------------------------------------------------------------------
Import shim
----------------------------------------------------------------------------------------
ops.transaction_ops / ops.block_ops pull in tornado/zstandard/coloredlogs at *module
load* time purely for the node's own networking + block storage — code paths this wallet
never executes (it talks to the node with `requests`). So that the wallet can reuse the
genuine, consensus-critical `draft_transaction`/`create_transaction`/`solve_registration_pow`
without dragging in the full node stack, we inject lightweight stand-ins for those three
third-party packages *only when they are not already installed*. On a real node host the
genuine packages are present and used unchanged.
"""

import os
import sys
import json
import types
import argparse
from decimal import Decimal, ROUND_DOWN, InvalidOperation

# --- make `import ops...` work regardless of the current working directory ---------------
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _install_repo_import_shim():
    """Stub the node-only heavy deps (tornado/zstandard/coloredlogs) if, and only if, they
    are missing, so the consensus tx-building functions remain importable in a lean wallet
    environment. Never overrides a real install."""

    class _Dummy:
        def __init__(self, *a, **k):
            """Accept any constructor signature so one stub class can stand in for anything."""
            pass

        def __getattr__(self, _name):
            """Every attribute resolves to a no-op callable — absorbs arbitrary stub API usage."""
            return lambda *a, **k: None

    def _stub(name, attrs=None):
        """Register a fake module under `name` in sys.modules (idempotent — never shadows a real install)."""
        if name in sys.modules:
            return sys.modules[name]
        mod = types.ModuleType(name)
        for key, val in (attrs or {}).items():
            setattr(mod, key, val)
        sys.modules[name] = mod
        return mod

    try:
        import tornado  # noqa: F401
    except ImportError:
        tornado = _stub("tornado")
        httpclient = _stub("tornado.httpclient", {"AsyncHTTPClient": object})
        tornado.httpclient = httpclient

    try:
        import coloredlogs  # noqa: F401
    except ImportError:
        _stub("coloredlogs", {"install": (lambda *a, **k: None)})

    try:
        import zstandard  # noqa: F401
    except ImportError:
        _stub("zstandard", {"ZstdCompressor": _Dummy, "ZstdDecompressor": _Dummy})


_install_repo_import_shim()

# --- REUSED repo modules (crypto + tx building + constants — never reimplemented here) ----
import protocol
from config import get_timestamp_seconds
from signatures import generate_keydict, from_private_key, sign, verify, unhex  # noqa: F401
from ops.address_ops import make_address, validate_address
from ops.key_ops import load_keys, generate_keys, save_keys
from ops.mining_ops import (
    solve_registration_pow,
    verify_registration_pow,
    lane_of,
)
from ops.transaction_ops import (
    draft_transaction,
    draft_open_lane_transaction,
    create_transaction,
    to_raw_amount,        # noqa: F401  (Decimal path used for input; kept for parity)
    to_readable_amount,
)

import requests
from ops import codec

from PySide6.QtCore import Qt, QTimer, QThreadPool, QRunnable, QObject, Signal, QRectF
from PySide6.QtGui import (
    QColor, QPalette, QPainter, QPainterPath, QLinearGradient, QGuiApplication,
    QAction, QPen, QBrush,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFormLayout, QFrame, QToolBar, QStatusBar, QMessageBox,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy, QFileDialog,
    QInputDialog, QComboBox, QSpinBox,
)


# =========================================================================================
# Protocol constants (pulled straight from protocol.py — single source of truth)
# =========================================================================================
DENOMINATION = protocol.DENOMINATION          # raw units per 1 NADO (1e10)
EPOCH_LENGTH = protocol.EPOCH_LENGTH           # slots per epoch (60)
K_OPEN = protocol.K_OPEN                        # open-lane slots per epoch (12)
OPEN_BPS = protocol.OPEN_BPS                    # open lane share in basis points (2000 = 20%)
B_MIN = protocol.B_MIN                          # raw per bonded selection share (100 NADO)
BOND_CAP = protocol.BOND_CAP                    # max effective bond per identity (10k NADO)
MIN_TX_FEE = protocol.MIN_TX_FEE                # deterministic min fee (raw)
AUTO_BOND_MIN_RAW = protocol.AUTO_BOND_MIN_RAW  # dust floor for an auto-bond (0.001 NADO)
AUTO_BOND_DEFAULT_PERCENT = protocol.AUTO_BOND_DEFAULT_PERCENT  # default auto-bond % when unset (80)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9173

# =========================================================================================
# Theme
# =========================================================================================
C_BG       = "#0e1116"
C_PANEL    = "#151a21"
C_PANEL2   = "#1b212b"
C_BORDER   = "#2a323e"
C_TEXT     = "#e7ebf2"
C_MUTED    = "#8a93a3"
C_ACCENT   = "#4c8bf5"
C_ACCENT_D = "#3b6fd4"
C_OPEN     = "#38bdf8"   # OPEN lane (free / no-coin)
C_BONDED   = "#a78bfa"   # BONDED lane (locked stake)
C_GOOD     = "#34d399"
C_BAD      = "#f87171"
C_WARN     = "#fbbf24"

STYLESHEET = f"""
QWidget {{
    background: {C_BG};
    color: {C_TEXT};
    font-family: "Segoe UI", "DejaVu Sans", "Inter", Arial, sans-serif;
    font-size: 13px;
}}
QFrame#Header {{
    background: {C_PANEL};
    border-bottom: 1px solid {C_BORDER};
}}
QLabel#Brand {{ font-size: 17px; font-weight: 700; color: {C_TEXT}; }}
QLabel#BrandMark {{ font-size: 17px; font-weight: 800; color: {C_ACCENT}; }}
QFrame#Card {{
    background: {C_PANEL2};
    border: 1px solid {C_BORDER};
    border-radius: 12px;
}}
QLabel#CardTitle {{ color: {C_MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QLabel#CardValue {{ color: {C_TEXT}; font-size: 21px; font-weight: 700; }}
QLabel#CardSub {{ color: {C_MUTED}; font-size: 11px; }}
QLabel#SectionTitle {{ color: {C_TEXT}; font-size: 15px; font-weight: 700; }}
QLabel#Hint {{ color: {C_MUTED}; font-size: 11px; }}
QLineEdit, QPlainTextEdit, QComboBox {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: {C_ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {C_ACCENT}; }}
QLineEdit#Address {{ font-family: "DejaVu Sans Mono", "Consolas", monospace; color: {C_TEXT}; }}
QLineEdit:read-only {{ color: {C_MUTED}; }}
QPushButton {{
    background: {C_PANEL2};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 8px 16px;
    color: {C_TEXT};
    font-weight: 600;
}}
QPushButton:hover {{ border: 1px solid {C_ACCENT}; }}
QPushButton:disabled {{ color: {C_MUTED}; border: 1px solid {C_BORDER}; }}
QPushButton#Primary {{ background: {C_ACCENT}; border: 1px solid {C_ACCENT}; color: #ffffff; }}
QPushButton#Primary:hover {{ background: {C_ACCENT_D}; border: 1px solid {C_ACCENT_D}; }}
QPushButton#Primary:disabled {{ background: {C_PANEL2}; border: 1px solid {C_BORDER}; color: {C_MUTED}; }}
QPushButton#Danger:hover {{ border: 1px solid {C_BAD}; color: {C_BAD}; }}
QTabWidget::pane {{ border: none; background: {C_BG}; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    color: {C_MUTED};
    padding: 10px 18px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{ color: {C_TEXT}; border-bottom: 2px solid {C_ACCENT}; }}
QTabBar::tab:hover {{ color: {C_TEXT}; }}
QStatusBar {{ background: {C_PANEL}; border-top: 1px solid {C_BORDER}; color: {C_MUTED}; }}
QStatusBar::item {{ border: none; }}
QToolBar {{ background: {C_PANEL}; border-bottom: 1px solid {C_BORDER}; spacing: 8px; padding: 6px 10px; }}
QToolBar QLabel {{ color: {C_MUTED}; }}
QTableWidget {{
    background: {C_PANEL2};
    border: 1px solid {C_BORDER};
    border-radius: 10px;
    gridline-color: {C_BORDER};
}}
QHeaderView::section {{
    background: {C_PANEL};
    color: {C_MUTED};
    border: none;
    border-bottom: 1px solid {C_BORDER};
    padding: 8px;
    font-weight: 700;
}}
QTableWidget::item {{ padding: 4px 6px; }}
QPlainTextEdit#Log {{ font-family: "DejaVu Sans Mono", "Consolas", monospace; font-size: 12px; color: {C_MUTED}; }}
QScrollBar:vertical {{ background: {C_BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {C_BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QCheckBox {{ color: {C_MUTED}; }}
"""


# =========================================================================================
# Formatting helpers
# =========================================================================================
def fmt_nado(raw, suffix=" NADO"):
    """raw integer -> human NADO string with thousands separators and trimmed decimals."""
    try:
        raw = int(raw)
    except (TypeError, ValueError):
        return "—"
    s = to_readable_amount(raw)  # reuse repo formatter -> 10 decimals
    whole, _, frac = s.partition(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    frac = (frac or "").rstrip("0")
    if len(frac) < 2:
        frac = (frac + "00")[:2]
    grouped = f"{int(whole):,}"
    return f"{'-' if neg else ''}{grouped}.{frac}{suffix}"


def nado_to_raw(text):
    """Parse a NADO amount string (up to 10 decimals) into integer raw units. Raises ValueError."""
    text = str(text).strip().replace(",", "")
    if not text:
        raise ValueError("empty amount")
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise ValueError("not a number")
    if d < 0:
        raise ValueError("amount cannot be negative")
    raw = int((d * Decimal(DENOMINATION)).to_integral_value(rounding=ROUND_DOWN))
    return raw


def humanize_seconds(seconds):
    """Seconds -> compact human duration using the two largest units ("3d 4h"); "—" for unknown/nonpositive."""
    if seconds is None:
        return "—"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if s <= 0:
        return "—"
    if s < 1:
        return "< 1 s"
    units = [("y", 31_536_000), ("d", 86_400), ("h", 3_600), ("m", 60), ("s", 1)]
    parts = []
    for name, size in units:
        if s >= size:
            val = int(s // size)
            s -= val * size
            parts.append(f"{val}{name}")
        if len(parts) == 2:
            break
    return " ".join(parts) if parts else "< 1 s"


# =========================================================================================
# Persistent wallet store (settings + key file location)
# =========================================================================================
class WalletStore:
    def __init__(self):
        """Create ~/.nado_wallet, seed defaults (node endpoint, key file path, auto-refresh), then
        overlay whatever wallet.json already holds."""
        self.dir = os.path.join(os.path.expanduser("~"), ".nado_wallet")
        os.makedirs(self.dir, exist_ok=True)
        self.settings_path = os.path.join(self.dir, "wallet.json")
        self.default_keyfile = os.path.join(self.dir, "keys.dat")
        self.settings = {
            "host": DEFAULT_HOST,
            "port": DEFAULT_PORT,
            "keyfile": self.default_keyfile,
            "auto_refresh": True,
        }
        self._load()

    def _load(self):
        """Overlay wallet.json onto the defaults; a missing or corrupt file silently keeps defaults."""
        try:
            with open(self.settings_path) as fh:
                self.settings.update(json.load(fh))
        except (FileNotFoundError, ValueError):
            pass

    def save(self):
        """Persist settings to wallet.json; write errors are swallowed — settings are a convenience,
        never worth crashing the wallet over."""
        try:
            with open(self.settings_path, "w") as fh:
                json.dump(self.settings, fh, indent=2)
        except OSError:
            pass

    def get(self, key, default=None):
        """Read a setting with a fallback."""
        return self.settings.get(key, default)

    def set(self, key, value):
        """Set a setting and persist immediately, so every change survives a crash."""
        self.settings[key] = value
        self.save()


# =========================================================================================
# Node HTTP client
# =========================================================================================
class NodeError(Exception):
    pass


class NodeClient:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=6.0):
        """Bind to one node endpoint; a shared requests.Session keeps HTTP connections alive
        across the wallet's frequent polling."""
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.session = requests.Session()

    def base(self):
        """Root URL of the node's HTTP API."""
        return f"http://{self.host}:{self.port}"

    def _get(self, path, params=None):
        """GET an endpoint -> (status_code, parsed JSON or raw text). Transport failures raise
        NodeError; HTTP error statuses are handed back for the caller to interpret per endpoint."""
        try:
            r = self.session.get(self.base() + path, params=params or {}, timeout=self.timeout)
        except requests.RequestException as exc:
            raise NodeError(str(exc))
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text

    # ---- read endpoints -----------------------------------------------------------------
    def resolve_alias(self, name):
        """Resolve an alias to its current owner address; None when unregistered or unreachable."""
        status, data = self._get("/resolve_alias", {"name": name})
        if status == 200 and isinstance(data, dict):
            return data.get("owner")   # None when unregistered
        return None

    def get_account(self, address):
        """Fetch account state (balance/bonded/registered/fidelity); None for an address the chain
        has never seen — callers treat that as a distinct 'not yet on chain' UI state."""
        status, data = self._get("/get_account", {"address": address})
        if status == 200 and isinstance(data, dict) and "balance" in data:
            return data
        return None  # unknown / never-funded address

    def mining_status(self, address):
        """Fetch the node's per-address selection snapshot (lane weights, epoch, beacon, win ETA).
        Raises NodeError on failure."""
        status, data = self._get("/mining_status", {"address": address})
        if status == 200 and isinstance(data, dict):
            return data
        raise NodeError(f"mining_status: {data}")

    def get_latest_block(self):
        """Fetch the chain-tip block dict. Raises NodeError — doubles as the connectivity probe."""
        status, data = self._get("/get_latest_block")
        if status == 200 and isinstance(data, dict):
            return data
        raise NodeError(f"get_latest_block: {data}")

    def get_latest_block_number(self):
        """Height of the chain tip."""
        return int(self.get_latest_block()["block_number"])

    def get_max_block(self):
        """Target block for a fresh tx: tip + 2, mirroring transaction_ops.get_max_block so
        wallet-built txs land in exactly the validity window the node expects."""
        # node convention (transaction_ops.get_max_block): latest + 2
        return self.get_latest_block_number() + 2

    def get_supply(self):
        """Fetch network supply totals (total / circulating / treasury). Raises NodeError."""
        status, data = self._get("/get_supply")
        if status == 200 and isinstance(data, dict):
            return data
        raise NodeError(f"get_supply: {data}")

    def get_transactions(self, address, min_block=0):
        """List an address's transactions from min_block on; returns [] on any failure — history
        is best-effort display data, never worth an error dialog."""
        status, data = self._get(
            "/get_transactions_of_account", {"address": address, "min_block": min_block}
        )
        if status == 200 and isinstance(data, dict):
            return data.get("transactions", [])
        return []

    # ---- write endpoint -----------------------------------------------------------------
    def submit_transaction(self, tx):
        """Submit a signed transaction via POST+JSON (a PQ tx is far too large for a GET URL)."""
        try:
            r = self.session.post(
                self.base() + "/submit_transaction",
                data=codec.pack(tx),
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise NodeError(str(exc))
        try:
            data = r.json()
        except ValueError:
            data = {"message": r.text}
        if not isinstance(data, dict):
            data = {"message": str(data)}
        data.setdefault("result", r.status_code == 200)
        data.setdefault("message", "")
        return data


# =========================================================================================
# Background worker plumbing (keeps the GUI thread responsive)
# =========================================================================================
class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn):
        """Wrap a zero-arg callable for QThreadPool; signals live on a separate QObject because
        QRunnable itself cannot emit."""
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self):
        """Execute on a pool thread: emit `result` on success or the stringified exception on
        `error` — exactly one of the two, and never an exception escaping into Qt."""
        try:
            res = self.fn()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI as an error string
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(res)


# =========================================================================================
# Reusable small widgets
# =========================================================================================
class StatCard(QFrame):
    """A titled value card used across the overview."""

    def __init__(self, title, value="—", sub="", parent=None):
        """Stack title/value/sub labels; the value is mouse-selectable so amounts can be copied."""
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        self.title = QLabel(title.upper())
        self.title.setObjectName("CardTitle")
        self.value = QLabel(value)
        self.value.setObjectName("CardValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.sub = QLabel(sub)
        self.sub.setObjectName("CardSub")
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value, sub=None, color=None):
        """Update the value in place, optionally recoloring it and replacing the sub line."""
        self.value.setText(str(value))
        if color:
            self.value.setStyleSheet(f"color: {color};")
        if sub is not None:
            self.sub.setText(sub)


def section_title(text):
    """QLabel styled as a section heading (SectionTitle in the stylesheet)."""
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    return lbl


def hint(text):
    """Muted, word-wrapped explainer QLabel (Hint style) for inline help under a heading."""
    lbl = QLabel(text)
    lbl.setObjectName("Hint")
    lbl.setWordWrap(True)
    return lbl


# =========================================================================================
# Selection visualization (pure QPainter — no matplotlib)
# =========================================================================================
class SelectionWidget(QWidget):
    """Draws the epoch's EPOCH_LENGTH slots split into OPEN (K_OPEN) vs BONDED lanes using the
    beacon-keyed permutation (mining_ops.lane_of), plus gauges for this wallet's share of each
    lane and the derived per-block win probability."""

    def __init__(self, parent=None):
        """Start as an empty expanding canvas; the slot layout is computed lazily in set_data,
        once per beacon."""
        super().__init__(parent)
        self.setMinimumHeight(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._data = None
        self._open_slots = set()
        self._beacon = None

    def set_data(self, status):
        """Ingest a mining_status payload and schedule a repaint. The open-slot set is recomputed
        only when the beacon changes — lane_of is deterministic per beacon, so caching avoids
        EPOCH_LENGTH hash calls on every refresh tick."""
        self._data = status or None
        beacon = (status or {}).get("beacon")
        if beacon and beacon != self._beacon:
            self._beacon = beacon
            # canonical, browser-reproducible lane layout — computed once per beacon
            try:
                self._open_slots = {j for j in range(EPOCH_LENGTH) if lane_of(j, beacon) == "open"}
            except Exception:
                self._open_slots = set()
        elif not beacon:
            self._beacon = None
            self._open_slots = set()
        self.update()

    # -- drawing helpers ------------------------------------------------------------------
    @staticmethod
    def _rounded(painter, rect, radius, color):
        """Fill a rounded-corner rectangle with a solid color (path fill, so it antialiases)."""
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, QColor(color))

    def _draw_gauge(self, painter, rect, frac, color, label, value_text):
        """Draw one labeled gauge: caption left, value right, gradient bar below. frac is clamped
        to [0,1] and any nonzero fill keeps a minimum width so tiny shares stay visible."""
        frac = max(0.0, min(1.0, frac or 0.0))
        painter.setPen(QColor(C_MUTED))
        f = painter.font()
        f.setPointSize(9)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(QRectF(rect.x(), rect.y(), rect.width(), 16),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label.upper())
        painter.setPen(QColor(C_TEXT))
        painter.drawText(QRectF(rect.x(), rect.y(), rect.width(), 16),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value_text)
        bar = QRectF(rect.x(), rect.y() + 20, rect.width(), 14)
        self._rounded(painter, bar, 7, C_PANEL)
        if frac > 0:
            fill = QRectF(bar.x(), bar.y(), max(14.0, bar.width() * frac), bar.height())
            grad = QLinearGradient(fill.topLeft(), fill.topRight())
            grad.setColorAt(0.0, QColor(color))
            grad.setColorAt(1.0, QColor(color).lighter(125))
            path = QPainterPath()
            path.addRoundedRect(fill, 7, 7)
            painter.fillPath(path, QBrush(grad))

    def paintEvent(self, _event):
        """Qt paint override — renders the full visualization each frame: lane legend, the epoch
        slot grid (lanes this wallet cannot win are dimmed, winnable ones outlined), and the two
        lane-share gauges plus the win-probability gauge. Degrades to neutral placeholders while
        no mining_status has arrived yet."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        W = self.width()
        m = 4
        data = self._data or {}

        # --- legend -----------------------------------------------------------------------
        f = painter.font()
        f.setPointSize(10)
        f.setBold(True)
        painter.setFont(f)
        k_open = data.get("k_open", K_OPEN)
        epoch_len = data.get("epoch_length", EPOCH_LENGTH)
        bonded_slots = epoch_len - k_open

        legend_y = m
        painter.setBrush(QColor(C_OPEN))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(m, legend_y, 13, 13), 3, 3)
        painter.setPen(QColor(C_TEXT))
        painter.drawText(QRectF(m + 19, legend_y - 2, 220, 18),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         f"OPEN lane · {k_open} slots ({OPEN_BPS // 100}%)")
        painter.setBrush(QColor(C_BONDED))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(m + 230, legend_y, 13, 13), 3, 3)
        painter.setPen(QColor(C_TEXT))
        painter.drawText(QRectF(m + 249, legend_y - 2, 240, 18),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         f"BONDED lane · {bonded_slots} slots")

        epoch = data.get("epoch")
        if epoch is not None:
            painter.setPen(QColor(C_MUTED))
            painter.drawText(QRectF(W - 200 - m, legend_y - 2, 200, 18),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"epoch #{epoch}")

        # --- slot grid --------------------------------------------------------------------
        grid_top = legend_y + 28
        cols = 12
        rows = (epoch_len + cols - 1) // cols
        gap = 7
        cell = (W - 2 * m - (cols - 1) * gap) / cols
        cell = max(10.0, min(cell, 46.0))
        my_open = data.get("my_open_weight", 0) or 0
        my_bonded = data.get("my_bonded_shares", 0) or 0
        eligible = (my_open > 0) or (my_bonded > 0)
        for idx in range(epoch_len):
            r = idx // cols
            c = idx % cols
            x = m + c * (cell + gap)
            y = grid_top + r * (cell + gap)
            is_open = idx in self._open_slots
            if not self._open_slots:
                base = QColor(C_PANEL2)
            else:
                base = QColor(C_OPEN if is_open else C_BONDED)
                # dim lanes the wallet cannot win, highlight the ones it can
                if is_open and my_open <= 0:
                    base = base.darker(190)
                if (not is_open) and my_bonded <= 0:
                    base = base.darker(190)
            rect = QRectF(x, y, cell, cell)
            path = QPainterPath()
            path.addRoundedRect(rect, 5, 5)
            painter.fillPath(path, base)
            if eligible and self._open_slots and (
                (is_open and my_open > 0) or ((not is_open) and my_bonded > 0)
            ):
                painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
                painter.drawPath(path)

        grid_bottom = grid_top + rows * (cell + gap)

        # --- gauges -----------------------------------------------------------------------
        total_open = data.get("total_open_weight", 0) or 0
        total_bonded = data.get("total_bonded_shares", 0) or 0
        open_frac = (my_open / total_open) if total_open else 0.0
        bonded_frac = (my_bonded / total_bonded) if total_bonded else 0.0
        exp_blocks = data.get("expected_blocks_between_wins")
        win_prob = (1.0 / exp_blocks) if exp_blocks else 0.0

        gy = grid_bottom + 14
        gh = 40
        col_w = (W - 2 * m - 24) / 2
        self._draw_gauge(
            painter, QRectF(m, gy, col_w, gh), open_frac, C_OPEN,
            "Your share · open lane",
            f"{my_open} / {total_open}  ({open_frac * 100:.1f}%)",
        )
        self._draw_gauge(
            painter, QRectF(m + col_w + 24, gy, col_w, gh), bonded_frac, C_BONDED,
            "Your share · bonded lane",
            f"{my_bonded} / {total_bonded}  ({bonded_frac * 100:.1f}%)",
        )
        self._draw_gauge(
            painter, QRectF(m, gy + gh + 18, W - 2 * m, gh), win_prob, C_GOOD,
            "Win probability per block",
            f"{win_prob * 100:.3f}%   ·   ~1 win / {humanize_seconds(data.get('expected_seconds_between_wins'))}",
        )
        painter.end()


# =========================================================================================
# Tabs
# =========================================================================================
class OverviewTab(QWidget):
    def __init__(self, app):
        """Assemble the account + network-supply stat-card grid and subscribe to the main
        window's refresh signals (all updates arrive via signals, never direct calls)."""
        super().__init__()
        self.app = app
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(16)

        root.addWidget(section_title("Account"))

        addr_row = QHBoxLayout()
        self.addr = QLineEdit()
        self.addr.setObjectName("Address")
        self.addr.setReadOnly(True)
        self.addr.setText("No wallet loaded")
        copy = QPushButton("Copy")
        copy.clicked.connect(self.app.copy_address)
        addr_row.addWidget(QLabel("Address"))
        addr_row.addWidget(self.addr, 1)
        addr_row.addWidget(copy)
        root.addLayout(addr_row)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_balance = StatCard("Spendable balance")
        self.c_bonded = StatCard("Bonded stake")
        self.c_total = StatCard("Total holdings")
        self.c_status = StatCard("Mining identity")
        self.c_fidelity = StatCard("Fidelity")
        self.c_height = StatCard("Chain height")
        grid.addWidget(self.c_balance, 0, 0)
        grid.addWidget(self.c_bonded, 0, 1)
        grid.addWidget(self.c_total, 0, 2)
        grid.addWidget(self.c_status, 1, 0)
        grid.addWidget(self.c_fidelity, 1, 1)
        grid.addWidget(self.c_height, 1, 2)
        root.addLayout(grid)

        root.addWidget(section_title("Network supply"))
        sgrid = QGridLayout()
        sgrid.setSpacing(14)
        self.c_total_supply = StatCard("Total supply")
        self.c_circulating = StatCard("Circulating")
        self.c_treasury = StatCard("Treasury")
        sgrid.addWidget(self.c_total_supply, 0, 0)
        sgrid.addWidget(self.c_circulating, 0, 1)
        sgrid.addWidget(self.c_treasury, 0, 2)
        root.addLayout(sgrid)
        root.addStretch(1)

        app.accountUpdated.connect(self.on_account)
        app.supplyUpdated.connect(self.on_supply)
        app.latestBlockUpdated.connect(self.on_block)
        app.walletChanged.connect(self.on_wallet)

    def on_wallet(self, keys):
        """Show the active wallet's address (slot for walletChanged)."""
        self.addr.setText(keys["address"] if keys else "No wallet loaded")

    def on_account(self, acc):
        """Repaint balance/bond/registration/fidelity cards from an account payload; None means
        the address has never been on chain, shown as a distinct 'Unknown' state, not an error."""
        if not acc:
            for c in (self.c_balance, self.c_bonded, self.c_total):
                c.set("—")
            self.c_status.set("Unknown", "address not yet on chain", C_MUTED)
            self.c_fidelity.set("—")
            return
        balance = acc.get("balance", 0)
        bonded = acc.get("bonded", 0)
        self.c_balance.set(fmt_nado(balance))
        self.c_bonded.set(fmt_nado(bonded))
        self.c_total.set(fmt_nado(balance + bonded))
        registered = acc.get("registered", 0)
        self.c_status.set(
            "Registered" if registered else "Not registered",
            "open-lane miner" if registered else "not mining",
            C_GOOD if registered else C_MUTED,
        )
        fidelity = acc.get("fidelity", 0)
        self.c_fidelity.set(str(fidelity), f"of {protocol.FIDELITY_CAP} epochs")

    def on_supply(self, sup):
        """Update the network supply cards (slot for supplyUpdated)."""
        self.c_total_supply.set(fmt_nado(sup.get("total_supply", 0)))
        self.c_circulating.set(fmt_nado(sup.get("circulating", 0)))
        self.c_treasury.set(fmt_nado(sup.get("treasury", 0)))

    def on_block(self, block):
        """Update the chain-height card (slot for latestBlockUpdated)."""
        self.c_height.set(f"#{block.get('block_number', 0):,}", "latest block")


class SendTab(QWidget):
    def __init__(self, app):
        """Build the recipient/amount form. The fee row is informational only — the fee is always
        the protocol minimum, chosen automatically, so there is deliberately no fee input."""
        super().__init__()
        self.app = app
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)
        root.addWidget(section_title("Send NADO"))

        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(12)
        self.recipient = QLineEdit()
        self.recipient.setPlaceholderText("ndo… recipient address")
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0.0")
        form.addRow("Recipient", self.recipient)
        form.addRow("Amount (NADO)", self.amount)
        form.addRow("Network fee", QLabel(f"{fmt_nado(MIN_TX_FEE)} (automatic)"))
        root.addWidget(card)
        root.addWidget(hint(
            "Amounts are in NADO. The tiny network fee is set automatically to the protocol "
            "minimum and destroyed (not paid to anyone) — you don't need to think about it."
        ))

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.send_btn = QPushButton("Review & send")
        self.send_btn.setObjectName("Primary")
        self.send_btn.clicked.connect(self.do_send)
        btn_row.addWidget(self.send_btn)
        root.addLayout(btn_row)
        root.addStretch(1)

    def do_send(self):
        """Validate the recipient (ndo… address, or a registered alias resolved via the node) and
        amount, show an explicit confirmation summary, then build+submit off-thread. The send
        button stays disabled until the worker reports back so a double-click can't double-send."""
        if not self.app.require_wallet():
            return
        # lowercase: alias names are all-lowercase on-chain and ndo… addresses are lowercase hex,
        # so "Alice" is accepted and sends to "alice".
        recipient = self.recipient.text().strip().lower()
        resolved = None
        if not validate_address(recipient):
            # not an address — accept a registered alias (the chain credits its current owner)
            if (protocol.ALIAS_MIN_LEN <= len(recipient) <= protocol.ALIAS_MAX_LEN
                    and not recipient.startswith("ndo")):
                try:
                    resolved = self.app.client.resolve_alias(recipient)
                except NodeError:
                    resolved = None
            if not resolved:
                self.app.error("Invalid recipient",
                               "The recipient is not a valid NADO address or a registered alias.")
                return
        try:
            amount_raw = nado_to_raw(self.amount.text())
        except ValueError as exc:
            self.app.error("Invalid amount", str(exc))
            return
        if amount_raw <= 0:
            self.app.error("Invalid amount", "Amount must be greater than zero.")
            return
        fee = MIN_TX_FEE                          # automatic network fee (no raw-units entry)
        to_line = f"{recipient}  (alias → {resolved})" if resolved else recipient
        summary = (f"Send  {fmt_nado(amount_raw)}\n"
                   f"To    {to_line}\n"
                   f"Fee   {fmt_nado(fee)} (network fee)")
        if not self.app.confirm("Confirm transfer", summary):
            return
        self.send_btn.setEnabled(False)
        self.app.submit_async(
            lambda: self.app.build_transfer(recipient, amount_raw, fee),
            done=lambda _ok: self.send_btn.setEnabled(True),
        )


class BondTab(QWidget):
    def __init__(self, app):
        """Build the bond/unbond form: one amount field plus a direction combo (both directions
        are the same transfer tx with a magic recipient, so one form serves both)."""
        super().__init__()
        self.app = app
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)
        root.addWidget(section_title("Bond / Unbond stake"))
        root.addWidget(hint(
            f"Bonding locks spendable balance into refundable stake that earns weight in the "
            f"BONDED mining lane. Selection weight is capped & split-neutral: one share per "
            f"{fmt_nado(B_MIN)} bonded, up to {fmt_nado(BOND_CAP)} effective per identity. Bonding "
            f"pays the tiny automatic network fee ({fmt_nado(MIN_TX_FEE)}); unbonding is free. "
            f"Unbonding moves stake back toward spendable balance (subject to the node's unlock delay)."
        ))

        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(12)
        self.direction = QComboBox()
        self.direction.addItems(["Bond  (balance → stake)", "Unbond  (stake → balance)"])
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0.0")
        form.addRow("Action", self.direction)
        form.addRow("Amount (NADO)", self.amount)
        form.addRow("Network fee", QLabel(f"bond: {fmt_nado(MIN_TX_FEE)} · unbond: free"))
        root.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn = QPushButton("Review & submit")
        self.btn.setObjectName("Primary")
        self.btn.clicked.connect(self.do_submit)
        btn_row.addWidget(self.btn)
        root.addLayout(btn_row)
        root.addStretch(1)

    def do_submit(self):
        """Validate + confirm, then submit a bond or unbond transfer off-thread. Bond pays the
        automatic MIN_TX_FEE; unbond MUST carry fee=0 (fee-exempt on-chain — the node rejects a
        fee-bearing unbond), which is why the fee is derived from the direction, never entered."""
        if not self.app.require_wallet():
            return
        is_bond = self.direction.currentIndex() == 0
        recipient = "bond" if is_bond else "unbond"
        try:
            amount_raw = nado_to_raw(self.amount.text())
        except ValueError as exc:
            self.app.error("Invalid amount", str(exc))
            return
        if amount_raw <= 0:
            self.app.error("Invalid amount", "Amount must be greater than zero.")
            return
        # bond pays the automatic network fee; unbond is FEE-EXEMPT on-chain (fee MUST be 0 or the node
        # rejects it) — never attach a fee to an unbond.
        fee = MIN_TX_FEE if is_bond else 0
        verb = "Bond" if is_bond else "Unbond"
        fee_line = f"Fee   {fmt_nado(fee)} (network fee)" if is_bond else "Fee   none (unbonding is free)"
        summary = f"{verb}  {fmt_nado(amount_raw)}\n{fee_line}"
        if not self.app.confirm(f"Confirm {verb.lower()}", summary):
            return
        self.btn.setEnabled(False)
        self.app.submit_async(
            lambda: self.app.build_transfer(recipient, amount_raw, fee),
            done=lambda _ok: self.btn.setEnabled(True),
        )


class MiningTab(QWidget):
    def __init__(self, app):
        """Build the mining dashboard: ETA hero card, presence/weight/epoch stat cards, the
        auto-bond percentage control and the activity log, all driven by the main window's
        mining signals (the tab holds no mining state of its own)."""
        super().__init__()
        self.app = app
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.addWidget(section_title("Open-lane mining"))
        header.addStretch(1)
        self.register_btn = QPushButton("Register & start mining")
        self.register_btn.setObjectName("Primary")
        self.register_btn.clicked.connect(self.app.register_and_mine)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.clicked.connect(self.app.stop_mining)
        self.stop_btn.setEnabled(False)
        header.addWidget(self.register_btn)
        header.addWidget(self.stop_btn)
        root.addLayout(header)

        root.addWidget(hint(
            "Register once with a light proof-of-work (a few seconds, no coins needed), then this "
            "wallet posts a signed heartbeat every epoch so the node counts you as present. The "
            "open lane is capital-free and structurally capped at the network's open-lane share."
        ))

        # expected-time hero card
        hero = QFrame()
        hero.setObjectName("Card")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(20, 18, 20, 18)
        hero_l.setSpacing(4)
        t = QLabel("EXPECTED TIME TO MINE A BLOCK")
        t.setObjectName("CardTitle")
        self.eta = QLabel("—")
        self.eta.setStyleSheet(f"color:{C_ACCENT}; font-size:34px; font-weight:800;")
        self.eta_sub = QLabel("Register and stay present to start earning.")
        self.eta_sub.setObjectName("CardSub")
        hero_l.addWidget(t)
        hero_l.addWidget(self.eta)
        hero_l.addWidget(self.eta_sub)
        root.addWidget(hero)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_present = StatCard("Presence")
        self.c_open = StatCard("Open weight")
        self.c_bonded = StatCard("Bonded shares")
        self.c_epoch = StatCard("Epoch")
        grid.addWidget(self.c_present, 0, 0)
        grid.addWidget(self.c_open, 0, 1)
        grid.addWidget(self.c_bonded, 0, 2)
        grid.addWidget(self.c_epoch, 0, 3)
        root.addLayout(grid)

        # AUTO-BOND: compound a % of mining rewards straight into bonded stake while mining (mirrors the
        # node's headless auto_bond_percent and the browser miner's setting). Once per epoch, dust-floored,
        # stops at BOND_CAP.
        ab_row = QHBoxLayout()
        ab_row.addWidget(QLabel("Auto-bond mining rewards"))
        self.auto_bond_spin = QSpinBox()
        self.auto_bond_spin.setRange(0, 100)
        self.auto_bond_spin.setSuffix(" %")
        self.auto_bond_spin.setValue(int(self.app.auto_bond_pct))
        self.auto_bond_spin.setToolTip(
            "While mining, automatically bond this percentage of each block reward you earn — "
            "compounding your bonded-lane weight hands-free. Capped at BOND_CAP; 0 = off.")
        self.auto_bond_spin.valueChanged.connect(self.app.set_auto_bond_pct)
        ab_row.addWidget(self.auto_bond_spin)
        ab_row.addStretch(1)
        root.addLayout(ab_row)
        self.auto_bond_note = QLabel()
        self.auto_bond_note.setObjectName("CardSub")
        root.addWidget(self.auto_bond_note)
        self.update_auto_bond_note(int(self.app.auto_bond_pct))
        app.autoBondChanged.connect(self.update_auto_bond_note)

        root.addWidget(QLabel("Activity"))
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        root.addWidget(self.log)
        root.addStretch(1)

        app.miningUpdated.connect(self.on_mining)
        app.miningActiveChanged.connect(self.on_active)
        app.miningLog.connect(self.append_log)

    def append_log(self, text):
        """Append a line to the activity log (slot for miningLog)."""
        self.log.appendPlainText(text)

    def on_active(self, active):
        """Sync button states/labels with the heartbeat loop (slot for miningActiveChanged)."""
        self.stop_btn.setEnabled(active)
        self.register_btn.setText("Mining active — heartbeats running" if active
                                  else "Register & start mining")

    def update_auto_bond_note(self, pct):
        """Refresh the one-line auto-bond explainer for the current percentage (0 = off)."""
        self.auto_bond_note.setText(
            f"On — bonding {pct}% of new mining rewards each epoch (auto-compounding the bonded lane)."
            if pct else "Off — mining rewards stay in your spendable balance.")

    def on_mining(self, status):
        """Repaint presence, lane weights, epoch and win ETA from a mining_status payload; the
        ETA sub-line distinguishes 'present but no selection weight yet' (fidelity still ramping)
        from 'not registered at all'."""
        present = status.get("registered_present")
        self.c_present.set(
            "Present" if present else "Absent",
            "counted this epoch" if present else "no recent heartbeat",
            C_GOOD if present else C_MUTED,
        )
        my_open = status.get("my_open_weight", 0)
        total_open = status.get("total_open_weight", 0)
        self.c_open.set(str(my_open), f"of {total_open} total")
        my_bonded = status.get("my_bonded_shares", 0)
        total_bonded = status.get("total_bonded_shares", 0)
        self.c_bonded.set(str(my_bonded), f"of {total_bonded} total")
        self.c_epoch.set(f"#{status.get('epoch', 0)}",
                         f"{status.get('k_open', K_OPEN)}/{status.get('epoch_length', EPOCH_LENGTH)} open slots")
        secs = status.get("expected_seconds_between_wins")
        blocks = status.get("expected_blocks_between_wins")
        self.eta.setText(humanize_seconds(secs))
        if blocks:
            self.eta_sub.setText(f"≈ 1 win every {blocks:,.0f} blocks  ·  "
                                 f"{(1.0 / blocks) * 100:.3f}% chance per block")
        elif present:
            self.eta_sub.setText("Present, but no selection weight yet — fidelity ramps with presence.")
        else:
            self.eta_sub.setText("Register and stay present to start earning.")


class SelectionTab(QWidget):
    def __init__(self, app):
        """Host the SelectionWidget and pipe every miningUpdated payload straight into it."""
        super().__init__()
        self.app = app
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)
        root.addWidget(section_title("Epoch selection lanes"))
        root.addWidget(hint(
            "Each epoch's slots are split by a beacon-keyed permutation into the OPEN lane and the "
            "BONDED lane. The split is over slot indices, so the open lane is always exactly its "
            "configured share no matter how many identities register. Slots you can win are "
            "highlighted; gauges show your share of each lane."
        ))
        self.view = SelectionWidget()
        root.addWidget(self.view, 1)
        app.miningUpdated.connect(self.view.set_data)


class HistoryTab(QWidget):
    COLS = ["Time", "Type", "Counterparty", "Amount", "Fee", "Tx"]

    def __init__(self, app):
        """Build the transactions table. History is fetched on demand (Refresh button) rather
        than on the auto-refresh timer to keep the polling loop cheap."""
        super().__init__()
        self.app = app
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(section_title("Transaction history"))
        header.addStretch(1)
        self.refresh_btn = QPushButton("Refresh history")
        self.refresh_btn.clicked.connect(self.app.refresh_history)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for i in (0, 1, 3, 4, 5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)
        app.historyUpdated.connect(self.on_history)

    def on_history(self, txs):
        """Rebuild the table from a raw tx list: newest first, each row classified as Send /
        Receive / protocol op (bond, unbond, register, heartbeat), direction-colored, with
        addresses and txids ellipsized (full txid available via tooltip)."""
        import datetime
        me = self.app.keys["address"] if self.app.keys else None
        rows = sorted(txs, key=lambda t: t.get("timestamp", 0), reverse=True)
        self.table.setRowCount(len(rows))
        for r, tx in enumerate(rows):
            sender = tx.get("sender", "")
            recipient = tx.get("recipient", "")
            outgoing = sender == me
            if recipient in ("bond", "unbond", "register", "heartbeat"):
                kind = recipient.capitalize()
                counter = "—"
                color = C_MUTED
            elif outgoing:
                kind = "Send"
                counter = recipient
                color = C_BAD
            else:
                kind = "Receive"
                counter = sender
                color = C_GOOD
            amount = tx.get("amount", 0)
            sign_ = "-" if (outgoing and amount) else ("+" if amount else "")
            ts = tx.get("timestamp")
            try:
                when = datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M") if ts else "—"
            except (ValueError, OSError, OverflowError):
                when = "—"
            txid = tx.get("txid", "")
            values = [
                when,
                kind,
                counter if counter == "—" else (counter[:10] + "…" + counter[-6:]),
                (sign_ + fmt_nado(amount, suffix="")) if amount else "0",
                f"{tx.get('fee', 0):,}",
                (txid[:10] + "…") if txid else "—",
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 1:
                    item.setForeground(QColor(color))
                if c in (3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c == 5 and txid:
                    item.setToolTip(txid)
                self.table.setItem(r, c, item)


# =========================================================================================
# Main window — owns state, networking orchestration and tx building
# =========================================================================================
class WalletWindow(QMainWindow):
    accountUpdated = Signal(object)
    miningUpdated = Signal(object)
    supplyUpdated = Signal(object)
    latestBlockUpdated = Signal(object)
    historyUpdated = Signal(object)
    walletChanged = Signal(object)
    connectionChanged = Signal(bool, str)
    miningActiveChanged = Signal(bool)
    miningLog = Signal(str)
    autoBondChanged = Signal(int)

    def __init__(self, store, host, port):
        """Wire the whole app: node client, persisted settings, tabs, and the two timers
        (8 s auto-refresh polling; per-epoch mining heartbeats). Threading contract: every
        blocking node call runs in a QThreadPool Worker, and results come back to widgets
        exclusively through the class signals above — nothing off the GUI thread touches Qt."""
        super().__init__()
        self.store = store
        self.keys = None
        self.pool = QThreadPool.globalInstance()
        self.client = NodeClient(host, port)
        self.connected = False
        self.block_time = 60.0
        self.mining_active = False
        self._last_hb_epoch = None
        # AUTO-BOND: compound a % of newly-mined earnings into bonded stake while mining. Defaults to
        # AUTO_BOND_DEFAULT_PERCENT (80) when the user has never chosen one; an explicit stored 0 (off)
        # is honoured (so we distinguish "unset" from "off" rather than using `or`, which would map 0->80).
        _ab = store.get("auto_bond_pct")
        self.auto_bond_pct = AUTO_BOND_DEFAULT_PERCENT if _ab is None else max(0, min(100, int(_ab)))
        self.auto_bond_baseline = None
        self._last_auto_bond_epoch = None

        self.setWindowTitle("NADO Wallet")
        self.resize(1080, 760)

        self._build_toolbar()
        self._build_header()
        self._build_tabs()
        self._build_statusbar()

        # timers
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_all)
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._heartbeat_tick)

        self._load_initial_keys()
        if store.get("auto_refresh", True):
            self.refresh_timer.start(8000)
        QTimer.singleShot(150, self.refresh_all)

    # ---- UI construction ----------------------------------------------------------------
    def _build_toolbar(self):
        """Toolbar: Wallet menu, editable node host:port with a Connect button, manual Refresh."""
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        wallet_menu = QPushButton("Wallet ▾")
        menu = self._wallet_menu()
        wallet_menu.setMenu(menu)
        tb.addWidget(wallet_menu)
        tb.addSeparator()

        tb.addWidget(QLabel("  Node "))
        self.host_edit = QLineEdit(self.client.host)
        self.host_edit.setFixedWidth(140)
        self.port_edit = QLineEdit(str(self.client.port))
        self.port_edit.setFixedWidth(70)
        tb.addWidget(self.host_edit)
        tb.addWidget(QLabel(":"))
        tb.addWidget(self.port_edit)
        connect = QPushButton("Connect")
        connect.clicked.connect(self.apply_node_settings)
        tb.addWidget(connect)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_all)
        tb.addWidget(refresh)

    def _wallet_menu(self):
        """Build the Wallet dropdown (new / import / open key file / copy address / reveal key)."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act_new = QAction("New wallet…", self)
        act_new.triggered.connect(self.new_wallet)
        act_import = QAction("Import private key…", self)
        act_import.triggered.connect(self.import_private_key)
        act_open = QAction("Open key file…", self)
        act_open.triggered.connect(self.open_keyfile)
        act_reveal = QAction("Reveal private key…", self)
        act_reveal.triggered.connect(self.reveal_private_key)
        act_copy = QAction("Copy address", self)
        act_copy.triggered.connect(self.copy_address)
        menu.addAction(act_new)
        menu.addAction(act_import)
        menu.addAction(act_open)
        menu.addSeparator()
        menu.addAction(act_copy)
        menu.addAction(act_reveal)
        return menu

    def _build_header(self):
        """Brand header with the always-visible address + balance, kept live via signal lambdas.
        Also creates the central widget's outer layout that _build_tabs later extends."""
        header = QFrame()
        header.setObjectName("Header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 12, 18, 12)
        mark = QLabel("◆")
        mark.setObjectName("BrandMark")
        brand = QLabel("NADO Wallet")
        brand.setObjectName("Brand")
        lay.addWidget(mark)
        lay.addWidget(brand)
        lay.addSpacing(18)

        self.header_addr = QLineEdit("No wallet loaded")
        self.header_addr.setObjectName("Address")
        self.header_addr.setReadOnly(True)
        copy = QPushButton("Copy")
        copy.clicked.connect(self.copy_address)
        lay.addWidget(self.header_addr, 1)
        lay.addWidget(copy)
        lay.addSpacing(12)

        self.header_balance = QLabel("—")
        self.header_balance.setStyleSheet(f"font-size:16px; font-weight:700; color:{C_TEXT};")
        lay.addWidget(self.header_balance)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(header)
        self._central_outer = outer
        self.setCentralWidget(central)

        self.accountUpdated.connect(
            lambda acc: self.header_balance.setText(fmt_nado(acc["balance"]) if acc else "—")
        )
        self.walletChanged.connect(
            lambda keys: self.header_addr.setText(keys["address"] if keys else "No wallet loaded")
        )

    def _build_tabs(self):
        """Instantiate the six tabs (each subscribes to signals in its own constructor) and
        mount them under the header."""
        self.tabs = QTabWidget()
        self.overview = OverviewTab(self)
        self.send = SendTab(self)
        self.bond = BondTab(self)
        self.mining = MiningTab(self)
        self.selection = SelectionTab(self)
        self.history = HistoryTab(self)
        self.tabs.addTab(self.overview, "Overview")
        self.tabs.addTab(self.send, "Send")
        self.tabs.addTab(self.bond, "Bond / Unbond")
        self.tabs.addTab(self.mining, "Mining")
        self.tabs.addTab(self.selection, "Selection")
        self.tabs.addTab(self.history, "History")
        self._central_outer.addWidget(self.tabs, 1)

    def _build_statusbar(self):
        """Status bar: connection dot + text (driven by connectionChanged) and a right-aligned
        slot for transient flash() messages."""
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.conn_dot = QLabel("●")
        self.conn_dot.setStyleSheet(f"color:{C_BAD};")
        self.conn_text = QLabel("Disconnected")
        sb.addWidget(self.conn_dot)
        sb.addWidget(self.conn_text)
        self.status_msg = QLabel("")
        sb.addPermanentWidget(self.status_msg)
        self.connectionChanged.connect(self._on_connection)

    def _on_connection(self, ok, text):
        """Update the connection indicator (slot for connectionChanged)."""
        self.connected = ok
        self.conn_dot.setStyleSheet(f"color:{C_GOOD if ok else C_BAD};")
        self.conn_text.setText(text)

    # ---- key management -----------------------------------------------------------------
    def _load_initial_keys(self):
        """Load the key file remembered in settings at startup; always emits walletChanged (with
        None when absent/unreadable) so every tab renders a consistent no-wallet state."""
        keyfile = self.store.get("keyfile")
        if keyfile and os.path.isfile(keyfile):
            try:
                self.keys = load_keys(file=keyfile)
                self.walletChanged.emit(self.keys)
                return
            except Exception as exc:  # noqa: BLE001
                self.error("Key load failed", f"Could not load {keyfile}:\n{exc}")
        self.walletChanged.emit(None)

    def _set_keys(self, keydict, save_to=None):
        """Adopt a new keydict: persist it, remember the path, stop any heartbeat loop still keyed
        to the old identity, then broadcast walletChanged and refresh everything."""
        self.keys = keydict
        path = save_to or self.store.get("keyfile")
        try:
            save_keys(keydict, file=path)
            self.store.set("keyfile", path)
        except Exception as exc:  # noqa: BLE001
            self.error("Could not save key file", str(exc))
        self.stop_mining()
        self.walletChanged.emit(keydict)
        self.refresh_all()

    def new_wallet(self):
        """Generate a fresh key pair (after confirming replacement of a loaded wallet — the old
        key file gets overwritten) and prompt the user to back up the new private key."""
        if self.keys and not self.confirm(
            "Replace current wallet?",
            "A new key pair will be generated and saved as the active wallet.\n"
            "Make sure the current private key is backed up first.",
        ):
            return
        keydict = generate_keys()
        self._set_keys(keydict)
        self.info("New wallet created",
                  f"Address:\n{keydict['address']}\n\nBack up your private key via "
                  f"Wallet → Reveal private key.")

    def import_private_key(self):
        """Import a 64-hex private key; the derived address is cross-checked against make_address
        so a corrupted paste can never silently install a wallet whose funds we can't spend."""
        sk, ok = QInputDialog.getText(self, "Import private key",
                                      "Enter the 64-character hex private key:")
        if not ok or not sk.strip():
            return
        try:
            keydict = from_private_key(sk.strip())
            assert make_address(keydict["public_key"]) == keydict["address"]
        except Exception as exc:  # noqa: BLE001
            self.error("Invalid private key", str(exc))
            return
        self._set_keys(keydict)
        self.info("Wallet imported", f"Address:\n{keydict['address']}")

    def open_keyfile(self):
        """Switch to an existing key file picked via dialog — validated (address + private key
        present) before it replaces the active wallet, and never re-saved (unlike _set_keys)."""
        path, _ = QFileDialog.getOpenFileName(self, "Open key file", self.store.dir,
                                              "Key files (*.dat *.json);;All files (*)")
        if not path:
            return
        try:
            keydict = load_keys(file=path)
            assert keydict.get("address") and keydict.get("private_key")
        except Exception as exc:  # noqa: BLE001
            self.error("Could not open key file", str(exc))
            return
        self.store.set("keyfile", path)
        self.keys = keydict
        self.stop_mining()
        self.walletChanged.emit(keydict)
        self.refresh_all()

    def reveal_private_key(self):
        """Show the private key behind an explicit warning; it sits in the collapsed 'details'
        pane so it is never on screen without a further deliberate click."""
        if not self.require_wallet():
            return
        if not self.confirm("Reveal private key",
                            "Your private key controls all funds. Only reveal it somewhere private."):
            return
        box = QMessageBox(self)
        box.setWindowTitle("Private key")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Keep this secret — anyone with it controls this wallet.")
        box.setDetailedText(self.keys["private_key"])
        box.exec()

    def copy_address(self):
        """Copy the wallet address to the clipboard (silent no-op without a wallet)."""
        if not self.keys:
            return
        QGuiApplication.clipboard().setText(self.keys["address"])
        self.flash("Address copied to clipboard")

    # ---- settings -----------------------------------------------------------------------
    def apply_node_settings(self):
        """Point the client at the toolbar's host:port, persist it, and probe with a refresh."""
        host = self.host_edit.text().strip() or DEFAULT_HOST
        try:
            port = int(self.port_edit.text().strip())
        except ValueError:
            self.error("Invalid port", "Port must be a number.")
            return
        self.client.host = host
        self.client.port = port
        self.store.set("host", host)
        self.store.set("port", port)
        self.flash(f"Connecting to {host}:{port}…")
        self.refresh_all()

    # ---- refresh orchestration ----------------------------------------------------------
    def run_async(self, fn, on_result=None, on_error=None):
        """Run fn() on the shared QThreadPool; on_result/on_error fire back on the GUI thread via
        queued signal delivery — the only path by which worker results may touch widgets."""
        worker = Worker(fn)
        if on_result:
            worker.signals.result.connect(on_result)
        if on_error:
            worker.signals.error.connect(on_error)
        self.pool.start(worker)

    def refresh_all(self):
        """Kick off all polls concurrently as fire-and-forget workers: chain tip (which doubles as
        the connectivity check), supply, and — when a wallet is loaded — account + mining status."""
        self.run_async(self.client.get_latest_block, self._on_latest, self._on_net_error)
        self.run_async(self.client.get_supply, lambda s: self.supplyUpdated.emit(s), None)
        if self.keys:
            addr = self.keys["address"]
            self.run_async(lambda: self.client.get_account(addr),
                           lambda acc: self.accountUpdated.emit(acc), None)
            self.run_async(lambda: self.client.mining_status(addr), self._on_mining, None)

    def refresh_history(self):
        """Fetch the wallet's full transaction history off-thread (manual — deliberately not part
        of the 8 s poll cycle, since it can be a heavy query)."""
        if not self.require_wallet():
            return
        addr = self.keys["address"]
        self.run_async(lambda: self.client.get_transactions(addr, 0),
                       lambda txs: self.historyUpdated.emit(txs),
                       lambda e: self.flash(f"History error: {e}"))

    def _on_latest(self, block):
        """Tip fetch succeeded: mark the node connected and fan out latestBlockUpdated."""
        num = block.get("block_number", 0)
        self.connectionChanged.emit(True, f"Connected · {self.client.host}:{self.client.port} · block #{num:,}")
        self.latestBlockUpdated.emit(block)

    def _on_mining(self, status):
        """Cache the node's block_time (it paces the heartbeat timer) and fan out miningUpdated."""
        try:
            self.block_time = float(status.get("block_time") or self.block_time)
        except (TypeError, ValueError):
            pass
        self.miningUpdated.emit(status)

    def _on_net_error(self, msg):
        """Tip fetch failed: flip the status bar to Disconnected (other polls fail silently)."""
        self.connectionChanged.emit(False, f"Disconnected · {self.client.host}:{self.client.port}")

    # ---- transaction building (reuses repo tx ops; runs inside workers) -----------------
    def build_transfer(self, recipient, amount_raw, fee):
        """Build, sign and submit a value transfer (bond/unbond ride the same path via their magic
        recipients) using the repo's own draft/create functions — the wallet never reimplements tx
        hashing or signing, so its txids can't diverge from consensus. Blocking; worker-only."""
        keys = self.keys
        target = self.client.get_max_block()
        draft = draft_transaction(
            sender=keys["address"], recipient=recipient, amount=amount_raw,
            public_key=keys["public_key"], timestamp=get_timestamp_seconds(),
            data="", max_block=target,
        )
        tx = create_transaction(draft, keys["private_key"], fee=fee)
        return self.client.submit_transaction(tx)

    def build_register(self):
        """Solve the one-time open-lane registration PoW (seconds of CPU — self-verified before
        submitting) and post the signed, fee-free register tx. Blocking; the PoW alone makes this
        worker-only."""
        keys = self.keys
        nonce = solve_registration_pow(keys["address"])
        if nonce is None or not verify_registration_pow(keys["address"], nonce):
            raise NodeError("could not solve registration proof-of-work")
        target = self.client.get_max_block()
        draft = draft_open_lane_transaction(
            sender=keys["address"], recipient="register", public_key=keys["public_key"],
            timestamp=get_timestamp_seconds(), max_block=target, pow_nonce=nonce,
        )
        tx = create_transaction(draft, keys["private_key"], fee=0)
        return self.client.submit_transaction(tx)

    def build_heartbeat(self):
        """Build and submit the per-epoch presence heartbeat (fee-free). The epoch is derived from
        the live tip exactly as the node derives it, so the heartbeat lands in the epoch it claims;
        returns {'epoch', 'response'} so the caller can dedupe per epoch. Blocking; worker-only."""
        keys = self.keys
        num = self.client.get_latest_block_number()
        target = num + 2
        epoch = num // EPOCH_LENGTH  # must match the node's block_height // EPOCH_LENGTH on merge
        draft = draft_open_lane_transaction(
            sender=keys["address"], recipient="heartbeat", public_key=keys["public_key"],
            timestamp=get_timestamp_seconds(), max_block=target, epoch=epoch,
        )
        tx = create_transaction(draft, keys["private_key"], fee=0)
        resp = self.client.submit_transaction(tx)
        return {"epoch": epoch, "response": resp}

    def submit_async(self, build_fn, done=None):
        """Run a build+submit closure in a worker, then report and refresh."""
        def on_result(resp):
            """GUI-thread: surface the node's verdict, release the caller's button, refresh."""
            ok = bool(resp.get("result"))
            if ok:
                self.info("Submitted", resp.get("message") or "Transaction accepted by the node.")
            else:
                self.error("Rejected", resp.get("message") or "The node rejected the transaction.")
            if done:
                done(ok)
            self.refresh_all()

        def on_error(msg):
            """GUI-thread: the tx never reached the node — report and release, no refresh."""
            self.error("Network error", msg)
            if done:
                done(False)

        self.run_async(build_fn, on_result, on_error)

    # ---- mining control -----------------------------------------------------------------
    def register_and_mine(self):
        """One-click miner start: solve + submit the registration in a worker, then start the
        heartbeat loop regardless of the node's verdict — a rejection usually just means the
        identity is already registered, in which case heartbeats are exactly what's needed."""
        if not self.require_wallet():
            return
        self.mining.register_btn.setEnabled(False)
        self.miningLog.emit("Solving one-time registration proof-of-work…")

        def on_result(resp):
            """GUI-thread: log the verdict and start heartbeats either way (see docstring above)."""
            ok = bool(resp.get("result"))
            self.miningLog.emit(("Registration submitted: " if ok else "Registration rejected: ")
                                + str(resp.get("message")))
            self._start_mining_loop()
            self.mining.register_btn.setEnabled(True)
            self.refresh_all()

        def on_error(msg):
            """GUI-thread: registration never reached the node — log and re-arm the button."""
            self.miningLog.emit(f"Registration failed: {msg}")
            self.mining.register_btn.setEnabled(True)

        self.run_async(self.build_register, on_result, on_error)

    def set_auto_bond_pct(self, pct):
        """Set + persist the auto-bond percentage (0..100). Re-arms the baseline so only earnings from
        now on are compounded."""
        self.auto_bond_pct = max(0, min(100, int(pct or 0)))
        self.auto_bond_baseline = None
        self.store.set("auto_bond_pct", self.auto_bond_pct)
        self.autoBondChanged.emit(self.auto_bond_pct)

    def _start_mining_loop(self):
        """Arm the heartbeat timer at roughly one block interval (min 15 s — the tick itself skips
        epochs already covered, so over-ticking is cheap) and reset the auto-bond baseline so only
        earnings from this point on compound."""
        self.mining_active = True
        self._last_hb_epoch = None
        self.auto_bond_baseline = None            # only earnings AFTER mining starts auto-bond
        self._last_auto_bond_epoch = None
        self.miningActiveChanged.emit(True)
        interval = max(int(self.block_time), 15) * 1000
        self.heartbeat_timer.start(interval)
        self.miningLog.emit("Heartbeat loop started — posting once per epoch while present.")
        QTimer.singleShot(500, self._heartbeat_tick)

    def stop_mining(self):
        """Stop the heartbeat loop and drop the auto-bond baseline; idempotent, so it is safely
        called on every wallet switch."""
        if self.heartbeat_timer.isActive():
            self.heartbeat_timer.stop()
        if self.mining_active:
            self.miningLog.emit("Heartbeat loop stopped.")
        self.mining_active = False
        self.auto_bond_baseline = None
        self.miningActiveChanged.emit(False)

    def _heartbeat_tick(self):
        """Timer slot: post a presence heartbeat in a worker when the epoch has advanced past the
        last accepted one (the node dedupes per (address, epoch) anyway — the local check just
        avoids pointless txs), then give auto-bond its once-per-epoch chance."""
        if not self.mining_active or not self.keys:
            return

        def on_result(out):
            """GUI-thread: record the accepted epoch; a rejection is logged but benign (register
            still unconfirmed, or already present this epoch)."""
            epoch = out["epoch"]
            resp = out["response"]
            if resp.get("result"):
                self._last_hb_epoch = epoch
                self.miningLog.emit(f"Heartbeat accepted for epoch #{epoch}.")
            else:
                # benign while the register tx is still unconfirmed, or already sent this epoch
                self.miningLog.emit(f"Heartbeat (epoch #{epoch}) not accepted: {resp.get('message')}")

        def on_error(msg):
            """GUI-thread: transport failure — log it; the next timer tick retries naturally."""
            self.miningLog.emit(f"Heartbeat error: {msg}")

        # Only post when the epoch advanced (the node dedupes per (address, epoch) anyway).
        def build():
            """Worker-thread: short-circuit with a synthetic success when this epoch's heartbeat
            was already accepted; otherwise build + submit a fresh one."""
            num = self.client.get_latest_block_number()
            epoch = num // EPOCH_LENGTH
            if epoch == self._last_hb_epoch:
                return {"epoch": epoch, "response": {"result": True, "message": "already present this epoch"}}
            return self.build_heartbeat()

        self.run_async(build, on_result, on_error)
        self._maybe_auto_bond()   # compound a % of new mining rewards into bonded stake (once/epoch)

    def _maybe_auto_bond(self):
        """AUTO-BOND: route a configured % of newly-mined spendable earnings straight into bonded stake.
        Mirrors core_loop.maybe_auto_bond and the browser miner: one bond per epoch, accrues below the
        AUTO_BOND_MIN_RAW dust floor, stops at BOND_CAP. Runs the decision + build+submit in a worker."""
        if not self.auto_bond_pct or self.auto_bond_pct <= 0 or not self.mining_active or not self.keys:
            return
        pct = int(self.auto_bond_pct)

        def work():
            """Worker-thread: measure the balance gain over the baseline and submit at most one
            bond when it clears the dust floor + fee (otherwise keep accruing under the same
            baseline). Returns None (nothing to do), a summary dict, or {'error': message}."""
            acc = self.client.get_account(self.keys["address"]) or {}
            if acc.get("registered") != 1:
                return None
            num = self.client.get_latest_block_number()
            epoch = num // EPOCH_LENGTH
            if epoch == self._last_auto_bond_epoch:
                return None
            balance = int(acc.get("balance", 0))
            bonded = int(acc.get("bonded", 0))
            if self.auto_bond_baseline is None:
                self.auto_bond_baseline = balance         # only future earnings
                return None
            if bonded >= BOND_CAP:
                self.auto_bond_baseline = balance         # already at the weight cap
                return None
            gain = balance - self.auto_bond_baseline
            if gain <= 0:
                self.auto_bond_baseline = balance         # balance fell — rebaseline
                return None
            to_bond = min((gain * pct) // 100, BOND_CAP - bonded)
            if to_bond < AUTO_BOND_MIN_RAW or balance < to_bond + MIN_TX_FEE:
                return None                               # accrue (no rebaseline)
            resp = self.build_transfer("bond", to_bond, MIN_TX_FEE)
            if resp.get("result"):
                self._last_auto_bond_epoch = epoch
                self.auto_bond_baseline = balance - to_bond - MIN_TX_FEE
                return {"amount": to_bond, "pct": pct, "gain": gain}
            return {"error": resp.get("message")}

        def done(out):
            """GUI-thread: log the outcome; only a successful bond warrants a refresh."""
            if not out:
                return
            if out.get("error"):
                self.miningLog.emit(f"Auto-bond rejected: {out['error']}")
            else:
                self.miningLog.emit(
                    f"Auto-bonded {out['amount'] / DENOMINATION:.4f} NADO "
                    f"({out['pct']}% of {out['gain'] / DENOMINATION:.4f} new rewards) → bonded lane.")
                self.refresh_all()

        self.run_async(work, done, lambda e: self.miningLog.emit(f"Auto-bond error: {e}"))

    # ---- helpers ------------------------------------------------------------------------
    def require_wallet(self):
        """Gate for wallet-requiring actions: True when keys are loaded, else shows an error
        dialog and returns False so callers can simply early-return."""
        if not self.keys:
            self.error("No wallet", "Create or import a wallet first (Wallet menu).")
            return False
        return True

    def confirm(self, title, text):
        """Modal Ok/Cancel question -> True on Ok."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Ok

    def error(self, title, text):
        """Modal error dialog."""
        QMessageBox.critical(self, title, text)

    def info(self, title, text):
        """Modal information dialog."""
        QMessageBox.information(self, title, text)

    def flash(self, text):
        """Show a transient status-bar message that auto-clears after 4 s."""
        self.status_msg.setText(text)
        QTimer.singleShot(4000, lambda: self.status_msg.setText(""))


# =========================================================================================
# Entry point
# =========================================================================================
def main():
    """Entry point: CLI args override stored settings for the node endpoint; a dark Fusion
    palette is applied alongside the stylesheet so native chrome (menus, tooltips) matches the
    themed widgets, then the Qt event loop runs until the window closes."""
    parser = argparse.ArgumentParser(description="NADO desktop wallet (PySide6)")
    parser.add_argument("--host", default=None, help="node host (default from settings / 127.0.0.1)")
    parser.add_argument("--port", default=None, type=int, help="node port (default from settings / 9173)")
    args = parser.parse_args()

    store = WalletStore()
    host = args.host or store.get("host", DEFAULT_HOST)
    port = args.port or store.get("port", DEFAULT_PORT)

    app = QApplication(sys.argv)
    app.setApplicationName("NADO Wallet")
    app.setStyle("Fusion")

    # dark base palette so native chrome (menus, tooltips) matches the stylesheet
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    pal.setColor(QPalette.ColorRole.Base, QColor(C_PANEL))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(C_PANEL2))
    pal.setColor(QPalette.ColorRole.Text, QColor(C_TEXT))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(C_TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(C_PANEL2))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(C_TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(C_ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(C_PANEL2))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(C_TEXT))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)

    win = WalletWindow(store, host, port)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
