"""Runtime-only browser-presence tracking for optional DLMS shutdown."""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager


BROWSER_PRESENCE_HEARTBEAT_SECONDS = 30.0
BROWSER_PRESENCE_TOKEN_TTL_SECONDS = 90.0
BROWSER_PRESENCE_SHUTDOWN_GRACE_SECONDS = 300.0
BROWSER_PRESENCE_POLL_SECONDS = 2.0
BROWSER_PRESENCE_SUSPEND_GAP_SECONDS = 120.0

_PRESENCE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class BrowserPresenceManager:
    """Track ephemeral page tokens and request a safe automatic shutdown."""

    def __init__(
        self,
        shutdown_callback,
        *,
        clock=time.monotonic,
        heartbeat_seconds=BROWSER_PRESENCE_HEARTBEAT_SECONDS,
        token_ttl_seconds=BROWSER_PRESENCE_TOKEN_TTL_SECONDS,
        grace_seconds=BROWSER_PRESENCE_SHUTDOWN_GRACE_SECONDS,
        poll_seconds=BROWSER_PRESENCE_POLL_SECONDS,
        suspend_gap_seconds=BROWSER_PRESENCE_SUSPEND_GAP_SECONDS,
        runtime_eligible=True,
    ):
        self._shutdown_callback = shutdown_callback
        self._clock = clock
        self.heartbeat_seconds = float(heartbeat_seconds)
        self.token_ttl_seconds = float(token_ttl_seconds)
        self.grace_seconds = float(grace_seconds)
        self.poll_seconds = float(poll_seconds)
        self.suspend_gap_seconds = float(suspend_gap_seconds)
        self._lock = threading.RLock()
        self._preference_enabled = False
        self._runtime_eligible = bool(runtime_eligible)
        self._presences = {}
        self._absence_started_at = None
        self._critical_operations = 0
        self._shutdown_requested = False
        self._last_poll_at = None
        self._stop_event = threading.Event()
        self._thread = None

    @staticmethod
    def validate_token(token):
        value = str(token or "")
        if not _PRESENCE_TOKEN_RE.fullmatch(value):
            raise ValueError("Invalid browser presence token")
        return value

    def configure_timing(
        self,
        *,
        heartbeat_seconds=None,
        token_ttl_seconds=None,
        grace_seconds=None,
        poll_seconds=None,
        suspend_gap_seconds=None,
    ):
        """Override timing before start, primarily for deterministic harnesses."""
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("Browser presence timing cannot change after start")
            for name, value in (
                ("heartbeat_seconds", heartbeat_seconds),
                ("token_ttl_seconds", token_ttl_seconds),
                ("grace_seconds", grace_seconds),
                ("poll_seconds", poll_seconds),
                ("suspend_gap_seconds", suspend_gap_seconds),
            ):
                if value is None:
                    continue
                parsed = float(value)
                if parsed <= 0:
                    raise ValueError(f"{name} must be positive")
                setattr(self, name, parsed)

    def set_enabled(self, enabled, *, now=None):
        now = self._clock() if now is None else float(now)
        enabled = bool(enabled)
        with self._lock:
            was_enabled = self._effective_enabled_locked()
            self._preference_enabled = enabled
            self._apply_effective_transition_locked(was_enabled, now)

    def set_runtime_eligible(self, eligible, *, now=None):
        """Apply bind-host policy without changing the saved preference."""
        now = self._clock() if now is None else float(now)
        with self._lock:
            was_enabled = self._effective_enabled_locked()
            self._runtime_eligible = bool(eligible)
            self._apply_effective_transition_locked(was_enabled, now)

    @property
    def runtime_eligible(self):
        with self._lock:
            return self._runtime_eligible

    @property
    def preference_enabled(self):
        with self._lock:
            return self._preference_enabled

    def _effective_enabled_locked(self):
        return self._preference_enabled and self._runtime_eligible

    def _apply_effective_transition_locked(self, was_enabled, now):
        is_enabled = self._effective_enabled_locked()
        if is_enabled == was_enabled:
            return
        self._presences.clear()
        self._shutdown_requested = False
        self._absence_started_at = now if is_enabled else None

    def heartbeat(self, token, *, now=None):
        token = self.validate_token(token)
        now = self._clock() if now is None else float(now)
        with self._lock:
            if not self._effective_enabled_locked():
                return False
            self._presences[token] = now
            self._absence_started_at = None
            self._shutdown_requested = False
            return True

    def close(self, token, *, now=None):
        token = self.validate_token(token)
        now = self._clock() if now is None else float(now)
        with self._lock:
            if not self._effective_enabled_locked():
                return False
            removed = self._presences.pop(token, None) is not None
            self._expire_stale_locked(now)
            if not self._presences and self._absence_started_at is None:
                self._absence_started_at = now
            return removed

    def begin_critical_operation(self):
        with self._lock:
            self._critical_operations += 1

    def end_critical_operation(self):
        with self._lock:
            if self._critical_operations <= 0:
                raise RuntimeError("Browser presence critical-operation count is unbalanced")
            self._critical_operations -= 1

    @contextmanager
    def critical_operation(self):
        self.begin_critical_operation()
        try:
            yield
        finally:
            self.end_critical_operation()

    def _expire_stale_locked(self, now):
        expired_at = None
        stale = [
            token
            for token, last_seen in self._presences.items()
            if now - last_seen >= self.token_ttl_seconds
        ]
        for token in stale:
            last_seen = self._presences.pop(token)
            candidate = last_seen + self.token_ttl_seconds
            expired_at = candidate if expired_at is None else max(expired_at, candidate)
        if not self._presences and self._absence_started_at is None and expired_at is not None:
            self._absence_started_at = expired_at

    def _defer_for_clock_gap_locked(self, gap):
        if gap <= self.suspend_gap_seconds:
            return False
        self._presences = {
            token: last_seen + gap
            for token, last_seen in self._presences.items()
        }
        if self._absence_started_at is not None:
            self._absence_started_at += gap
        return True

    def poll_once(self, *, now=None):
        """Evaluate presence once; return True only for the first due shutdown."""
        now = self._clock() if now is None else float(now)
        with self._lock:
            if self._last_poll_at is not None:
                self._defer_for_clock_gap_locked(now - self._last_poll_at)
            self._last_poll_at = now

            if not self._effective_enabled_locked() or self._shutdown_requested:
                return False
            self._expire_stale_locked(now)
            if self._presences:
                self._absence_started_at = None
                return False
            if self._absence_started_at is None:
                self._absence_started_at = now
            if now - self._absence_started_at < self.grace_seconds:
                return False
            if self._critical_operations:
                return False
            self._shutdown_requested = True

        try:
            self._shutdown_callback()
        except Exception:
            with self._lock:
                self._shutdown_requested = False
            raise
        return True

    def snapshot(self, *, now=None):
        now = self._clock() if now is None else float(now)
        with self._lock:
            self._expire_stale_locked(now)
            return {
                "enabled": self._effective_enabled_locked(),
                "active_clients": len(self._presences),
                "grace_started": self._absence_started_at is not None,
                "critical_operations": self._critical_operations,
                "shutdown_requested": self._shutdown_requested,
            }

    def complete_automatic_shutdown(self, shutdown_callback, *, now=None):
        """Run the final shutdown action only while the due state is still safe."""
        now = self._clock() if now is None else float(now)
        with self._lock:
            self._expire_stale_locked(now)
            still_due = (
                self._effective_enabled_locked()
                and self._shutdown_requested
                and not self._presences
                and self._absence_started_at is not None
                and now - self._absence_started_at >= self.grace_seconds
                and not self._critical_operations
            )
            if not still_due:
                self._shutdown_requested = False
                return False
            try:
                shutdown_callback()
            except Exception:
                self._shutdown_requested = False
                raise
            return True

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._last_poll_at = self._clock()
            self._thread = threading.Thread(
                target=self._run,
                name="dlms-browser-presence",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, timeout=2.0):
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def _run(self):
        while not self._stop_event.wait(self.poll_seconds):
            try:
                self.poll_once()
            except Exception as exc:
                print(
                    "[BROWSER PRESENCE ERROR] Automatic shutdown check failed: "
                    f"{type(exc).__name__}: {exc}"
                )
