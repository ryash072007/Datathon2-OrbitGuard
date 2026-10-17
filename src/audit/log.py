"""Append-only, hash-chained decision log (JSON lines). See README.md in this package."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path("data/audit/decisions.jsonl")
KINDS = ("decision", "brief", "screen")
MAX_PAYLOAD_CHARS = 8000
GENESIS = "0" * 64
_LOCK = threading.Lock()


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record_hash(prev_hash: str, record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "record_hash"}
    return _sha(prev_hash + canonical(body))


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def log_event(kind: str, payload, path: str | Path | None = None) -> dict:
    """Append one record; returns it. Thread-safe within a process."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    p = Path(path) if path else DEFAULT_PATH
    full = canonical(payload)
    stored = payload
    truncated = len(full) > MAX_PAYLOAD_CHARS
    if truncated:
        stored = {"truncated": True, "preview": full[:MAX_PAYLOAD_CHARS]}
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = _read_lines(p)
        if lines:
            last = json.loads(lines[-1])
            seq, prev = last["seq"] + 1, last["record_hash"]
        else:
            seq, prev = 0, GENESIS
        rec = {"seq": seq, "utc": datetime.now(timezone.utc).isoformat(), "kind": kind,
               "payload_sha256": _sha(full), "payload_truncated": truncated, "payload": stored,
               "prev_hash": prev}
        rec["record_hash"] = _record_hash(prev, rec)
        with p.open("a", encoding="utf-8", newline="\n") as f:
            f.write(canonical(rec) + "\n")
    return rec


def verify_log(path: str | Path | None = None) -> tuple[bool, int | None]:
    """(ok, first_bad_seq). A missing/deleted line shows up as a seq gap or broken prev_hash.
    If the very last line(s) are deleted the chain still verifies (truncation of the tail is not detectable
    without an external anchor of the head hash)."""
    p = Path(path) if path else DEFAULT_PATH
    prev, expect = GENESIS, 0
    for ln in _read_lines(p):
        try:
            rec = json.loads(ln)
            seq = rec["seq"]
            good = (seq == expect and rec["prev_hash"] == prev and rec["record_hash"] == _record_hash(prev, rec)
                    and rec["payload_sha256"] == (_sha(canonical(rec["payload"])) if not rec["payload_truncated"]
                                                  else rec["payload_sha256"]))
        except (ValueError, KeyError, TypeError):
            return False, expect
        if not good:
            return False, expect
        prev, expect = rec["record_hash"], expect + 1
    return True, None
