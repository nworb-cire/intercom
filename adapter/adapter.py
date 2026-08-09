#!/usr/bin/env python3
"""Baresip wrapper: device-native audio on one side, RTP/SIP on the other."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


DEVICE_ID = os.environ["DEVICE_ID"]
SOURCE_KIND = os.environ.get("SOURCE_KIND", "silence")
SOURCE_URI = os.environ.get("SOURCE_URI", "")
CAPTURE_RECEIVED = os.environ.get("CAPTURE_RECEIVED", "false").lower() == "true"
SENDSPIN_RECEIVED = os.environ.get("SENDSPIN_RECEIVED", "false").lower() == "true"
SENDSPIN_PORT = int(os.environ.get("SENDSPIN_PORT", "8927"))
SENDSPIN_CLIENT_URL = os.environ.get("SENDSPIN_CLIENT_URL", "")
BLUETOOTH_RECEIVED = os.environ.get("BLUETOOTH_RECEIVED", "false").lower() == "true"
BLUETOOTH_DEVICE = os.environ.get("BLUETOOTH_DEVICE", "").upper()
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
FREESWITCH_URI = os.environ.get("FREESWITCH_URI", "sip:9000@freeswitch:5070")
CONFIG = Path("/run/intercom/baresip")

if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", DEVICE_ID):
    raise SystemExit("DEVICE_ID must contain only lowercase letters, digits, and hyphens")
if SOURCE_KIND not in {"silence", "sine", "gstreamer"}:
    raise SystemExit("SOURCE_KIND must be silence, sine, or gstreamer")
if SOURCE_KIND == "gstreamer" and not SOURCE_URI.startswith(("rtsp://", "http://", "https://")):
    raise SystemExit("gstreamer SOURCE_URI must be an RTSP or HTTP URL")
if BLUETOOTH_RECEIVED and not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", BLUETOOTH_DEVICE):
    raise SystemExit("BLUETOOTH_DEVICE must be a Bluetooth MAC address")


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
    subprocess.run(
        ["pactl", "load-module", "module-null-sink", "sink_name=intercom", "rate=16000", "channels=1"],
        check=True,
        stdout=subprocess.DEVNULL,
    )


bluetooth_ready = False


def start_bluetooth() -> None:
    """Keep the paired Echo connected and mirror conference audio to its A2DP sink."""
    if not BLUETOOTH_RECEIVED:
        return
    subprocess.run(["pactl", "load-module", "module-bluetooth-discover"], check=True)
    subprocess.run(["bluetoothctl", "trust", BLUETOOTH_DEVICE], check=False)
    sink_prefix = "bluez_sink." + BLUETOOTH_DEVICE.replace(":", "_")

    def maintain() -> None:
        global bluetooth_ready
        loopback_sink = ""
        while True:
            try:
                info = subprocess.run(
                    ["bluetoothctl", "info", BLUETOOTH_DEVICE],
                    text=True,
                    capture_output=True,
                    check=False,
                ).stdout
                if "Connected: yes" not in info:
                    bluetooth_ready = False
                    subprocess.run(
                        ["bluetoothctl", "connect", BLUETOOTH_DEVICE],
                        timeout=15,
                        check=False,
                    )

                sinks = subprocess.run(
                    ["pactl", "list", "short", "sinks"],
                    text=True,
                    capture_output=True,
                    check=True,
                ).stdout
                sink = next(
                    (line.split("\t", 2)[1] for line in sinks.splitlines() if sink_prefix in line),
                    "",
                )
                if not sink:
                    loopback_sink = ""
                elif sink != loopback_sink:
                    subprocess.run(
                        [
                            "pactl", "load-module", "module-loopback",
                            "source=intercom.monitor", f"sink={sink}",
                            "latency_msec=60", "adjust_time=1",
                        ],
                        check=True,
                    )
                    loopback_sink = sink
                    print(f"received PCM feeding Bluetooth sink {sink}", flush=True)
                bluetooth_ready = bool(sink)
            except (OSError, subprocess.SubprocessError) as exc:
                bluetooth_ready = False
                print(f"Bluetooth maintenance failed: {type(exc).__name__}", flush=True)
            time.sleep(3)

    threading.Thread(target=maintain, daemon=True).start()


def start_capture() -> subprocess.Popen[bytes] | None:
    if not CAPTURE_RECEIVED:
        return None
    parec = subprocess.Popen(
        ["parec", "--device=intercom.monitor", "--format=s16le", "--rate=16000", "--channels=1"],
        stdout=subprocess.PIPE,
    )


def start_sendspin() -> list[subprocess.Popen[Any]]:
    """Feed received PCM to a LAN-visible standalone Sendspin server via a FIFO."""
    if not SENDSPIN_RECEIVED:
        return []
    fifo = CONFIG / "received.wav"
    fifo.unlink(missing_ok=True)
    os.mkfifo(fifo)
    server_command = [
        "sendspin", "serve", str(fifo), "--port", str(SENDSPIN_PORT),
        "--name", f"Intercom {DEVICE_ID}", "--log-level", "INFO",
    ]
    if SENDSPIN_CLIENT_URL:
        if not SENDSPIN_CLIENT_URL.startswith(("ws://", "wss://")):
            raise SystemExit("SENDSPIN_CLIENT_URL must be a WebSocket URL")
        server_command.extend(("--client", SENDSPIN_CLIENT_URL))
    server = subprocess.Popen(server_command)
    parec = subprocess.Popen(
        ["parec", "--device=intercom.monitor", "--format=s16le", "--rate=16000", "--channels=1"],
        stdout=subprocess.PIPE,
    )
    pcm = subprocess.Popen(
        [
            "ffmpeg", "-y", "-nostdin", "-loglevel", "warning", "-f", "s16le",
            "-ar", "16000", "-ac", "1", "-i", "pipe:0", "-ar", "48000", "-ac", "2",
            "-codec:a", "pcm_s16le", "-f", "wav", str(fifo),
        ],
        stdin=parec.stdout,
    )
    print(f"received PCM feeding standalone Sendspin on :{SENDSPIN_PORT}", flush=True)
    return [server, parec, pcm]
    return subprocess.Popen(
        [
            "ffmpeg", "-nostdin", "-loglevel", "warning", "-f", "s16le", "-ar", "16000",
            "-ac", "1", "-i", "pipe:0", "-f", "segment", "-segment_time", "10",
            "-segment_wrap", "3", "-reset_timestamps", "1", "/captures/received-%d.wav",
        ],
        stdin=parec.stdout,
    )


write_config()
start_pulse()
start_bluetooth()
capture = start_capture()
sendspin_processes = start_sendspin()
for process_name, process in zip(("sendspin", "parec", "pcm bridge"), sendspin_processes):
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
connected = False


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
        if self.path != "/health":
            self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        healthy = baresip.poll() is None and (not BLUETOOTH_RECEIVED or bluetooth_ready)
        self.reply(HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE, {
            "ok": healthy,
            "device_id": DEVICE_ID,
            "source_kind": SOURCE_KIND,
            "connected": connected,
            "capture": CAPTURE_RECEIVED,
            "sendspin": SENDSPIN_RECEIVED,
            "bluetooth": BLUETOOTH_RECEIVED,
            "bluetooth_ready": bluetooth_ready,
        })

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
        self.reply(HTTPStatus.OK, {"connected": connected})


# Give Baresip time to load modules before reporting a usable HTTP endpoint.
time.sleep(1)
ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler).serve_forever()
