"""
app/decision/circuit_breaker.py — Rolling hold-rate circuit breaker.

Spec §9.4 + CLAUDE.md:
  - Trips when hold_rate > 5% of traffic over a 5-minute window
  - OPEN state: bypass ML action selection, but compliance + blocklist still run
  - Floor policy ALWAYS on (spec §11 invariant #5)
  - Hysteresis: breaker stays OPEN for `hysteresis_seconds` after tripping
  - Minimum sample: ignore rate if fewer than `minimum_sample` transactions
  - Breaker state recorded on EVERY decision record

Attacker note (§A.3): a breaker that sets ALL traffic to PASS is
attacker-triggerable (flood obvious fraud → trip the breaker → walk through).
Keeping compliance + blocklist active when OPEN prevents this.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from app.config import get_circuit_breaker_cfg

logger = logging.getLogger(__name__)

BreakerState = Literal["CLOSED", "OPEN"]


@dataclass
class CircuitBreakerStatus:
    state: BreakerState
    hold_rate: float
    window_size: int          # number of transactions in the window
    opened_at: float | None   # time.monotonic() when it opened, None if CLOSED
    reason: str


class CircuitBreaker:
    """
    Rolling-window circuit breaker on hold rate.
    Thread-safe via asyncio.Lock (single-process async server).
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        # Ring buffer of (timestamp, is_hold) pairs
        self._window: list[tuple[float, bool]] = []
        self._opened_at: float | None = None
        self._cfg: dict | None = None

    def _get_cfg(self) -> dict:
        if self._cfg is None:
            self._cfg = get_circuit_breaker_cfg()
        return self._cfg

    def _prune_window(self, now: float) -> None:
        """Remove events older than the rolling window."""
        cfg = self._get_cfg()
        window_seconds = cfg["hold_rate_window_seconds"]
        cutoff = now - window_seconds
        self._window = [(ts, held) for ts, held in self._window if ts >= cutoff]

    def _current_hold_rate(self, now: float) -> tuple[float, int]:
        """Return (hold_rate, window_size) after pruning."""
        self._prune_window(now)
        if not self._window:
            return 0.0, 0
        total = len(self._window)
        holds = sum(1 for _, held in self._window if held)
        return holds / total, total

    async def record(self, is_hold: bool) -> None:
        """Record a transaction decision (call AFTER the decision is made)."""
        async with self._lock:
            now = time.monotonic()
            self._window.append((now, is_hold))

            cfg = self._get_cfg()
            rate, size = self._current_hold_rate(now)

            if (
                size >= cfg["minimum_sample"] and
                rate > cfg["hold_rate_threshold"] and
                self._opened_at is None
            ):
                self._opened_at = now
                logger.warning(
                    f"Circuit breaker OPENED: hold_rate={rate:.1%} "
                    f"({size} tx in window) — defaulting all traffic to PASS"
                )

    async def status(self) -> CircuitBreakerStatus:
        """Return the current breaker status."""
        async with self._lock:
            now = time.monotonic()
            cfg = self._get_cfg()
            rate, size = self._current_hold_rate(now)

            # Check hysteresis: auto-close after hysteresis_seconds
            if self._opened_at is not None:
                elapsed = now - self._opened_at
                if elapsed >= cfg.get("hysteresis_seconds", 60):
                    # Reset: check if rate is back below threshold
                    if rate <= cfg["hold_rate_threshold"]:
                        logger.info(
                            f"Circuit breaker CLOSED: hold_rate={rate:.1%} "
                            f"after {elapsed:.0f}s hysteresis"
                        )
                        self._opened_at = None

            state: BreakerState = "OPEN" if self._opened_at is not None else "CLOSED"

            return CircuitBreakerStatus(
                state=state,
                hold_rate=rate,
                window_size=size,
                opened_at=self._opened_at,
                reason=(
                    f"Hold rate {rate:.1%} > threshold {cfg['hold_rate_threshold']:.0%}"
                    if state == "OPEN" else "Normal"
                ),
            )

    async def is_open(self) -> bool:
        s = await self.status()
        return s.state == "OPEN"


# ── Singleton ──────────────────────────────────────────────────────────────────
_breaker: CircuitBreaker | None = None


def get_breaker() -> CircuitBreaker:
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker()
    return _breaker
