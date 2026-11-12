"""Windows entry point, logging, and packaged smoke test."""

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from pm7fixer import __version__
from pm7fixer.ui import start_window


def dispose_widgets(app):
    # Dispose C++ widgets before QApplication / Python teardown. Signal closures
    # can keep Python wrappers alive beyond their local scope on Windows.
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def main():
    QCoreApplication.setOrganizationName("PM7PreviewFixer")
    QCoreApplication.setApplicationName("PM7 Cloud Preview Fixer")
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv[:1])
    report_path = None
    if "--smoke-test" in sys.argv:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetErrorMode(0x0002)
        report_path = Path(sys.argv[sys.argv.index("--smoke-test") + 1]).resolve()
        folder = report_path.parent / "smoke-data"
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(folder))
    else:
        folder = Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        )
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        folder / "app.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s"
    )

    def handle_exception(exc_type, exc, traceback):
        logging.critical("Unhandled application error", exc_info=(exc_type, exc, traceback))
        QMessageBox.critical(None, "PM7 Cloud Preview Fixer", str(exc))

    sys.excepthook = handle_exception
    if report_path:
        # Explicit diagnostic mode; no printer, network, or user files involved.
        from pm7fixer.smoke import run_smoke

        try:
            report = run_smoke()
            window = start_window()
            report["window_title"] = window.windowTitle()
            report["update_button"] = window.update_button.text()
            QTimer.singleShot(200, app.quit)
            exit_code = app.exec()
            dispose_widgets(app)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return exit_code
        except Exception as exc:
            report_path.write_text(json.dumps({"error": str(exc)}), encoding="utf-8")
            return 1
    window = start_window([arg for arg in sys.argv[1:] if not arg.startswith("--")])
    window.raise_()
    exit_code = app.exec()
    dispose_widgets(app)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
