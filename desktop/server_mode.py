"""Explicit, project-local Local/Server selection and Server browser identity.

This file contains no network probe and no credential storage. A configured
origin is not evidence that a deployed service is authenticated or compatible.
"""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

from .isolation import AREA, FROZEN, NAME, assert_safe_leaf
from .profile_state import atomic_json
from .platform_files import owned


def _owned_directory(path: Path) -> Path:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError(f"Unsafe Desktop mode directory: {path}")
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    if not owned(path, private=True):
        raise ValueError(f"Desktop mode directory is not private and owned: {path}")
    return path


def shell_root(name: str) -> Path:
    if not NAME.fullmatch(name):
        raise ValueError("Invalid Desktop profile name")
    _owned_directory(AREA)
    _owned_directory(AREA / "shell")
    return _owned_directory(AREA / "shell" / name)


def server_root(identifier: str) -> dict[str, Path]:
    uuid.UUID(identifier)
    _owned_directory(AREA)
    _owned_directory(AREA / "server-profiles")
    root = _owned_directory(AREA / "server-profiles" / identifier)
    web = _owned_directory(root / "web")
    return {"root": root, "storage": _owned_directory(web / "storage"),
            "cache": _owned_directory(web / "cache"),
            "downloads": _owned_directory(root / "downloads")}


def server_environment(name: str) -> dict[str, str]:
    """Scope Qt's generic HOME/XDG files outside the Local dataset."""
    root = shell_root(name)
    xdg = _owned_directory(root / "xdg")
    folders = {
        "HOME": _owned_directory(root / "home"),
        "XDG_DATA_HOME": _owned_directory(xdg / "data"),
        "XDG_CONFIG_HOME": _owned_directory(xdg / "config"),
        "XDG_CACHE_HOME": _owned_directory(xdg / "cache"),
        "TMPDIR": _owned_directory(root / "tmp"),
    }
    result = {key: value for key, value in os.environ.items()
              if not key.startswith(("DLMS_", "QUIZAPP_"))
              and key not in {"QTWEBENGINE_DISABLE_SANDBOX", "QTWEBENGINE_CHROMIUM_FLAGS",
                              "QTWEBENGINE_PROCESS_PATH", "QT_PLUGIN_PATH",
                              "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONPATH", "PYTHONHOME"}}
    result.update({key: str(path) for key, path in folders.items()})
    result["TMP"] = result["TEMP"] = result["TMPDIR"]
    if os.name == "nt":
        from .windows_home import prepare
        prepare(folders['HOME'])
        result.update(USERPROFILE=str(folders["HOME"]), LOCALAPPDATA=str(folders["XDG_DATA_HOME"]),
                      APPDATA=str(folders["XDG_CONFIG_HOME"]))
    if FROZEN:
        result["DLMS_DESKTOP_DATA_ROOT"] = str(AREA)
        result["DLMS_DESKTOP_ROOT_KIND"] = os.environ.get("DLMS_DESKTOP_ROOT_KIND", "disposable")
    if __import__('sys').platform == 'darwin' and os.environ.get('DLMS_MACOS_DATA_ROOT') == str(AREA):
        result['DLMS_MACOS_DATA_ROOT'] = str(AREA)
        result['DLMS_DESKTOP_DATA_ROOT'] = str(AREA)
        result['DLMS_DESKTOP_ROOT_KIND'] = 'macos-candidate'
    return result


def canonical_endpoint(raw: str, *, private_http_opt_in: bool) -> str:
    """Accept one root-mounted exact origin; HTTP needs affirmative consent.

    Numeric private/loopback addresses are the initial HTTP form. DNS names
    remain eligible for HTTPS only; no DNS lookup is used as a trust test.
    """
    if not isinstance(raw, str) or not raw or raw != raw.strip() or len(raw) > 512:
        raise ValueError("Enter one complete server URL without surrounding space")
    if any(ord(char) < 33 or ord(char) == 127 for char in raw) or "%" in raw or "\\" in raw:
        raise ValueError("The server URL contains unsupported characters")
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The server URL has an invalid host or port") from exc
    if (scheme not in {"https", "http"} or not host or parsed.username is not None
            or parsed.password is not None or "@" in parsed.netloc
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("Use a root-mounted HTTPS or explicitly allowed HTTP origin, without credentials, path, query or fragment")
    if host.endswith(".") or "_" in host:
        raise ValueError("Use a canonical host without a trailing dot or underscore")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or ".." in host:
            raise ValueError("Use a DNS hostname or numeric IP address")
        labels = host.split(".")
        if any(not label or label.startswith("-") or label.endswith("-") for label in labels):
            raise ValueError("The server hostname is invalid")
        host = host.lower()
    else:
        if address.is_unspecified or address.is_multicast:
            raise ValueError("The server address cannot be unspecified or multicast")
        host = address.compressed
    if scheme == "http":
        if not private_http_opt_in:
            raise ValueError("Private HTTP requires explicit consent for this exact origin")
        permitted = tuple(ipaddress.ip_network(block) for block in
                          ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "fc00::/7", "::1/128"))
        if address is None or not any(address in block for block in permitted if block.version == address.version):
            raise ValueError("This private-HTTP option requires an RFC1918/ULA address (or synthetic loopback)")
    elif private_http_opt_in:
        raise ValueError("Private-HTTP consent cannot be attached to an HTTPS endpoint")
    if port is None:
        port = 443 if scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise ValueError("The server port is invalid")
    host_part = f"[{host}]" if ":" in host else host
    return f"{scheme}://{host_part}:{port}"


def default_config(name: str) -> dict:
    return {"version": 1, "profile": name, "mode": "local", "server": None}


def _validate_config(name: str, value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"version", "profile", "mode", "server"}
            or value["version"] != 1 or value["profile"] != name
            or value["mode"] not in {"local", "server"}):
        raise ValueError("Desktop mode configuration fields are invalid")
    server = value["server"]
    if server is not None:
        if (not isinstance(server, dict)
                or set(server) != {"id", "label", "origin", "private_http"}
                or not isinstance(server["label"], str) or not 1 <= len(server["label"]) <= 60
                or not isinstance(server["private_http"], bool)):
            raise ValueError("Server configuration fields are invalid")
        uuid.UUID(server["id"])
        if canonical_endpoint(server["origin"], private_http_opt_in=server["private_http"]) != server["origin"]:
            raise ValueError("Server origin is not canonical")
    elif value["mode"] == "server":
        raise ValueError("Server mode has no configured endpoint")
    return value


def read_config(name: str) -> dict:
    path = shell_root(name) / "mode.json"
    assert_safe_leaf(path)
    if not path.exists():
        return default_config(name)
    if path.stat().st_size > 4096:
        raise ValueError("Desktop mode configuration is oversized")
    try:
        return _validate_config(name, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, TypeError, KeyError, ValueError) as exc:
        raise ValueError("Desktop mode configuration needs inspection; no mode fallback was selected") from exc


def write_config(name: str, config: dict) -> None:
    path = shell_root(name) / "mode.json"
    _validate_config(name, config)
    atomic_json(path, config)


def configured_server(config: dict, raw: str, label: str, *, private_http_opt_in: bool) -> dict:
    origin = canonical_endpoint(raw, private_http_opt_in=private_http_opt_in)
    label = label.strip()
    if not label or len(label) > 60 or any(ord(char) < 32 for char in label):
        raise ValueError("Enter a short server label")
    prior = config.get("server")
    identifier = prior["id"] if prior and prior["origin"] == origin else str(uuid.uuid4())
    return {"id": identifier, "label": label, "origin": origin,
            "private_http": private_http_opt_in}
