import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from test_core import hashes

from pm7fixer.core import PREVIEWS, RepairError, default_output, inspect_file, write_repaired
from pm7fixer.formats import FORMATS, OPEN_FILE_FILTER, file_format, is_supported_file


@pytest.mark.parametrize("printer_format", FORMATS, ids=lambda value: value.extension)
@pytest.mark.parametrize("layer_extension", ["pw0Img", "pwszImg"])
def test_each_format_repairs_without_changing_print_data(make_pm7, printer_format, layer_extension):
    source = make_pm7(f"model{printer_format.extension}", layer_extension=layer_extension)
    inspection = inspect_file(source)
    original_data = hashes(source)
    output = default_output(source)
    result = write_repaired(inspection, output)
    assert result.status == "Saved"
    assert output.name == f"model_with_preview{printer_format.extension}"
    assert file_format(output) == printer_format
    assert hashes(output) == original_data
    assert inspect_file(output).compatible
    with zipfile.ZipFile(output) as archive:
        assert len([name for name in archive.namelist() if name.endswith(layer_extension)]) == 4
        assert archive.testzip() is None


@pytest.mark.parametrize("printer_format", FORMATS, ids=lambda value: value.extension)
def test_formats_are_case_insensitive_and_compatible_files_skip(make_pm7, printer_format):
    source = make_pm7(f"model{printer_format.extension.upper()}", compatible=True)
    assert is_supported_file(source)
    assert file_format(source) == printer_format
    assert f"*{printer_format.extension}" in OPEN_FILE_FILTER
    assert inspect_file(source).compatible
    assert write_repaired(inspect_file(source), default_output(source)).status == "Skipped"


def test_output_extension_cannot_convert_printers(make_pm7, tmp_path):
    source = make_pm7("model.pwsz")
    with pytest.raises(RepairError, match="retain the input extension"):
        write_repaired(inspect_file(source), tmp_path / "model_with_preview.pm7")
    assert not (tmp_path / "model_with_preview.pm7").exists()


@pytest.mark.parametrize("extension", [".photon", ".pwmb", ".pm5s", ".stl", ".zip"])
def test_other_formats_are_rejected_without_modification(make_pm7, extension):
    source = make_pm7(f"unsupported{extension}")
    before = source.read_bytes()
    assert not is_supported_file(source)
    with pytest.raises(RepairError, match="Unsupported file extension"):
        inspect_file(source)
    assert source.read_bytes() == before
    assert not default_output(source).exists()


def test_renamed_non_anycubic_zip_is_rejected(tmp_path):
    source = tmp_path / "fake.pwsz"
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(buffer, format="PNG")
    with zipfile.ZipFile(source, "w") as archive:
        for name in PREVIEWS:
            archive.writestr(name, buffer.getvalue())
        archive.writestr("unrelated.txt", "This is not a print archive")
    with pytest.raises(RepairError, match="Unsupported archive layout"):
        inspect_file(source)


def test_format_extension_is_not_detected_from_stem():
    assert file_format(Path("model.pwsz.backup")) is None
