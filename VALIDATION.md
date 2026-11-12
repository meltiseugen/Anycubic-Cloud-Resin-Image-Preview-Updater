# Build validation — 2026-11-12

Version **1.1.0** built locally on Windows 10 x64 using Python 3.13.12, PyInstaller 6.22.3,
PySide6 6.12.0, Pillow 13.0.0 and Inno Setup 6.7.4.

- **61 automated tests passed**, with process exit code 0. One real-reference test was skipped
  because the three PM7 sample archives were not attached.
- Ruff checks, formatting checks and Python compilation passed.
- Synthetic archive regression tests preserve SHA-256 hashes of all 2,486 layers and all other
  non-preview entries. Tests cover metadata, colors, alpha, image sizes, idempotence, corrupt
  layers, failed writes, batch isolation, cancellation and overwrite protection.
- Qt tests exercise Add Files, recursive dropped folders, manual inspection, before/after views,
  Update Preview, save cancellation, overwrite confirmation, batch repair and bounded caching.
- Format tests cover `.pm7`, `.pwsz`, `.pm7m`, `.pm4u`, `.pp1` and `.pp1m`, including uppercase
  extensions, both `.pw0Img` and `.pwszImg` layer entries, mixed-printer batches and per-format
  file/save dialogs. Cross-printer output extensions and unrelated ZIP layouts are rejected.
- Rendered the real Qt interface offscreen at default and minimum sizes and inspected the images.
- An initial packaged smoke test exposed a Windows shutdown crash. The final build explicitly
  disposes Qt widgets before application teardown. A fresh-interpreter regression test passes.
- The final standalone EXE started, repaired synthetic archives for all six formats, verified
  unchanged print data,
  checked ZIP integrity, displayed its Qt window offscreen, and exited with **code 0**. The test
  ran from an isolated working folder with Python removed from PATH.
- The final installer installed into an isolated project test folder with **code 0**. The installed
  application reported version **1.1.0** and repeated the six-format repair/startup/shutdown smoke
  test with **code 0**. Uninstallation
  returned **code 0**, removed the app and removed its per-user uninstall registration. The
  temporary installer test needed access outside the sandbox for Windows shortcut/registry APIs.

Final artifacts:

- `dist/PM7CloudPreviewFixer.exe` — standalone portable app.
- `dist/PM7CloudPreviewFixer-Setup.exe` — Windows installer.
- `dist/SHA256SUMS.txt` — artifact hashes.

The executables are unsigned. Windows 11 has not been tested directly. No actual reference
archives for any of the six formats, live Anycubic Cloud uploads or printer runs were available;
those acceptance checks
remain manual. Generated-fixture checks do not establish cloud rendering or physical print results.

## GitHub Actions configuration

- `.github/workflows/build-windows.yml` passed actionlint 1.7.12.
- `tools/verify_windows_build.ps1` passed the Windows PowerShell syntax check and was executed
  against the built EXE. Repair, SHA-256 integrity, ZIP integrity, all six extensions, the UI
  control and clean process exit passed; distribution checksums were generated.
- Official action metadata was checked for checkout v7, setup-python v7, upload-artifact v7
  and download-artifact v8. The Windows Server 2022 runner image includes Inno Setup.
- The hosted workflow and release-upload job have not run yet: the local changes have not been
  committed or pushed. The workflow provides Actions artifacts on ordinary builds and release
  downloads after a successful version-tag build.
