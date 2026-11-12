import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from pm7fixer.core import default_output, inspect_file
from pm7fixer.formats import FORMATS
from pm7fixer.settings import Preferences
from pm7fixer.ui import MainWindow, SettingsDialog


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    from PySide6.QtCore import QSettings

    QCoreApplication.setOrganizationName("PM7FixerTests")
    QCoreApplication.setApplicationName("IsolatedTests")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path_factory.mktemp("settings")),
    )
    instance = QApplication.instance() or QApplication([])
    yield instance
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    instance.processEvents()


@pytest.fixture
def window(app):
    widget = MainWindow()
    widget.prefs = Preferences()
    yield widget
    wait_for_idle(widget, app)
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def wait_for_idle(window, app, timeout=15):
    end = time.monotonic() + timeout
    while window.thread is not None:
        app.processEvents()
        if time.monotonic() > end:
            window.cancel()
            pytest.fail("Worker did not finish")
        time.sleep(0.005)
    app.processEvents()


def test_select_update_save_and_inspect_flow(window, app, make_pm7, monkeypatch):
    source = make_pm7()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: ([str(source)], ""))
    window.add_files_button.click()
    wait_for_idle(window, app)
    assert len(window.rows) == 1
    assert window.table.item(0, 2).text() == "Missing cloud preview"
    assert window.preview.inspection is not None
    assert not window.preview.after.picture.isNull()
    assert window.preview.before.picture.isNull()  # cloud preview missing
    destination = default_output(source)
    suggestions = []

    def save(*args):
        suggestions.append(args[2])
        return str(destination), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save)
    window.update_button.click()
    assert not window.update_button.isEnabled()
    wait_for_idle(window, app)
    assert Path(suggestions[0]).name == "original_with_preview.pm7"
    assert inspect_file(destination).compatible
    assert window.table.item(0, 3).text() == "Saved"
    assert window.rows[0].output == destination
    assert "1 saved" in window.log.toPlainText()
    assert window.update_button.isEnabled()


@pytest.mark.parametrize("printer_format", FORMATS, ids=lambda value: value.extension)
def test_every_format_import_and_save_dialog(window, app, make_pm7, monkeypatch, printer_format):
    source = make_pm7(f"printer{printer_format.extension.upper()}")
    dialogs = []

    def choose(*args):
        dialogs.append(args)
        return [str(source)], ""

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", choose)
    window.add_files_button.click()
    wait_for_idle(window, app)
    assert f"*{printer_format.extension}" in dialogs[0][3]
    assert printer_format.printer in window.preview.title.text()
    saved = []

    def save(*args):
        saved.append(args)
        # An extensionless filename should receive this input's extension.
        return str(source.with_name("saved_with_preview")), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save)
    window.update_button.click()
    wait_for_idle(window, app)
    output = source.with_name(f"saved_with_preview{source.suffix}")
    assert Path(saved[0][2]).name == f"printer_with_preview{source.suffix}"
    assert saved[0][3] == printer_format.dialog_filter
    assert inspect_file(output).compatible
    assert window.rows[0].output == output


def test_folder_discovers_all_supported_formats(window, app, make_pm7, tmp_path):
    originals = [make_pm7(f"printer{item.extension.upper()}") for item in FORMATS]
    ignored = make_pm7("legacy.pm5s")
    window.import_paths([tmp_path])
    wait_for_idle(window, app)
    assert {row.path for row in window.rows} == set(originals)
    assert ignored not in {row.path for row in window.rows}


def test_mixed_printer_batch_retains_each_extension(window, app, make_pm7, tmp_path, monkeypatch):
    sources = [make_pm7(f"same_model{item.extension}") for item in FORMATS]
    folder = tmp_path / "output"
    folder.mkdir()
    window.import_paths(sources)
    wait_for_idle(window, app)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(folder))
    window.prepare_jobs(list(range(len(sources))))
    wait_for_idle(window, app)
    for index, source in enumerate(sources):
        assert window.rows[index].output == default_output(source, folder)
        assert inspect_file(default_output(source, folder)).compatible
    assert "6 saved, 0 skipped, 0 failed" in window.log.toPlainText()


def test_gui_rejects_cross_printer_output_extension(window, app, make_pm7, monkeypatch):
    source = make_pm7("model.pwsz")
    window.import_paths([source])
    wait_for_idle(window, app)
    output = source.with_suffix(".pm7")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.update_button.click()
    assert warnings
    assert window.thread is None
    assert not output.exists()


def test_drag_drop_and_recursive_folder_discovery(window, app, make_pm7, tmp_path):
    source = make_pm7()
    nested = tmp_path / "nested"
    nested.mkdir()
    second = source.rename(nested / "nested.PM7")
    make_pm7("root.pm7")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path))])
    enter = QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(enter)
    assert enter.isAccepted()
    drop = QDropEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(drop)
    wait_for_idle(window, app)
    assert len(window.rows) == 2
    assert second in [row.path for row in window.rows]


def test_cancel_save_produces_no_output(window, app, make_pm7, monkeypatch):
    source = make_pm7()
    window.import_paths([source])
    wait_for_idle(window, app)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    window.update_button.click()
    assert window.thread is None
    assert not default_output(source).exists()


def test_original_output_is_rejected(window, app, make_pm7, monkeypatch):
    source = make_pm7()
    window.import_paths([source])
    wait_for_idle(window, app)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(source), ""))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.update_button.click()
    assert warnings
    assert window.thread is None
    assert not inspect_file(source).compatible


def test_settings_restore_and_roundtrip(app):
    dialog = SettingsDialog(Preferences(output_folder="D:/example", compression=9))
    dialog.reset()
    assert dialog.preferences() == Preferences()
    prefs = Preferences(auto_inspect=False, compression=8)
    prefs.save()
    assert Preferences.load() == prefs
    Preferences().save()


def test_manual_inspection_and_remove_clear(window, app, make_pm7):
    source = make_pm7()
    window.prefs.auto_inspect = False
    window.import_paths([source])
    wait_for_idle(window, app)
    assert window.table.item(0, 2).text() == "Not inspected"
    window.inspect_selected()
    wait_for_idle(window, app)
    assert window.rows[0].inspection is not None
    window.remove_selected()
    assert not window.rows
    window.import_paths([source])
    wait_for_idle(window, app)
    window.clear_rows()
    assert not window.rows


def test_preview_cache_is_bounded_and_reloads_selection(window, app, make_pm7):
    paths = [make_pm7(f"model_{i}.pm7") for i in range(12)]
    window.import_paths(paths)
    wait_for_idle(window, app)
    assert len(window.rows) == 12
    assert sum(row.inspection is not None for row in window.rows) <= 4
    evicted = next(i for i, row in enumerate(window.rows) if row.inspection is None)
    window.table.selectRow(evicted)
    wait_for_idle(window, app)
    assert window.rows[evicted].inspection is not None
    assert window.preview.inspection.source == paths[evicted]


def test_overwrite_requires_confirmation(window, app, make_pm7, monkeypatch):
    source = make_pm7()
    window.import_paths([source])
    wait_for_idle(window, app)
    output = default_output(source)
    output.write_bytes(b"existing output")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.update_button.click()
    assert output.read_bytes() == b"existing output"
    assert window.thread is None
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.update_button.click()
    wait_for_idle(window, app)
    assert inspect_file(output).compatible


def test_batch_ui_continues_after_invalid_archive(window, app, make_pm7, tmp_path, monkeypatch):
    first = make_pm7()
    bad = tmp_path / "bad.pm7"
    bad.write_bytes(b"invalid")
    folder = tmp_path / "output"
    folder.mkdir()
    window.import_paths([first, bad])
    wait_for_idle(window, app)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(folder))
    window.prepare_jobs([0, 1])
    wait_for_idle(window, app)
    assert window.table.item(0, 3).text() == "Saved"
    assert window.table.item(1, 3).text() == "Failed"
    assert "1 saved, 0 skipped, 1 failed" in window.log.toPlainText()
