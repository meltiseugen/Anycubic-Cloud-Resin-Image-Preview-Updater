"""Desktop workflow. Qt widgets stay on the GUI thread; file work runs in workers."""

from __future__ import annotations

import logging
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSize, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pm7fixer.core import (
    Inspection,
    default_output,
    inspect_file,
    write_repaired,
)
from pm7fixer.formats import OPEN_FILE_FILTER, file_format, is_supported_file
from pm7fixer.settings import Preferences

log = logging.getLogger(__name__)


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
        self.selector = QComboBox()
        self.selector.addItems(["Preview 0 · printer", "Preview 1 · printer", "Preview 2 · cloud"])
        self.selector.setCurrentIndex(2)
        self.selector.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.selector)
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
        preview = self.inspection.previews[self.selector.currentIndex()]
        self.before.set_image(preview.original)
        self.after.set_image(preview.repaired)
        original = (
            f"{preview.dimensions[0]} × {preview.dimensions[1]} · {preview.mode} · "
            f"{'transparent pixels' if preview.transparent else 'opaque'}"
            if preview.dimensions
            else "Missing"
        )
        image = QImage.fromData(preview.repaired)
        self.details.setText(
            f"Before: {original}\nAfter: {image.width()} × {image.height()} · opaque"
            f" · {preview.change}"
        )


class SettingsDialog(QDialog):
    def __init__(self, prefs: Preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(540)
        self.colors = list(prefs.colors)
        form = QFormLayout(self)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(prefs.output_folder)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_folder)
        folder_row.addWidget(self.folder)
        folder_row.addWidget(browse)
        form.addRow("Default output folder", folder_row)
        preserve = QCheckBox("Always preserve original files")
        preserve.setChecked(True)
        preserve.setEnabled(False)
        form.addRow(preserve)
        self.auto = QCheckBox("Automatically inspect imported files")
        self.auto.setChecked(prefs.auto_inspect)
        self.skip = QCheckBox("Skip files that are already compatible")
        self.skip.setChecked(prefs.skip_compatible)
        self.verify = QCheckBox("Additional full ZIP integrity check")
        self.verify.setChecked(prefs.verify_zip)
        for checkbox in (self.auto, self.skip, self.verify):
            form.addRow(checkbox)
        note = QLabel("SHA-256 verification of all print data is always enabled.")
        note.setObjectName("muted")
        form.addRow(note)
        self.compression = QSpinBox()
        self.compression.setRange(0, 9)
        self.compression.setValue(prefs.compression)
        form.addRow("PNG compression", self.compression)
        self.color_buttons = []
        for i in range(3):
            button = QPushButton()
            button.clicked.connect(lambda checked=False, index=i: self.choose_color(index))
            self.color_buttons.append(button)
            form.addRow(f"Preview {i} background", button)
        self.refresh_colors()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.reset)
        form.addRow(buttons)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Default output folder", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def choose_color(self, index):
        color = QColorDialog.getColor(QColor(*self.colors[index]), self, "Preview background")
        if color.isValid():
            self.colors[index] = color.getRgb()[:3]
            self.refresh_colors()

    def refresh_colors(self):
        for button, color in zip(self.color_buttons, self.colors, strict=True):
            button.setText(f"RGB {color[0]}, {color[1]}, {color[2]}")
            button.setStyleSheet(f"border-left: 18px solid {QColor(*color).name()};")

    def reset(self):
        defaults = Preferences()
        self.folder.clear()
        self.auto.setChecked(True)
        self.skip.setChecked(True)
        self.verify.setChecked(True)
        self.compression.setValue(defaults.compression)
        self.colors = defaults.colors
        self.refresh_colors()

    def preferences(self):
        return Preferences(
            self.folder.text().strip(),
            self.auto.isChecked(),
            self.skip.isChecked(),
            self.verify.isChecked(),
            self.compression.value(),
            self.colors,
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
                    root = Path(raw)
                    if root.is_dir():

                        def walk_error(error):
                            self.message.emit(f"Folder discovery: {error}")

                        paths = (
                            directory / name
                            for directory, _, files in root.walk(on_error=walk_error)
                            for name in files
                            if is_supported_file(name)
                        )
                    else:
                        paths = [root]
                    for path in paths:
                        if self.cancelled():
                            break
                        path = path.resolve()
                        if path in seen:
                            continue
                        seen.add(path)
                        self.imported.emit(path)
                        self.progress.emit(0, f"Inspecting {path.name}…")
                        if self.auto:
                            self.inspect(path)
                self.message.emit(f"Import finished: {len(seen)} file(s) discovered.")
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
        self.preview_cache = OrderedDict()
        self.thread = None
        self.worker = None
        self.last_output = None
        self.setWindowTitle("PM7 Cloud Preview Fixer")
        self.resize(1220, 940)
        self.setMinimumSize(900, 900)
        self.setAcceptDrops(True)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 22, 28, 20)
        layout.setSpacing(12)
        title = QLabel("PM7 Cloud Preview Fixer")
        title.setObjectName("title")
        layout.addWidget(title)
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
            "Drop Anycubic print files or a folder here\n"
            "M7 · M7 Pro · M7 Max · Mono 4 Ultra · P1 · P1 Max\n"
            "Your original files are always preserved."
        )
        hint.setWordWrap(True)
        drop_layout.addWidget(hint, 1)
        self.buttons = []
        self.add_files_button = self.button("Add Files", self.add_files, drop_layout)
        self.button("Add Folder", self.add_folder, drop_layout)
        layout.addWidget(drop)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        self.table = QTableWidget(0, 5)
        self.table.setMinimumHeight(85)
        self.table.setHorizontalHeaderLabels(
            ["Filename", "Size", "Preview status", "Repair status", "Output path"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, width in enumerate((250, 85, 240, 125)):
            self.table.setColumnWidth(i, width)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        splitter.addWidget(self.table)
        self.preview = PreviewPanel()
        splitter.addWidget(self.preview)
        splitter.setMinimumHeight(
            self.table.minimumHeight() + self.preview.minimumHeight() + splitter.handleWidth()
        )
        splitter.setSizes([240, 260])
        layout.addWidget(splitter, 1)
        actions = QHBoxLayout()
        self.update_button = self.button("Update Preview", self.update_selected, actions)
        self.update_button.setObjectName("primary")
        self.update_button.setToolTip("Fix selected files and choose where to save the result")
        self.button("Fix All", lambda: self.prepare_jobs(list(range(len(self.rows)))), actions)
        self.button("Inspect Selected", self.inspect_selected, actions)
        self.button("Remove Selected", self.remove_selected, actions)
        self.button("Clear List", self.clear_rows, actions)
        actions.addStretch()
        self.button("Settings", self.settings, actions)
        layout.addLayout(actions)
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output folder"))
        self.output_folder = QLineEdit(self.prefs.output_folder)
        self.output_folder.setPlaceholderText(
            "Choose on save (single file) or select a batch folder"
        )
        output_row.addWidget(self.output_folder, 1)
        self.button("Browse…", self.browse_output, output_row)
        self.button("Open Output Folder", self.open_output, output_row)
        layout.addLayout(output_row)
        options_row = QHBoxLayout()
        self.force = QCheckBox("Process already compatible files")
        options_row.addWidget(self.force)
        options_row.addStretch()
        self.cancel_button = QPushButton("Cancel after current file")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        options_row.addWidget(self.cancel_button)
        layout.addLayout(options_row)
        self.operation = QLabel("Ready · Offline processing")
        self.operation.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.operation)
        progress_row = QHBoxLayout()
        progress_row.addWidget(QLabel("File"))
        self.file_progress = QProgressBar()
        progress_row.addWidget(self.file_progress, 1)
        progress_row.addWidget(QLabel("Batch"))
        self.batch_progress = QProgressBar()
        progress_row.addWidget(self.batch_progress, 1)
        layout.addLayout(progress_row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setMaximumHeight(80)
        self.log.setPlaceholderText("Progress and error details appear here.")
        layout.addWidget(self.log)
        self.setCentralWidget(root)
        self.setMinimumHeight(max(900, layout.minimumSize().height()))

    def button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        self.buttons.append(button)
        return button

    def selected(self):
        return sorted({item.row() for item in self.table.selectedItems()})

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Anycubic print files", "", OPEN_FILE_FILTER
        )
        if files:
            self.import_paths(files)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Discover Anycubic print files in folder")
        if folder:
            self.import_paths([folder])

    def import_paths(self, paths):
        if self.thread is None:
            self.start_worker("import", paths)

    def dragEnterEvent(self, event):
        if self.thread is None and event.mimeData().hasUrls():
            if all(url.isLocalFile() for url in event.mimeData().urls()):
                event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
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
        printer_format = file_format(path)
        self.table.item(row, 0).setToolTip(
            f"{path}\n{printer_format.printer if printer_format else 'Unsupported format'}"
        )
        if len(self.rows) == 1:
            self.table.selectRow(0)

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
                len(p.original or b"") + len(p.repaired) for p in inspection.previews
            )
        # Bound the cache by file count and a 64 MiB target; keep the active
        # selection and incoming result. Individual PNG limits also apply.
        selected_paths = {self.rows[i].path for i in self.selected()[:1]}
        for cached in list(self.preview_cache):
            if (
                len(self.preview_cache) <= 4
                and sum(self.preview_cache.values()) <= 64 * 1024 * 1024
            ):
                break
            if cached == path or cached in selected_paths:
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
        if index in self.selected():
            self.selection_changed()

    @Slot(object, object, str, str)
    def repaired(self, path, output, status, message):
        index = self.row_index(path)
        if index is None:
            return
        self.rows[index].output = output
        self.table.item(index, 3).setText(status)
        self.table.item(index, 3).setToolTip(message)
        self.table.item(index, 4).setText(str(output) if output else "")
        if output:
            self.last_output = output.parent
        self.add_log(f"{path.name}: {message}")

    def selection_changed(self):
        selected = self.selected()
        row = self.rows[selected[0]] if selected and selected[0] < len(self.rows) else None
        self.preview.set_inspection(row.inspection if row else None, row.error if row else "")
        if row and row.inspection:
            self.preview_cache.move_to_end(row.path, last=True)
        elif row and row.was_inspected and not row.error and self.thread is None:
            self.start_worker("inspect", [row.path])

    def inspect_selected(self):
        paths = [self.rows[i].path for i in self.selected()]
        if paths:
            self.start_worker("inspect", paths)

    def update_selected(self):
        selected = self.selected()
        if not selected and len(self.rows) == 1:
            selected = [0]
        if not selected:
            QMessageBox.information(self, "Select a file", "Add and select an Anycubic file first.")
            return
        self.prepare_jobs(selected)

    def prepare_jobs(self, indices):
        if not indices or self.thread is not None:
            return
        force = self.force.isChecked()
        jobs = []
        if len(indices) == 1:
            source = self.rows[indices[0]].path
            printer_format = file_format(source)
            if printer_format is None:
                QMessageBox.warning(self, "Unsupported format", "Select a supported Anycubic file.")
                return
            folder = Path(self.output_folder.text()) if self.output_folder.text().strip() else None
            suggestion = default_output(source, folder)
            name, _ = QFileDialog.getSaveFileName(
                self,
                "Save file with updated previews",
                str(suggestion),
                printer_format.dialog_filter,
                "",
                QFileDialog.Option.DontConfirmOverwrite,
            )
            if not name:
                return
            output = Path(name)
            if not output.suffix:
                output = output.with_suffix(source.suffix)
            jobs.append((source, output, False, force))
        else:
            folder = QFileDialog.getExistingDirectory(
                self, "Save repaired Anycubic files in folder", self.output_folder.text()
            )
            if not folder:
                return
            self.output_folder.setText(folder)
            reserved = set()
            for index in indices:
                source = self.rows[index].path
                output = default_output(source, Path(folder))
                if output in reserved:
                    QMessageBox.warning(
                        self,
                        "Duplicate output names",
                        "Two selected files have the same filename. Process them "
                        "separately or choose distinct save names.",
                    )
                    return
                reserved.add(output)
                jobs.append((source, output, False, force))
        input_paths = {row.path.resolve() for row in self.rows}
        for source, output, _, _ in jobs:
            if output.resolve() in input_paths:
                QMessageBox.warning(
                    self,
                    "Preserve original files",
                    "An output path matches an imported input file. "
                    "Choose a different name or folder.",
                )
                return
            if output.suffix.lower() != source.suffix.lower():
                QMessageBox.warning(
                    self,
                    "Keep the printer file extension",
                    f"Use the original {source.suffix} extension. "
                    "Preview repair does not convert files between printers.",
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

    def remove_selected(self):
        self.table.blockSignals(True)
        for index in reversed(self.selected()):
            self.preview_cache.pop(self.rows[index].path, None)
            del self.rows[index]
            self.table.removeRow(index)
        self.table.blockSignals(False)
        self.selection_changed()

    def clear_rows(self):
        self.rows.clear()
        self.preview_cache.clear()
        self.table.setRowCount(0)
        self.preview.set_inspection(None)

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Output folder", self.output_folder.text())
        if folder:
            self.output_folder.setText(folder)
            self.prefs.output_folder = folder
            self.prefs.save()

    def open_output(self):
        folder = self.last_output or self.output_folder.text()
        if folder and Path(folder).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def settings(self):
        dialog = SettingsDialog(self.prefs, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.prefs = dialog.preferences()
            self.prefs.save()
            self.output_folder.setText(self.prefs.output_folder)
            # Recompute proposals using the new background/compression choices.
            if self.rows:
                self.start_worker("inspect", [row.path for row in self.rows])

    def start_worker(self, kind, items):
        if self.thread is not None:
            return
        self.set_busy(True)
        self.file_progress.setValue(0)
        self.batch_progress.setRange(0, 0 if kind == "import" else len(items))
        self.batch_progress.setValue(0)
        self.thread = QThread(self)
        self.worker = Worker(kind, items, self.prefs.options(), self.prefs.auto_inspect)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.imported.connect(self.add_row)
        self.worker.inspected.connect(self.inspected)
        self.worker.repaired.connect(self.repaired)
        self.worker.progress.connect(self.show_progress)
        self.worker.overall.connect(self.show_overall)
        self.worker.message.connect(self.add_log)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def set_busy(self, busy):
        for button in self.buttons:
            button.setEnabled(not busy)
        self.force.setEnabled(not busy)
        self.output_folder.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    @Slot(int, str)
    def show_progress(self, value, message):
        self.file_progress.setValue(value)
        self.operation.setText(message)

    @Slot(int, int)
    def show_overall(self, value, total):
        self.batch_progress.setRange(0, total)
        self.batch_progress.setValue(value)

    @Slot(str)
    def add_log(self, message):
        self.log.appendPlainText(message)
        self.operation.setText(message)
        log.info(message)

    @Slot()
    def worker_finished(self):
        self.thread, self.worker = None, None
        if self.batch_progress.maximum() == 0:
            self.batch_progress.setRange(0, 1)
            self.batch_progress.setValue(1)
        self.set_busy(False)
        self.selection_changed()

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
        self.prefs.output_folder = self.output_folder.text().strip()
        self.prefs.save()
        event.accept()


STYLESHEET = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #e5edf9; }
QMainWindow, QDialog { background: #101722; }
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
