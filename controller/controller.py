#!/usr/bin/env python3
"""Stateless, fail-closed control plane for one FreeSWITCH conference."""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit


ROOM = os.environ.get("INTERCOM_ROOM", "intercom")
ESL_HOST = os.environ.get("FREESWITCH_ESL_HOST", "freeswitch")
ESL_PORT = int(os.environ.get("FREESWITCH_ESL_PORT", "8021"))
ESL_PASSWORD = os.environ["INTERCOM_ESL_PASSWORD"]
DEVICE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
operations_lock = threading.Lock()
ADAPTER_TIMEOUT = float(os.environ.get("INTERCOM_ADAPTER_TIMEOUT", "20"))


class Error(RuntimeError):
    pass


class ValidationError(Error):
    pass


@dataclass(frozen=True)
class GainSettings:
    """Optional per-member audio settings, owned and persisted by the caller."""

    input_level: int | None = None
    output_level: int | None = None
    agc_target: int | None = None


@dataclass(frozen=True)
class Endpoint:
    """Application-supplied adapter details for one connection operation."""

    device_id: str
    adapter_url: str | None
    can_transmit: bool
    can_receive: bool
    gain: GainSettings = field(default_factory=GainSettings)


def gain_from_body(body: Any) -> GainSettings:
    if body is None:
        return GainSettings()
    if not isinstance(body, dict):
        raise ValidationError("gain must be an object")

    def level(name: str) -> int | None:
        value = body.get(name)
        if value is None:
            return None
        if type(value) is not int or not -4 <= value <= 4:
            raise ValidationError(f"gain.{name} must be an integer from -4 through 4")
        return value

    agc_target = body.get("agc_target")
    if agc_target is not None and (type(agc_target) is not int or not 1 <= agc_target <= 1800):
        raise ValidationError("gain.agc_target must be an integer from 1 through 1800")
    return GainSettings(level("input_level"), level("output_level"), agc_target)


def endpoint_from_body(body: Any) -> Endpoint:
    if not isinstance(body, dict):
        raise ValidationError("request body must be an object")
    device_id = body.get("device_id")
    adapter_url = body.get("adapter_url")
    can_transmit = body.get("can_transmit")
    can_receive = body.get("can_receive")
    if not isinstance(device_id, str) or not DEVICE_ID_RE.fullmatch(device_id):
        raise ValidationError("device_id must contain lowercase letters, digits, and hyphens")
    if adapter_url is not None:
        if not isinstance(adapter_url, str):
            raise ValidationError("adapter_url must be a string or null")
        parsed = urlsplit(adapter_url)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValidationError("adapter_url must be an HTTP base URL without credentials, query, or path")
        adapter_url = adapter_url.rstrip("/")
    if not isinstance(can_transmit, bool) or not isinstance(can_receive, bool):
        raise ValidationError("can_transmit and can_receive must be booleans")
    return Endpoint(device_id, adapter_url, can_transmit, can_receive, gain_from_body(body.get("gain")))


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


def adapter_request(adapter_url: str, method: str) -> dict[str, Any]:
    request = urllib.request.Request(adapter_url + "/connect", method=method)
    try:
        with urllib.request.urlopen(request, timeout=ADAPTER_TIMEOUT) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = exc.reason if hasattr(exc, "reason") else exc
        raise Error(f"adapter failed: {reason}") from exc


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
            "input_gain": member.get("input-volume"),
            "output_gain": member.get("output-volume"),
        })
    return {"room": ROOM, "active": bool(conference), "members": normalized}


def member_for_device(device_id: str) -> dict[str, Any] | None:
    matches = [member for member in session()["members"] if member["device_id"] == device_id]
    if len(matches) > 1:
        raise Error(f"multiple conference members identify as {device_id}")
    return matches[0] if matches else None


def wait_for_member(device_id: str, present: bool, timeout: float = 8) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        member = member_for_device(device_id)
        if (member is not None) is present:
            return member
        time.sleep(0.2)
    raise Error(f"timed out waiting for {device_id} to {'join' if present else 'leave'}")


def enforce_capabilities(member_id: int, endpoint: Endpoint) -> None:
    ESL().api(f"conference {ROOM} {'unmute' if endpoint.can_transmit else 'mute'} {member_id} quiet")
    ESL().api(f"conference {ROOM} {'undeaf' if endpoint.can_receive else 'deaf'} {member_id}")

    # Deny all new cross-member paths until the application enables each one.
    for other in session()["members"]:
        other_id = other["member_id"]
        if other_id == member_id:
            continue
        ESL().api(f"conference {ROOM} relate {member_id} {other_id} nospeak")
        ESL().api(f"conference {ROOM} relate {other_id} {member_id} nospeak")


def apply_gain(member_id: int, gain: GainSettings) -> None:
    if gain.input_level is not None:
        ESL().api(f"conference {ROOM} volume_in {member_id} {gain.input_level}")
    if gain.output_level is not None:
        ESL().api(f"conference {ROOM} volume_out {member_id} {gain.output_level}")
    if gain.agc_target is not None:
        ESL().api(f"conference {ROOM} agc {member_id} {gain.agc_target}")


def connect(endpoint: Endpoint) -> dict[str, Any]:
    """Connect or re-authorize an endpoint without retaining its definition."""
    with operations_lock:
        member = member_for_device(endpoint.device_id)
        if member is None:
            if endpoint.adapter_url is None:
                raise Error("adapter_url is required to connect a device that is not already in the conference")
            adapter_request(endpoint.adapter_url, "POST")
            try:
                member = wait_for_member(endpoint.device_id, True)
            except Error:
                adapter_request(endpoint.adapter_url, "DELETE")
                raise
        assert member is not None
        enforce_capabilities(member["member_id"], endpoint)
        apply_gain(member["member_id"], endpoint.gain)
        return session()


def disconnect(endpoint: Endpoint) -> dict[str, Any]:
    """Disconnect an endpoint using application-supplied adapter details."""
    with operations_lock:
        member = member_for_device(endpoint.device_id)
        if member is not None:
            ESL().api(f"conference {ROOM} hup {member['member_id']}")
        if endpoint.adapter_url is not None:
            adapter_request(endpoint.adapter_url, "DELETE")
        if member is not None:
            wait_for_member(endpoint.device_id, False)
        return session()


def set_route(source: str, sink: str, enabled: bool) -> None:
    if source == sink:
        raise Error("source and sink must be different devices")
    with operations_lock:
        source_member = member_for_device(source)
        sink_member = member_for_device(sink)
        if source_member is None or sink_member is None:
            raise Error("both route endpoints must be connected")
        action = "clear" if enabled else "nospeak"
        ESL().api(f"conference {ROOM} relate {source_member['member_id']} {sink_member['member_id']} {action}")


class Handler(BaseHTTPRequestHandler):
    server_version = "intercom-controller/0.3"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValidationError("invalid Content-Length") from exc
        if length < 0 or length > 65536:
            raise ValidationError("request body must be at most 65536 bytes")
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValidationError("request body must be valid JSON") from exc

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
        if self.command == "GET" and parts == ["session"]:
            return HTTPStatus.OK, session()
        if self.command == "POST" and parts == ["connections"]:
            return HTTPStatus.OK, connect(endpoint_from_body(self.body()))
        if self.command == "DELETE" and parts == ["connections"]:
            return HTTPStatus.OK, disconnect(endpoint_from_body(self.body()))
        if self.command == "PUT" and len(parts) == 3 and parts[0] == "routes":
            source, sink = parts[1:]
            enabled = self.body().get("enabled")
            if not isinstance(enabled, bool):
                raise ValidationError("enabled must be boolean")
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
        except ValidationError as exc:
            status, payload = HTTPStatus.BAD_REQUEST, {"error": str(exc)}
        except Error as exc:
            status, payload = HTTPStatus.CONFLICT, {"error": str(exc)}
        except Exception as exc:  # keep errors JSON and avoid leaking tracebacks to clients
            print(f"request failed: {type(exc).__name__}: {exc}", flush=True)
            status, payload = HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"}
        self.reply(status, payload)


if __name__ == "__main__":
    bind = os.environ.get("HTTP_BIND", "0.0.0.0")
    port = int(os.environ.get("HTTP_PORT", "8099"))
    ThreadingHTTPServer((bind, port), Handler).serve_forever()
