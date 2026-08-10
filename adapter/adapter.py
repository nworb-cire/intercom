#!/usr/bin/env python3
"""Baresip wrapper: device-native audio on one side, RTP/SIP on the other."""

from __future__ import annotations

import json
import os
import re
import socket
import socket as udp_socket
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from streaming import STREAM_CONTENT_TYPES, flac_encoder_command, pcm_peak


DEVICE_ID = os.environ["DEVICE_ID"]
SOURCE_KIND = os.environ.get("SOURCE_KIND", "silence")
SOURCE_URI = os.environ.get("SOURCE_URI", "")
CAPTURE_RECEIVED = os.environ.get("CAPTURE_RECEIVED", "false").lower() == "true"
UDP_REMOTE_HOST = os.environ.get("UDP_REMOTE_HOST", "")
UDP_REMOTE_PORT = int(os.environ.get("UDP_REMOTE_PORT", "18555"))
UDP_TOKEN = os.environ.get("UDP_TOKEN", "")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
FREESWITCH_URI = os.environ.get("FREESWITCH_URI", "sip:9000@freeswitch:5070")
CONFIG = Path("/run/intercom/baresip")

if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", DEVICE_ID):
    raise SystemExit("DEVICE_ID must contain only lowercase letters, digits, and hyphens")
if SOURCE_KIND not in {"silence", "sine", "gstreamer", "udp-pcm"}:
    raise SystemExit("SOURCE_KIND must be silence, sine, gstreamer, or udp-pcm")
if SOURCE_KIND == "gstreamer" and not SOURCE_URI.startswith(("rtsp://", "http://", "https://")):
    raise SystemExit("gstreamer SOURCE_URI must be an RTSP or HTTP URL")
if SOURCE_KIND == "udp-pcm" and (not UDP_REMOTE_HOST or len(UDP_TOKEN) < 24):
    raise SystemExit("udp-pcm requires UDP_REMOTE_HOST and a UDP_TOKEN of at least 24 characters")
connected = False
stream_lock = threading.Lock()
stream_processes: set[subprocess.Popen[bytes]] = set()
stream_clients = 0
stream_pcm_bytes = 0
stream_peak = 0
def media_ip() -> str:
    match = re.search(r"@([^:;>]+)", FREESWITCH_URI)
    if not match:
        raise SystemExit("FREESWITCH_URI must contain a host after @")
    target = socket.gethostbyname(match.group(1))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((target, 5070))
        return str(probe.getsockname()[0])


def write_config() -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)
    bind_ip = media_ip()
    source = {
        # Baresip 1.0 rejects 0 Hz; speaker-only endpoints are conference-muted.
        "silence": "ausine,10",
        "sine": f"ausine,{int(os.environ.get('SINE_FREQUENCY', '440'))}",
        "gstreamer": f"gst,{SOURCE_URI}",
        "udp-pcm": "pulse,voice_pe_intercom",
    }[SOURCE_KIND]
    config = f"""poll_method epoll
net_interface {bind_ip}
sip_listen {bind_ip}:5060
call_max_calls 1
audio_player pulse,intercom
audio_source {source}
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
module stdio.so
module g711.so
module pulse.so
module ausine.so
module gst.so
module account.so
module menu.so
"""
    account = (
        f'"{DEVICE_ID}" <sip:{DEVICE_ID}@127.0.0.1;transport=udp>'
        ";regint=0;answermode=auto;audio_codecs=PCMU/8000/1,PCMA/8000/1\n"
    )
    (CONFIG / "config").write_text(config)
    (CONFIG / "accounts").write_text(account)


def start_pulse() -> None:
    subprocess.run(
        ["pulseaudio", "--start", "--exit-idle-time=-1", "--log-target=stderr"],
        check=True,
    )

    # pulseaudio --start returns before its native socket is ready. In
    # particular, a container restart can otherwise race the first pactl call
    # and leave the adapter in a restart loop. Reuse an already-created sink
    # too, which makes initialization safe when PulseAudio survives briefly
    # across a container restart.
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
            ["pactl", "load-module", "module-null-sink", "sink_name=intercom", "rate=16000", "channels=1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if loaded.returncode == 0:
            break
        if time.monotonic() >= deadline:
            raise subprocess.CalledProcessError(loaded.returncode, loaded.args)
        time.sleep(0.1)
    if SOURCE_KIND == "udp-pcm":
        fifo = CONFIG / "microphone.pcm"
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


def start_udp_microphone() -> None:
    """Hold a short Voice PE stream lease and feed its PCM into PulseAudio."""
    if SOURCE_KIND != "udp-pcm":
        return

    fifo = CONFIG / "microphone.pcm"

    def receive() -> None:
        target = (UDP_REMOTE_HOST, UDP_REMOTE_PORT)
        subscriber = udp_socket.socket(udp_socket.AF_INET, udp_socket.SOCK_DGRAM)
        subscriber.bind(("0.0.0.0", 0))
        subscriber.settimeout(0.25)
        pipe_fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        last_heartbeat = 0.0
        was_connected = False
        while True:
            now = time.monotonic()
            if connected and now - last_heartbeat >= 1.0:
                subscriber.sendto(f"START {UDP_TOKEN}".encode(), target)
                last_heartbeat = now
            if was_connected and not connected:
                subscriber.sendto(f"STOP {UDP_TOKEN}".encode(), target)
            was_connected = connected
            try:
                payload, source = subscriber.recvfrom(2048)
            except TimeoutError:
                continue
            if connected and source[0] == UDP_REMOTE_HOST:
                try:
                    os.write(pipe_fd, payload)
                except BlockingIOError:
                    pass

    threading.Thread(target=receive, name="udp-microphone", daemon=True).start()


def start_capture() -> list[subprocess.Popen[Any]]:
    if not CAPTURE_RECEIVED:
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


write_config()
start_pulse()
start_udp_microphone()
capture_processes = start_capture()
for process_name, process in zip(("capture source", "capture writer"), capture_processes):
    def watch_child(name: str = process_name, child: subprocess.Popen[Any] = process) -> None:
        return_code = child.wait()
        print(f"{name} exited unexpectedly with status {return_code}", flush=True)
        os._exit(return_code or 1)

    threading.Thread(target=watch_child, daemon=True).start()
baresip = subprocess.Popen(
    ["baresip", "-f", str(CONFIG)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)


def drain_output() -> None:
    assert baresip.stdout is not None
    for line in baresip.stdout:
        print(line.rstrip(), flush=True)


threading.Thread(target=drain_output, daemon=True).start()
lock = threading.Lock()


def command(value: str) -> None:
    if baresip.poll() is not None or baresip.stdin is None:
        raise RuntimeError("baresip is not running")
    baresip.stdin.write(value + "\n")
    baresip.stdin.flush()


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
        global stream_clients, stream_pcm_bytes, stream_peak
        if self.path in STREAM_CONTENT_TYPES:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", STREAM_CONTENT_TYPES[self.path])
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            source = subprocess.Popen(
                [
                    "parec", "--device=intercom.monitor", "--format=s16le",
                    "--rate=16000", "--channels=1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            encoder: subprocess.Popen[bytes] | None = None
            pump: threading.Thread | None = None
            if self.path == "/stream.flac":
                encoder = subprocess.Popen(
                    flac_encoder_command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )

                def pump_pcm() -> None:
                    global stream_pcm_bytes, stream_peak
                    assert source.stdout is not None
                    assert encoder is not None and encoder.stdin is not None
                    try:
                        while payload := source.stdout.read1(4096):
                            peak = pcm_peak(payload)
                            with stream_lock:
                                stream_pcm_bytes += len(payload)
                                stream_peak = max(stream_peak, peak)
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
                pump.start()
            with stream_lock:
                stream_processes.add(source)
                if encoder is not None:
                    stream_processes.add(encoder)
                stream_clients += 1
            try:
                output = source.stdout if encoder is None else encoder.stdout
                assert output is not None
                while payload := output.read1(4096):
                    self.wfile.write(payload)
                    self.wfile.flush()
                    if encoder is None:
                        peak = pcm_peak(payload)
                        with stream_lock:
                            stream_pcm_bytes += len(payload)
                            stream_peak = max(stream_peak, peak)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                for process in (encoder, source):
                    if process is None:
                        continue
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
                if pump is not None:
                    pump.join(timeout=2)
                with stream_lock:
                    stream_processes.discard(source)
                    if encoder is not None:
                        stream_processes.discard(encoder)
                    stream_clients -= 1
            return
        if self.path != "/health":
            self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        with stream_lock:
            stream_status = {
                "stream_clients": stream_clients,
                "stream_pcm_bytes": stream_pcm_bytes,
                "stream_peak": stream_peak,
            }
        self.reply(HTTPStatus.OK if baresip.poll() is None else HTTPStatus.SERVICE_UNAVAILABLE, {
            "ok": baresip.poll() is None,
            "device_id": DEVICE_ID,
            "source_kind": SOURCE_KIND,
            "connected": connected,
            "capture": CAPTURE_RECEIVED,
            **stream_status,
        })

    def do_HEAD(self) -> None:
        if self.path not in STREAM_CONTENT_TYPES:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", STREAM_CONTENT_TYPES[self.path])
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_POST(self) -> None:
        global connected
        if self.path != "/connect":
            self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        with lock:
            if not connected:
                command(f"/dial {FREESWITCH_URI}")
            connected = True
        self.reply(HTTPStatus.ACCEPTED, {"connected": connected})

    def do_DELETE(self) -> None:
        global connected
        if self.path != "/connect":
            self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        with lock:
            if connected:
                command("/hangup")
                connected = False
            with stream_lock:
                for process in tuple(stream_processes):
                    process.terminate()
        self.reply(HTTPStatus.OK, {"connected": connected})


# Give Baresip time to load modules before reporting a usable HTTP endpoint.
time.sleep(1)
ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler).serve_forever()
