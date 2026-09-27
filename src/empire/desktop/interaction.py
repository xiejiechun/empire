"""Application-wide input rules shared by every current and future page."""

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSlider, QAbstractSpinBox, QComboBox


class PreventAccidentalWheelChanges(QObject):
    """Keep page scrolling from silently changing a value under the pointer."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and isinstance(
            watched, (QAbstractSpinBox, QComboBox, QAbstractSlider)
        ):
            event.ignore()
            return True
        return super().eventFilter(watched, event)


def install_input_rules(app):
    rules = PreventAccidentalWheelChanges(app)
    app.installEventFilter(rules)
    # QApplication does not take Python ownership of installed filters.
    app._empire_input_rules = rules
    return rules
