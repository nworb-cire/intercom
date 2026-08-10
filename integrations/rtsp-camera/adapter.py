"""RTSP camera microphone integration using Baresip's GStreamer source."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

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

    def prepare(self, _config_dir: Path) -> None:
        return

    def start(self, _connected: Callable[[], bool]) -> None:
        return

    def stop(self) -> None:
        return


def create_source() -> RtspCameraSource:
    uri = os.environ.get("SOURCE_URI", "")
    parsed = urlsplit(uri)
    if parsed.scheme not in {"rtsp", "http", "https"} or not parsed.hostname:
        raise SystemExit("camera SOURCE_URI must be an RTSP or HTTP URL")
    return RtspCameraSource(uri)


if __name__ == "__main__":
    AdapterRuntime(create_source()).run()
