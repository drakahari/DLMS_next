"""Task-owned loopback WSGI process; only the shell may start it."""
from __future__ import annotations

import os
import errno
import json
import io
import socket
import signal
import subprocess
import sys
import threading
import time

from .isolation import PROJECT, assert_safe_leaf, profile_paths
from .frozen_runtime import source_import_path
from .processes import reap_owned_group


class TrackedIterable:
    """Own a WSGI result and release its outer gate on every close path."""

    def __init__(self, result, finish, *, before_iteration=None, after_close=None):
        self.result = result
        self.finish = finish
        self.before_iteration = before_iteration
        self.after_close = after_close
        self.closed = False

    def __iter__(self):
        try:
            if self.before_iteration:
                self.before_iteration()
            yield from self.result
        finally:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if hasattr(self.result, "close"):
                self.result.close()
        finally:
            try:
                if self.after_close:
                    self.after_close()
            finally:
                self.finish()


def acquire_writer_lock(path):
    """Hold a backend-side lock before app import, surviving launcher death."""
    from .platform_files import writer_path
    path = writer_path(path)
    assert_safe_leaf(path)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    handle = os.fdopen(fd, "r+b", buffering=0)
    deadline = time.monotonic() + 8
    while True:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN} or time.monotonic() >= deadline:
                handle.close()
                raise RuntimeError("Disposable profile is still owned by a backend; reopen after it stops") from exc
            time.sleep(0.1)


def main() -> int:
    if sys.platform == "darwin":
        from .macos_processes import seal_private_descriptors
        seal_private_descriptors()
    name = os.environ.get("DLMS_DESKTOP_PROFILE_NAME", "")
    paths = profile_paths(name, create=False)
    from .removal import read_tombstone
    if read_tombstone(name) is not None:
        raise RuntimeError("An intentional profile removal is recorded; backend startup is refused")
    if (os.environ.get("DLMS_DESKTOP_PROFILE") != str(paths["root"])
            or os.environ.get("QUIZAPP_DATA_DIR") != str(paths["backend"])
            or os.environ.get("HOME") != str(paths["home"])):
        raise RuntimeError("Desktop backend isolation variables are missing or inconsistent")
    nonce = os.environ.get("DLMS_DESKTOP_NONCE", "")
    if len(nonce) < 32:
        raise RuntimeError("Desktop backend readiness nonce is missing")
    parent = int(os.environ["DLMS_DESKTOP_PARENT_PID"])
    parent_group = int(os.environ["DLMS_DESKTOP_PARENT_GROUP"])
    parent_pipe = int(os.environ["DLMS_DESKTOP_PARENT_PIPE"])
    socket_fd = int(os.environ["DLMS_DESKTOP_SOCKET_FD"])
    port = int(os.environ["DLMS_DESKTOP_PORT"])
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid desktop loopback port")
    bound = socket.socket(fileno=socket_fd)
    if bound.family != socket.AF_INET or bound.getsockname() != ("127.0.0.1", port):
        raise RuntimeError("Inherited socket is not the reserved Desktop loopback endpoint")

    def parent_watchdog():
        try:
            os.read(parent_pipe, 1)  # EOF only when the owning launcher exits.
        finally:
            os.close(parent_pipe)
        if sys.platform == "darwin":
            from .macos_processes import parent_lost
            parent_lost(parent_group=parent_group if os.getppid() != parent else None)
        if os.name == "nt":
            os._exit(70)
        if os.getppid() != parent:
            reap_owned_group(parent_group, nonce)
        os.killpg(os.getpgrp(), signal.SIGTERM)

    threading.Thread(target=parent_watchdog, name="desktop-parent-watchdog", daemon=True).start()
    writer_lock = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    from .maintenance import read_marker, serve_transition
    maintenance = read_marker(name)
    if maintenance is not None:
        if maintenance["phase"] not in {"committed", "browser_check_pending"}:
            raise RuntimeError("Maintenance transition is unresolved; refusing captured application startup")
        try:
            serve_transition(paths, name, bound, port, nonce)
        finally:
            writer_lock.close()
        return 0
    if os.environ.get("DLMS_DESKTOP_TEST_FAIL_BACKEND") == "1":
        raise RuntimeError("Synthetic Gate 1 backend startup failure")
    from .transition import pre_import_journal, finalize
    pre_restore_journal = pre_import_journal(paths)
    # Importing app.py performs startup/recovery and may write data. The lock
    # above must be held before that import, including after launcher SIGKILL.
    from .webview2_runtime import configure_backend_stdio
    configure_backend_stdio()
    source_import_path()
    import app as captured_app  # noqa: PLC0415
    publication_startup = captured_app._quiz_publication_startup_report
    if publication_startup.get("unsafe") or publication_startup.get("failed"):
        raise RuntimeError("Quiz publication recovery is unresolved; this Desktop profile remains closed for inspection")
    from .import_operations import unresolved_count
    from .pack_operations import reconcile as reconcile_pack_installs
    from .profile_state import read_manifest
    identity = read_manifest(paths, name)
    if identity is not None:
        unresolved_count(paths["root"], identity["epoch"])  # malformed accepted evidence fails readiness closed
        reconcile_pack_installs(captured_app)
    # Only this isolated Desktop backend renders the managed-control notice.
    # The copied application's ordinary web templates keep their defaults.
    captured_app.app.jinja_env.globals["dlms_desktop_managed"] = True
    from .webview2_runtime import worker_active as webview2_active
    if webview2_active():
        from .webview2_ai_contract import install as install_ai_contract
        install_ai_contract(captured_app.app, captured_app.load_portal_config)
    if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
            and os.environ.get("DLMS_DESKTOP_TEST_PAUSE_PUBLICATION") == "1"):
        from .profile_state import atomic_json
        original_publication_checkpoint = captured_app._quiz_publication_checkpoint

        def paused_publication_checkpoint(stage, journal):
            original_publication_checkpoint(stage, journal)
            if stage == "db_committed":
                atomic_json(paths["root"] / "blockc-publication-paused.json",
                            {"stage": stage, "pid": os.getpid()})
                release = paths["root"] / "blockc-publication-release"
                deadline = time.monotonic() + 20
                while not release.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)

        captured_app._quiz_publication_checkpoint = paused_publication_checkpoint
    if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
            and os.environ.get("DLMS_DESKTOP_TEST_PAUSE_SETTINGS_WRITE") == "1"):
        from .profile_state import atomic_json
        original_settings_write = captured_app._write_settings_portal_config

        def paused_settings_write(config):
            result = original_settings_write(config)
            atomic_json(paths["root"] / "blockc-settings-write-paused.json",
                        {"theme": config.get("theme"), "pid": os.getpid()})
            release = paths["root"] / "blockc-settings-write-release"
            deadline = time.monotonic() + 20
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            return result

        captured_app._write_settings_portal_config = paused_settings_write
    from waitress import create_server  # noqa: PLC0415
    from PySide6.QtCore import qVersion
    from PySide6.QtWebEngineCore import qWebEngineChromiumVersion, qWebEngineVersion
    from .policy import local_webengine_policy
    from .recovery import DurableActions, RecoveryFailure
    from .profile_state import atomic_json
    from .requests import PendingRequests, KINDS

    finalize(paths, name, captured_app, pre_restore_journal)
    actions = DurableActions(paths, name, captured_app)
    actions.reconcile()  # accepted files are authority even if Chromium lost storage
    pending_requests = PendingRequests(paths, name, captured_app, actions.lock)

    origin = f"http://127.0.0.1:{port}"
    active = 0
    draining = False
    condition = threading.Condition()

    def denied(start_response, status="403 Forbidden"):
        start_response(status, [("Content-Type", "text/plain"), ("Content-Length", "0")])
        return [b""]

    def wsgi(environ, start_response):
        nonlocal active, draining
        from .webview2_runtime import worker_active as webview2_active, local_response_policy
        if webview2_active():
            # Apply before every branch, including readiness, denials and
            # managed responses. The C# host verifies this policy before it
            # enables authenticated browser requests. Linux/Qt is unchanged.
            start_response = local_response_policy(start_response)
        # The Qt interceptor is not an authorization boundary for another
        # local client. Require the exact authority and launcher token here.
        authority = environ.get("HTTP_HOST")
        request_origin = environ.get("HTTP_ORIGIN")
        if (authority != f"127.0.0.1:{port}"
                or environ.get("wsgi.url_scheme") != "http"
                or request_origin not in (None, origin)
                or environ.get("HTTP_SEC_FETCH_SITE", "").lower() == "cross-site"
                or environ.get("HTTP_X_FORWARDED_HOST")
                or environ.get("HTTP_X_FORWARDED_PROTO")):
            print(f"[DESKTOP] denied authority/origin for {environ.get('REQUEST_METHOD')} "
                  f"{environ.get('PATH_INFO')}: host={authority!r} origin={request_origin!r}", flush=True)
            return denied(start_response)
        if environ.get("HTTP_X_DLMS_DESKTOP_TOKEN") != nonce:
            print(f"[DESKTOP] denied missing or wrong launcher token for {environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')}", flush=True)
            return denied(start_response)
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD")
        # Only the closed-window Desktop transaction may replace a dataset.
        # These source routes remain available in ordinary web mode.
        if (method == "POST" and (path.startswith("/settings/backup/restore/")
                or path.startswith("/settings/data/restore/")
                or path.startswith("/api/reset_")
                or path in {"/api/remove_all_dlms_data", "/api/wipe_database",
                            "/api/delete_study_history", "/api/clear_db_history"})):
            body = b"Desktop data changes require the managed import workflow; no dataset was changed."
            start_response("409 Conflict", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
            return [body]
        if method == "POST" and path in KINDS.values():
            body = b"Desktop requests require the managed recovery endpoint."
            start_response("409 Conflict", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
            return [body]
        if path.startswith("/_desktop/request/"):
            if (request_origin not in (None, origin)
                    or environ.get("HTTP_X_DLMS_RECOVERY_CLIENT") != "1"
                    or environ.get("HTTP_SEC_FETCH_SITE", "same-origin").lower() not in {"same-origin", "none"}):
                return denied(start_response)
            with condition:
                if draining:
                    return denied(start_response, "503 Service Unavailable")
                active += 1
            try:
                with actions.lock:
                    if path == "/_desktop/request/context" and method == "GET":
                        value, code = {"enabled": True, "context": pending_requests.context()}, 200
                    elif path == "/_desktop/request/list" and method == "GET":
                        value, code = {"records": pending_requests.list_records()}, 200
                    elif path in {"/_desktop/request/status", "/_desktop/request/action", "/_desktop/request/ack"} and method == "POST":
                        if (request_origin != origin or not environ.get("CONTENT_TYPE", "").startswith("application/json")):
                            return denied(start_response)
                        length = int(environ.get("CONTENT_LENGTH") or "0")
                        if not 0 < length <= 128 * 1024:
                            raise RecoveryFailure("Invalid Desktop request size", 413)
                        envelope = json.loads(environ["wsgi.input"].read(length))
                        if path.endswith("/status"):
                            value, code = pending_requests.status(envelope), 200
                        elif path.endswith("/ack"):
                            value, code = pending_requests.acknowledge(envelope), 200
                        else:
                            target, record = pending_requests.accept(envelope)
                            if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
                                    and os.environ.get("DLMS_DESKTOP_TEST_ABORT_REQUEST") == "accepted"):
                                os._exit(72)
                            source_bytes = json.dumps(record["payload"], separators=(",", ":")).encode()
                            forwarded = dict(environ, PATH_INFO=target, CONTENT_LENGTH=str(len(source_bytes)),
                                             **{"wsgi.input": io.BytesIO(source_bytes)})
                            response = {}
                            def source_start(status, headers, exc_info=None):
                                response["status"], response["headers"] = status, headers
                            output = captured_app.app(forwarded, source_start)
                            try:
                                source_body = b"".join(output)
                            finally:
                                if hasattr(output, "close"):
                                    output.close()
                            if len(source_body) > 128 * 1024:
                                raise RecoveryFailure("Source response is too large; retained request needs inspection", 500)
                            status_code = int(response["status"].split()[0])
                            try:
                                value = json.loads(source_body)
                            except (ValueError, UnicodeError):
                                raise RecoveryFailure("Source response was not JSON; retained request needs inspection", 500)
                            code = status_code
                            value["desktop_accepted"] = True
                            if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
                                    and os.environ.get("DLMS_DESKTOP_TEST_ABORT_REQUEST") == "committed"):
                                os._exit(73)
                    else:
                        return denied(start_response, "405 Method Not Allowed")
            except RecoveryFailure as exc:
                value, code = {"error": str(exc), "code": exc.code}, exc.status
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
                value, code = {"error": "Invalid Desktop request"}, 400
            except Exception as exc:
                print(f"[DESKTOP] managed request error: {type(exc).__name__}: {exc}", flush=True)
                value, code = {"error": "Request outcome is uncertain; retained evidence needs inspection"}, 500
            finally:
                with condition:
                    active -= 1
                    condition.notify_all()
            body = json.dumps(value).encode()
            phrase = {200:"OK",400:"Bad Request",409:"Conflict",413:"Content Too Large",500:"Internal Server Error",503:"Service Unavailable",507:"Insufficient Storage"}.get(code,"Error")
            start_response(f"{code} {phrase}", [("Content-Type", "application/json"),
                           ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
            return [body]
        action_path = environ.get("PATH_INFO") == "/_desktop/recovery/action"
        capability_path = environ.get("PATH_INFO") == "/_desktop/recovery/capabilities"
        if action_path or capability_path:
            if ((action_path and request_origin != origin)
                    or (capability_path and request_origin not in (None, origin))
                    or environ.get("HTTP_X_DLMS_RECOVERY_CLIENT") != "1"
                    or environ.get("HTTP_SEC_FETCH_SITE", "same-origin").lower() not in {"same-origin", "none"}):
                return denied(start_response)
            if capability_path and environ.get("REQUEST_METHOD") == "GET":
                body = json.dumps({"enabled": True, "recovery": actions.pending_summary()}).encode()
                start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(body))),
                                        ("Cache-Control", "no-store")])
                return [body]
            if not action_path or environ.get("REQUEST_METHOD") != "POST" or not environ.get("CONTENT_TYPE", "").startswith("application/json"):
                return denied(start_response, "405 Method Not Allowed")
            with condition:
                if draining:
                    return denied(start_response, "503 Service Unavailable")
                active += 1
            request_body = None
            try:
                length = int(environ.get("CONTENT_LENGTH") or "0")
                if not 0 < length <= 768 * 1024:
                    raise RecoveryFailure("Invalid Desktop action size", 413)
                request_body = json.loads(environ["wsgi.input"].read(length))
                result, status = actions.accept(request_body)
            except RecoveryFailure as exc:
                result, status = {"ok": False, "error": str(exc)}, exc.status
                if exc.code:
                    result["code"] = exc.code
            except (ValueError, UnicodeError, json.JSONDecodeError):
                result, status = {"ok": False, "error": "Invalid Desktop action JSON"}, 400
            except Exception as exc:
                print(f"[DESKTOP] action acceptance error: {type(exc).__name__}", flush=True)
                result, status = {"ok": False, "error": "Desktop action was not confirmed; recovery evidence requires inspection"}, 500
            finally:
                with condition:
                    active -= 1
                    condition.notify_all()
            # Disposable test hook: the durable Exam result and journal cleanup
            # have completed, but this one success acknowledgment is withheld.
            marker = paths["root"] / "recovery-exam-reply-withheld.json"
            if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
                    and os.environ.get("DLMS_DESKTOP_TEST_DROP_CLEANED_EXAM_REPLY") == "1"
                    and isinstance(request_body, dict) and request_body.get("kind") == "exam" and status == 200
                    and not result.get("cleanup_pending") and not marker.exists()):
                atomic_json(marker, {"attempt_id": result["attempt_id"], "status_before_drop": status})
                raise ConnectionAbortedError("Synthetic Exam success acknowledgment withheld after cleanup")
            body = json.dumps(result).encode()
            phrase = {200: "OK", 202: "Accepted", 400: "Bad Request", 409: "Conflict",
                      413: "Content Too Large", 500: "Internal Server Error", 503: "Service Unavailable",
                      507: "Insufficient Storage"}.get(status, "Error")
            start_response(f"{status} {phrase}", [("Content-Type", "application/json"),
                                                 ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
            return [body]
        if environ.get("PATH_INFO") == "/_desktop/ready":
            if environ.get("HTTP_X_DLMS_DESKTOP_NONCE") != nonce:
                return denied(start_response)
            data = b"DLMS Desktop Block A ready"
            start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(data)))])
            return [data]
        if environ.get("PATH_INFO") == "/_desktop/settings/summary":
            # Native Local Settings only. The launcher token and readiness nonce
            # are both required; no page content or ordinary browser request
            # can enumerate this private profile summary.
            if (method != "GET" or environ.get("HTTP_X_DLMS_DESKTOP_NONCE") != nonce
                    or request_origin is not None):
                return denied(start_response)
            with condition:
                if draining:
                    return denied(start_response, "503 Service Unavailable")
                active += 1
            try:
                from dlms.services.storage_health import storage_snapshot
                with actions.lock:
                    value = {"recent_backups": captured_app._settings_recent_backups(),
                             "storage": storage_snapshot(captured_app.APP_DATA_DIR)}
                body = json.dumps(value).encode("utf-8")
                start_response("200 OK", [("Content-Type", "application/json"),
                                          ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
                return [body]
            finally:
                with condition:
                    active -= 1
                    condition.notify_all()
        if environ.get("PATH_INFO") == "/_desktop/drain":
            if (environ.get("REQUEST_METHOD") != "POST"
                    or environ.get("HTTP_X_DLMS_DESKTOP_NONCE") != nonce):
                return denied(start_response)
            with condition:
                draining = True
                deadline = time.monotonic() + 4
                while active and time.monotonic() < deadline:
                    condition.wait(timeout=max(0, deadline - time.monotonic()))
                quiet = active == 0
            data = b"drained" if quiet else b"pending"
            start_response("200 OK" if quiet else "503 Service Unavailable",
                           [("Content-Type", "text/plain"), ("Content-Length", str(len(data)))])
            return [data]
        if environ.get("PATH_INFO") == "/api/shutdown" and environ.get("REQUEST_METHOD") == "POST":
            marker = paths["root"] / "shutdown.request"
            assert_safe_leaf(marker)
            marker.write_text(nonce)
            data = b'{"status":"ok"}'
            start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(data)))])
            return [data]
        with condition:
            if draining:
                return denied(start_response, "503 Service Unavailable")
            active += 1
        backup_request = method == "POST" and path in {"/settings/backup/create", "/settings/data/backup/create"}
        import_request = (method == "POST" and path.startswith("/quiz-bundles/import/")
                          and path.rsplit("/", 1)[-1] in {"confirm", "cancel"})
        import_request = import_request or (method == "POST" and path.startswith("/content-packs/import/")
                                            and path.rsplit("/", 1)[-1] in {"install", "cancel"})
        gated_request = backup_request or import_request
        if (backup_request and os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
                and (os.environ.get("DLMS_DESKTOP_TEST_PAUSE_PUBLICATION") == "1"
                     or os.environ.get("DLMS_DESKTOP_TEST_PAUSE_SETTINGS_WRITE") == "1")):
            atomic_json(paths["root"] / "blockc-backup-request-entered.json",
                        {"entered": True, "pid": os.getpid()})
        if gated_request:
            actions.lock.acquire()  # before Flask's source snapshot permit
        try:
            from .import_operations import unresolved_count
            from .pack_operations import unresolved_count as pending_pack_installs
            from .profile_state import read_manifest
            identity = read_manifest(paths, name)
            if gated_request and (actions.pending_summary()["count"] or pending_requests.count()
                                  or (backup_request and (unresolved_count(paths["root"], identity["epoch"])
                                                          or pending_pack_installs(paths["root"], identity["epoch"])))):
                body = b"Accepted Desktop actions or an import are unresolved; settle them before another data operation."
                start_response("409 Conflict", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
                actions.lock.release()
                with condition:
                    active -= 1
                    condition.notify_all()
                return [body]
            def desktop_start_response(status, headers, exc_info=None):
                from .webview2_runtime import worker_active as webview2_active
                if webview2_active():
                    # WebView2 recognizes the complete source policy, including
                    # payment/USB denial. Qt's parser compatibility is not used.
                    return start_response(status, headers, exc_info)
                return start_response(status, local_webengine_policy(
                    headers, qt=qVersion(), webengine=qWebEngineVersion(),
                    chromium=qWebEngineChromiumVersion()), exc_info)

            result = captured_app.app(environ, desktop_start_response)
        except BaseException:
            if gated_request:
                actions.lock.release()
            with condition:
                active -= 1
                condition.notify_all()
            raise

        def before_iteration():
            if (backup_request and os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
                    and os.environ.get("DLMS_DESKTOP_TEST_PAUSE_BACKUP_ITERATION") == "1"):
                atomic_json(paths["root"] / "blockc-backup-iteration.json",
                            {"entered": True, "pid": os.getpid()})
                release = paths["root"] / "blockc-backup-iteration-release"
                deadline = time.monotonic() + 15
                while not release.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)

        def after_close():
            if (backup_request and os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
                    and os.environ.get("DLMS_DESKTOP_TEST_PAUSE_BACKUP_ITERATION") == "1"):
                try:
                    atomic_json(paths["root"] / "blockc-backup-iterable-closed.json",
                                {"closed": True, "pid": os.getpid()})
                except (OSError, ValueError):
                    pass

        def finish():
            nonlocal active
            if gated_request:
                actions.lock.release()
            with condition:
                active -= 1
                condition.notify_all()

        return TrackedIterable(result, finish, before_iteration=before_iteration,
                               after_close=after_close)

    if os.environ.get("DLMS_DESKTOP_TEST_CHILD") == "1":
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                         cwd=PROJECT, env=os.environ.copy(), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[DESKTOP] inherited reserved 127.0.0.1:{port}", flush=True)
    server = create_server(wsgi, sockets=[bound], threads=4)
    try:
        server.run()
    finally:
        writer_lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
