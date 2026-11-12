"""Collect installed dependency license texts for redistribution alongside the EXE."""

import sys
from importlib.metadata import distribution
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / "licenses"
destination.mkdir(exist_ok=True)
(destination / "Python").mkdir(exist_ok=True)
(destination / "Python" / "LICENSE.txt").write_bytes(
    (Path(sys.base_prefix) / "LICENSE.txt").read_bytes()
)
for name in ("Pillow", "PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6"):
    package = distribution(name)
    count = 0
    for file in package.files or []:
        if "license" in str(file).lower() or "copying" in file.name.lower():
            source = Path(package.locate_file(file))
            if source.is_file():
                target = destination / name / str(file).replace("..", "_")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
                count += 1
    print(f"{name}: collected {count} license files")
