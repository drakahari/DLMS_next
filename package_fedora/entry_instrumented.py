"""Separately labeled synthetic crash-test PyInstaller entry; never ship it."""
from desktop.package_entry import main
import sys


if __name__ == "__main__":
    try:
        raise SystemExit(main(instrumented=True))
    except ValueError as exc:
        print(f"DLMS Desktop instrumented: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
