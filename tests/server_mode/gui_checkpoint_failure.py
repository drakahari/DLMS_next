"""A failed independent browser checkpoint must not publish Server mode."""
from __future__ import annotations

import argparse
import json

from desktop.server_mode import configured_server, read_config, write_config
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("fail", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    try:
        manifest = dict(q.window.manifest)
        if args.phase == "fail":
            config = dict(q.window.mode_config,
                          server=configured_server(q.window.mode_config, "http://127.0.0.2:65530/",
                                                   "Absent synthetic Server", private_http_opt_in=True))
            write_config(args.profile, config)
            q.window.mode_config = config
            q.window._update_mode_toolbar()
            original_quiesce = q.window._quiesce_browser
            def quiesce_with_reentry_probe():
                assert q.window._mode_switch_busy
                assert not q.window.server_mode_action.isEnabled()
                assert not q.window.configure_server_action.isEnabled()
                assert not q.window.switch_to_server(), "Nested switch started another transition"
                return original_quiesce()
            q.window._quiesce_browser = quiesce_with_reentry_probe
            q.window._checkpoint_browser = lambda: False
            assert not q.window.switch_to_server()
            assert q.window.mode == "local" and q.window._settings_transition_refused
            assert read_config(args.profile)["mode"] == "local"
            result = {"checkpoint_failure_blocked_switch": True, "origin": manifest["port"]}
        else:
            assert read_config(args.profile)["mode"] == "local"
            previous = json.loads((q.paths["root"] / "mode-checkpoint-fail.json").read_text())
            assert q.window.manifest["port"] == previous["origin"]
            assert q.window.backend.poll() is None
            result = {"separate_process_reopened_same_local_origin": True, "origin": manifest["port"]}
        (q.paths["root"] / f"mode-checkpoint-{args.phase}.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        return 0
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
