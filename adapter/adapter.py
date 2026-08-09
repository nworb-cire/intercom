#!/usr/bin/env python3
"""Baresip wrapper: device-native audio on one side, RTP/SIP on the other."""

from __future__ import annotations

import json
import os
import re
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
FREESWITCH_URI = os.environ.get("FREESWITCH_URI", "sip:9000@freeswitch:5070")
CONFIG = Path("/run/intercom/baresip")

if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", DEVICE_ID):
    raise SystemExit("DEVICE_ID must contain only lowercase letters, digits, and hyphens")
if SOURCE_KIND not in {"silence", "sine", "gstreamer"}:
    raise SystemExit("SOURCE_KIND must be silence, sine, or gstreamer")
if SOURCE_KIND == "gstreamer" and not SOURCE_URI.startswith(("rtsp://", "http://", "https://")):
    raise SystemExit("gstreamer SOURCE_URI must be an RTSP or HTTP URL")


def write_config() -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)
    source = {
        "silence": "ausine,0",
        "sine": f"ausine,{int(os.environ.get('SINE_FREQUENCY', '440'))}",
        "gstreamer": f"gst,{SOURCE_URI}",
    }[SOURCE_KIND]
    config = f"""poll_method epoll
net_interface eth0
sip_listen 0.0.0.0:5060
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


def start_capture() -> subprocess.Popen[bytes] | None:
    if not CAPTURE_RECEIVED:
        return None
    parec = subprocess.Popen(
        ["parec", "--device=intercom.monitor", "--format=s16le", "--rate=16000", "--channels=1"],
        stdout=subprocess.PIPE,
    )
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
capture = start_capture()
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
        self.reply(HTTPStatus.OK if baresip.poll() is None else HTTPStatus.SERVICE_UNAVAILABLE, {
            "ok": baresip.poll() is None,
            "device_id": DEVICE_ID,
            "source_kind": SOURCE_KIND,
            "connected": connected,
            "capture": CAPTURE_RECEIVED,
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
ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
