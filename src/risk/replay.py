"""Replay a historical ESA warning sequence: feed CDMs one at a time to the decision layer.

CLI: python -m src.risk.replay [event_id]   (no argument: pick and print the 3 demo events)
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from src.risk.decision import Decision, decide, load_artifact
from src.risk.features import MIN_TTCA_DAYS
from src.risk.train import DATA, HIGH_RISK, usable_labels

ACTIONS = ("MONITOR", "WAIT", "ACT")


def _load(split: str) -> tuple[pd.DataFrame, pd.Series]:
    if split == "test":
        cdms = pd.read_csv(DATA / "test_data.csv")
        true = pd.read_csv(DATA / "test_data_private.csv").set_index("event_id")["true_risk"]
    elif split == "train":
        cdms = pd.read_csv(DATA / "train_data.csv")
        true = usable_labels(cdms)
    else:
        raise ValueError(f"split must be 'test' or 'train', got {split!r}")
    return cdms, true


def replay_cdms(cdms: pd.DataFrame, true_final: float | None, art: dict | None = None) -> list[dict]:
    """Walk through the CDMs of ONE event (time_to_tca >= 2 d only). Last element is the ground truth."""
    u = cdms[cdms["time_to_tca"] >= MIN_TTCA_DAYS].sort_values("time_to_tca", ascending=False, kind="stable")
    if u.empty:
        raise ValueError("event has no CDMs with time_to_tca >= 2 days")
    if art is None:
        art = load_artifact()
    steps: list[dict] = []
    for i in range(1, len(u) + 1):
        d: Decision = decide(u.iloc[:i], art)
        steps.append({"step": i, "n_cdms": i, "time_to_tca_days": float(u["time_to_tca"].iloc[i - 1]),
                      "latest_risk": d.latest_risk, "predicted_risk": d.predicted_risk, "p_high": d.p_high,
                      "action": d.action, "reasons": list(d.reasons),
                      "interval": [d.interval[0], d.interval[1]]})
    if true_final is not None:
        steps.append({"step": len(steps) + 1, "final": True, "true_final_risk": float(true_final),
                      "true_high": bool(true_final >= HIGH_RISK),
                      "note": "what actually happened (final CDM risk at closest approach)"})
    return steps


def replay(event_id: int, split: str = "test") -> list[dict]:
    cdms, true = _load(split)
    rows = cdms[cdms["event_id"] == event_id]
    if rows.empty:
        raise ValueError(f"event {event_id} not in the {split} set")
    return replay_cdms(rows, float(true[event_id]) if event_id in true.index else None)


def _summary(event_id: int, steps: list[dict]) -> dict:
    s = [x for x in steps if not x.get("final")]
    fin = steps[-1] if steps[-1].get("final") else None
    return {"event_id": int(event_id), "actions": [x["action"] for x in s], "n_steps": len(s),
            "final_action": s[-1]["action"], "true_final_risk": fin["true_final_risk"] if fin else None,
            "true_high": fin["true_high"] if fin else None}


def _changes(actions: list[str]) -> int:
    return sum(a != b for a, b in zip(actions, actions[1:]))


def pick_demo_events(split: str = "test", n_candidates: int = 60, seed: int = 0, min_cdms: int = 4,
                     max_cdms: int = 12) -> list[dict]:
    """3 demo events: (1) action escalates and the final risk really was high, (2) correctly dismissed
    (MONITOR throughout, truly low), (3) a miss or false alarm. Each dict has event_id, role, title, summary."""
    cdms, true = _load(split)
    art = load_artifact()
    u = cdms[cdms["time_to_tca"] >= MIN_TTCA_DAYS]
    counts = u.groupby("event_id").size()
    ok = counts[(counts >= min_cdms) & (counts <= max_cdms)].index.intersection(true.index)
    rng = np.random.default_rng(seed)
    high = [e for e in ok if true[e] >= HIGH_RISK]
    low = [e for e in ok if true[e] < HIGH_RISK]
    pool = list(rng.permutation(high)[:n_candidates]) + list(rng.permutation(low)[:n_candidates])
    sums = {}
    for e in pool:
        sums[int(e)] = _summary(int(e), replay_cdms(cdms[cdms["event_id"] == e], float(true[e]), art))

    def rank_escalate(s: dict):  # prefer a clean MONITOR -> (WAIT) -> ACT climb with no downgrades
        a = [ACTIONS.index(x) for x in s["actions"]]
        monotone = all(y >= x for x, y in zip(a, a[1:]))
        return (monotone and a[0] == 0, 1 in a, -abs(s["n_steps"] - 8))

    cand_a = [s for s in sums.values() if s["true_high"] and s["final_action"] == "ACT" and _changes(s["actions"])]
    cand_b = [s for s in sums.values() if not s["true_high"] and set(s["actions"]) == {"MONITOR"}]
    cand_c = [s for s in sums.values() if (s["true_high"] and s["final_action"] != "ACT")
              or (not s["true_high"] and s["final_action"] == "ACT")]
    out = []
    for role, cands, key, title in (
            ("escalation", cand_a, rank_escalate, "Escalates to ACT, and the risk was real"),
            ("dismissed", cand_b, lambda s: (s["n_steps"], -s["true_final_risk"]), "Correctly dismissed"),
            ("miss", cand_c, lambda s: (s["true_high"], s["n_steps"]), "The model gets this one wrong")):
        if cands:
            best = max(cands, key=key) if role != "dismissed" else max(cands, key=lambda s: s["n_steps"])
            out.append({"event_id": best["event_id"], "role": role, "title": title, "summary": best})
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        for s in replay(int(argv[0])):
            print({k: v for k, v in s.items() if k != "reasons"})
        return 0
    for d in pick_demo_events():
        print(d["role"], d["event_id"], d["summary"]["actions"], d["summary"]["true_final_risk"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
