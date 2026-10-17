"""Normal, non-instrumented PyInstaller entry."""
from desktop.package_entry import main
import sys


if __name__ == "__main__":
    try:
        raise SystemExit(main(instrumented=False))
    except (ValueError, OSError) as exc:
        print(f"DLMS Desktop: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
