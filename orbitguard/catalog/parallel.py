"""Spawn-safe process-pool helper.

Workers are module-level functions that take one explicit argument (no globals); the pool uses the
``spawn`` start method on every OS so Windows and LinuxONE behave identically. Entry points that call
``map_tasks`` must be guarded by ``if __name__ == "__main__":`` (``orbitguard.catalog.run`` is).
"""
from __future__ import annotations

import multiprocessing as mp
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import Any


def default_workers() -> int:
    env = os.environ.get("WORKERS")
    if env:
        n = int(env)
        if n < 1:
            raise ValueError(f"WORKERS must be >= 1, got {env}")
        return n
    return os.cpu_count() or 1


def map_tasks(fn: Callable[[Any], Any], tasks: Sequence[Any], workers: int) -> list[Any]:
    """Run ``fn`` over ``tasks`` (order preserved). workers<=1 runs inline (no pool, easier debugging)."""
    if workers <= 1 or len(tasks) <= 1:
        return [fn(t) for t in tasks]
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=min(workers, len(tasks)), mp_context=ctx) as pool:
        return list(pool.map(fn, tasks))
