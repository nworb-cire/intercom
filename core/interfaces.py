"""Small interfaces shared by the core runtime and device integrations.

The core deliberately knows nothing about cameras, Voice PE, or synthetic test
devices. An integration supplies an :class:`AudioSource`; the runtime owns the
FreeSWITCH leg, lifecycle, health endpoint, and optional live stream.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol


class AudioSource(Protocol):
    """A device-side source that can feed the adapter's Baresip leg."""

    @property
    def kind(self) -> str:
        """Stable source kind reported by the adapter health endpoint."""

    @property
    def baresip_source(self) -> str:
        """Baresip ``audio_source`` value for this integration."""

    @property
    def baresip_modules(self) -> tuple[str, ...]:
        """Baresip modules required by this source."""

    def prepare(self, config_dir: Path) -> None:
        """Create any local audio resources before Baresip starts."""

    def start(self, connected: Callable[[], bool]) -> None:
        """Start background device-side work."""

    def stop(self) -> None:
        """Stop background work and release device-side resources."""


class StreamEncoder(Protocol):
    """An encoder for the adapter's application-consumable media stream."""

    path: str
    content_type: str

    def encoder_command(self) -> list[str]:
        """Return the command that encodes PCM from stdin."""


class AudioSink(Protocol):
    """Optional device sink controlled by an integration or application."""

    def play(self, stream_url: str) -> None:
        """Start device playback from a stream URL."""

    def stop(self) -> None:
        """Stop device playback."""


class Integration(Protocol):
    """A concrete adapter integration assembled from reusable capabilities."""

    name: str
    source: AudioSource
    sink: AudioSink | None

    def health(self) -> dict[str, Any]:
        """Return integration-specific health details."""

    def prepare(self, config_dir: Path) -> None:
        """Prepare source and sink resources before the media process starts."""

    def start(self, connected: Callable[[], bool]) -> None:
        """Start integration background work."""

    def stop(self) -> None:
        """Stop integration background work."""
