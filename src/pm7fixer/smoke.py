"""Exercise packaged dependencies and the actual repair core in an isolated temp folder."""

import hashlib
import io
import tempfile
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from pm7fixer.core import PREVIEWS, Options, inspect_file, png_image, write_repaired
from pm7fixer.formats import FORMATS


def run_smoke():
    with tempfile.TemporaryDirectory(prefix="pm7-smoke-") as directory:
        artwork = Image.new("RGBA", (224, 168))
        ImageDraw.Draw(artwork).rectangle((60, 25, 164, 140), fill=(200, 100, 80, 255))
        buffer = io.BytesIO()
        artwork.save(buffer, format="PNG")
        layer = b"SLICED PRINT DATA\x00" * 10000
        formats = {}
        for printer_format in FORMATS:
            source = Path(directory) / f"example{printer_format.extension}"
            output = source.with_name(f"example_with_preview{printer_format.extension}")
            layer_name = "layer_images/layer_0.pwszImg"
            settings = (f'{{"machine_type":{{"name":"{printer_format.printer}"}}}}').encode()
            with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(PREVIEWS[0], buffer.getvalue())
                archive.writestr(PREVIEWS[1], buffer.getvalue())
                archive.writestr(layer_name, layer)
                archive.writestr("anycubic_photon_resins.pwsp", settings)
                archive.writestr("print_info.json", '{"exposure": 2.5}')
            inspection = inspect_file(source)
            write_repaired(inspection, output, Options())
            with zipfile.ZipFile(output) as archive:
                assert archive.testzip() is None
                assert hashlib.sha256(archive.read(layer_name)).digest() == (
                    hashlib.sha256(layer).digest()
                )
                assert archive.read("anycubic_photon_resins.pwsp") == settings
                assert png_image(archive.read(PREVIEWS[2])).size == (800, 600)
            assert inspect_file(output).compatible
            formats[printer_format.extension] = "passed"
        return {
            "repair": "passed",
            "non_preview_sha256": "passed",
            "zip_integrity": "passed",
            "cloud_preview_size": [800, 600],
            "formats": formats,
        }
