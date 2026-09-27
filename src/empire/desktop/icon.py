"""Application icon resolution shared by source and packaged desktop runs."""

from pathlib import Path

from PySide6.QtGui import QIcon

ICON_PATH = Path(__file__).parent / "assets" / "empire.ico"


def application_icon() -> QIcon:
    return QIcon(str(ICON_PATH))
