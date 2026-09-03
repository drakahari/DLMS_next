"""Small standard-library WebDriver BiDi client for the opt-in Firefox tests."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time


_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class BidiError(RuntimeError):
    """Raised when Firefox rejects or cannot complete a BiDi command."""


class FirefoxBidi:
    def __init__(self, sock: socket.socket, initial_bytes: bytes = b""):
        self._socket = sock
        self._buffer = initial_bytes
        self._next_id = 1
        self.context = ""

    @classmethod
    def connect(cls, host: str, port: int, timeout: float = 5.0) -> "FirefoxBidi":
        sock = socket.create_connection((host, port), timeout=timeout)
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (
                "GET /session HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)

            response = bytearray()
            while b"\r\n\r\n" not in response:
                chunk = sock.recv(4096)
                if not chunk:
                    raise BidiError("Firefox closed the WebSocket handshake")
                response.extend(chunk)
                if len(response) > 65536:
                    raise BidiError("Firefox returned an oversized WebSocket handshake")

            headers, remainder = bytes(response).split(b"\r\n\r\n", 1)
            lines = headers.decode("latin-1").split("\r\n")
            if not lines or " 101 " not in f" {lines[0]} ":
                status = lines[0] if lines else "empty response"
                raise BidiError(f"Firefox rejected the WebSocket handshake: {status}")
            values = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    values[name.strip().lower()] = value.strip()
            expected = base64.b64encode(
                hashlib.sha1((key + _WEBSOCKET_GUID).encode("ascii")).digest()
            ).decode("ascii")
            if values.get("sec-websocket-accept") != expected:
                raise BidiError("Firefox returned an invalid WebSocket acknowledgement")
            return cls(sock, remainder)
        except Exception:
            sock.close()
            raise

    def start_session(self) -> None:
        self.command("session.new", {"capabilities": {}})
        tree = self.command("browsingContext.getTree", {})
        contexts = tree.get("contexts") or []
        if not contexts:
            created = self.command("browsingContext.create", {"type": "tab"})
            self.context = created["context"]
        else:
            self.context = contexts[0]["context"]

    def close(self) -> None:
        try:
            self.command("session.end", {}, timeout=2.0)
        except Exception:
            pass
        try:
            self._socket.close()
        except OSError:
            pass

    def command(self, method: str, params: dict, timeout: float = 8.0) -> dict:
        command_id = self._next_id
        self._next_id += 1
        self._send_json({"id": command_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._socket.settimeout(max(0.05, deadline - time.monotonic()))
            message = json.loads(self._receive_text())
            if message.get("id") != command_id:
                continue
            if message.get("type") == "error" or "error" in message:
                detail = message.get("message") or message.get("error") or message
                raise BidiError(f"{method} failed: {detail}")
            return message.get("result") or {}
        raise TimeoutError(f"Timed out waiting for Firefox command {method}")

    def navigate(self, url: str) -> None:
        self.command(
            "browsingContext.navigate",
            {"context": self.context, "url": url, "wait": "complete"},
            timeout=12.0,
        )

    def evaluate(self, expression: str):
        result = self.command(
            "script.evaluate",
            {
                "expression": expression,
                "target": {"context": self.context},
                "awaitPromise": True,
                "userActivation": True,
            },
        )
        if result.get("type") == "exception":
            details = result.get("exceptionDetails") or {}
            raise BidiError(details.get("text") or f"Browser expression failed: {expression}")
        return _decode_remote_value(result.get("result") or {})

    def wait_for(self, expression: str, timeout: float = 6.0):
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                value = self.evaluate(expression)
                if value:
                    return value
            except (BidiError, OSError, TimeoutError) as exc:
                last_error = exc
            time.sleep(0.05)
        suffix = f" Last error: {last_error}" if last_error else ""
        raise TimeoutError(f"Browser condition did not become true: {expression}.{suffix}")

    def click(self, selector: str) -> None:
        encoded = json.dumps(selector)
        coordinates = json.loads(self.evaluate(
            f"(() => {{ const element = document.querySelector({encoded}); "
            "if (!element) throw new Error('Element not found'); "
            "element.scrollIntoView({block: 'center', inline: 'center'}); "
            "const rect = element.getBoundingClientRect(); "
            "return JSON.stringify({x: rect.left + rect.width / 2, "
            "y: rect.top + rect.height / 2}); })()"
        ))
        self.command(
            "input.performActions",
            {
                "context": self.context,
                "actions": [{
                    "type": "pointer",
                    "id": "mouse",
                    "parameters": {"pointerType": "mouse"},
                    "actions": [
                        {
                            "type": "pointerMove",
                            "x": round(coordinates["x"]),
                            "y": round(coordinates["y"]),
                            "duration": 0,
                            "origin": "viewport",
                        },
                        {"type": "pointerDown", "button": 0},
                        {"type": "pointerUp", "button": 0},
                    ],
                }],
            },
        )

    def press_key(self, value: str) -> None:
        self.command(
            "input.performActions",
            {
                "context": self.context,
                "actions": [{
                    "type": "key",
                    "id": "keyboard",
                    "actions": [
                        {"type": "keyDown", "value": value},
                        {"type": "keyUp", "value": value},
                    ],
                }],
            },
        )
        self.command("input.releaseActions", {"context": self.context})

    def activate(self) -> None:
        self.command("browsingContext.activate", {"context": self.context})

    def set_viewport(self, width: int, height: int) -> None:
        self.command(
            "browsingContext.setViewport",
            {
                "context": self.context,
                "viewport": {"width": width, "height": height},
                "devicePixelRatio": 1,
            },
        )

    def _send_json(self, value: dict) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(bytes(header) + masked)

    def _receive_text(self) -> str:
        fragments = bytearray()
        while True:
            first, second = self._read_exact(2)
            opcode = first & 0x0F
            finished = bool(first & 0x80)
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length)
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise BidiError("Firefox closed the WebSocket connection")
            if opcode == 0x9:
                self._send_control_frame(0xA, payload)
                continue
            if opcode not in {0x0, 0x1}:
                continue
            fragments.extend(payload)
            if finished:
                return fragments.decode("utf-8")

    def _send_control_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)

    def _read_exact(self, length: int) -> bytes:
        while len(self._buffer) < length:
            chunk = self._socket.recv(max(4096, length - len(self._buffer)))
            if not chunk:
                raise BidiError("Firefox closed the WebSocket connection")
            self._buffer += chunk
        result = self._buffer[:length]
        self._buffer = self._buffer[length:]
        return result


def _decode_remote_value(value):
    value_type = value.get("type")
    if value_type in {"null", "undefined"}:
        return None
    if value_type in {"string", "boolean", "number", "bigint"}:
        return value.get("value")
    if value_type in {"array", "set"}:
        return [_decode_remote_value(item) for item in value.get("value") or []]
    if value_type in {"object", "map"}:
        return {
            key: _decode_remote_value(item)
            for key, item in value.get("value") or []
        }
    return value.get("value")
