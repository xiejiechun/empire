import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication

from empire.desktop.icon import ICON_PATH, application_icon


def test_application_icon_assets_are_available() -> None:
    app = QApplication.instance() or QApplication([])
    preview = ICON_PATH.with_suffix(".png")

    assert ICON_PATH.is_file()
    assert preview.is_file()
    assert QImageReader(str(preview)).size() == QSize(256, 256)

    icon = application_icon()
    assert not icon.isNull()
    assert QSize(16, 16) in icon.availableSizes()
    assert QSize(256, 256) in icon.availableSizes()
    assert app is not None
