"""Per-user local preferences, with defensive loading."""

from dataclasses import dataclass, field

from PySide6.QtCore import QSettings

from anycubic_file_updater.core import DEFAULT_COLORS, Options


@dataclass
class Preferences:
    auto_inspect: bool = True
    skip_compatible: bool = True
    verify_zip: bool = True
    compression: int = 6
    colors: list[tuple[int, int, int]] = field(default_factory=lambda: list(DEFAULT_COLORS))
    transparent_preview2: bool = True

    def options(self) -> Options:
        return Options(
            colors=tuple(self.colors),
            compression=self.compression,
            verify_zip=self.verify_zip,
            skip_compatible=self.skip_compatible,
            transparent_preview2=self.transparent_preview2,
        )

    @classmethod
    def load(cls):
        store = QSettings()
        defaults = cls()
        try:
            return cls(
                auto_inspect=store.value("auto_inspect", True, bool),
                skip_compatible=store.value("skip_compatible", True, bool),
                verify_zip=store.value("verify_zip", True, bool),
                compression=max(0, min(9, store.value("compression", 6, int))),
                transparent_preview2=store.value("transparent_preview2", True, bool),
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
            "auto_inspect",
            "skip_compatible",
            "verify_zip",
            "compression",
            "transparent_preview2",
        ):
            store.setValue(name, getattr(self, name))
        for i, color in enumerate(self.colors):
            store.setValue(f"color_{i}", ",".join(map(str, color)))
        store.sync()
