"""Home Assistant Voice PE source integration."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.interfaces import AudioSink
from core.adapter_runtime.runtime import AdapterRuntime


@dataclass
class VoicePeSource:
    enabled: bool
    remote_host: str = ""
    remote_port: int = 18555
    token: str = ""
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _fifo: Path | None = field(default=None, init=False)

    @property
    def kind(self) -> str:
        return "udp-pcm" if self.enabled else "silence"

    @property
    def baresip_source(self) -> str:
        return "pulse,voice_pe_intercom" if self.enabled else "ausine,10"

    @property
    def baresip_modules(self) -> tuple[str, ...]:
        return ("stdio.so", "g711.so", "pulse.so", "ausine.so", "account.so", "menu.so")

    def prepare(self, config_dir: Path) -> None:
        if not self.enabled:
            return
        fifo = config_dir / "microphone.pcm"
        fifo.unlink(missing_ok=True)
        os.mkfifo(fifo)
        subprocess.run(
            [
                "pactl", "load-module", "module-pipe-source",
                "source_name=voice_pe_intercom", f"file={fifo}", "format=s16le",
                "rate=16000", "channels=1",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        self._fifo = fifo

    def start(self, connected: Callable[[], bool]) -> None:
        if not self.enabled:
            return
        assert self._fifo is not None
        self._stop.clear()

        def receive() -> None:
            allowed_host = socket.gethostbyname(self.remote_host)
            subscriber = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            subscriber.bind(("0.0.0.0", 0))
            subscriber.settimeout(0.25)
            pipe_fd = os.open(self._fifo, os.O_WRONLY | os.O_NONBLOCK)
            last_heartbeat = 0.0
            was_connected = False
            try:
                while not self._stop.is_set():
                    now = time.monotonic()
                    if connected() and now - last_heartbeat >= 1.0:
                        subscriber.sendto(
                            f"START {self.token}".encode(),
                            (allowed_host, self.remote_port),
                        )
                        last_heartbeat = now
                    if was_connected and not connected():
                        subscriber.sendto(
                            f"STOP {self.token}".encode(),
                            (allowed_host, self.remote_port),
                        )
                    was_connected = connected()
                    try:
                        payload, source = subscriber.recvfrom(2048)
                    except TimeoutError:
                        continue
                    if connected() and source[0] == allowed_host:
                        try:
                            os.write(pipe_fd, payload)
                        except BlockingIOError:
                            pass
            finally:
                os.close(pipe_fd)
                subscriber.close()

        self._thread = threading.Thread(target=receive, name="voice-pe-microphone", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)


@dataclass
class VoicePeIntegration:
    source: VoicePeSource
    sink: AudioSink | None = None
    name: str = "voice-pe"

    def health(self) -> dict[str, str]:
        return {"integration": self.name}

    def prepare(self, config_dir: Path) -> None:
        self.source.prepare(config_dir)

    def start(self, connected: Callable[[], bool]) -> None:
        self.source.start(connected)

    def stop(self) -> None:
        self.source.stop()


def create_integration() -> VoicePeIntegration:
    enabled = os.environ.get("VOICE_PE_MICROPHONE", "false").lower() == "true"
    remote_host = os.environ.get("UDP_REMOTE_HOST", "")
    token = os.environ.get("UDP_TOKEN", "")
    if enabled and (not remote_host or len(token) < 24):
        raise SystemExit(
            "VOICE_PE_MICROPHONE requires UDP_REMOTE_HOST and a UDP_TOKEN of at least 24 characters"
        )
    return VoicePeIntegration(
        VoicePeSource(
            enabled=enabled,
            remote_host=remote_host,
            remote_port=int(os.environ.get("UDP_REMOTE_PORT", "18555")),
            token=token,
        )
    )


def main() -> None:
    AdapterRuntime(create_integration()).run()
