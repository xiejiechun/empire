import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QScrollArea,
    QSpinBox,
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
    area.close()


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
