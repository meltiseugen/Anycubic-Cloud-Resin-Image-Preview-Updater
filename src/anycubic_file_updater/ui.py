"""Desktop workflow. Qt widgets stay on the GUI thread; file work runs in workers."""

from __future__ import annotations

import logging
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QObject,
    QProcess,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anycubic_file_updater import APP_NAME
from anycubic_file_updater.core import (
    Inspection,
    default_output,
    inspect_file,
    write_repaired,
)
from anycubic_file_updater.formats import OPEN_FILE_FILTER, file_format, is_supported_file
from anycubic_file_updater.settings import Preferences

log = logging.getLogger(__name__)


class WindowButton(QPushButton):
    """Window controls drawn in the same colors as the rest of the interface."""

    def __init__(self, action, callback, parent):
        super().__init__(parent)
        self.action = action
        self.setObjectName("closeWindow" if action == "Close" else "windowControl")
        self.setFixedSize(42, 34)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.clicked.connect(callback)
        self.refresh()

    def refresh(self):
        name = self.action
        if name == "Maximize" and self.window().isMaximized():
            name = "Restore"
        self.setToolTip(name)
        self.setAccessibleName(name)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#e5edf9"), 1.2))
        x, y = self.width() // 2 - 5, self.height() // 2 - 5
        if self.action == "Minimize":
            painter.drawLine(x, y + 5, x + 10, y + 5)
        elif self.action == "Close":
            painter.drawLine(x, y, x + 10, y + 10)
            painter.drawLine(x + 10, y, x, y + 10)
        elif self.window().isMaximized():
            painter.drawLine(x + 3, y + 3, x + 3, y)
            painter.drawLine(x + 3, y, x + 10, y)
            painter.drawLine(x + 10, y, x + 10, y + 7)
            painter.drawLine(x + 10, y + 7, x + 7, y + 7)
            painter.drawRect(x, y + 3, 7, 7)
        else:
            painter.drawRect(x, y, 10, 10)


class SettingsButton(QPushButton):
    def __init__(self, callback, parent):
        super().__init__(parent)
        self.setObjectName("settingsButton")
        self.setFixedSize(34, 34)
        self.setToolTip("Settings")
        self.setAccessibleName("Settings")
        self.clicked.connect(callback)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        color = QColor("#e5edf9" if self.isEnabled() else "#708097")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for _ in range(8):
            painter.drawRect(QRect(-2, -11, 4, 5))
            painter.rotate(45)
        ring = QPainterPath()
        ring.addEllipse(QRectF(-8, -8, 16, 16))
        ring.addEllipse(QRectF(-3, -3, 6, 6))
        painter.fillPath(ring, color)


class OutputPathLabel(QLabel):
    def __init__(self, path):
        super().__init__(str(path))
        self.setToolTip(str(path))
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle, self.width()),
        )


class ImageView(QWidget):
    """Transparent source art is displayed on a checkerboard."""

    def __init__(self):
        super().__init__()
        self.picture = QImage()
        self.caption = "Select an inspected file"
        self.setMinimumSize(170, 130)

    def set_image(self, data: bytes | None, caption="Missing embedded preview"):
        self.picture = QImage.fromData(data) if data else QImage()
        self.caption = caption
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor("#1b2433"))
        if self.picture.isNull():
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(
                rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.caption
            )
            return
        size = self.picture.size().scaled(
            rect.size() - QSize(16, 16), Qt.AspectRatioMode.KeepAspectRatio
        )
        target = QRect(0, 0, size.width(), size.height())
        target.moveCenter(rect.center())
        for y in range(target.top(), target.bottom() + 1, 12):
            for x in range(target.left(), target.right() + 1, 12):
                color = (
                    "#445064"
                    if ((x - target.left()) // 12 + (y - target.top()) // 12) % 2
                    else "#647084"
                )
                painter.fillRect(
                    QRect(x, y, min(12, target.right() - x + 1), min(12, target.bottom() - y + 1)),
                    QColor(color),
                )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self.picture)


class PreviewPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(320)
        self.inspection = None
        layout = QVBoxLayout(self)
        self.title = QLabel("Preview comparison")
        self.title.setObjectName("sectionTitle")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        pictures = QHBoxLayout()
        self.before, self.after = ImageView(), ImageView()
        for title, widget in (("Before", self.before), ("After", self.after)):
            column = QVBoxLayout()
            label = QLabel(title)
            label.setObjectName("muted")
            column.addWidget(label)
            column.addWidget(widget, 1)
            pictures.addLayout(column)
        layout.addLayout(pictures, 1)
        self.details = QLabel("Import an Anycubic print file to inspect its embedded previews.")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.details)

    def set_inspection(self, inspection: Inspection | None, message=""):
        self.inspection = inspection
        self.refresh()
        if message:
            self.details.setText(message)

    def refresh(self):
        if self.inspection is None:
            self.title.setText("Preview comparison")
            self.before.set_image(None, "Select an inspected file")
            self.after.set_image(None, "Proposed preview appears here")
            self.details.setText("Import an Anycubic print file to inspect its embedded previews.")
            return
        printer_format = file_format(self.inspection.source)
        self.title.setText(
            f"Preview comparison · {printer_format.printer} ({printer_format.extension})"
        )
        preview = self.inspection.previews[2]
        self.before.set_image(preview.original)
        self.after.set_image(preview.repaired)
        original = (
            f"{preview.dimensions[0]} × {preview.dimensions[1]} · {preview.mode} · "
            f"{'transparent pixels' if preview.transparent else 'opaque'}"
            if preview.dimensions
            else "Missing"
        )
        image = QImage.fromData(preview.repaired)
        after_alpha = "transparent pixels" if preview.repaired_transparent else "opaque"
        self.details.setText(
            f"Before: {original}\nAfter: {image.width()} × {image.height()} · {after_alpha}"
            f" · {preview.change}"
        )


class SettingsDialog(QDialog):
    def __init__(self, prefs: Preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(540)
        self.colors = list(prefs.colors)
        form = QFormLayout(self)
        preserve = QCheckBox("Always preserve original files")
        preserve.setChecked(True)
        preserve.setEnabled(False)
        form.addRow(preserve)
        self.auto = QCheckBox("Inspect all files when added")
        self.auto.setChecked(prefs.auto_inspect)
        self.skip = QCheckBox("Skip files that are already compatible")
        self.skip.setChecked(prefs.skip_compatible)
        self.verify = QCheckBox("Additional full ZIP integrity check")
        self.verify.setChecked(prefs.verify_zip)
        self.transparent_preview2 = QCheckBox("Transparent background for preview 2")
        self.transparent_preview2.setChecked(prefs.transparent_preview2)
        self.transparent_preview2.setToolTip(
            "Uses embedded transparency and keeps preview 2 at 800 × 600. "
            "Solid backgrounds baked into all previews cannot be removed."
        )
        for checkbox in (self.auto, self.skip, self.verify, self.transparent_preview2):
            form.addRow(checkbox)
        note = QLabel("SHA-256 verification of all print data is always enabled.")
        note.setObjectName("muted")
        form.addRow(note)
        self.compression = QSpinBox()
        self.compression.setRange(0, 9)
        self.compression.setValue(prefs.compression)
        form.addRow("PNG compression", self.compression)
        self.color_buttons = {}
        for i in (2,):
            button = QPushButton()
            button.clicked.connect(lambda checked=False, index=i: self.choose_color(index))
            self.color_buttons[i] = button
            form.addRow(f"Preview {i} background", button)
        self.refresh_colors()
        self.transparent_preview2.toggled.connect(self.color_buttons[2].setDisabled)
        self.color_buttons[2].setDisabled(prefs.transparent_preview2)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.reset)
        form.addRow(buttons)

    def choose_color(self, index):
        color = QColorDialog.getColor(QColor(*self.colors[index]), self, "Preview background")
        if color.isValid():
            self.colors[index] = color.getRgb()[:3]
            self.refresh_colors()

    def refresh_colors(self):
        for index, button in self.color_buttons.items():
            color = self.colors[index]
            button.setText(f"RGB {color[0]}, {color[1]}, {color[2]}")
            button.setStyleSheet(f"border-left: 18px solid {QColor(*color).name()};")

    def reset(self):
        defaults = Preferences()
        self.auto.setChecked(True)
        self.skip.setChecked(True)
        self.verify.setChecked(True)
        self.transparent_preview2.setChecked(defaults.transparent_preview2)
        self.compression.setValue(defaults.compression)
        self.colors = defaults.colors
        self.refresh_colors()

    def preferences(self):
        return Preferences(
            auto_inspect=self.auto.isChecked(),
            skip_compatible=self.skip.isChecked(),
            verify_zip=self.verify.isChecked(),
            compression=self.compression.value(),
            colors=self.colors,
            transparent_preview2=self.transparent_preview2.isChecked(),
        )


class Worker(QObject):
    imported = Signal(object)
    inspected = Signal(object, object, str)
    repaired = Signal(object, object, str, str)
    progress = Signal(int, str)
    overall = Signal(int, int)
    message = Signal(str)
    finished = Signal()

    def __init__(self, kind, items, options, auto=True):
        super().__init__()
        self.kind, self.items, self.options, self.auto = kind, items, options, auto

    def cancelled(self):
        return QThread.currentThread().isInterruptionRequested()

    def inspect(self, path):
        try:
            inspection = inspect_file(path, self.options)
            self.inspected.emit(path, inspection, "")
            return inspection
        except Exception as exc:
            log.exception("Inspection failed: %s", path)
            self.inspected.emit(path, None, str(exc))
            return None

    @Slot()
    def run(self):
        try:
            if self.kind == "import":
                seen = set()
                for raw in self.items:
                    if self.cancelled():
                        break
                    path = Path(raw).resolve()
                    if not path.is_file() or not is_supported_file(path):
                        self.message.emit(f"Select individual supported print files: {path.name}")
                        continue
                    if path in seen:
                        continue
                    seen.add(path)
                    self.imported.emit(path)
                    self.progress.emit(0, f"Inspecting {path.name}…")
                    if self.auto:
                        self.inspect(path)
                self.message.emit(f"Import finished: {len(seen)} file(s) added.")
            elif self.kind == "inspect":
                for index, path in enumerate(self.items):
                    if self.cancelled():
                        break
                    self.progress.emit(0, f"Inspecting {path.name}…")
                    self.inspect(path)
                    self.overall.emit(index + 1, len(self.items))
            else:
                counts = Counter()
                for index, (path, output, overwrite, force) in enumerate(self.items):
                    if self.cancelled():
                        break
                    self.progress.emit(0, f"Inspecting {path.name}…")
                    try:
                        inspection = inspect_file(path, self.options)
                        self.inspected.emit(path, inspection, "")
                        result = write_repaired(
                            inspection,
                            output,
                            self.options,
                            overwrite=overwrite,
                            force=force,
                            progress=lambda value, text, name=path.name: self.progress.emit(
                                value, f"{name}: {text}"
                            ),
                        )
                        counts[result.status] += 1
                        self.repaired.emit(path, result.output, result.status, result.message)
                    except Exception as exc:
                        log.exception("Repair failed: %s", path)
                        counts["Failed"] += 1
                        self.repaired.emit(path, None, "Failed", str(exc))
                    self.overall.emit(index + 1, len(self.items))
                remaining = len(self.items) - sum(counts.values())
                self.message.emit(
                    f"Batch complete: {counts['Saved']} saved, "
                    f"{counts['Skipped']} skipped, {counts['Failed']} failed, "
                    f"{remaining} cancelled."
                )
        except Exception as exc:
            log.exception("Worker failed")
            self.message.emit(f"Operation failed: {exc}")
        finally:
            self.finished.emit()


@dataclass
class Row:
    path: Path
    inspection: Inspection | None = None
    error: str = ""
    output: Path | None = None
    was_inspected: bool = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.prefs = Preferences.load()
        self.rows: list[Row] = []
        self.active_path = None
        self.preview_cache = OrderedDict()
        self.thread = None
        self.worker = None
        self.buttons = []
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.resize(1220, 940)
        self.setMinimumSize(900, 900)
        self.setAcceptDrops(True)
        root = QWidget()
        root.setMouseTracking(True)
        root.installEventFilter(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 22, 28, 20)
        layout.setSpacing(12)
        self.title_bar = QWidget()
        self.title_bar.setMouseTracking(True)
        self.title_bar.installEventFilter(self)
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout.addWidget(title, 1)
        self.settings_button = SettingsButton(self.settings, self.title_bar)
        title_layout.addWidget(self.settings_button)
        self.buttons.append(self.settings_button)
        self.minimize_button = WindowButton("Minimize", self.showMinimized, self.title_bar)
        self.maximize_button = WindowButton("Maximize", self.toggle_maximized, self.title_bar)
        self.close_button = WindowButton("Close", self.close, self.title_bar)
        for control in (self.minimize_button, self.maximize_button, self.close_button):
            title_layout.addWidget(control)
        layout.addWidget(self.title_bar)
        subtitle = QLabel(
            "Repair missing Anycubic Cloud thumbnails while preserving your print data."
        )
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        drop = QFrame()
        drop.setObjectName("dropZone")
        drop_layout = QHBoxLayout(drop)
        drop_layout.setContentsMargins(22, 18, 22, 18)
        hint = QLabel(
            "Drop Anycubic print files here\n"
            "M7 · M7 Pro · M7 Max · Mono 4 Ultra · P1 · P1 Max\n"
            "Updated copies are saved beside your original files."
        )
        hint.setWordWrap(True)
        drop_layout.addWidget(hint, 1)
        self.add_files_button = self.button("Add Files", self.add_files, drop_layout)
        layout.addWidget(drop)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        self.files_panel = QWidget()
        files_layout = QVBoxLayout(self.files_panel)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.setSpacing(8)
        files_heading = QHBoxLayout()
        files_title = QLabel("Input files")
        files_title.setObjectName("sectionTitle")
        files_heading.addWidget(files_title)
        files_heading.addStretch()
        self.clear_button = self.button("Clear List", self.clear_rows, files_heading)
        files_layout.addLayout(files_heading)
        self.table = QTableWidget(0, 6)
        self.table.setMinimumHeight(112)
        self.table.setHorizontalHeaderLabels(
            ["Filename", "Size", "Preview status", "Repair status", "Output path", ""]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, 44)
        for i, width in enumerate((235, 75, 210, 115)):
            self.table.setColumnWidth(i, width)
        self.table.cellClicked.connect(self.show_file)
        self.table.setToolTip(
            "Click a file to view its preview. Update Preview processes all listed files."
        )
        files_layout.addWidget(self.table)
        splitter.addWidget(self.files_panel)
        self.preview = PreviewPanel()
        splitter.addWidget(self.preview)
        splitter.setMinimumHeight(
            self.files_panel.minimumSizeHint().height()
            + self.preview.minimumHeight()
            + splitter.handleWidth()
        )
        splitter.setSizes([240, 260])
        layout.addWidget(splitter, 1)
        actions = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel after current file")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        self.update_button = self.button("Update Preview", self.update_all, actions)
        self.update_button.setObjectName("primary")
        self.update_button.setToolTip(
            "Save filename_with_preview beside every original file in the list"
        )
        layout.addLayout(actions)
        self.operation = QLabel("Ready · Offline processing")
        self.operation.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.operation)
        progress_row = QHBoxLayout()
        progress_row.addWidget(QLabel("File"))
        self.file_progress = QProgressBar()
        progress_row.addWidget(self.file_progress, 1)
        layout.addLayout(progress_row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setMaximumHeight(80)
        self.log.setPlaceholderText("Progress and error details appear here.")
        layout.addWidget(self.log)
        self.setCentralWidget(root)
        self.add_files_button.setFocus()
        self.setMinimumHeight(max(900, layout.minimumSize().height()))

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.maximize_button.refresh()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
        ):
            return super().eventFilter(watched, event)
        point = self.mapFromGlobal(event.globalPosition().toPoint())
        edges = Qt.Edge(0)
        if not self.isMaximized():
            if point.x() < 6:
                edges |= Qt.Edge.LeftEdge
            elif point.x() >= self.width() - 6:
                edges |= Qt.Edge.RightEdge
            if point.y() < 6:
                edges |= Qt.Edge.TopEdge
            elif point.y() >= self.height() - 6:
                edges |= Qt.Edge.BottomEdge
        if kind == QEvent.Type.MouseMove:
            cursors = {
                Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
                Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
                Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
                Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
                Qt.Edge.TopEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeFDiagCursor,
                Qt.Edge.BottomEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeFDiagCursor,
                Qt.Edge.TopEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeBDiagCursor,
                Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeBDiagCursor,
            }
            watched.setCursor(cursors.get(edges, Qt.CursorShape.ArrowCursor))
        elif event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if kind == QEvent.Type.MouseButtonPress and edges and handle:
                return handle.startSystemResize(edges)
            if watched is self.title_bar or point.y() < self.title_bar.geometry().top():
                if kind == QEvent.Type.MouseButtonDblClick:
                    self.toggle_maximized()
                    return True
                if handle:
                    return handle.startSystemMove()
        return super().eventFilter(watched, event)

    def button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        self.buttons.append(button)
        return button

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Anycubic print files", "", OPEN_FILE_FILTER
        )
        if files:
            self.import_paths(files)

    def import_paths(self, paths):
        if self.thread is None:
            self.start_worker("import", paths)

    def dropped_files(self, event):
        urls = event.mimeData().urls()
        if urls and all(
            url.isLocalFile()
            and Path(url.toLocalFile()).is_file()
            and is_supported_file(url.toLocalFile())
            for url in urls
        ):
            return [url.toLocalFile() for url in urls]
        return []

    def dragEnterEvent(self, event):
        if self.thread is None and self.dropped_files(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = self.dropped_files(event)
        if paths and self.thread is None:
            self.import_paths(paths)
            event.acceptProposedAction()

    @Slot(object)
    def add_row(self, path):
        if any(row.path == path for row in self.rows):
            return
        row = len(self.rows)
        self.rows.append(Row(path))
        self.table.insertRow(row)
        try:
            size = f"{path.stat().st_size / 1024 / 1024:.1f} MB"
        except OSError:
            size = "—"
        for column, text in enumerate((path.name, size, "Not inspected", "Ready", "")):
            self.table.setItem(row, column, QTableWidgetItem(text))
        remove = QPushButton("×")
        remove.setObjectName("removeFile")
        remove.setToolTip(f"Remove {path.name} from the list")
        remove.setAccessibleName(f"Remove {path.name} from the list")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setEnabled(self.thread is None)
        remove.clicked.connect(lambda checked=False, path=path: self.remove_file(path))
        self.table.setCellWidget(row, 5, remove)
        printer_format = file_format(path)
        self.table.item(row, 0).setToolTip(
            f"{path}\n{printer_format.printer if printer_format else 'Unsupported format'}"
        )
        if self.active_path is None:
            self.active_path = path

    def row_index(self, path):
        return next((i for i, row in enumerate(self.rows) if row.path == path), None)

    @Slot(object, object, str)
    def inspected(self, path, inspection, error):
        index = self.row_index(path)
        if index is None:
            return
        row = self.rows[index]
        row.inspection, row.error = inspection, error
        row.was_inspected = True
        self.preview_cache.pop(path, None)
        if inspection:
            self.preview_cache[path] = sum(
                len(p.original or b"") + len(p.repaired or b"") for p in inspection.previews
            )
        # Bound the cache by file count and a 64 MiB target; keep the active
        # preview and incoming result. Individual PNG limits also apply.
        active_paths = {self.active_path}
        for cached in list(self.preview_cache):
            if (
                len(self.preview_cache) <= 4
                and sum(self.preview_cache.values()) <= 64 * 1024 * 1024
            ):
                break
            if cached == path or cached in active_paths:
                continue
            self.preview_cache.pop(cached)
            cached_index = self.row_index(cached)
            if cached_index is not None:
                self.rows[cached_index].inspection = None
        status = (
            inspection.status
            if inspection
            else ("Unsupported file" if "unsupported" in error.lower() else "Invalid archive")
        )
        self.table.item(index, 2).setText(status)
        self.table.item(index, 2).setToolTip(error or status)
        if error:
            self.add_log(f"{path.name}: {error}")
        if path == self.active_path:
            self.refresh_preview()

    @Slot(object, object, str, str)
    def repaired(self, path, output, status, message):
        index = self.row_index(path)
        if index is None:
            return
        self.rows[index].output = output
        self.table.item(index, 3).setText(status)
        self.table.item(index, 3).setToolTip(message)
        # The cell widget draws the path; keep the backing item free of duplicate text.
        self.table.item(index, 4).setData(Qt.ItemDataRole.UserRole, str(output) if output else "")
        self.table.item(index, 4).setToolTip(str(output) if output else "")
        self.table.removeCellWidget(index, 4)
        if output:
            cell = QWidget()
            layout = QHBoxLayout(cell)
            layout.setContentsMargins(5, 0, 5, 0)
            layout.setSpacing(6)
            path_label = OutputPathLabel(output)
            layout.addWidget(path_label, 1)
            open_folder = QPushButton("Open folder")
            open_folder.setObjectName("openOutputFolder")
            open_folder.setFixedHeight(26)
            open_folder.setToolTip(f"Show and select {output.name} in its folder")
            open_folder.setAccessibleName(f"Open folder for {path.name}")
            open_folder.clicked.connect(
                lambda checked=False, output=output: self.open_output_folder(output)
            )
            layout.addWidget(open_folder)
            self.table.setCellWidget(index, 4, cell)
        self.add_log(f"{path.name}: {message}")

    def open_output_folder(self, output):
        if not output.is_file():
            self.add_log(f"Output file no longer exists: {output}")
            return
        if sys.platform == "win32":
            started, _pid = QProcess.startDetached(
                "explorer.exe", ["/select,", str(output.resolve())]
            )
        else:
            started = QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.parent)))
        if not started:
            self.add_log(f"Could not reveal output: {output}")

    def show_file(self, index, column=0):
        if 0 <= index < len(self.rows):
            self.active_path = self.rows[index].path
            self.refresh_preview()

    def refresh_preview(self):
        index = self.row_index(self.active_path)
        row = self.rows[index] if index is not None else None
        self.preview.set_inspection(row.inspection if row else None, row.error if row else "")
        if row and row.inspection:
            self.preview_cache.move_to_end(row.path, last=True)
        elif row and not row.error and self.thread is None:
            self.start_worker("inspect", [row.path])

    def update_all(self):
        if not self.rows:
            QMessageBox.information(self, "Add files", "Add Anycubic print files first.")
            return
        self.prepare_jobs(list(range(len(self.rows))))

    def prepare_jobs(self, indices):
        if not indices or self.thread is not None:
            return
        jobs = []
        reserved = set()
        for index in indices:
            source = self.rows[index].path
            if file_format(source) is None:
                QMessageBox.warning(self, "Unsupported format", "Select a supported Anycubic file.")
                return
            output = default_output(source)
            if output.resolve() in reserved:
                QMessageBox.warning(
                    self,
                    "Duplicate output names",
                    "Two input files would write the same output. "
                    "Rename one original file before updating its preview.",
                )
                return
            reserved.add(output.resolve())
            jobs.append((source, output, False, False))
        input_paths = {row.path.resolve() for row in self.rows}
        for _source, output, _, _ in jobs:
            if output.resolve() in input_paths:
                QMessageBox.warning(
                    self,
                    "Preserve original files",
                    "An output path matches an imported input file. "
                    "Remove the conflicting file from the list or rename it before updating.",
                )
                return
        collisions = [output for _, output, _, _ in jobs if output.exists()]
        if collisions:
            answer = QMessageBox.question(
                self,
                "Replace existing output files?",
                "Replace these existing output files?\n\n"
                + "\n".join(str(path) for path in collisions[:12])
                + (f"\n…and {len(collisions) - 12} more" if len(collisions) > 12 else ""),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        jobs = [(s, o, o in collisions, f) for s, o, _, f in jobs]
        self.start_worker("repair", jobs)

    def remove_file(self, path):
        if self.thread is not None:
            return
        index = self.row_index(path)
        if index is None:
            return
        self.table.blockSignals(True)
        self.preview_cache.pop(path, None)
        del self.rows[index]
        self.table.removeRow(index)
        self.table.blockSignals(False)
        if self.active_path == path:
            self.active_path = self.rows[0].path if self.rows else None
        self.refresh_preview()

    def clear_rows(self):
        if self.thread is not None:
            return
        self.rows.clear()
        self.active_path = None
        self.preview_cache.clear()
        self.table.setRowCount(0)
        self.preview.set_inspection(None)

    def settings(self):
        dialog = SettingsDialog(self.prefs, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.prefs = dialog.preferences()
            self.prefs.save()
            # Recompute proposals using the new background/compression choices.
            if self.rows:
                self.start_worker("inspect", [row.path for row in self.rows])

    def start_worker(self, kind, items):
        if self.thread is not None:
            return
        self.set_busy(True)
        self.file_progress.setValue(0)
        self.thread = QThread(self)
        self.worker = Worker(kind, items, self.prefs.options(), self.prefs.auto_inspect)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.imported.connect(self.add_row)
        self.worker.inspected.connect(self.inspected)
        self.worker.repaired.connect(self.repaired)
        self.worker.progress.connect(self.show_progress)
        self.worker.message.connect(self.add_log)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def set_busy(self, busy):
        for button in self.buttons:
            button.setEnabled(not busy)
        for index in range(self.table.rowCount()):
            self.table.cellWidget(index, 5).setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    @Slot(int, str)
    def show_progress(self, value, message):
        self.file_progress.setValue(value)
        self.operation.setText(message)

    @Slot(str)
    def add_log(self, message):
        self.log.appendPlainText(message)
        self.operation.setText(message)
        log.info(message)

    @Slot()
    def worker_finished(self):
        self.thread, self.worker = None, None
        self.set_busy(False)
        self.refresh_preview()

    def cancel(self):
        if self.thread is not None:
            self.thread.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.add_log("Cancellation requested. The current file will finish safely.")

    def closeEvent(self, event):
        if self.thread is not None:
            self.cancel()
            QMessageBox.information(
                self,
                "Finishing current file",
                "Please wait for the current file to finish, then close the app.",
            )
            event.ignore()
            return
        self.prefs.save()
        event.accept()


STYLESHEET = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #e5edf9; }
QMainWindow, QDialog { background: #101722; }
QPushButton#windowControl, QPushButton#closeWindow {
    background: transparent; border: none; border-radius: 4px; padding: 0;
}
QPushButton#windowControl:hover { background: #26374d; }
QPushButton#closeWindow:hover { background: #b83245; }
QPushButton#windowControl:pressed { background: #334c69; }
QPushButton#closeWindow:pressed { background: #912638; }
QPushButton#windowControl:focus, QPushButton#closeWindow:focus { border: 1px solid #55728e; }
QPushButton#settingsButton { background: transparent; border: none; padding: 0; }
QPushButton#settingsButton:hover { background: #26374d; }
QPushButton#settingsButton:focus { border: 1px solid #55728e; }
QPushButton#openOutputFolder { padding: 2px 7px; font-size: 9pt; }
QLabel#title { font-size: 23pt; font-weight: 650; }
QLabel#sectionTitle { font-size: 13pt; font-weight: 600; }
QLabel#muted { color: #96a7be; }
QFrame#dropZone { border: 1px dashed #55728e; border-radius: 10px; background: #192535; }
QPushButton { background: #26374d; border: 1px solid #3b506b; border-radius: 6px;
              padding: 8px 13px; }
QPushButton:hover { background: #334c69; }
QPushButton:pressed { background: #17283d; }
QPushButton:disabled { color: #708097; border-color: #283548; background: #1b2737; }
QPushButton#primary { background: #29c6b0; color: #082722; border-color: #29c6b0;
                     font-weight: 700; }
QPushButton#primary:hover { background: #58e1cb; }
QPushButton#primary:disabled { background: #2d5b57; color: #95b3b0; }
QPushButton#removeFile { background: transparent; border: none; border-radius: 4px;
                        padding: 0; font-size: 15pt; color: #96a7be; }
QPushButton#removeFile:hover { background: #532c3d; color: #ffb4c1; }
QPushButton#removeFile:disabled { color: #526079; }
QTableWidget, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {
    background: #172232; border: 1px solid #304159; border-radius: 5px;
    selection-background-color: #285c70; padding: 5px; }
QTableWidget { alternate-background-color: #1c2a3c; gridline-color: #28394e; }
QHeaderView::section { background: #22334a; color: #b9c9de; padding: 9px;
                       border: none; border-right: 1px solid #304159; }
QProgressBar { background: #1b2a3d; border: none; border-radius: 4px;
               text-align: center; min-height: 17px; }
QProgressBar::chunk { background: #258d86; border-radius: 4px; }
QCheckBox { spacing: 8px; }
QSplitter::handle { background: #293a50; height: 3px; }
QToolTip { background: #22334a; color: #e5edf9; border: 1px solid #55728e; }
"""


def start_window(paths=()):
    app = QApplication.instance()
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    if paths:
        QTimer.singleShot(0, lambda: window.import_paths(paths))
    return window
