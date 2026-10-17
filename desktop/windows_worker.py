"""Source worker bootstrap; no Qt/application import before the owner gate."""
import sys
from .windows_processes import bootstrap

bootstrap()
role = sys.argv.pop(1)
if role not in {"backend", "adopt", "maintenance", "removal"}:
    raise ValueError("Unknown Desktop worker")
module = __import__("desktop." + role, fromlist=["main"])
raise SystemExit(module.main())
