"""Render the real Qt window to PNG using synthetic artwork, without desktop control."""

import io
import os
import sys
import time
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from anycubic_file_updater.core import PREVIEWS, default_output, inspect_file, write_repaired  # noqa: E402
from anycubic_file_updater.settings import Preferences  # noqa: E402
from anycubic_file_updater.ui import SettingsDialog, start_window  # noqa: E402

folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".cache/ui-preview").resolve()
folder.mkdir(parents=True, exist_ok=True)
QCoreApplication.setOrganizationName("PM7FixerPreview")
QCoreApplication.setApplicationName("UIReview")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(folder))
source = folder / "sample_model.pm7"
with zipfile.ZipFile(source, "w") as archive:
    for i, size in enumerate(((224, 168), (336, 252))):
        image = Image.new("RGBA", size)
        draw = ImageDraw.Draw(image)
        w, h = size
        draw.polygon(
            [
                (w * 0.3, h * 0.78),
                (w * 0.35, h * 0.4),
                (w * 0.5, h * 0.12),
                (w * 0.65, h * 0.4),
                (w * 0.7, h * 0.78),
            ],
            fill=(184, 163, 205, 255),
        )
        draw.ellipse((w * 0.2, h * 0.72, w * 0.8, h * 0.9), fill=(125, 112, 145, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        archive.writestr(PREVIEWS[i], buffer.getvalue())
    archive.writestr("layer_images/layer_0.pw0Img", b"synthetic sliced data")
    archive.writestr("anycubic_photon_resins.pwsp", b'{"machine_type":{"name":"M7"}}')
app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
window = start_window()
window.prefs = Preferences()
app.processEvents()
window.grab().save(str(folder / "empty-window.png"))
window.import_paths([str(source)])
deadline = time.monotonic() + 15
app.processEvents()
while window.thread is not None:
    app.processEvents()
    if time.monotonic() > deadline:
        raise RuntimeError("Inspection timed out")
    time.sleep(0.01)
app.processEvents()
window.grab().save(str(folder / "cloud-preview.png"))
app.processEvents()
window.grab().save(str(folder / "transparency-preview.png"))
window.resize(900, 700)
app.processEvents()
window.grab().save(str(folder / "minimum-window.png"))
second = folder / "second_model.pm7"
second.write_bytes(source.read_bytes())
window.resize(1220, 940)
window.import_paths([str(second)])
deadline = time.monotonic() + 15
while window.thread is not None:
    app.processEvents()
    if time.monotonic() > deadline:
        raise RuntimeError("Second inspection timed out")
    time.sleep(0.01)
app.processEvents()
app.processEvents()
window.grab().save(str(folder / "batch-preview.png"))
for path in (source, second):
    result = write_repaired(inspect_file(path), default_output(path), overwrite=True)
    window.repaired(path, result.output, result.status, result.message)
window.show_progress(100, "Saved and verified")
app.processEvents()
window.grab().save(str(folder / "saved-outputs.png"))
window.resize(900, 900)
app.processEvents()
window.grab().save(str(folder / "saved-outputs-minimum.png"))
window.prefs.transparent_preview2 = True
window.start_worker("inspect", [source])
deadline = time.monotonic() + 15
while window.thread is not None:
    app.processEvents()
    if time.monotonic() > deadline:
        raise RuntimeError("Transparent preview inspection timed out")
    time.sleep(0.01)
app.processEvents()
window.grab().save(str(folder / "transparent-cloud-preview.png"))
dialog = SettingsDialog(window.prefs, window)
dialog.show()
app.processEvents()
dialog.grab().save(str(folder / "settings.png"))
dialog.close()
window.close()
print(f"Rendered {folder}")
