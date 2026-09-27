"""Shared desktop theme and offline document typography."""
import ctypes
import sys
from pathlib import Path

PAGE_SPACING = 12
TABLE_ROW_HEIGHT = 38
SIDEBAR_WIDTH = 184

_CHECK = (Path(__file__).parent / "assets" / "check.svg").as_posix()
_DOWN = (Path(__file__).parent / "assets" / "down.svg").as_posix()
_UP = (Path(__file__).parent / "assets" / "up.svg").as_posix()

STYLE = """
QMainWindow, QWidget { background: #ffffff; color: #242b36; font: 10pt 'Microsoft YaHei UI'; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QWidget#sidebar { background: #f7f8fa; border-right: 1px solid #e9ecf0; }
QLabel#brand { font-size: 21pt; font-weight: 700; color: #202938; padding: 4px 0; }
QLabel#muted { color: #667085; }
QLabel#breadcrumb { color: #667085; font-size: 9pt; }
QLabel#pageTitle { font-size: 21pt; font-weight: 600; margin: 4px 0 8px; color: #202938; }
QLabel#sectionTitle { font-size: 12pt; font-weight: 600; }
QLabel#cardValue { font-size: 26pt; font-weight: 600; color: #202938; }
QFrame#card, QGroupBox { background: #ffffff; border: 1px solid #e3e7ed; border-radius: 8px; }
QFrame#card QLabel, QGroupBox QLabel { background: transparent; }
QListWidget { background: transparent; border: 1px solid transparent; padding: 0; outline: none; }
QListWidget::item:focus { background: #e7eefb; border-left: 3px solid #2459b8; }
QListWidget::item { padding: 10px 14px; margin: 2px 0; border-radius: 5px; color: #4b5565; }
QListWidget::item:hover { background: #f2f4f7; }
QListWidget::item:selected { background: #edf3ff; color: #2459b8; }
QListWidget#primaryNav::item { padding: 12px 14px; margin: 3px 0; }
QListWidget#primaryNav::item:selected { background: #e9effa; color: #2459b8; font-weight: 600; }
QListWidget#secondaryNav { border-bottom: 1px solid #e9ecf0; }
QListWidget#secondaryNav::item { padding: 10px 16px; margin: 0 8px 0 0; border-radius: 0; border-bottom: 2px solid transparent; }
QListWidget#secondaryNav::item:selected { background: #ffffff; color: #2459b8; border-bottom: 2px solid #3568c0; }
QPushButton { background: #ffffff; border: 1px solid #d7dce3; padding: 8px 14px; border-radius: 5px; }
QPushButton:hover { background: #f7f9fc; border-color: #adb9cc; }
QPushButton:pressed { background: #edf2fa; }
QPushButton:focus { border-color: #3568c0; }
QPushButton:disabled { color: #929aa7; background: #f7f8fa; border-color: #e6e9ee; }
QPushButton#primary { background: #315fb5; border-color: #315fb5; color: #ffffff; }
QPushButton#primary:hover { background: #264f9e; border-color: #264f9e; }
QPushButton#primary:pressed { background: #204486; }
QPushButton#primary:focus { border: 2px solid #123468; }
QPushButton#primary:disabled { color: #929aa7; background: #edf0f5; border-color: #e3e7ed; }
QLineEdit, QSpinBox, QTimeEdit, QComboBox { padding: 6px 8px; background: #ffffff; border: 1px solid #858f9f; border-radius: 5px; min-height: 20px; selection-background-color: #dce8fc; selection-color: #1f4180; }
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QComboBox:focus { border: 2px solid #2459b8; }
QLineEdit:disabled, QSpinBox:disabled, QTimeEdit:disabled, QComboBox:disabled { color: #929aa7; background: #f7f8fa; }
QComboBox QAbstractItemView { background: #ffffff; color: #242b36; border: 1px solid #d7dce3; selection-background-color: #edf3ff; selection-color: #2459b8; outline: none; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 26px; border: none; }
QComboBox::down-arrow { image: url("DOWN_ASSET"); width: 12px; height: 12px; }
QSpinBox, QTimeEdit { padding-right: 26px; }
QSpinBox::up-button, QTimeEdit::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 23px; border-left: 1px solid #e3e7ed; background: #f7f8fa; border-top-right-radius: 5px; }
QSpinBox::down-button, QTimeEdit::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 23px; border-left: 1px solid #e3e7ed; background: #f7f8fa; border-bottom-right-radius: 5px; }
QSpinBox::up-arrow, QTimeEdit::up-arrow { image: url("UP_ASSET"); width: 10px; height: 10px; }
QSpinBox::down-arrow, QTimeEdit::down-arrow { image: url("DOWN_ASSET"); width: 10px; height: 10px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #747f90; border-radius: 3px; background: #ffffff; }
QCheckBox::indicator:checked { background: #315fb5; border-color: #315fb5; image: url("CHECK_ASSET"); }
QCheckBox::indicator:hover { border-color: #3568c0; }
QCheckBox::indicator:disabled { border-color: #d7dce3; background: #e6e9ee; }
QTableWidget, QTextEdit, QPlainTextEdit, QTextBrowser { background: #ffffff; alternate-background-color: #fafbfc; border: 1px solid #e3e7ed; border-radius: 6px; selection-background-color: #e8f0ff; selection-color: #204b91; }
QTableWidget { gridline-color: #eef0f3; outline: none; }
QTableWidget::item { padding: 6px; }
QTableWidget::item:focus { border-bottom: 2px solid #2459b8; }
QTableWidget::item:selected { background: #e8f0ff; color: #204b91; }
QHeaderView::section { background: #f7f8fa; color: #586477; border: none; border-bottom: 1px solid #e3e7ed; padding: 10px; font-weight: 600; }
QTableCornerButton::section { background: #f7f8fa; border: none; }
QTabWidget::pane { border: 1px solid #e3e7ed; background: #ffffff; }
QTabBar { outline: none; }
QTabBar::tab { padding: 10px 20px; background: #ffffff; color: #667085; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { background: #f7f8fa; }
QTabBar::tab:selected { color: #2459b8; border-bottom: 2px solid #3568c0; }
QTabBar::tab:focus { background: #f2f5fb; border-bottom: 3px solid #2459b8; }
QGroupBox { margin-top: 16px; padding: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #465367; }
QScrollArea { border: none; background: #ffffff; }
QScrollBar:vertical { background: #fafbfc; width: 10px; margin: 0; }
QScrollBar:horizontal { background: #fafbfc; height: 10px; margin: 0; }
QScrollBar::handle { background: #7d899a; border: 2px solid #fafbfc; border-radius: 4px; min-width: 24px; min-height: 24px; }
QScrollBar::handle:hover { background: #a8b3c2; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QProgressBar { border: none; background: #edf0f5; border-radius: 4px; text-align: center; color: #344054; }
QProgressBar::chunk { background: #a8c3f1; border-radius: 4px; }
QStatusBar { background: #ffffff; color: #667085; }
QStatusBar::item { border: none; }
QSplitter::handle { background: #f0f2f5; }
QToolTip { color: #344054; background: #ffffff; border: 1px solid #d7dce3; padding: 6px; }
QMenu { background: #ffffff; color: #242b36; border: 1px solid #e3e7ed; }
QMenu::item:selected { background: #edf3ff; color: #2459b8; }
""".replace("CHECK_ASSET", _CHECK).replace("DOWN_ASSET", _DOWN).replace("UP_ASSET", _UP)


def windows_high_contrast():
    """Return the Windows accessibility setting without changing application state."""
    if sys.platform != "win32":
        return False

    class HighContrast(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                    ("lpszDefaultScheme", ctypes.c_wchar_p)]

    value = HighContrast()
    value.cbSize = ctypes.sizeof(value)
    try:
        read = ctypes.windll.user32.SystemParametersInfoW(0x0042, value.cbSize, ctypes.byref(value), 0)
    except (AttributeError, OSError):
        return False
    return bool(read and value.dwFlags & 0x00000001)


def desktop_style():
    """Let the native Windows palette own colors in High Contrast mode."""
    return "" if windows_high_contrast() else STYLE

DOCUMENT_STYLE = """
body { color: #344054; }
table { border-collapse: collapse; }
td, th { border: 1px solid #e3e7ed; padding: 10px; }
th { background: #f7f8fa; color: #344054; }
h1 { font-size: 22px; color: #202938; margin-bottom: 16px; }
h2 { font-size: 17px; color: #202938; margin-top: 22px; }
p, li { line-height: 160%; }
a { color: #2459b8; }
code { background: #f5f7fa; color: #465367; }
"""
