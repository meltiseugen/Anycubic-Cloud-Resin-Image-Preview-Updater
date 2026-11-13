import hashlib
import io
import zipfile
import zlib
from pathlib import Path

import pytest
from conftest import artwork
from PIL import Image

from anycubic_file_updater.core import (
    DEFAULT_COLORS,
    PREVIEWS,
    Options,
    RepairError,
    default_output,
    flatten,
    inspect_file,
    png_image,
    repair_batch,
    write_repaired,
)


def hashes(path):
    with zipfile.ZipFile(path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name != PREVIEWS[2]
        }


def test_missing_and_transparent_previews_detected(make_pm7):
    inspection = inspect_file(make_pm7())
    assert not inspection.compatible
    assert inspection.status == "Missing cloud preview"
    assert inspection.previews[0].transparent
    assert inspection.previews[1].dimensions == (336, 252)
    assert inspection.previews[2].original is None


def test_repair_artwork_colors_dimensions_and_integrity(make_pm7):
    source = make_pm7(layers=2486)
    original_hashes = hashes(source)
    original_file_hash = hashlib.sha256(source.read_bytes()).digest()
    options = Options(transparent_preview2=False)
    inspection = inspect_file(source, options)
    destination = default_output(source)
    progress = []
    result = write_repaired(
        inspection, destination, options, progress=lambda value, message: progress.append(value)
    )
    assert result.status == "Saved"
    assert destination.name == "original_with_preview.pm7"
    assert hashes(destination) == original_hashes
    assert len([name for name in original_hashes if name.endswith(".pw0Img")]) == 2486
    assert hashlib.sha256(source.read_bytes()).digest() == original_file_hash
    assert progress[-1] == 100
    assert sorted(progress) == progress
    with zipfile.ZipFile(destination) as output, zipfile.ZipFile(source) as original:
        assert output.testzip() is None
        assert output.comment == original.comment
        for name in original_hashes:
            old, new = original.getinfo(name), output.getinfo(name)
            assert old.date_time == new.date_time
            assert old.external_attr == new.external_attr
            assert old.comment == new.comment
            assert old.compress_type == new.compress_type
        for i, size in enumerate(((224, 168), (336, 252), (800, 600))):
            if i != 2:
                assert output.read(PREVIEWS[i]) == original.read(PREVIEWS[i])
                continue
            image = png_image(output.read(PREVIEWS[i]))
            assert image.size == size
            assert image.mode == "RGBA"
            assert image.getextrema()[3] == (255, 255)
            assert image.getpixel((0, 0))[:3] == DEFAULT_COLORS[i]
            assert image.getpixel((size[0] // 2, size[1] // 2)) == (190, 80, 130, 255)
    assert inspect_file(destination, options).compatible


def test_compatible_skip_and_idempotence(make_pm7):
    source = make_pm7(compatible=True)
    inspection = inspect_file(source)
    assert inspection.compatible
    destination = default_output(source)
    assert write_repaired(inspection, destination).status == "Skipped"
    assert not destination.exists()
    write_repaired(inspection, destination, force=True)
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(destination) as new:
        for name in old.namelist():
            assert old.read(name) == new.read(name)
    second = default_output(destination)
    write_repaired(inspect_file(destination), second, force=True)
    with zipfile.ZipFile(destination) as first, zipfile.ZipFile(second) as again:
        assert [first.read(name) for name in first.namelist()] == [
            again.read(name) for name in again.namelist()
        ]


def test_generate_only_cloud_preview_from_single_source(make_pm7):
    source = make_pm7(previews={1: artwork((300, 100))})
    inspection = inspect_file(source)
    image = png_image(inspection.previews[2].repaired)
    assert image.size == (800, 600)
    assert image.getpixel((400, 0))[3] == 0
    destination = default_output(source)
    write_repaired(inspection, destination)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination) as output:
        assert PREVIEWS[0] not in output.namelist()
        assert output.read(PREVIEWS[1]) == original.read(PREVIEWS[1])


def test_transparent_cloud_preview_preserves_alpha_and_print_data(make_pm7):
    source = make_pm7(previews={1: artwork((300, 100), color=(200, 80, 130, 128))})
    original = source.read_bytes()
    options = Options(transparent_preview2=True)
    inspection = inspect_file(source, options)
    assert inspection.previews[2].repaired_transparent
    destination = default_output(source)
    assert write_repaired(inspection, destination, options).status == "Saved"
    assert source.read_bytes() == original
    assert hashes(source) == hashes(destination)
    with zipfile.ZipFile(destination) as archive:
        cloud = png_image(archive.read(PREVIEWS[2]))
        assert cloud.size == (800, 600)
        assert cloud.getpixel((0, 0))[3] == 0
        center = cloud.getpixel((400, 300))
        assert center[3] == 128
        # Resizing premultiplied alpha can round RGB channels by one level.
        assert all(
            abs(actual - expected) <= 1
            for actual, expected in zip(center[:3], (200, 80, 130), strict=True)
        )
        assert PREVIEWS[0] not in archive.namelist()
        with zipfile.ZipFile(source) as original_archive:
            assert archive.read(PREVIEWS[1]) == original_archive.read(PREVIEWS[1])
    checked = inspect_file(destination, options)
    assert checked.compatible
    assert checked.previews[2].original == checked.previews[2].repaired
    assert write_repaired(checked, default_output(destination), options).status == "Skipped"
    assert not inspect_file(destination, Options(transparent_preview2=False)).compatible


@pytest.mark.parametrize("cloud_kind", ["opaque", "transparent", "empty"])
def test_transparent_cloud_uses_available_artwork(make_pm7, cloud_kind):
    cloud = (
        artwork((400, 300), transparent=cloud_kind != "opaque", color=(0, 0, 255, 255))
        if cloud_kind != "empty"
        else encode_blank_cloud()
    )
    source = make_pm7(previews={0: artwork((600, 450), color=(255, 0, 0, 255)), 2: cloud})
    inspection = inspect_file(source, Options(transparent_preview2=True))
    rendered = png_image(inspection.previews[2].repaired)
    assert rendered.getpixel((0, 0))[3] == 0
    assert rendered.getpixel((400, 300)) == (
        (0, 0, 255, 255) if cloud_kind == "transparent" else (255, 0, 0, 255)
    )


def encode_blank_cloud():
    buffer = io.BytesIO()
    Image.new("RGBA", (800, 600)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_valid_transparent_cloud_is_kept_byte_for_byte(make_pm7):
    cloud = artwork((800, 600))
    source = make_pm7(
        previews={0: artwork(transparent=False), 1: artwork(transparent=False), 2: cloud}
    )
    inspection = inspect_file(source, Options(transparent_preview2=True))
    assert inspection.compatible
    assert inspection.status == "Already compatible"
    assert inspection.previews[2].repaired == cloud
    assert inspection.previews[2].repaired_transparent


def test_transparency_setting_keeps_baked_in_backgrounds(make_pm7):
    source = make_pm7(compatible=True)
    inspection = inspect_file(source, Options(transparent_preview2=True))
    assert inspection.compatible
    assert not inspection.previews[2].repaired_transparent
    assert inspection.previews[2].original == inspection.previews[2].repaired


@pytest.mark.parametrize("index", [0, 1])
def test_writer_never_replaces_printer_previews(make_pm7, index):
    source = make_pm7()
    inspection = inspect_file(source)
    inspection.previews[index].repaired = b"This proposal must never reach the output"
    destination = default_output(source)
    write_repaired(inspection, destination)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination) as output:
        assert output.read(PREVIEWS[index]) == original.read(PREVIEWS[index])
    assert hashes(source) == hashes(destination)


@pytest.mark.parametrize("transparent", [True, False])
def test_cloud_compatibility_does_not_require_printer_previews(make_pm7, transparent):
    cloud = artwork((800, 600), transparent=transparent)
    source = make_pm7(previews={2: cloud})
    options = Options(transparent_preview2=transparent)
    inspection = inspect_file(source, options)
    assert inspection.compatible
    destination = default_output(source)
    write_repaired(inspection, destination, options, force=True)
    with zipfile.ZipFile(destination) as output:
        assert PREVIEWS[0] not in output.namelist()
        assert PREVIEWS[1] not in output.namelist()
        assert output.read(PREVIEWS[2]) == cloud


def test_cloud_source_prefers_highest_resolution_and_preserves_existing(make_pm7):
    source = make_pm7(
        previews={
            0: artwork((600, 450), color=(255, 0, 0, 255)),
            1: artwork((300, 225), color=(0, 255, 0, 255)),
        }
    )
    assert png_image(inspect_file(source).previews[2].repaired).getpixel((400, 300)) == (
        255,
        0,
        0,
        255,
    )
    existing = artwork((400, 300), color=(0, 0, 255, 255))
    source = make_pm7("existing.pm7", previews={0: artwork((600, 450)), 2: existing})
    assert png_image(inspect_file(source).previews[2].repaired).getpixel((400, 300)) == (
        0,
        0,
        255,
        255,
    )


def test_palette_transparency_and_partial_alpha():
    rgba = Image.new("RGBA", (2, 1), (200, 100, 0, 128))
    flattened = flatten(rgba, (20, 40, 60))
    assert flattened.getpixel((0, 0)) == (110, 70, 30, 255)
    palette = Image.new("P", (2, 2), 0)
    palette.info["transparency"] = 0
    assert flatten(palette, (2, 72, 100)).getpixel((0, 0)) == (2, 72, 100, 255)


def test_incorrect_cloud_dimensions(make_pm7):
    source = make_pm7(
        previews={
            0: artwork(transparent=False),
            1: artwork(transparent=False),
            2: artwork((400, 300), False),
        }
    )
    result = inspect_file(source)
    assert result.status == "Preview dimensions incorrect"
    assert png_image(result.previews[2].repaired).size == (800, 600)


def test_preserve_original_and_existing_output(make_pm7, tmp_path):
    source = make_pm7()
    inspection = inspect_file(source)
    with pytest.raises(RepairError, match="original"):
        write_repaired(inspection, source, overwrite=True)
    destination = tmp_path / "exists.pm7"
    destination.write_bytes(b"existing contents")
    with pytest.raises(FileExistsError):
        write_repaired(inspection, destination)
    assert destination.read_bytes() == b"existing contents"
    write_repaired(inspection, destination, overwrite=True)
    assert inspect_file(destination).compatible
    with pytest.raises(RepairError, match=".pm7"):
        write_repaired(inspection, tmp_path / "wrong.txt")


def test_changed_source_is_rejected(make_pm7):
    source = make_pm7()
    inspection = inspect_file(source)
    with source.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(RepairError, match="changed"):
        write_repaired(inspection, default_output(source))
    assert not default_output(source).exists()


def test_corrupt_archive_and_no_artwork_fail(make_pm7, tmp_path):
    bad = tmp_path / "broken.pm7"
    bad.write_bytes(b"not a ZIP")
    with pytest.raises(RepairError, match="Invalid archive"):
        inspect_file(bad)
    no_previews = make_pm7("no-preview.pm7", previews={})
    with pytest.raises(RepairError, match="no embedded"):
        inspect_file(no_previews)
    blank = io.BytesIO()
    Image.new("RGBA", (10, 10)).save(blank, format="PNG")
    empty = make_pm7("transparent-only.pm7", previews={0: blank.getvalue()})
    with pytest.raises(RepairError, match="no embedded"):
        inspect_file(empty)


def test_malformed_png_and_duplicate_entries(make_pm7):
    bad = make_pm7(previews={0: b"not PNG data"})
    with pytest.raises(RepairError, match="Invalid embedded PNG"):
        inspect_file(bad)
    with zipfile.ZipFile(bad, "a") as archive, pytest.warns(UserWarning, match="Duplicate"):
        archive.writestr("print_info.json", b"duplicate")
    with pytest.raises(RepairError, match="duplicate"):
        inspect_file(bad)


def test_write_failure_cleans_temp_and_preserves_destination(make_pm7, tmp_path, monkeypatch):
    source = make_pm7()
    destination = tmp_path / "result.pm7"
    destination.write_bytes(b"old file")

    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("anycubic_file_updater.core.os.replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        write_repaired(inspect_file(source), destination, overwrite=True)
    assert destination.read_bytes() == b"old file"
    assert not list(tmp_path.glob(".pm7-preview-*.tmp"))


def test_integrity_failure_discards_temp(make_pm7, tmp_path, monkeypatch):
    source = make_pm7()
    monkeypatch.setattr("anycubic_file_updater.core._digest", lambda stream: "incorrect hash")
    destination = default_output(source)
    with pytest.raises(RepairError, match="integrity verification"):
        write_repaired(inspect_file(source), destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".pm7-preview-*.tmp"))


def test_corrupt_print_layer_fails_safely(make_pm7, tmp_path):
    source = make_pm7()
    with zipfile.ZipFile(source) as archive:
        info = archive.getinfo("layer_images/layer_0.pw0Img")
        offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    with source.open("r+b") as stream:
        stream.seek(offset + 3)
        byte = stream.read(1)
        stream.seek(offset + 3)
        stream.write(bytes([byte[0] ^ 0xFF]))
    with pytest.raises((zipfile.BadZipFile, zlib.error)):
        write_repaired(inspect_file(source), default_output(source))
    assert not default_output(source).exists()
    assert not list(tmp_path.glob(".pm7-preview-*.tmp"))


def test_batch_continues_and_can_cancel(make_pm7, tmp_path):
    first = make_pm7()
    compatible = make_pm7("compatible.pm7", compatible=True)
    bad = tmp_path / "bad.pm7"
    bad.write_bytes(b"bad")
    jobs = [(path, default_output(path), False, False) for path in (bad, first, compatible)]
    results = repair_batch(jobs)
    assert [result.status for result in results] == ["Failed", "Saved", "Skipped"]
    assert repair_batch(jobs, cancelled=lambda: True) == []
    seen = []
    other = make_pm7("other.pm7")
    last = make_pm7("last.pm7")
    pending = [(p, default_output(p), False, False) for p in (other, last)]
    results = repair_batch(
        pending, cancelled=lambda: bool(seen), progress=lambda *args: seen.append(args)
    )
    assert len(results) == 1
    assert results[0].status == "Saved"
    assert not default_output(last).exists()


def test_options_validation():
    with pytest.raises(RepairError):
        Options(compression=11)
    with pytest.raises(RepairError):
        Options(colors=((1, 2, 999),) * 3)


def test_optional_real_references(tmp_path):
    """Opt in with PM7_REFERENCE_DIR. Never require or commit private print files."""
    import os

    directory = os.environ.get("PM7_REFERENCE_DIR")
    if not directory:
        pytest.skip("Real PM7 references not supplied; set PM7_REFERENCE_DIR to test them")
    folder = Path(directory)
    original = folder / "rapunzel_continuarea_Plate 5.pm7"
    workshop = folder / "01_preset_model.pm7"
    repaired = folder / "rapunzel_cloud_preview_opaque.pm7"
    assert not inspect_file(original).compatible
    assert inspect_file(workshop).compatible
    assert inspect_file(repaired).compatible
    generated = tmp_path / "rapunzel_with_preview.pm7"
    write_repaired(inspect_file(original), generated)
    assert inspect_file(generated).compatible
    assert hashes(original) == hashes(generated)
    with zipfile.ZipFile(generated) as archive:
        layers = [name for name in archive.namelist() if name.endswith(".pw0Img")]
        assert len(layers) == 2486
        image = png_image(archive.read(PREVIEWS[2]))
        assert image.size == (800, 600)
        assert archive.testzip() is None
