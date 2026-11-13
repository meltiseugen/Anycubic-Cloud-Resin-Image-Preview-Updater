"""Anycubic formats sharing the ZIP/embedded-PNG container layout.

Printer/extension mappings are documented in CHITUBOX's printer list and the
UVtools AnycubicZipFile format registry (links in README). No slicer code is used.
The archive structure is checked separately; an extension is not proof of compatibility.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PrinterFormat:
    printer: str
    extension: str

    @property
    def dialog_filter(self) -> str:
        return f"{self.printer} (*{self.extension})"


FORMATS = (
    PrinterFormat("Photon Mono M7", ".pm7"),
    PrinterFormat("Photon Mono M7 Pro", ".pwsz"),
    PrinterFormat("Photon Mono M7 Max", ".pm7m"),
    PrinterFormat("Photon Mono 4 Ultra", ".pm4u"),
    PrinterFormat("Photon P1", ".pp1"),
    PrinterFormat("Photon P1 Max", ".pp1m"),
)
FORMATS_BY_EXTENSION = {item.extension: item for item in FORMATS}
SUPPORTED_EXTENSIONS = tuple(FORMATS_BY_EXTENSION)
EXTENSIONS_TEXT = ", ".join(SUPPORTED_EXTENSIONS)
OPEN_FILE_FILTER = ";;".join(
    ["Supported Anycubic files (" + " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS) + ")"]
    + [item.dialog_filter for item in FORMATS]
    + ["All files (*)"]
)


def file_format(path: str | Path) -> PrinterFormat | None:
    return FORMATS_BY_EXTENSION.get(Path(path).suffix.lower())


def is_supported_file(path: str | Path) -> bool:
    return file_format(path) is not None
