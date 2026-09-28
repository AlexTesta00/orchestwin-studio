from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from threading import Lock

MAXIMUM_TRACKED_KEYS = 10000


class AttemptLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        *,
        maximum_keys: int = MAXIMUM_TRACKED_KEYS,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if maximum_keys < 1:
            raise ValueError("maximum_keys must be at least 1")
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._maximum_keys = maximum_keys
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    @property
    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._attempts)

    def retry_after(self, key: str) -> int | None:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            attempts = self._active_attempts(key, now)
            if attempts is None or len(attempts) < self._limit:
                return None
            return max(1, math.ceil(attempts[0] + self._window_seconds - now))

    def record(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            attempts = self._active_attempts(key, now)
            if attempts is None:
                attempts = deque(maxlen=self._limit)
                self._attempts[key] = attempts
            else:
                self._attempts.move_to_end(key)
            attempts.append(now)
            while len(self._attempts) > self._maximum_keys:
                self._attempts.popitem(last=False)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _active_attempts(self, key: str, now: float) -> deque[float] | None:
        attempts = self._attempts.get(key)
        if attempts is None:
            return None
        threshold = now - self._window_seconds
        while attempts and attempts[0] <= threshold:
            attempts.popleft()
        if attempts:
            return attempts
        del self._attempts[key]
        return None

    def _purge_expired(self, now: float) -> None:
        threshold = now - self._window_seconds
        while self._attempts:
            key, attempts = next(iter(self._attempts.items()))
            if attempts and attempts[-1] > threshold:
                return
            del self._attempts[key]
