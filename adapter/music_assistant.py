"""Small authenticated client for the Music Assistant JSON-RPC API."""

from __future__ import annotations

import json
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class MusicAssistantError(RuntimeError):
    """A Music Assistant request could not be completed."""


def wav_header() -> bytes:
    """Return a streaming PCM WAV header with an intentionally unknown length."""
    return (
        b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data" + struct.pack("<I", 0xFFFFFFFF)
    )


def pcm_peak(payload: bytes) -> int:
    """Return the greatest absolute signed 16-bit sample in a PCM chunk."""
    usable = len(payload) - (len(payload) % 2)
    if not usable:
        return 0
    samples = struct.unpack(f"<{usable // 2}h", payload[:usable])
    return max(abs(sample) for sample in samples)


class MusicAssistantSink:
    """Start and stop one application-owned live stream on one MA player."""

    def __init__(self, base_url: str, token_file: Path, player_id: str, stream_url: str) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("Music Assistant URL must be HTTP or HTTPS")
        if not stream_url.startswith(("http://", "https://")):
            raise ValueError("stream URL must be HTTP or HTTPS")
        self.api_url = base_url.rstrip("/") + "/api"
        self.token_file = token_file
        self.player_id = player_id
        self.stream_url = stream_url

    def _token(self) -> str:
        try:
            token = self.token_file.read_text().strip()
        except OSError as exc:
            raise MusicAssistantError("Music Assistant token file is unavailable") from exc
        if len(token) < 32:
            raise MusicAssistantError("Music Assistant token file is invalid")
        return token

    def command(self, command: str, **args: Any) -> Any:
        body = json.dumps({"command": command, "args": args}, separators=(",", ":")).encode()
        request = urllib.request.Request(
            self.api_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            raise MusicAssistantError(f"Music Assistant returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise MusicAssistantError("Music Assistant is unavailable") from exc
        return json.loads(payload) if payload else None

    def play(self) -> None:
        self.command(
            "player_queues/play_media",
            queue_id=self.player_id,
            media=self.stream_url,
        )

    def stop(self) -> None:
        self.command("player_queues/stop", queue_id=self.player_id)
