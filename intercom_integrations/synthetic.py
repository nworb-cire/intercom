"""Synthetic source integration used for local demos and end-to-end tests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.interfaces import AudioSink
from core.adapter_runtime.runtime import AdapterRuntime


@dataclass(frozen=True)
class SyntheticSource:
    mode: str
    frequency: int = 440

    @property
    def kind(self) -> str:
        return self.mode

    @property
    def baresip_source(self) -> str:
        return "ausine,10" if self.mode == "silence" else f"ausine,{self.frequency}"

    @property
    def baresip_modules(self) -> tuple[str, ...]:
        return ("stdio.so", "g711.so", "pulse.so", "ausine.so", "account.so", "menu.so")

    def prepare(self, _config_dir: Path) -> None:
        return

    def start(self, _connected: Callable[[], bool]) -> None:
        return

    def stop(self) -> None:
        return


@dataclass
class SyntheticIntegration:
    source: SyntheticSource
    sink: AudioSink | None = None
    name: str = "synthetic"

    def health(self) -> dict[str, str]:
        return {"integration": self.name}

    def prepare(self, config_dir: Path) -> None:
        self.source.prepare(config_dir)

    def start(self, connected: Callable[[], bool]) -> None:
        self.source.start(connected)

    def stop(self) -> None:
        self.source.stop()


def create_integration() -> SyntheticIntegration:
    mode = os.environ.get("SOURCE_KIND", "silence")
    if mode not in {"silence", "sine"}:
        raise SystemExit("synthetic SOURCE_KIND must be silence or sine")
    frequency = int(os.environ.get("SINE_FREQUENCY", "440"))
    if not 1 <= frequency <= 20000:
        raise SystemExit("SINE_FREQUENCY must be between 1 and 20000 Hz")
    return SyntheticIntegration(SyntheticSource(mode, frequency))


def main() -> None:
    AdapterRuntime(create_integration()).run()
