"""Pure runtime-option and browser-selection helpers for DLMS."""

import os
import re
import sys


DLMS_SERVER_HOST = "127.0.0.1"
DLMS_SERVER_PORT = 9001


def _dlms_validate_server_host(value):
    """Validate an explicit Flask bind host without resolving it over DNS."""
    host = str(value or "").strip()
    if (
        not host
        or len(host) > 255
        or host.startswith("-")
        or re.search(r"\s", host)
        or not re.fullmatch(r"[A-Za-z0-9_.:-]+", host)
    ):
        raise ValueError(
            "Invalid --host value. Use an IP address or hostname, such as "
            "127.0.0.1 or 0.0.0.0."
        )
    return host


def _dlms_is_loopback_host(host):
    """Return True only for host values that unambiguously bind to loopback."""
    host = str(host or "").strip().lower()
    if host == "localhost":
        return True
    try:
        import ipaddress
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _dlms_parse_startup_options(argv=None, environ=None, desktop_available=None):
    """Resolve bind and browser options while keeping those choices independent."""
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    host = DLMS_SERVER_HOST
    force_browser = False
    disable_browser = False

    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--browser":
            force_browser = True
        elif arg == "--no-browser":
            disable_browser = True
        elif arg == "--host":
            index += 1
            if index >= len(args):
                raise ValueError("--host requires an IP address or hostname.")
            host = _dlms_validate_server_host(args[index])
        elif arg.startswith("--host="):
            host = _dlms_validate_server_host(arg.split("=", 1)[1])
        index += 1

    env_no_browser = str(env.get("DLMS_NO_BROWSER") or "").strip().lower()
    disable_browser = disable_browser or env_no_browser in {"1", "true", "yes", "on"}
    if desktop_available is None:
        desktop_available = _dlms_desktop_browser_available()
    open_browser = not disable_browser and (force_browser or bool(desktop_available))

    return {
        "host": host,
        "force_browser": force_browser,
        "disable_browser": disable_browser,
        "open_browser": open_browser,
    }


def _dlms_detect_lan_ip():
    """Best-effort LAN address discovery for the console access summary."""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # UDP connect does not transmit application data; it asks the OS
            # which local interface it would use for an external destination.
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
        finally:
            sock.close()
        if candidate and not candidate.startswith("127."):
            return candidate
    except Exception:
        pass
    try:
        import socket
        candidate = socket.gethostbyname(socket.gethostname())
        if candidate and not candidate.startswith("127."):
            return candidate
    except Exception:
        pass
    return None


def _dlms_desktop_browser_available():
    """Return True when this looks like an interactive desktop session."""
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if sys.platform == "win32" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _dlms_url_host(host):
    """Format an IPv6 bind address for use in a displayed HTTP URL."""
    host = str(host or "")
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _dlms_browser_host(bind_host):
    """Choose an address the local browser can use for the selected bind."""
    if bind_host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return bind_host
