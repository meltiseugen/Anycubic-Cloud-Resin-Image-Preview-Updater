# PM7 Cloud Preview Fixer

A Windows desktop app for repairing embedded PNG previews in ZIP-based Anycubic resin files.
Everything runs offline. The original input file is always preserved. Only
`preview_images/preview_0.png`, `preview_1.png`, and `preview_2.png` may change.

## Printer and file-format support

Version 1.1 adds all three documented M7 models and other printers using the same archive family:

| Printer | Extension |
| --- | --- |
| Photon Mono M7 | `.pm7` |
| Photon Mono M7 Pro | `.pwsz` |
| Photon Mono M7 Max | `.pm7m` |
| Photon Mono 4 Ultra | `.pm4u` |
| Photon P1 | `.pp1` |
| Photon P1 Max | `.pp1m` |

The printer mappings are listed in [CHITUBOX's supported-printer documentation](https://tm.chitubox.com/en-US/chitubox/latest/introduction).
The shared ZIP family, embedded PNG paths and cloud preview size are described by the
[UVtools AnycubicZipFile implementation](https://github.com/sn4k3/UVtools/blob/master/UVtools.Core/FileFormats/AnycubicZipFile.cs).
These are format references; the app does not bundle UVtools or its implementation.

Repair is conditional on the actual file structure: a valid ZIP archive with
`anycubic_photon_resins.pwsp`, embedded `layer_images/` files and usable PNG preview artwork.
Printer-specific settings and layers are copied as opaque data and verified with SHA-256.
Both `.pw0Img` and `.pwszImg` layers are retained without decoding, renaming or conversion.

The original extension is always retained: `model.pwsz` becomes `model_with_preview.pwsz`,
and `model.pm7m` becomes `model_with_preview.pm7m`. Changing the extension to another printer's
format is rejected. Import and folder discovery are case-insensitive.

Older binary formats such as `.photon`, `.pwmb`, `.pm5s` and `.m5sp` are **not supported** by
this ZIP/PNG repair. Renaming one of those files will not make it compatible. Actual slicer
exports and Anycubic Cloud rendering still need manual validation for each printer; synthetic
format tests are not evidence of live printer or cloud compatibility.

## Install and use

Download **[PM7CloudPreviewFixer-Setup.exe from the latest release](https://github.com/meltiseugen/Anycubic-Cloud-Resin-Image-Preview-Updater/releases/latest/download/PM7CloudPreviewFixer-Setup.exe)**,
then run the downloaded file. The installer installs for your Windows user,
adds Start menu and optional desktop shortcuts, and includes an uninstaller. No Python,
administrator rights, cloud account, or internet connection is needed. The build targets
Windows 10/11 x64 (Windows ARM64 requires x64 emulation). The executable is unsigned.

Alternatively, download the **[portable EXE](https://github.com/meltiseugen/Anycubic-Cloud-Resin-Image-Preview-Updater/releases/latest/download/PM7CloudPreviewFixer.exe)**
and run it directly without installing. Release assets also include `SHA256SUMS.txt`.

If no release has been published yet, or you want the latest development build:

1. Open **[Actions → Build Windows installer](https://github.com/meltiseugen/Anycubic-Cloud-Resin-Image-Preview-Updater/actions/workflows/build-windows.yml)**.
2. Select a successful run and download **PM7CloudPreviewFixer-Windows-x64** under **Artifacts**.
3. Extract the downloaded ZIP and run `PM7CloudPreviewFixer-Setup.exe` (installer) or
   `PM7CloudPreviewFixer.exe` (portable).

GitHub requires signing in to download Actions artifacts. Artifacts are retained for 30 days;
published release downloads remain available. The repository contains source code; `dist/` is
generated during builds and is intentionally excluded from Git. GitHub's **Code → Download ZIP**
contains source, not the Windows executables.

1. Drag a supported Anycubic print file onto the app, or click **Add Files**. **Add Folder** and
   dropped folders recursively discover all six supported extensions. Select a row to see
   before/after previews and the printer format.
2. Choose Preview 0, 1, or 2 to inspect the proposed changes. Missing cloud artwork is generated
   from an existing embedded preview. Transparency appears on a checkerboard in the Before panel.
3. Click **Update Preview** and choose where to save. The suggested filename is
   **`original_with_preview`** followed by the original extension. You can choose a different
   output folder or filename while retaining that extension.
4. Wait for **Saved** and the integrity verification message. Upload the output to Anycubic Cloud.

For batches, select multiple rows and click **Update Preview**, or use **Fix All**. Choose a folder;
each output gets the `_with_preview` suffix. Existing outputs require overwrite confirmation.
Duplicate basenames in a batch are reported instead of overwriting one another. Invalid files
fail independently; other jobs continue. **Cancel after current file** finishes the current file
safely, then stops. Close the app after the worker finishes.

Already compatible files are skipped by default, producing no output. Check **Process already
compatible files** to save them anyway. Existing valid opaque previews are kept byte-for-byte.
**Inspect Selected** supports manual inspection when automatic inspection is disabled.

## Repair and integrity

- Preview 0: original dimensions; opaque background RGB `(2, 72, 100)`.
- Preview 1: original dimensions; opaque background RGB `(20, 27, 41)`.
- Preview 2: `800 × 600`; background RGB `(238, 240, 246)`. Existing artwork takes priority;
  otherwise the largest embedded PNG supplies the artwork. LANCZOS scaling preserves aspect ratio,
  with centered padding when needed. Valid opaque `800 × 600` preview 2 stays unchanged.
- Missing previews 0/1 use the highest-resolution embedded artwork at its original dimensions.
  Files without embedded PNG artwork, including entirely transparent sources, are unsupported.
  Duplicate ZIP entries, encrypted archives, invalid PNGs, non-ZIP files and unrecognized archive
  layouts are rejected.
- Every other ZIP entry is streamed in 1 MiB chunks. SHA-256 checks verify every copied entry,
  including all layers, configuration and unknown files. Entry timestamps, comments, compression
  methods, external attributes and archive comments are retained where Python ZIP support permits.
  Compressed archive bytes may change; uncompressed print-data bytes must match exactly.
- A temporary file in the destination folder is fully verified before atomic publication.
  Failures leave existing destinations intact. A crash can leave a hidden `.pm7-preview-*.tmp`
  file, which may be deleted after the app has stopped. No extraction of print files is performed.
- SHA-256 and output preview validation are always enabled. Settings can disable the additional
  full ZIP CRC pass. Image limits are 48 MiB encoded and 32 million pixels per preview.

Settings are stored locally using Windows QSettings (`HKCU\Software\PM7PreviewFixer`).
Settings include default folder, skip compatible files, auto-inspection, PNG compression,
background colors, and extra ZIP checking. **Restore Defaults** resets all choices. Original-file
preservation is always enabled. Logs rotate in the per-user AppLocalData directory (usually
`%LOCALAPPDATA%\PM7PreviewFixer\PM7 Cloud Preview Fixer\app.log`).

## Develop and test

Use Python 3.12+ on Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pm7fixer.app
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests tools
```

Tests build synthetic archives for all six formats, including a 2,486-layer PM7 fixture. They check
extension preservation, printer-specific dialogs, both layer-entry extensions, opaque backgrounds,
artwork colors, dimensions, highest-resolution source selection, idempotence, SHA-256 integrity,
metadata preservation, corrupted layers, failed writes, cancellation, batch isolation, bounded
preview caching, and actual Qt file import / save-dialog / drag-and-drop flows. A fresh-process
smoke test also checks startup and clean shutdown. GUI tests use Qt's offscreen backend.

No user reference PM7 files were supplied with the initial specification. To enable the optional
reference checks, set `PM7_REFERENCE_DIR` to a folder containing:

- `rapunzel_continuarea_Plate 5.pm7`
- `01_preset_model.pm7`
- `rapunzel_cloud_preview_opaque.pm7`

These large/private files are excluded from Git. **Anycubic Cloud rendering and live printing
require manual acceptance with actual files. Offline tests cannot establish those results.**

## Automated builds and releases

[`.github/workflows/build-windows.yml`](.github/workflows/build-windows.yml) builds on Windows x64
with Python 3.13 and Inno Setup. It runs on pushes to `main`, pull requests targeting `main`,
version-tag pushes (`v*`), and **Run workflow** on the Actions page.

Each run installs the locked build dependencies, runs the tests, builds the standalone app and
installer, checks code quality, then runs the bundled EXE in an isolated working directory with
Python removed from PATH. The smoke test checks repair, all six file formats, SHA-256 integrity,
ZIP integrity, Qt startup and clean shutdown. Successful runs upload both EXEs and SHA-256 checksums
as the **PM7CloudPreviewFixer-Windows-x64** artifact. Failed runs upload available build diagnostics.

To publish a release after committing and pushing the source/workflow:

```powershell
git tag v1.1.0
git push origin v1.1.0
```

The tag must match the version in `pyproject.toml`. For future releases, also update
`src/pm7fixer/__init__.py`, `packaging/version.txt`, and `packaging/installer.iss` to the same version
before tagging. After a successful tagged build, a separate job creates a GitHub Release and
attaches both EXEs and `SHA256SUMS.txt`. Re-running that tag's workflow replaces its release assets.
Normal branch, pull-request and manual builds only upload Actions artifacts. No personal access
token or extra repository secret is required; the release job uses the built-in `GITHUB_TOKEN`.

## Build the EXE and installer locally

Install Python 3.12+ x64 and [Inno Setup 6.4+ or 7](https://jrsoftware.org/isdl.php), then run:

```bat
build_windows.bat
```

The script installs build dependencies into `.venv`, collects license texts, runs tests, bundles
the standalone executable with PyInstaller, and compiles the installer. Set the `ISCC` environment
variable to the full `ISCC.exe` path if Inno Setup is not found automatically. Outputs:

```text
dist/PM7CloudPreviewFixer.exe
dist/PM7CloudPreviewFixer-Setup.exe
```

These are local output paths, not files committed to the repository. To run the same packaged-app
verification and generate checksums locally:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\verify_windows_build.ps1
```

For an existing environment without pip, use `uv pip install --python .venv/Scripts/python.exe
-e ".[dev]"`, then run license collection, pytest, PyInstaller and ISCC directly as in the script.
For repeatable builds, `requirements-build.lock` records the exact dependencies used for this build.

To exercise bundled Pillow, ZIP repair, SHA-256 verification and Qt startup without user files:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
Start-Process -FilePath .\dist\PM7CloudPreviewFixer.exe -ArgumentList '--smoke-test', 'smoke.json' -Wait
Get-Content smoke.json
```

The repo separates the printer/extension registry (`formats.py`) and pure archive/image logic
(`core.py`) from Qt workers/widgets (`ui.py`), local settings (`settings.py`), application startup
(`app.py`) and packaging definitions (`packaging/`). App identity, installer location and settings
keys are retained from version 1.0 so the 1.1 installer can upgrade an existing installation.
