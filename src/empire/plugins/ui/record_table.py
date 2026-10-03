"""Record table formatting and stable selection, independent of record queries."""
from PySide6.QtCore import QItemSelectionModel, Qt

from empire.core.redaction import redact
from empire.plugins.ui.common import rows
from empire.plugins.ui.record_detail import ARCHIVE_STATUS, record_time


def render_records(widget, records, kind, cfg, names, selected_ids, current_id):
    values = []
    for record in records:
        if kind == 'errors':
            cells = [record_time(record.get('created_at')), record.get('stage', '—'),
                     redact(record.get('error', ''), cfg), record.get('status_code') or '—']
        else:
            cells = [record_time(record.get('created_at')),
                     ARCHIVE_STATUS.get(record.get('status'), record.get('status', '—')),
                     record.get('processed_count', '—'), record.get('written_count', '—'),
                     record.get('snapshot_id', '—')]
        project = record.get('project_id', '')
        values.append([*cells, names.get(project, project)])
    widget.blockSignals(True)
    rows(widget, values)
    widget.clearSelection()
    model = widget.selectionModel()
    for index, record in enumerate(records):
        widget.item(index, 0).setData(Qt.ItemDataRole.UserRole, record['id'])
        if record['id'] in selected_ids:
            model.select(widget.model().index(index, 0),
                         QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        if record['id'] == current_id:
            model.setCurrentIndex(widget.model().index(index, 0), QItemSelectionModel.SelectionFlag.NoUpdate)
    widget.blockSignals(False)
