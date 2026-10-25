from __future__ import annotations

import math
import sys
import threading
import time
from dataclasses import dataclass
from typing import TextIO


def _format_duration(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "--:--:--"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class ProgressSnapshot:
    label: str
    completed: int
    total: int
    active: int
    max_active: int
    elapsed_seconds: float
    eta_seconds: float | None
    rate_per_second: float
    current_item: str | None


class ProgressReporter:
    """Thread-safe, dependency-free terminal progress display.

    Updates are throttled and written to stderr by default so stdout remains
    machine-readable for the final JSON manifest.
    """

    def __init__(
        self,
        *,
        label: str,
        total: int,
        mode: str = "auto",
        stream: TextIO | None = None,
        width: int = 28,
        min_interval_seconds: float = 0.25,
    ) -> None:
        if mode not in {"auto", "always", "never"}:
            raise ValueError(f"Unsupported progress mode: {mode}")
        self.label = label
        self.total = max(0, int(total))
        self.mode = mode
        self.stream = stream or sys.stderr
        self.width = max(10, int(width))
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.started_at = time.monotonic()
        self.completed = 0
        self.successful = 0
        self.failed = 0
        self.active = 0
        self.max_active = 0
        self.current_item: str | None = None
        self._last_render = 0.0
        self._line_open = False
        self._lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        if self.mode == "never":
            return False
        if self.mode == "always":
            return True
        isatty = getattr(self.stream, "isatty", None)
        return bool(isatty and isatty())

    def request_started(self, item: str | None = None) -> None:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if item:
                self.current_item = item
            self._render(force=False)

    def request_finished(self, item: str | None = None, *, successful: bool = True) -> None:
        with self._lock:
            self.active = max(0, self.active - 1)
            self.completed = min(self.total, self.completed + 1)
            if successful:
                self.successful += 1
            else:
                self.failed += 1
            if item:
                self.current_item = item
            self._render(force=self.completed >= self.total)

    def finish(self) -> None:
        with self._lock:
            self._render(force=True)
            if self.enabled and self._line_open:
                self.stream.write("\n")
                self.stream.flush()
                self._line_open = False

    def snapshot(self) -> ProgressSnapshot:
        with self._lock:
            elapsed = max(0.0, time.monotonic() - self.started_at)
            rate = self.completed / elapsed if elapsed > 0 else 0.0
            remaining = max(0, self.total - self.completed)
            eta = remaining / rate if rate > 0 else None
            return ProgressSnapshot(
                label=self.label,
                completed=self.completed,
                total=self.total,
                active=self.active,
                max_active=self.max_active,
                elapsed_seconds=elapsed,
                eta_seconds=eta,
                rate_per_second=rate,
                current_item=self.current_item,
            )

    def _render(self, *, force: bool) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and now - self._last_render < self.min_interval_seconds:
            return
        self._last_render = now
        snap = self.snapshot()
        fraction = snap.completed / snap.total if snap.total else 1.0
        filled = min(self.width, max(0, int(round(fraction * self.width))))
        bar = "█" * filled + "░" * (self.width - filled)
        percentage = 100.0 * fraction
        item = f" | item={snap.current_item}" if snap.current_item else ""
        line = (
            f"{snap.label} |{bar}| "
            f"scenes={snap.completed}/{snap.total} ({percentage:5.1f}%) "
            f"| successful={self.successful} failed={self.failed} "
            f"| active={snap.active} peak={snap.max_active} "
            f"| elapsed={_format_duration(snap.elapsed_seconds)} "
            f"eta={_format_duration(snap.eta_seconds)} "
            f"| rate={snap.rate_per_second:.2f} scene/s{item}"
        )
        self.stream.write("\r" + line)
        self.stream.flush()
        self._line_open = True
