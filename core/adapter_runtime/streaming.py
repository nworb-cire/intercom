"""Reusable live-stream format settings for intercom receiver adapters."""

from __future__ import annotations

from dataclasses import dataclass

STREAM_CONTENT_TYPES = {
    "/stream.flac": "audio/flac",
}


@dataclass(frozen=True)
class FlacStreamSink:
    """Low-latency FLAC sink exposed by adapters that support speaker playback."""

    path: str = "/stream.flac"
    content_type: str = "audio/flac"

    def encoder_command(self) -> list[str]:
        return flac_encoder_command()


def pcm_peak(payload: bytes) -> int:
    """Return the absolute peak of little-endian signed 16-bit PCM."""
    usable = len(payload) // 2 * 2
    return max(
        (abs(int.from_bytes(payload[index:index + 2], "little", signed=True))
         for index in range(0, usable, 2)),
        default=0,
    )


def flac_encoder_command() -> list[str]:
    """Encode live 16 kHz mono PCM for the Voice PE HTTP media source."""
    return [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0",
        "-ac", "2", "-ar", "48000",
        "-c:a", "flac", "-compression_level", "0",
        "-flush_packets", "1", "-f", "flac", "pipe:1",
    ]
