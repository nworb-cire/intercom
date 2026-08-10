"""Synthetic source integration used for local demos and end-to-end tests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
        if self.mode == "silence":
            return "ausine,10"
        return f"ausine,{self.frequency}"

    def prepare(self, _config_dir: Path) -> None:
        return

    def start(self, _connected: Callable[[], bool]) -> None:
        return

    def stop(self) -> None:
        return


def create_source() -> SyntheticSource:
    mode = os.environ.get("SOURCE_KIND", "silence")
    if mode not in {"silence", "sine"}:
        raise SystemExit("synthetic SOURCE_KIND must be silence or sine")
    frequency = int(os.environ.get("SINE_FREQUENCY", "440"))
    if not 1 <= frequency <= 20000:
        raise SystemExit("SINE_FREQUENCY must be between 1 and 20000 Hz")
    return SyntheticSource(mode, frequency)


if __name__ == "__main__":
    AdapterRuntime(create_source()).run()
