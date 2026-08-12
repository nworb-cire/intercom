"""Generic HTTP/Baresip adapter runtime.

Integrations provide only an :class:`~core.interfaces.AudioSource`. This
runtime owns the common FreeSWITCH SIP leg, PulseAudio sink, health endpoint,
connection lifecycle, and optional low-latency FLAC stream.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from core.interfaces import Integration, StreamEncoder

from .streaming import FlacStreamEncoder, pcm_peak


@dataclass(frozen=True)
class RuntimeConfig:
    device_id: str
    freeswitch_uri: str
    http_port: int
    capture_received: bool
    config_dir: Path

    @classmethod
    def from_environment(cls) -> "RuntimeConfig":
        device_id = os.environ["DEVICE_ID"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", device_id):
            raise SystemExit("DEVICE_ID must contain only lowercase letters, digits, and hyphens")
        return cls(
            device_id=device_id,
            freeswitch_uri=os.environ.get("FREESWITCH_URI", "sip:intercom@freeswitch:5070"),
            http_port=int(os.environ.get("HTTP_PORT", "8080")),
            capture_received=os.environ.get("CAPTURE_RECEIVED", "false").lower() == "true",
            config_dir=Path(os.environ.get("BARESIP_CONFIG_DIR", "/run/intercom/baresip")),
        )


class AdapterRuntime:
    """Run one application-supplied device adapter around a shared media leg."""

    def __init__(self, integration: Integration, config: RuntimeConfig | None = None) -> None:
        self.integration = integration
        self.config = config or RuntimeConfig.from_environment()
        self.connected = False
        self.connected_call: str | None = None
        self.lock = threading.Lock()
        self.stream_lock = threading.Lock()
        self.stream_processes: set[subprocess.Popen[bytes]] = set()
        self.stream_clients = 0
        self.stream_pcm_bytes = 0
        self.stream_peak = 0
        self.baresip: subprocess.Popen[str] | None = None
        self.stream_encoder: StreamEncoder = FlacStreamEncoder()
        self.capture_processes: list[subprocess.Popen[Any]] = []
        self.server: ThreadingHTTPServer | None = None
        self.shutdown_event = threading.Event()
        self._stopped = False

    def media_ip(self) -> str:
        match = re.search(r"@([^:;>]+)", self.config.freeswitch_uri)
        if not match:
            raise SystemExit("FREESWITCH_URI must contain a host after @")
        target = socket.gethostbyname(match.group(1))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((target, 5070))
            return str(probe.getsockname()[0])

    def write_baresip_config(self) -> None:
        self.config.config_dir.mkdir(parents=True, exist_ok=True)
        bind_ip = self.media_ip()
        modules = "\n".join(f"module {module}" for module in self.integration.source.baresip_modules)
        baresip_config = f"""poll_method epoll
net_interface {bind_ip}
sip_listen {bind_ip}:5060
call_max_calls 1
audio_player pulse,intercom
audio_source {self.integration.source.baresip_source}
audio_alert pulse,intercom
auplay_srate 16000
ausrc_srate 48000
auplay_channels 1
ausrc_channels 2
audio_level no
rtcp_enable yes
rtcp_mux no
jitter_buffer_delay 2-10
module_path /usr/lib/baresip/modules
{modules}
"""
        account = (
            f'"{self.config.device_id}" <sip:{self.config.device_id}@127.0.0.1;transport=udp>'
            ";regint=0;answermode=auto;audio_codecs=PCMU/8000/1,PCMA/8000/1\n"
        )
        (self.config.config_dir / "config").write_text(baresip_config)
        (self.config.config_dir / "accounts").write_text(account)

    def start_pulse(self) -> None:
        subprocess.run(
            ["pulseaudio", "--start", "--exit-idle-time=-1", "--log-target=stderr"],
            check=True,
        )

        # pulseaudio --start returns before its native socket is ready. Reuse
        # an already-created sink when a container restarts.
        deadline = time.monotonic() + 5
        while True:
            sinks = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            if any(line.split("\t", 2)[1:2] == ["intercom"] for line in sinks.stdout.splitlines()):
                break
            loaded = subprocess.run(
                [
                    "pactl", "load-module", "module-null-sink", "sink_name=intercom",
                    "rate=16000", "channels=1",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if loaded.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise subprocess.CalledProcessError(loaded.returncode, loaded.args)
            time.sleep(0.1)
        self.integration.prepare(self.config.config_dir)

    def start_capture(self) -> list[subprocess.Popen[Any]]:
        if not self.config.capture_received:
            return []
        parec = subprocess.Popen(
            ["parec", "--device=intercom.monitor", "--format=s16le", "--rate=16000", "--channels=1"],
            stdout=subprocess.PIPE,
        )
        capture_process = subprocess.Popen(
            [
                "ffmpeg", "-nostdin", "-loglevel", "warning", "-f", "s16le", "-ar", "16000",
                "-ac", "1", "-i", "pipe:0", "-f", "segment", "-segment_time", "10",
                "-segment_wrap", "3", "-reset_timestamps", "1", "/captures/received-%d.wav",
            ],
            stdin=parec.stdout,
        )
        return [parec, capture_process]

    def watch_child(self, name: str, child: subprocess.Popen[Any]) -> None:
        return_code = child.wait()
        if self.shutdown_event.is_set():
            return
        print(f"{name} exited unexpectedly with status {return_code}", flush=True)
        os._exit(return_code or 1)

    def start_processes(self) -> None:
        self.write_baresip_config()
        self.start_pulse()
        self.integration.start(lambda: self.connected)
        self.capture_processes = self.start_capture()
        for process_name, process in zip(("capture source", "capture writer"), self.capture_processes):
            threading.Thread(
                target=self.watch_child,
                args=(process_name, process),
                daemon=True,
            ).start()
        self.baresip = subprocess.Popen(
            ["baresip", "-f", str(self.config.config_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(
            target=self.watch_child,
            args=("baresip", self.baresip),
            daemon=True,
        ).start()
        threading.Thread(target=self.drain_baresip_output, daemon=True).start()

    def drain_baresip_output(self) -> None:
        assert self.baresip is not None and self.baresip.stdout is not None
        for line in self.baresip.stdout:
            print(line.rstrip(), flush=True)

    def command(self, value: str) -> None:
        if self.baresip is None or self.baresip.poll() is not None or self.baresip.stdin is None:
            raise RuntimeError("baresip is not running")
        self.baresip.stdin.write(value + "\n")
        self.baresip.stdin.flush()

    @staticmethod
    def call_id(value: object) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
            raise ValueError("call_id must contain lowercase letters, digits, and hyphens")
        return value

    def call_uri(self, call: str) -> str:
        """Use the configured FreeSWITCH host while selecting a call by name."""
        match = re.fullmatch(r"sip:[^@]+@(.+)", self.config.freeswitch_uri)
        if not match:
            raise RuntimeError("FREESWITCH_URI must be a SIP URI with a destination and host")
        return f"sip:{call}@{match.group(1)}"

    def connect(self, call: str = "intercom") -> None:
        call = self.call_id(call)
        with self.lock:
            if not self.connected:
                self.command(f"/dial {self.call_uri(call)}")
            elif self.connected_call != call:
                raise RuntimeError(f"adapter is already connected to call {self.connected_call}")
            self.connected = True
            self.connected_call = call

    def disconnect(self) -> None:
        with self.lock:
            if self.connected:
                self.command("/hangup")
                self.connected = False
                self.connected_call = None
            with self.stream_lock:
                for process in tuple(self.stream_processes):
                    process.terminate()

    def request_shutdown(self, _signum: int, _frame: Any) -> None:
        if not self.shutdown_event.is_set():
            threading.Thread(target=self.shutdown, name="adapter-shutdown", daemon=True).start()

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.shutdown_event.set()
        if self.server is not None:
            self.server.shutdown()
        with self.lock:
            if self.connected and self.baresip is not None and self.baresip.poll() is None:
                try:
                    self.command("/hangup")
                except RuntimeError:
                    pass
            self.connected = False
            self.connected_call = None
        try:
            self.integration.stop()
        finally:
            with self.stream_lock:
                active_processes = tuple(self.stream_processes)
            for process in active_processes + tuple(self.capture_processes):
                if process.poll() is None:
                    process.terminate()
            if self.baresip is not None and self.baresip.poll() is None:
                self.baresip.terminate()
            for process in active_processes + tuple(self.capture_processes):
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            if self.baresip is not None:
                try:
                    self.baresip.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.baresip.kill()

    def health(self) -> dict[str, Any]:
        with self.stream_lock:
            stream_status = {
                "stream_clients": self.stream_clients,
                "stream_pcm_bytes": self.stream_pcm_bytes,
                "stream_peak": self.stream_peak,
            }
        baresip_ok = self.baresip is not None and self.baresip.poll() is None
        return {
            "ok": baresip_ok,
            "device_id": self.config.device_id,
            "integration": self.integration.name,
            "source_kind": self.integration.source.kind,
            "connected": self.connected,
            "call_id": self.connected_call,
            "capture": self.config.capture_received,
            **self.integration.health(),
            **stream_status,
        }

    def stream_flac(self, handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", self.stream_encoder.content_type)
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        source = subprocess.Popen(
            [
                "parec", "--device=intercom.monitor", "--format=s16le",
                "--rate=16000", "--channels=1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        encoder = subprocess.Popen(
            self.stream_encoder.encoder_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        def pump_pcm() -> None:
            assert source.stdout is not None and encoder.stdin is not None
            try:
                while payload := source.stdout.read1(4096):
                    with self.stream_lock:
                        self.stream_pcm_bytes += len(payload)
                        self.stream_peak = max(self.stream_peak, pcm_peak(payload))
                    encoder.stdin.write(payload)
                    encoder.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    encoder.stdin.close()
                except OSError:
                    pass

        pump = threading.Thread(target=pump_pcm, name="flac-pcm-pump", daemon=True)
        with self.stream_lock:
            self.stream_processes.update((source, encoder))
            self.stream_clients += 1
        pump.start()
        try:
            assert encoder.stdout is not None
            while payload := encoder.stdout.read1(4096):
                handler.wfile.write(payload)
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            for process in (encoder, source):
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            pump.join(timeout=2)
            with self.stream_lock:
                self.stream_processes.difference_update((source, encoder))
                self.stream_clients -= 1

    def handler_class(self) -> type[BaseHTTPRequestHandler]:
        runtime = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                print(f"{self.address_string()} {fmt % args}", flush=True)

            def reply(self, status: int, payload: Any) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == runtime.stream_encoder.path:
                    runtime.stream_flac(self)
                    return
                if self.path != "/health":
                    self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                health = runtime.health()
                self.reply(HTTPStatus.OK if health["ok"] else HTTPStatus.SERVICE_UNAVAILABLE, health)

            def do_HEAD(self) -> None:
                if self.path != runtime.stream_encoder.path:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", runtime.stream_encoder.content_type)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

            def do_POST(self) -> None:
                if self.path != "/connect":
                    self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(payload, dict):
                        raise ValueError("request body must be an object")
                    runtime.connect(payload.get("call_id", "intercom"))
                except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
                    self.reply(HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                self.reply(HTTPStatus.ACCEPTED, {"connected": runtime.connected, "call_id": runtime.connected_call})

            def do_DELETE(self) -> None:
                if self.path != "/connect":
                    self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                runtime.disconnect()
                self.reply(HTTPStatus.OK, {"connected": runtime.connected})

        return Handler

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.request_shutdown)
        signal.signal(signal.SIGINT, self.request_shutdown)
        try:
            self.start_processes()
            time.sleep(1)
            self.server = ThreadingHTTPServer(("0.0.0.0", self.config.http_port), self.handler_class())
            self.server.daemon_threads = True
            self.server.serve_forever()
        finally:
            self.shutdown()
