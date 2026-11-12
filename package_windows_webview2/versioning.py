"""Keep Windows numeric metadata separate from the displayed candidate version."""
import re


def windows_numeric_version(version):
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?: RC[1-9][0-9]{0,2})?", version)
    if match is None:
        raise ValueError("Expected a numeric release or bounded RC version")
    parts = tuple(map(int, match.groups()))
    if any(part > 65535 for part in parts):
        raise ValueError("Windows version components must fit unsigned 16-bit fields")
    return ".".join(map(str, (*parts, 0)))
