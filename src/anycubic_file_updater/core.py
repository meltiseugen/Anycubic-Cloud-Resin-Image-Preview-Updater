"""Image repair and streaming, verified archive writing. No GUI dependencies."""

from __future__ import annotations

import copy
import hashlib
import io
import os
import tempfile
import warnings
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from anycubic_file_updater.formats import EXTENSIONS_TEXT, file_format

PREVIEWS = tuple(f"preview_images/preview_{i}.png" for i in range(3))
DEFAULT_COLORS = ((2, 72, 100), (20, 27, 41), (238, 240, 246))
MAX_PNG_BYTES = 48 * 1024 * 1024
MAX_PIXELS = 32_000_000
CHUNK = 1024 * 1024
Progress = Callable[[int, str], None]


class RepairError(ValueError):
    """An unsupported, invalid, or unsafe repair request."""


@dataclass(frozen=True)
class Options:
    colors: tuple[tuple[int, int, int], ...] = DEFAULT_COLORS
    compression: int = 6
    verify_zip: bool = True
    skip_compatible: bool = True
    transparent_preview2: bool = True

    def __post_init__(self):
        if len(self.colors) != 3 or any(
            len(c) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in c)
            for c in self.colors
        ):
            raise RepairError("Each preview background must be an RGB color.")
        if type(self.compression) is not int or not 0 <= self.compression <= 9:
            raise RepairError("PNG compression must be between 0 and 9.")


DEFAULT_OPTIONS = Options()


@dataclass
class Preview:
    original: bytes | None
    repaired: bytes | None
    dimensions: tuple[int, int] | None
    mode: str | None
    transparent: bool
    change: str
    repaired_transparent: bool = False


@dataclass
class Inspection:
    source: Path
    signature: tuple[int, int]
    status: str
    compatible: bool
    previews: list[Preview] = field(default_factory=list)


@dataclass
class Result:
    source: Path
    output: Path | None
    status: str
    message: str


def signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def png_image(data: bytes) -> Image.Image:
    if len(data) > MAX_PNG_BYTES:
        raise RepairError("An embedded preview exceeds the 48 MiB safety limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG":
                    raise RepairError("Embedded previews must be PNG images.")
                if image.width * image.height > MAX_PIXELS:
                    raise RepairError("An embedded preview exceeds the 32 megapixel limit.")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                return image.copy()
    except RepairError:
        raise
    except Exception as exc:
        raise RepairError(f"Invalid embedded PNG: {exc}") from exc


def has_alpha(image: Image.Image) -> bool:
    return image.convert("RGBA").getextrema()[3][0] < 255


def encode(image: Image.Image, compression: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=compression)
    return buffer.getvalue()


def flatten(image: Image.Image, color: tuple[int, int, int] | None, size=None) -> Image.Image:
    artwork = image.convert("RGBA")
    if size is None:
        size = artwork.size
    else:
        artwork = ImageOps.contain(artwork, size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (*color, 255) if color is not None else (0, 0, 0, 0))
    canvas.alpha_composite(
        artwork, ((size[0] - artwork.width) // 2, (size[1] - artwork.height) // 2)
    )
    return canvas


def _archive_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(names) != len(set(names)):
        raise RepairError("Archive has duplicate entry names; repair is unsafe.")
    if any(entry.flag_bits & 1 for entry in entries):
        raise RepairError("Encrypted archives are unsupported.")
    return entries


def inspect_file(path: str | Path, options: Options = DEFAULT_OPTIONS) -> Inspection:
    path = Path(path).resolve()
    if file_format(path) is None:
        raise RepairError(
            f"Unsupported file extension {path.suffix or '(none)'}. "
            f"Supported ZIP-based Anycubic formats: {EXTENSIONS_TEXT}. "
            "Other binary resin formats need a different repair method."
        )
    before = signature(path)
    originals: dict[int, bytes] = {}
    images: dict[int, Image.Image] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            entries = _archive_entries(archive)
            names = {entry.filename for entry in entries}
            if "anycubic_photon_resins.pwsp" not in names or not any(
                entry.filename.startswith("layer_images/") and not entry.is_dir()
                for entry in entries
            ):
                raise RepairError(
                    "Unsupported archive layout: expected Anycubic printer settings "
                    "and embedded print layers. Renaming a file does not convert its format."
                )
            for i, name in enumerate(PREVIEWS):
                if name in names:
                    info = archive.getinfo(name)
                    if info.file_size > MAX_PNG_BYTES:
                        raise RepairError("An embedded preview exceeds the 48 MiB safety limit.")
                    originals[i] = archive.read(info)
                    images[i] = png_image(originals[i])
    except RepairError:
        raise
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as exc:
        raise RepairError(f"Invalid archive: {exc}") from exc
    artwork = {
        i: img
        for i, img in images.items()
        if img.convert("RGBA").getchannel("A").getbbox() is not None
    }
    if not artwork:
        raise RepairError("Unsupported file: no embedded PNG model artwork is available.")
    best = max(artwork, key=lambda i: artwork[i].width * artwork[i].height)
    missing = 2 not in images
    transparent = 2 in images and has_alpha(images[2]) and not options.transparent_preview2
    wrong_size = 2 in images and images[2].size != (800, 600)
    previews = []
    for i in range(3):
        original = images.get(i)
        if i != 2:
            previews.append(
                Preview(
                    originals.get(i),
                    originals.get(i),
                    original.size if original else None,
                    original.mode if original else None,
                    has_alpha(original) if original else False,
                    "Keep unchanged",
                    has_alpha(original) if original else False,
                )
            )
            continue
        target = (800, 600) if i == 2 else None
        # Keep an existing cloud preview's artwork, even when another image is larger.
        source = original if original is not None else images[best]
        alpha = has_alpha(original) if original is not None else False
        transparent_cloud = i == 2 and options.transparent_preview2
        if transparent_cloud and (not alpha or i not in artwork):
            if i not in artwork:
                source = images[best]
            transparent_artwork = {j: img for j, img in artwork.items() if has_alpha(img)}
            if transparent_artwork:
                source = max(transparent_artwork.values(), key=lambda img: img.width * img.height)
        unchanged = (
            original is not None
            and (i != 2 or not wrong_size)
            and (source is original if transparent_cloud else not alpha)
        )
        if unchanged:
            repaired, repaired_alpha = originals[i], alpha
        else:
            rendered = flatten(source, None if transparent_cloud else options.colors[i], target)
            repaired = encode(rendered, options.compression)
            repaired_alpha = has_alpha(rendered)
        change = (
            "Keep unchanged"
            if unchanged
            else "Fit embedded artwork onto transparent background"
            if transparent_cloud
            else "Generate from embedded artwork"
            if original is None
            else "Composite onto opaque background" + ("; fit to 800 × 600" if i == 2 else "")
        )
        previews.append(
            Preview(
                originals.get(i),
                repaired,
                original.size if original else None,
                original.mode if original else None,
                alpha,
                change,
                repaired_alpha,
            )
        )
    if signature(path) != before:
        raise RepairError("Input changed during inspection. Please import it again.")
    compatible = previews[2].original == previews[2].repaired
    status = (
        "Missing cloud preview"
        if missing
        else "Transparent previews detected"
        if transparent
        else "Preview dimensions incorrect"
        if wrong_size
        else "Preview 2 transparency update"
        if not compatible
        else "Already compatible"
    )
    return Inspection(path, before, status, compatible, previews)


def default_output(source: Path, folder: Path | None = None) -> Path:
    return (folder or source.parent) / f"{source.stem}_with_preview{source.suffix}"


def _digest(stream) -> str:
    digest = hashlib.sha256()
    while block := stream.read(CHUNK):
        digest.update(block)
    return digest.hexdigest()


def write_repaired(
    inspection: Inspection,
    destination: str | Path,
    options: Options = DEFAULT_OPTIONS,
    *,
    overwrite: bool = False,
    force: bool = False,
    progress: Progress = lambda value, message: None,
) -> Result:
    source = inspection.source
    destination = Path(destination).resolve()
    if source == destination or (destination.exists() and os.path.samefile(source, destination)):
        raise RepairError("Choose a different output file. The original is always preserved.")
    if destination.suffix.lower() != source.suffix.lower():
        raise RepairError(
            f"The output filename must retain the input extension ({source.suffix}). "
            "Preview repair does not convert files between printers."
        )
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {destination}")
    if signature(source) != inspection.signature:
        raise RepairError("Input changed after inspection. Please import it again.")
    if inspection.compatible and options.skip_compatible and not force:
        return Result(source, None, "Skipped", "Already compatible; no output was needed.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        handle, name = tempfile.mkstemp(
            prefix=".pm7-preview-", suffix=".tmp", dir=destination.parent
        )
        temporary = Path(name)
        os.close(handle)
        hashes = {}
        replacements = {PREVIEWS[2]: inspection.previews[2].repaired}
        progress(0, "Copying archive and updating previews…")
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(temporary, "w") as output:
            entries = _archive_entries(original)
            total_bytes = max(1, sum(entry.file_size for entry in entries))
            copied = 0
            output.comment = original.comment
            for entry in entries:
                metadata = copy.copy(entry)
                if entry.filename in replacements:
                    output.writestr(metadata, replacements.pop(entry.filename))
                    copied += entry.file_size
                else:
                    digest = hashlib.sha256()
                    with (
                        original.open(entry) as incoming,
                        output.open(
                            metadata, "w", force_zip64=entry.file_size >= zipfile.ZIP64_LIMIT
                        ) as outgoing,
                    ):
                        while block := incoming.read(CHUNK):
                            outgoing.write(block)
                            digest.update(block)
                            copied += len(block)
                            progress(int(65 * copied / total_bytes), "Copying print data…")
                    hashes[entry.filename] = digest.hexdigest()
            for name, data in replacements.items():
                output.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        progress(65, "Verifying unchanged print data (SHA-256)…")
        with zipfile.ZipFile(temporary) as completed:
            expected = {entry.filename for entry in entries} | {PREVIEWS[2]}
            if set(completed.namelist()) != expected:
                raise RepairError("Output archive entries failed validation.")
            for index, (name, expected_hash) in enumerate(hashes.items()):
                with completed.open(name) as stream:
                    if _digest(stream) != expected_hash:
                        raise RepairError(f"Print data integrity verification failed: {name}")
                progress(
                    65 + int(30 * (index + 1) / max(1, len(hashes))),
                    "Verifying unchanged print data (SHA-256)…",
                )
            for i, name in ((2, PREVIEWS[2]),):
                image = png_image(completed.read(name))
                unwanted_alpha = has_alpha(image) and not (i == 2 and options.transparent_preview2)
                if unwanted_alpha or (i == 2 and image.size != (800, 600)):
                    raise RepairError(f"Repaired preview failed validation: {name}")
            if options.verify_zip:
                progress(96, "Checking complete ZIP integrity…")
                damaged = completed.testzip()
                if damaged:
                    raise RepairError(f"ZIP integrity check failed: {damaged}")
        if signature(source) != inspection.signature:
            raise RepairError("Input changed during repair. Output was discarded.")
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        # Windows rename fails if a destination appeared after the save dialog.
        if overwrite:
            os.replace(temporary, destination)
        elif os.name == "nt":
            os.rename(temporary, destination)
        else:
            os.link(temporary, destination)
            temporary.unlink()
        temporary = None
        progress(100, "Saved and verified")
        return Result(source, destination, "Saved", "Saved; all non-preview SHA-256 hashes match.")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def repair_batch(jobs, options=DEFAULT_OPTIONS, *, cancelled=lambda: False, progress=None):
    """Independent jobs; cancellation is intentionally only between files."""
    results = []
    for index, (source, output, overwrite, force) in enumerate(jobs):
        if cancelled():
            break
        try:
            inspection = inspect_file(source, options)

            def callback(value, message, index=index):
                if progress:
                    progress(index, value, message)

            result = write_repaired(
                inspection, output, options, overwrite=overwrite, force=force, progress=callback
            )
        except Exception as exc:
            result = Result(Path(source), None, "Failed", str(exc))
        results.append(result)
    return results
