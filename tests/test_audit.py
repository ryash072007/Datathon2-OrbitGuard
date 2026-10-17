import json
import threading

from src.audit.log import log_event, verify_log


def _fill(p, n=5):
    for i in range(n):
        log_event("decision", {"i": i, "note": "x"}, p)


def test_clean_chain(tmp_path):
    p = tmp_path / "d.jsonl"
    _fill(p)
    assert verify_log(p) == (True, None)


def test_edit_detected(tmp_path):
    p = tmp_path / "d.jsonl"
    _fill(p)
    lines = p.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[2])
    rec["payload"]["i"] = 99
    lines[2] = json.dumps(rec)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert verify_log(p) == (False, 2)


def test_delete_detected(tmp_path):
    p = tmp_path / "d.jsonl"
    _fill(p)
    lines = p.read_text(encoding="utf-8").splitlines()
    del lines[1]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert verify_log(p) == (False, 1)


def test_threads(tmp_path):
    p = tmp_path / "d.jsonl"
    ts = [threading.Thread(target=_fill, args=(p, 10)) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert verify_log(p) == (True, None)
    assert len(p.read_text(encoding="utf-8").splitlines()) == 80
