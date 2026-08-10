"""RTSP camera microphone integration using Baresip's GStreamer source."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from core.interfaces import AudioSink
from core.adapter_runtime.runtime import AdapterRuntime


@dataclass(frozen=True)
class RtspCameraSource:
    uri: str

    @property
    def kind(self) -> str:
        return "gstreamer"

    @property
    def baresip_source(self) -> str:
        return f"gst,{self.uri}"

    @property
    def baresip_modules(self) -> tuple[str, ...]:
        return (
            "stdio.so", "g711.so", "pulse.so", "ausine.so", "gst.so", "account.so", "menu.so"
        )

    def prepare(self, _config_dir: Path) -> None:
        return

    def start(self, _connected: Callable[[], bool]) -> None:
        return

    def stop(self) -> None:
        return


@dataclass
class RtspCameraIntegration:
    source: RtspCameraSource
    sink: AudioSink | None = None
    name: str = "rtsp-camera"

    def health(self) -> dict[str, str]:
        return {"integration": self.name}

    def prepare(self, config_dir: Path) -> None:
        self.source.prepare(config_dir)

    def start(self, connected: Callable[[], bool]) -> None:
        self.source.start(connected)

    def stop(self) -> None:
        self.source.stop()


def create_integration() -> RtspCameraIntegration:
    uri = os.environ.get("SOURCE_URI", "")
    parsed = urlsplit(uri)
    if parsed.scheme not in {"rtsp", "http", "https"} or not parsed.hostname:
        raise SystemExit("camera SOURCE_URI must be an RTSP or HTTP URL")
    return RtspCameraIntegration(RtspCameraSource(uri))


def main() -> None:
    AdapterRuntime(create_integration()).run()
