"""Per-user local preferences, with defensive loading."""

from dataclasses import dataclass, field

from PySide6.QtCore import QSettings

from pm7fixer.core import DEFAULT_COLORS, Options


@dataclass
class Preferences:
    output_folder: str = ""
    auto_inspect: bool = True
    skip_compatible: bool = True
    verify_zip: bool = True
    compression: int = 6
    colors: list[tuple[int, int, int]] = field(default_factory=lambda: list(DEFAULT_COLORS))

    def options(self) -> Options:
        return Options(tuple(self.colors), self.compression, self.verify_zip, self.skip_compatible)

    @classmethod
    def load(cls):
        store = QSettings()
        defaults = cls()
        try:
            return cls(
                output_folder=store.value("output_folder", "", str),
                auto_inspect=store.value("auto_inspect", True, bool),
                skip_compatible=store.value("skip_compatible", True, bool),
                verify_zip=store.value("verify_zip", True, bool),
                compression=max(0, min(9, store.value("compression", 6, int))),
                colors=[
                    tuple(
                        int(v)
                        for v in store.value(f"color_{i}", ",".join(map(str, c)), str).split(",")
                    )
                    for i, c in enumerate(DEFAULT_COLORS)
                ],
            ).validated()
        except (ValueError, TypeError):
            return defaults

    def validated(self):
        self.options()
        return self

    def save(self):
        self.validated()
        store = QSettings()
        for name in (
            "output_folder",
            "auto_inspect",
            "skip_compatible",
            "verify_zip",
            "compression",
        ):
            store.setValue(name, getattr(self, name))
        for i, color in enumerate(self.colors):
            store.setValue(f"color_{i}", ",".join(map(str, color)))
        store.sync()
