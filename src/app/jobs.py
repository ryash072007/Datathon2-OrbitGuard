"""Tiny background-job registry: heavy computations run in a thread, the page polls /api/status."""
from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable


class Jobs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def start(self, key: str, fn: Callable[[], object], label: str = "") -> bool:
        """Start ``fn`` in a thread unless a job with the same key is already running. Returns True if started."""
        with self._lock:
            cur = self._jobs.get(key)
            if cur and cur["state"] == "running":
                return False
            self._jobs[key] = {"key": key, "label": label or key, "state": "running", "started": time.time(),
                               "finished": None, "error": None}

        def runner() -> None:
            try:
                fn()
                state, err = "done", None
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI through the status endpoint
                traceback.print_exc()
                state, err = "error", f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._jobs[key].update(state=state, error=err, finished=time.time())

        threading.Thread(target=runner, name=f"job-{key}", daemon=True).start()
        return True

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            jobs = {k: dict(v, elapsed_s=round((v["finished"] or now) - v["started"], 1)) for k, v in self._jobs.items()}
        return {"running": any(j["state"] == "running" for j in jobs.values()), "jobs": jobs}
