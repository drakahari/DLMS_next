"""Packaging shares the Windows launch compatibility policy, not security currency."""
from desktop.webview2_runtime import MIN_RUNTIME_VERSION, compatible_runtime

MINIMUM_VERSION = tuple(map(int, MIN_RUNTIME_VERSION.split(".")))
supported_runtime = compatible_runtime
