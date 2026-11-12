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

from pm7fixer.core import PREVIEWS  # noqa: E402
from pm7fixer.ui import start_window  # noqa: E402

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
window = start_window([str(source)])
deadline = time.monotonic() + 15
app.processEvents()
while window.thread is not None:
    app.processEvents()
    if time.monotonic() > deadline:
        raise RuntimeError("Inspection timed out")
    time.sleep(0.01)
app.processEvents()
window.grab().save(str(folder / "cloud-preview.png"))
window.preview.selector.setCurrentIndex(0)
app.processEvents()
window.grab().save(str(folder / "transparency-preview.png"))
window.resize(900, 700)
app.processEvents()
window.grab().save(str(folder / "minimum-window.png"))
window.close()
print(f"Rendered {folder}")
