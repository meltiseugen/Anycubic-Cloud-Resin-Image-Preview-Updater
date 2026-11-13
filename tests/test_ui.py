import time

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMimeData,
    QPoint,
    QProcess,
    QSettings,
    Qt,
    QUrl,
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QPushButton,
)

from anycubic_file_updater.core import default_output, inspect_file, png_image
from anycubic_file_updater.formats import FORMATS
from anycubic_file_updater.settings import Preferences
from anycubic_file_updater.ui import MainWindow, SettingsDialog


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


def test_window_controls_and_title_bar(window, app):
    window.show()
    app.processEvents()
    assert window.windowTitle() == "Anycubic File Updater"
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    normal_size = window.size()
    window.maximize_button.click()
    app.processEvents()
    assert window.isMaximized()
    assert window.maximize_button.accessibleName() == "Restore"
    QTest.mouseDClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    app.processEvents()
    assert not window.isMaximized()
    assert window.size() == normal_size
    assert window.maximize_button.accessibleName() == "Maximize"
    window.minimize_button.click()
    app.processEvents()
    assert window.isMinimized()
    window.showNormal()
    window.close_button.click()
    assert not window.isVisible()


def test_window_delegates_drag_and_all_resize_edges_to_qt(window, app, monkeypatch):
    window.show()
    app.processEvents()
    handle = window.windowHandle()
    resizes, moves = [], []
    monkeypatch.setattr(handle, "startSystemResize", lambda edges: resizes.append(edges) or True)
    monkeypatch.setattr(handle, "startSystemMove", lambda: moves.append(True) or True)
    root = window.centralWidget()
    width, height = root.width(), root.height()
    positions = (
        (QPoint(1, height // 2), Qt.Edge.LeftEdge),
        (QPoint(width - 1, height // 2), Qt.Edge.RightEdge),
        (QPoint(width // 2, 1), Qt.Edge.TopEdge),
        (QPoint(width // 2, height - 1), Qt.Edge.BottomEdge),
        (QPoint(1, 1), Qt.Edge.TopEdge | Qt.Edge.LeftEdge),
        (QPoint(width - 1, 1), Qt.Edge.TopEdge | Qt.Edge.RightEdge),
        (QPoint(1, height - 1), Qt.Edge.BottomEdge | Qt.Edge.LeftEdge),
        (QPoint(width - 1, height - 1), Qt.Edge.BottomEdge | Qt.Edge.RightEdge),
    )
    for point, edges in positions:
        QTest.mouseClick(root, Qt.MouseButton.LeftButton, pos=point)
        assert resizes[-1] == edges
    QTest.mouseClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert moves == [True]
    window.showMaximized()
    app.processEvents()
    QTest.mouseClick(root, Qt.MouseButton.LeftButton, pos=QPoint(1, root.height() // 2))
    assert len(resizes) == len(positions)


@pytest.mark.parametrize("count", [1, 2])
def test_only_file_progress_is_shown_after_import(window, app, make_pm7, count):
    window.show()
    app.processEvents()
    file_width = window.file_progress.width()
    sources = [make_pm7(f"model_{index}.pm7") for index in range(count)]
    window.import_paths(sources)
    wait_for_idle(window, app)
    assert window.findChildren(QProgressBar) == [window.file_progress]
    assert window.file_progress.width() == file_width
    assert window.file_progress.value() == 0
    window.update_button.click()
    wait_for_idle(window, app)
    assert window.file_progress.value() == 100
    assert all(default_output(path).exists() for path in sources)
    window.clear_rows()
    assert window.findChildren(QProgressBar) == [window.file_progress]


def test_select_update_saves_beside_original_without_dialogs(window, app, make_pm7, monkeypatch):
    source = make_pm7()
    original = source.read_bytes()
    # An old output-folder preference must not redirect new output.
    QSettings().setValue("output_folder", "D:/old-output-folder")
    window.prefs = Preferences.load()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: pytest.fail("Save dialog"))
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args: pytest.fail("Folder dialog")
    )
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: ([str(source)], ""))
    window.add_files_button.click()
    wait_for_idle(window, app)
    assert len(window.rows) == 1
    assert window.table.item(0, 2).text() == "Missing cloud preview"
    assert window.preview.inspection is not None
    assert not window.preview.after.picture.isNull()
    assert window.preview.before.picture.isNull()  # cloud preview missing
    destination = default_output(source)
    window.update_button.click()
    assert not window.update_button.isEnabled()
    wait_for_idle(window, app)
    assert destination.parent == source.parent
    assert source.read_bytes() == original
    assert inspect_file(destination).compatible
    assert window.table.item(0, 3).text() == "Saved"
    assert window.rows[0].output == destination
    assert "1 saved" in window.log.toPlainText()
    assert window.update_button.isEnabled()


@pytest.mark.parametrize("printer_format", FORMATS, ids=lambda value: value.extension)
def test_every_format_import_and_automatic_output(
    window, app, make_pm7, monkeypatch, printer_format
):
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
    window.update_button.click()
    wait_for_idle(window, app)
    output = default_output(source)
    assert output.name == f"printer_with_preview{source.suffix}"
    assert inspect_file(output).compatible
    assert window.rows[0].output == output


def test_folder_import_is_rejected_and_manual_files_are_supported(window, app, make_pm7, tmp_path):
    originals = [make_pm7(f"printer{item.extension.upper()}") for item in FORMATS]
    ignored = make_pm7("legacy.pm5s")
    window.import_paths([tmp_path])
    wait_for_idle(window, app)
    assert not window.rows
    assert "Select individual supported print files" in window.log.toPlainText()
    window.import_paths([*originals, ignored])
    wait_for_idle(window, app)
    assert {row.path for row in window.rows} == set(originals)
    assert ignored not in {row.path for row in window.rows}


def test_mixed_printer_batch_saves_beside_each_original(
    window, app, make_pm7, tmp_path, monkeypatch
):
    sources = [make_pm7(f"same_model{item.extension}") for item in FORMATS]
    for index, source in enumerate(sources):
        folder = tmp_path / f"printer-{index}"
        folder.mkdir()
        sources[index] = source.rename(folder / source.name)
    window.import_paths(sources)
    wait_for_idle(window, app)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: pytest.fail("Save dialog"))
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args: pytest.fail("Folder dialog")
    )
    window.prepare_jobs(list(range(len(sources))))
    wait_for_idle(window, app)
    for index, source in enumerate(sources):
        assert window.rows[index].output == default_output(source)
        assert inspect_file(default_output(source)).compatible
    assert "6 saved, 0 skipped, 0 failed" in window.log.toPlainText()


def test_update_processes_every_imported_file_without_selection(window, app, make_pm7):
    window.show()
    sources = [make_pm7(f"model-{index}.pm7") for index in range(3)]
    window.import_paths(sources[:1])
    wait_for_idle(window, app)
    window.import_paths(sources[1:])
    wait_for_idle(window, app)
    window.show_file(2)
    assert not window.table.selectedItems()
    assert window.preview.inspection.source == sources[2]
    assert not hasattr(window, "fix_all_button")
    window.update_button.click()
    wait_for_idle(window, app)
    assert all(default_output(source).is_file() for source in sources)
    assert all(row.output == default_output(row.path) for row in window.rows)


def test_identical_filenames_in_different_folders_have_separate_outputs(
    window, app, make_pm7, tmp_path
):
    first = make_pm7("model.pm7")
    folder = tmp_path / "another-folder"
    folder.mkdir()
    second = folder / first.name
    second.write_bytes(first.read_bytes())
    window.import_paths([first, second])
    wait_for_idle(window, app)
    window.update_button.click()
    wait_for_idle(window, app)
    assert all(inspect_file(default_output(path)).compatible for path in (first, second))


def test_drag_drop_individual_files(window, app, make_pm7):
    source = make_pm7()
    second = make_pm7("second.PWSZ")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in (source, second)])
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


@pytest.mark.parametrize("kind", ["folder", "mixed", "unsupported"])
def test_folder_and_unsupported_drops_are_rejected(window, make_pm7, tmp_path, kind):
    source = make_pm7()
    paths = {
        "folder": [tmp_path],
        "mixed": [source, tmp_path],
        "unsupported": [make_pm7("legacy.pm5s")],
    }[kind]
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    enter = QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(enter)
    assert not enter.isAccepted()
    drop = QDropEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(drop)
    assert not drop.isAccepted()
    assert not window.rows
    assert window.thread is None


def test_output_cannot_replace_an_imported_original(window, app, make_pm7, monkeypatch):
    source = make_pm7()
    conflict = default_output(source)
    conflict.write_bytes(b"An imported original must not be overwritten")
    original_bytes = conflict.read_bytes()
    window.import_paths([source, conflict])
    wait_for_idle(window, app)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.update_button.click()
    assert warnings
    assert window.thread is None
    assert not inspect_file(source).compatible
    assert conflict.read_bytes() == original_bytes


def test_settings_restore_and_roundtrip(app):
    dialog = SettingsDialog(Preferences(compression=9, transparent_preview2=True))
    assert dialog.transparent_preview2.isChecked()
    assert not dialog.color_buttons[2].isEnabled()
    dialog.reset()
    assert not dialog.color_buttons[2].isEnabled()
    assert dialog.preferences() == Preferences()
    prefs = Preferences(auto_inspect=False, compression=8, transparent_preview2=True)
    prefs.save()
    assert Preferences.load() == prefs
    Preferences().save()


def test_settings_gear_updates_transparent_cloud_proposal_and_saved_file(
    window, app, make_pm7, monkeypatch
):
    source = make_pm7()
    window.prefs.transparent_preview2 = False
    window.import_paths([source])
    wait_for_idle(window, app)
    assert not window.preview.inspection.previews[2].repaired_transparent

    def accept_transparency(dialog):
        dialog.transparent_preview2.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SettingsDialog, "exec", accept_transparency)
    window.settings_button.click()
    wait_for_idle(window, app)
    assert Preferences.load().transparent_preview2
    assert window.preview.inspection.previews[2].repaired_transparent
    assert "transparent pixels" in window.preview.details.text().split("After:")[1]
    window.update_button.click()
    wait_for_idle(window, app)
    assert window.rows[0].output == default_output(source)
    assert inspect_file(default_output(source), window.prefs.options()).compatible
    assert png_image(window.preview.inspection.previews[2].repaired).getpixel((0, 0))[3] == 0
    Preferences().save()


def test_open_folder_buttons_follow_saved_outputs_after_row_removal(
    window, app, make_pm7, tmp_path, monkeypatch
):
    first, second = make_pm7("first.pm7"), make_pm7("second.pm7")
    other = tmp_path / "another folder, \u00fc"
    other.mkdir()
    second = second.rename(other / second.name)
    opened = []
    monkeypatch.setattr(
        QProcess,
        "startDetached",
        lambda program, args: (opened.append((program, args)) or True, 123),
    )
    window.import_paths([first, second])
    wait_for_idle(window, app)
    assert window.table.cellWidget(0, 4) is None
    window.prepare_jobs([0, 1])
    wait_for_idle(window, app)
    assert not opened
    first_open = window.table.cellWidget(0, 4).findChild(QPushButton, "openOutputFolder")
    second_open = window.table.cellWidget(1, 4).findChild(QPushButton, "openOutputFolder")
    assert first_open.text() == "Open folder"
    first_open.click()
    assert opened[-1] == ("explorer.exe", ["/select,", str(default_output(first).resolve())])
    window.table.cellWidget(0, 5).click()
    second_open.click()
    assert opened[-1] == ("explorer.exe", ["/select,", str(default_output(second).resolve())])
    assert window.rows[0].output == default_output(second)


def test_compatible_file_processing_uses_settings_without_main_checkbox(window, app, make_pm7):
    source = make_pm7(compatible=True)
    window.import_paths([source])
    wait_for_idle(window, app)
    window.update_button.click()
    wait_for_idle(window, app)
    assert window.table.item(0, 3).text() == "Skipped"
    assert window.table.cellWidget(0, 4) is None
    window.prefs.skip_compatible = False
    window.update_button.click()
    wait_for_idle(window, app)
    assert window.table.item(0, 3).text() == "Saved"
    assert window.table.cellWidget(0, 4).findChild(QPushButton, "openOutputFolder")


def test_selection_inspects_files_without_manual_inspect_button(window, app, make_pm7):
    sources = [make_pm7(f"model-{index}.pm7") for index in range(2)]
    window.prefs.auto_inspect = False
    window.import_paths(sources)
    wait_for_idle(window, app)
    assert window.rows[0].inspection is not None
    assert window.rows[1].inspection is None
    window.show_file(1)
    wait_for_idle(window, app)
    assert window.preview.inspection.source == sources[1]


def test_row_remove_buttons_keep_correct_paths_after_rows_shift(window, app, make_pm7):
    sources = [make_pm7(f"model-{index}.pm7") for index in range(3)]
    original_bytes = [source.read_bytes() for source in sources]
    window.import_paths(sources)
    wait_for_idle(window, app)
    window.show_file(2)
    last_remove = window.table.cellWidget(2, 5)
    assert sources[2].name in last_remove.accessibleName()
    window.table.cellWidget(0, 5).click()
    assert [row.path for row in window.rows] == sources[1:]
    assert window.preview.inspection.source == sources[2]
    last_remove.click()
    assert [row.path for row in window.rows] == [sources[1]]
    assert sources[0] not in window.preview_cache
    assert sources[2] not in window.preview_cache
    window.clear_button.click()
    assert not window.rows
    assert window.preview.inspection is None
    assert [source.read_bytes() for source in sources] == original_bytes


def test_list_controls_cannot_remove_files_during_work(window, app, make_pm7):
    source = make_pm7()
    window.import_paths([source])
    wait_for_idle(window, app)
    remove = window.table.cellWidget(0, 5)
    window.start_worker("inspect", [source])
    assert not remove.isEnabled()
    assert not window.clear_button.isEnabled()
    remove.click()
    window.remove_file(source)
    window.clear_rows()
    assert len(window.rows) == 1
    wait_for_idle(window, app)
    assert remove.isEnabled()
    assert window.clear_button.isEnabled()


def test_simplified_controls_and_clear_list_position(window, app):
    window.show()
    app.processEvents()
    captions = {button.text() for button in window.findChildren(QPushButton)}
    assert not captions.intersection(
        {"Add Folder", "Inspect Selected", "Remove Selected", "Browse…", "Open Output Folder"}
    )
    clear_position = window.clear_button.mapTo(window, QPoint(0, 0))
    table_position = window.table.mapTo(window, QPoint(0, 0))
    assert clear_position.x() > table_position.x() + window.table.width() // 2
    assert clear_position.y() < table_position.y()
    assert not window.findChildren(QCheckBox)
    assert not hasattr(window.preview, "selector")
    assert window.settings_button.accessibleName() == "Settings"
    settings_position = window.settings_button.mapTo(window, QPoint(0, 0))
    update_position = window.update_button.mapTo(window, QPoint(0, 0))
    assert settings_position.x() > window.width() // 2
    assert settings_position.y() < clear_position.y()
    assert update_position.x() > window.width() // 2
    assert update_position.x() + window.update_button.width() == (
        clear_position.x() + window.clear_button.width()
    )


def test_preview_cache_is_bounded_and_reloads_selection(window, app, make_pm7):
    paths = [make_pm7(f"model_{i}.pm7") for i in range(12)]
    window.import_paths(paths)
    wait_for_idle(window, app)
    assert len(window.rows) == 12
    assert sum(row.inspection is not None for row in window.rows) <= 4
    evicted = next(i for i, row in enumerate(window.rows) if row.inspection is None)
    window.show_file(evicted)
    wait_for_idle(window, app)
    assert window.rows[evicted].inspection is not None
    assert window.preview.inspection.source == paths[evicted]


def test_overwrite_requires_confirmation(window, app, make_pm7, monkeypatch):
    source = make_pm7()
    window.import_paths([source])
    wait_for_idle(window, app)
    output = default_output(source)
    output.write_bytes(b"existing output")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.update_button.click()
    assert output.read_bytes() == b"existing output"
    assert window.thread is None
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.update_button.click()
    wait_for_idle(window, app)
    assert inspect_file(output).compatible


def test_batch_ui_continues_after_invalid_archive(window, app, make_pm7, tmp_path):
    first = make_pm7()
    bad = tmp_path / "bad.pm7"
    bad.write_bytes(b"invalid")
    window.import_paths([first, bad])
    wait_for_idle(window, app)
    window.prepare_jobs([0, 1])
    wait_for_idle(window, app)
    assert window.table.item(0, 3).text() == "Saved"
    assert window.table.item(1, 3).text() == "Failed"
    assert "1 saved, 0 skipped, 1 failed" in window.log.toPlainText()
    window.clear_rows()
