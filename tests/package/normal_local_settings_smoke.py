"""Normal frozen launch/reopen and Local Settings HTTP boundary; no GUI input."""
from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def descendants(pid: int) -> list[int]:
    found, pending = [], [pid]
    while pending:
        current = pending.pop()
        proc = Path("/proc") / str(current)
        if not proc.exists():
            continue
        found.append(current)
        try:
            pending.extend(int(item) for item in (proc / "task" / str(current) / "children").read_text().split())
        except OSError:
            pass
    return found


def backend_nonce(pid: int) -> tuple[int, str] | None:
    for child in descendants(pid):
        if child == pid:
            continue
        try:
            cmdline = (Path("/proc") / str(child) / "cmdline").read_bytes()
            if b"--desktop-worker\x00backend" not in cmdline:
                continue
            raw = (Path("/proc") / str(child) / "environ").read_bytes()
            values = dict(item.split(b"=", 1) for item in raw.split(b"\0") if b"=" in item)
            value = values.get(b"DLMS_DESKTOP_NONCE")
            if value:
                return child, value.decode("ascii")
        except (OSError, ValueError):
            pass
    return None


def starttime(pid: int) -> str | None:
    try:
        return (Path("/proc") / str(pid) / "stat").read_text().rsplit(") ", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def stop_exact_owned(process: subprocess.Popen, observed: dict[int, str | None]) -> list[int]:
    """Clean only descendants observed under this launcher and with the same PID birth."""
    observed.update({pid: starttime(pid) for pid in descendants(process.pid)})
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        live = [pid for pid, born in observed.items() if born and starttime(pid) == born]
        if not live:
            break
        for pid in live:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        time.sleep(0.3)
    return [pid for pid, born in observed.items() if born and starttime(pid) == born]


def request(port: int, nonce: str, method: str, path: str, *, summary_nonce=True,
            extra_headers=None, body=None, include_headers=False):
    headers = {"Host": f"127.0.0.1:{port}", "X-DLMS-Desktop-Token": nonce}
    if summary_nonce:
        headers["X-DLMS-Desktop-Nonce"] = nonce
    headers.update(extra_headers or {})
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, response.read()
        return (*result, response.getheaders()) if include_headers else result
    finally:
        connection.close()


def run(args, index: int) -> dict:
    env_root = args.output / "environment"
    env = {"PATH": "/nonexistent", "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen"}
    for key, relative in (("HOME", "home"), ("XDG_DATA_HOME", "xdg/data"),
                          ("XDG_CONFIG_HOME", "xdg/config"), ("XDG_CACHE_HOME", "xdg/cache"),
                          ("TMPDIR", "tmp")):
        target = env_root / relative
        target.mkdir(parents=True, exist_ok=True)
        env[key] = str(target)
    runtime = env_root / "xdg/runtime"
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime.chmod(0o700)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    log_path = args.output / f"normal-{index}.log"
    started = time.monotonic()
    with log_path.open("w") as log:
        process = subprocess.Popen([str(args.exe), "--profile", args.profile,
                                    "--data-root", str(args.data_root)], cwd=args.cwd,
                                   env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        observed: dict[int, str | None] = {process.pid: starttime(process.pid)}
        try:
            manifest_path = args.data_root / "profiles" / args.profile / "desktop-profile.json"
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Normal package exited before readiness: {process.returncode}")
                observed.update({pid: starttime(pid) for pid in descendants(process.pid)})
                owner = backend_nonce(process.pid)
                if owner and manifest_path.exists():
                    manifest = json.loads(manifest_path.read_text())
                    try:
                        if request(manifest["port"], owner[1], "GET", "/_desktop/ready")[0] == 200:
                            break
                    except OSError:
                        pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Normal package did not reach authenticated readiness")
            ready = round(time.monotonic() - started, 3)
            port, nonce = manifest["port"], owner[1]
            pages = {}
            for path, marker in (("/settings/backup", b'data-dlms-desktop-settings="backup"'),
                                 ("/settings/reset-remove", b'data-dlms-desktop-settings="reset-remove"')):
                status, body, headers = request(port, nonce, "GET", path, include_headers=True)
                assert status == 200 and marker in body
                policy = dict((key.lower(), value) for key, value in headers).get("permissions-policy")
                assert policy == "camera=(), geolocation=(), microphone=()", policy
                pages[path] = {"status": status, "expected_marker": True, "bytes": len(body),
                               "permissions_policy": policy}
            for path in ("/", "/library", "/history", "/quiz-composer/study-mistakes"):
                status, body, headers = request(port, nonce, "GET", path, include_headers=True)
                policy = dict((key.lower(), value) for key, value in headers).get("permissions-policy")
                assert status == 200 and policy == "camera=(), geolocation=(), microphone=()", (path, status, policy)
                pages[path] = {"status": status, "bytes": len(body), "permissions_policy": policy}
            summary_status, summary_body = request(port, nonce, "GET", "/_desktop/settings/summary")
            assert summary_status == 200
            summary = json.loads(summary_body)
            assert "storage" in summary and "recent_backups" in summary
            config_status, config_body = request(port, nonce, "GET", "/config/portal.json")
            assert config_status == 200
            config = json.loads(config_body)
            theme_ids = [option["id"] for group in config["theme_groups"] for option in group["options"]]
            assert len(theme_ids) == len(set(theme_ids)) == 26
            if index == 1:
                csrf_status, csrf_body, csrf_headers = request(
                    port, nonce, "GET", "/api/csrf-token",
                    extra_headers={"X-DLMS-CSRF-Refresh": "1", "Origin": f"http://127.0.0.1:{port}"},
                    include_headers=True)
                assert csrf_status == 200
                cookies = "; ".join(value.split(";", 1)[0] for key, value in csrf_headers
                                    if key.lower() == "set-cookie")
                assert cookies
                theme_body = json.dumps({"theme": "omarchy-lumon"}).encode()
                theme_status, theme_result = request(port, nonce, "POST", "/api/theme",
                    extra_headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}",
                                   "Cookie": cookies, "X-CSRFToken": json.loads(csrf_body)["csrf_token"]},
                    body=theme_body)
                assert theme_status == 200 and json.loads(theme_result) == {"ok": True, "theme": "omarchy-lumon"}
            else:
                assert config["theme"] == "omarchy-lumon"
            icon_status, icon_body = request(port, nonce, "GET", "/static/icons.svg")
            assert icon_status == 200
            assert icon_body == (args.exe.parent / "_internal/static/icons.svg").read_bytes()
            missing_nonce, _ = request(port, nonce, "GET", "/_desktop/settings/summary", summary_nonce=False)
            assert missing_nonce == 403
            wrong_token, _ = request(port, "wrong", "GET", "/settings/backup")
            assert wrong_token == 403
            owned = descendants(process.pid)
            observed.update({pid: starttime(pid) for pid in owned})
            mapped = []
            for child in owned:
                try:
                    for line in (Path("/proc") / str(child) / "maps").read_text().splitlines():
                        parts = line.split(None, 5)
                        if len(parts) == 6 and parts[5].startswith("/"):
                            mapped.append(parts[5])
                except OSError:
                    pass
            project = Path(__file__).resolve().parents[2]
            forbidden = [path for path in mapped
                         if Path(path).is_relative_to(project)
                         and not Path(path).is_relative_to(args.exe.parent)
                         and not Path(path).is_relative_to(args.data_root)]
            assert not forbidden, forbidden[:4]
            svg_mapped = sorted(path for path in set(mapped)
                                if path.endswith("/PySide6/QtSvg.abi3.so") or path.endswith("/libQt6Svg.so.6"))
            assert len(svg_mapped) >= 2, svg_mapped
            shutdown_status, _ = request(port, nonce, "POST", "/api/shutdown")
            assert shutdown_status == 200
            code = process.wait(timeout=25)
            assert code == 0
            deadline = time.monotonic() + 5
            residual = [pid for pid in owned if Path("/proc", str(pid)).exists()]
            while residual and time.monotonic() < deadline:
                time.sleep(0.1)
                residual = [pid for pid in residual if Path("/proc", str(pid)).exists()]
            assert not residual, residual
            return {"run": index, "profile": args.profile, "uuid": manifest["uuid"],
                    "port": port, "backend_pid": owner[0], "authenticated_ready_seconds": ready,
                    "pages": pages, "summary_status": summary_status,
                    "theme_id_count": len(theme_ids), "theme_ids": theme_ids,
                    "configured_theme": config["theme"], "icons_svg_bytes": len(icon_body),
                    "svg_runtime_mapped": svg_mapped,
                    "summary_missing_nonce_status": missing_nonce, "wrong_token_status": wrong_token,
                    "owned_process_count": len(owned), "mapped_file_count": len(set(mapped)),
                    "forbidden_mapped_paths": forbidden, "shutdown_status": shutdown_status,
                    "exit_code": code, "residual_owned_pids": residual, "log": str(log_path)}
        except Exception as exc:
            (args.output / f"run-{index}-failure.json").write_text(json.dumps({
                "error": f"{type(exc).__name__}: {exc}", "launcher_pid": process.pid,
                "observed_descendants": descendants(process.pid), "log": str(log_path)}, indent=2) + "\n")
            raise
        finally:
            residual = stop_exact_owned(process, observed)
            if residual:
                (args.output / f"run-{index}-cleanup-failure.json").write_text(json.dumps({
                    "exact_owned_residual_pids": residual, "launcher_pid": process.pid}, indent=2) + "\n")
                raise RuntimeError(f"Exact owned processes survived cleanup: {residual}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.exe, args.data_root, args.cwd, args.output = (
        args.exe.resolve(), args.data_root.resolve(), args.cwd.resolve(), args.output.resolve())
    if not args.exe.is_file() or not args.cwd.is_dir() or not args.data_root.is_dir():
        raise ValueError("The package, unrelated cwd and disposable data root must exist")
    args.output.mkdir(parents=True, exist_ok=True)
    first, second = run(args, 1), run(args, 2)
    assert (first["uuid"], first["port"]) == (second["uuid"], second["port"])
    result = {"normal_executable": str(args.exe), "launches": [first, second],
              "same_origin": True, "pass": True,
              "scope": "Authenticated backend, packaged theme/config and SVG resources, served Settings documents; no native-button activation"}
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": True, "same_origin": True,
                      "ready_seconds": [first["authenticated_ready_seconds"],
                                        second["authenticated_ready_seconds"]],
                      "owned_processes": [first["owned_process_count"], second["owned_process_count"]]}, indent=2))


if __name__ == "__main__":
    main()
