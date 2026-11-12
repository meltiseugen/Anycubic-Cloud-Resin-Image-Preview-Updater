import io
import os
import zipfile

import pytest
from PIL import Image, ImageDraw

from pm7fixer.core import PREVIEWS

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def artwork(size=(224, 168), transparent=True, color=(190, 80, 130, 255)):
    image = Image.new("RGBA", size, (0, 0, 0, 0) if transparent else (20, 27, 41, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4), fill=color)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def make_pm7(tmp_path):
    def make(
        name="original.pm7", *, compatible=False, layers=4, previews=None, layer_extension="pw0Img"
    ):
        path = tmp_path / name
        if previews is None:
            previews = {0: artwork(), 1: artwork((336, 252))}
            if compatible:
                previews = {
                    0: artwork((168, 126), False),
                    1: artwork((168, 126), False),
                    2: artwork((800, 600), False),
                }
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b"original archive comment"
            for index, data in previews.items():
                archive.writestr(PREVIEWS[index], data)
            info = zipfile.ZipInfo("print_info.json", (2024, 5, 6, 7, 8, 10))
            info.comment = b"retain metadata"
            info.external_attr = 0o640 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, b'{"exposure_time": 2.5, "printer": "M7", "unaltered": true}')
            for name in (
                "layers_controller.conf",
                "software_info.conf",
                "anycubic_photon_resins.pwsp",
                "lcd_function.json",
                "other/unknown.bin",
            ):
                archive.writestr(name, b"\x00\xff\x01preserve exact contents\r\n")
            archive.writestr("layer_images/", b"")
            for index in range(layers):
                archive.writestr(
                    f"layer_images/layer_{index}.{layer_extension}",
                    b"SLICE\x00" + index.to_bytes(4, "little") + b"\x01" * 8192,
                )
        return path

    return make
