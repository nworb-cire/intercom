"""Reusable live-stream format settings for intercom receiver adapters."""

from __future__ import annotations


STREAM_CONTENT_TYPES = {
    "/stream.wav": "audio/wav",
    "/stream.flac": "audio/flac",
}


def flac_encoder_command() -> list[str]:
    """Encode live 16 kHz mono PCM for the Voice PE HTTP media source."""
    return [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0",
        "-ac", "2", "-ar", "48000",
        "-c:a", "flac", "-compression_level", "0",
        "-flush_packets", "1", "-f", "flac", "pipe:1",
    ]
