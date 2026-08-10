"""Small interfaces shared by the core runtime and device integrations.

The core deliberately knows nothing about cameras, Voice PE, or synthetic test
devices. An integration supplies an :class:`AudioSource`; the runtime owns the
FreeSWITCH leg, lifecycle, health endpoint, and optional live stream.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class AudioSource(Protocol):
    """A device-side source that can feed the adapter's Baresip leg."""

    @property
    def kind(self) -> str:
        """Stable source kind reported by the adapter health endpoint."""

    @property
    def baresip_source(self) -> str:
        """Baresip ``audio_source`` value for this integration."""

    def prepare(self, config_dir: Path) -> None:
        """Create any local audio resources before Baresip starts."""

    def start(self, connected: Callable[[], bool]) -> None:
        """Start background device-side work."""

    def stop(self) -> None:
        """Stop background work and release device-side resources."""


class AudioSink(Protocol):
    """A sink-facing live stream that an application can play on a device."""

    path: str
    content_type: str

    def encoder_command(self) -> list[str]:
        """Return the command that encodes the adapter's PCM stream."""
