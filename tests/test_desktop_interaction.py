import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QDial,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from empire.desktop.interaction import install_input_rules  # noqa: E402


def wheel(delta=-120):
    return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, delta),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.ScrollUpdate, False)


def test_wheel_never_changes_spin_box_or_closed_combo_but_page_still_scrolls():
    app = QApplication.instance() or QApplication([])
    rules = install_input_rules(app)
    spin = QSpinBox()
    spin.setRange(0, 10)
    spin.setValue(5)
    combo = QComboBox()
    combo.addItems(["一", "二", "三"])
    combo.setCurrentIndex(1)
    assert QApplication.sendEvent(spin, wheel(120))
    assert QApplication.sendEvent(combo, wheel(120))
    assert spin.value() == 5
    assert combo.currentIndex() == 1
    for control in (QSlider(), QDial()):
        control.setRange(0, 10)
        control.setValue(5)
        QApplication.sendEvent(control, wheel(120))
        assert control.value() == 5

    area = QScrollArea()
    content = QWidget()
    content.setMinimumHeight(2000)
    layout = QVBoxLayout(content)
    for _ in range(100):
        layout.addWidget(QWidget())
    area.setWidget(content)
    area.setWidgetResizable(True)
    area.resize(200, 120)
    area.show()
    app.processEvents()
    assert area.verticalScrollBar().maximum() > 0
    assert rules.eventFilter(area.viewport(), wheel(-120)) is False
    QApplication.sendEvent(area.viewport(), wheel(-120))
    assert area.verticalScrollBar().value() > 0
    area.close()


@pytest.mark.parametrize("kind", ("document", "table"))
def test_wheel_actually_scrolls_documents_and_tables(kind):
    app = QApplication.instance() or QApplication([])
    rules = install_input_rules(app)
    view = QTextBrowser() if kind == "document" else QTableWidget(100, 2)
    if kind == "document":
        view.setPlainText("\n".join(f"成员 {index}" for index in range(100)))
    view.resize(200, 120)
    view.show()
    app.processEvents()
    try:
        assert view.verticalScrollBar().maximum() > 0
        QApplication.sendEvent(view.viewport(), wheel(-120))
        assert view.verticalScrollBar().value() > 0
    finally:
        app.removeEventFilter(rules)
        view.close()
        view.deleteLater()
        app.processEvents()


def test_explicit_keyboard_and_step_buttons_can_still_change_values():
    app = QApplication.instance() or QApplication([])
    install_input_rules(app)
    spin = QSpinBox()
    spin.setValue(5)
    spin.stepUp()
    assert spin.value() == 6
    combo = QComboBox()
    combo.addItems(["一", "二"])
    combo.setCurrentIndex(1)
    assert combo.currentText() == "二"
