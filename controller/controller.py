#!/usr/bin/env python3
"""Small authoritative control plane for one FreeSWITCH conference."""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote


ROOM = os.environ.get("INTERCOM_ROOM", "intercom")
ESL_HOST = os.environ.get("FREESWITCH_ESL_HOST", "freeswitch")
ESL_PORT = int(os.environ.get("FREESWITCH_ESL_PORT", "8021"))
ESL_PASSWORD = os.environ["INTERCOM_ESL_PASSWORD"]
DEVICES = json.loads(Path(os.environ.get("DEVICES_FILE", "/app/devices.json")).read_text())


class Error(RuntimeError):
    pass


class ESL:
    """One-command-at-a-time FreeSWITCH event socket client."""

    def __init__(self, host: str = ESL_HOST, port: int = ESL_PORT) -> None:
        self.host = host
        self.port = port

    @staticmethod
    def _frame(stream: Any) -> tuple[dict[str, str], bytes]:
        headers: dict[str, str] = {}
        while True:
            line = stream.readline()
            if not line:
                raise Error("FreeSWITCH closed the event socket")
            if line in (b"\n", b"\r\n"):
                break
            key, _, value = line.decode("utf-8", "replace").partition(":")
            headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        return headers, stream.read(length) if length else b""

    def api(self, command: str) -> str:
        with socket.create_connection((self.host, self.port), timeout=5) as sock:
            stream = sock.makefile("rb")
            headers, _ = self._frame(stream)
            if headers.get("content-type") != "auth/request":
                raise Error("unexpected FreeSWITCH greeting")
            sock.sendall(f"auth {ESL_PASSWORD}\n\n".encode())
            headers, _ = self._frame(stream)
            if "+OK accepted" not in headers.get("reply-text", ""):
                raise Error("FreeSWITCH event socket authentication failed")
            sock.sendall(f"api {command}\n\n".encode())
            _, body = self._frame(stream)
            result = body.decode("utf-8", "replace").strip()
            if result.startswith("-ERR"):
                raise Error(result)
            return result


def adapter_request(device_id: str, method: str) -> dict[str, Any]:
    url = DEVICES[device_id]["adapter_url"] + "/connect"
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise Error(f"adapter {device_id} failed: {exc.reason if hasattr(exc, 'reason') else exc}") from exc


def conferences() -> list[dict[str, Any]]:
    raw = ESL().api("conference json_list compact")
    if not raw or raw == "[]":
        return []
    data = json.loads(raw)
    return data if isinstance(data, list) else data.get("conferences", [])


def session() -> dict[str, Any]:
    conference = next((item for item in conferences() if item.get("conference_name") == ROOM), None)
    members = [] if conference is None else conference.get("members", [])
    normalized = []
    for member in members:
        caller = member.get("caller_id_name") or member.get("caller_id_number") or "unknown"
        normalized.append({
            "device_id": caller,
            "member_id": int(member["id"]),
            "uuid": member.get("uuid"),
            "flags": member.get("flags", {}),
        })
    return {"room": ROOM, "active": bool(conference), "members": normalized}


def member_map() -> dict[str, int]:
    return {member["device_id"]: member["member_id"] for member in session()["members"]}


def wait_for_member(device_id: str, present: bool, timeout: float = 8) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (device_id in member_map()) is present:
            return
        time.sleep(0.2)
    raise Error(f"timed out waiting for {device_id} to {'join' if present else 'leave'}")


def enforce_capabilities(device_id: str) -> None:
    members = member_map()
    member_id = members[device_id]
    device = DEVICES[device_id]
    ESL().api(f"conference {ROOM} {'unmute' if device['can_transmit'] else 'mute'} {member_id} quiet")
    ESL().api(f"conference {ROOM} {'undeaf' if device['can_receive'] else 'deaf'} {member_id}")

    # Deny all new cross-member paths until the application enables each one.
    for other_id in members.values():
        if other_id == member_id:
            continue
        ESL().api(f"conference {ROOM} relate {member_id} {other_id} nospeak")
        ESL().api(f"conference {ROOM} relate {other_id} {member_id} nospeak")


def set_route(source: str, sink: str, enabled: bool) -> None:
    if source == sink:
        raise Error("source and sink must be different devices")
    members = member_map()
    if source not in members or sink not in members:
        raise Error("both route endpoints must be connected")
    if not DEVICES[source]["can_transmit"]:
        raise Error(f"{source} has no transmit direction")
    if not DEVICES[sink]["can_receive"]:
        raise Error(f"{sink} has no receive direction")
    action = "clear" if enabled else "nospeak"
    ESL().api(f"conference {ROOM} relate {members[source]} {members[sink]} {action}")


class Handler(BaseHTTPRequestHandler):
    server_version = "intercom-controller/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            raise Error("request body too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def reply(self, status: int, payload: Any) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def dispatch(self) -> tuple[int, Any]:
        parts = [unquote(part) for part in self.path.split("?", 1)[0].split("/") if part]
        if self.command == "GET" and parts == ["health"]:
            status = ESL().api("status").splitlines()[0]
            return HTTPStatus.OK, {"ok": True, "freeswitch": status}
        if self.command == "GET" and parts == ["devices"]:
            return HTTPStatus.OK, DEVICES
        if self.command == "GET" and parts == ["session"]:
            return HTTPStatus.OK, session()
        if len(parts) == 3 and parts[0] == "devices" and parts[2] == "connect":
            device_id = parts[1]
            if device_id not in DEVICES:
                return HTTPStatus.NOT_FOUND, {"error": "unknown device"}
            if self.command == "POST":
                adapter_request(device_id, "POST")
                try:
                    wait_for_member(device_id, True)
                except Error:
                    adapter_request(device_id, "DELETE")
                    raise
                enforce_capabilities(device_id)
                return HTTPStatus.OK, session()
            if self.command == "DELETE":
                existing = member_map().get(device_id)
                if existing is not None:
                    ESL().api(f"conference {ROOM} hup {existing}")
                adapter_request(device_id, "DELETE")
                wait_for_member(device_id, False)
                return HTTPStatus.OK, session()
        if self.command == "PUT" and len(parts) == 3 and parts[0] == "routes":
            source, sink = parts[1:]
            if source not in DEVICES or sink not in DEVICES:
                return HTTPStatus.NOT_FOUND, {"error": "unknown device"}
            enabled = self.body().get("enabled")
            if not isinstance(enabled, bool):
                return HTTPStatus.BAD_REQUEST, {"error": "enabled must be boolean"}
            set_route(source, sink, enabled)
            return HTTPStatus.OK, {"source": source, "sink": sink, "enabled": enabled}
        return HTTPStatus.NOT_FOUND, {"error": "not found"}

    def do_GET(self) -> None:
        self.handle_request()

    def do_POST(self) -> None:
        self.handle_request()

    def do_DELETE(self) -> None:
        self.handle_request()

    def do_PUT(self) -> None:
        self.handle_request()

    def handle_request(self) -> None:
        try:
            status, payload = self.dispatch()
        except (Error, json.JSONDecodeError) as exc:
            status, payload = HTTPStatus.CONFLICT, {"error": str(exc)}
        except Exception as exc:  # keep errors JSON and avoid leaking tracebacks to clients
            print(f"request failed: {type(exc).__name__}: {exc}", flush=True)
            status, payload = HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"}
        self.reply(status, payload)


if __name__ == "__main__":
    bind = os.environ.get("HTTP_BIND", "0.0.0.0")
    port = int(os.environ.get("HTTP_PORT", "8099"))
    ThreadingHTTPServer((bind, port), Handler).serve_forever()
