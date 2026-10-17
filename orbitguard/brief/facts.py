"""Run the tools (screener, consequence engine, network, decision layer) and gather one facts dict.

The facts dict is JSON-serialisable and is the ONLY source of numbers for the brief (see grounding.py).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from orbitguard.catalog.collision import TLE_SIGMA_RTN_M
from orbitguard.consequence.event import Params, assess
from orbitguard.consequence.objects import ASSUMPTIONS, object_mass_kg, object_type
from orbitguard.catalog.burns import burn_grid
from orbitguard.catalog.catalog import data_dir, load_catalog, period_min_from_tle
from orbitguard.catalog.parallel import default_workers
from orbitguard.catalog.screen import find_approach, prepare, run_burns

MIN_FRAGMENT_CM = 10
N_TOP_BURNS = 10


def _clean(obj):
    """Make numpy / datetime values JSON-friendly."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if np.isfinite(f) else None
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def latest_file(pattern: str, out_dir: Path | None = None) -> Path | None:
    files = sorted((out_dir or data_dir() / "out").glob(pattern))
    return files[-1] if files else None


def network_facts(primary_norad: int, threat_norad: int) -> dict | None:
    """Scores of both objects from the latest network file; None when no file exists."""
    path = latest_file("network_*.json")
    if path is None:
        return None
    net = json.loads(path.read_text(encoding="utf-8"))
    by_id = {n["norad"]: n for n in net["nodes"]}

    def one(norad: int) -> dict:
        n = by_id.get(norad)
        if n is None:
            return {"norad": norad, "listed": False}
        return {"norad": norad, "listed": True, "rank": n["rank"], "score": n["score"], "degree": n["degree"],
                "component_size": n["component_size"]}

    return {"file": path.name, "generated_utc": net.get("generated_utc"), "n_nodes_listed": len(net["nodes"]),
            "n_objects": net["summary"]["n_objects"], "primary": one(primary_norad), "threat": one(threat_norad)}


TABLE_COLUMNS = ("burn_id", "direction", "dv_mps", "lead_periods", "miss_km_threat", "new_conjunctions", "feasible",
                 "threat_pc_worst", "worst_pc", "worst_other_norad", "accepted")


def burn_table(bdf) -> list[dict]:
    """Every screened candidate, compact columns only. For the Ask agent's lookups; never shown to the brief LLM
    and excluded from the grounding guard's fact numbers (see brief.make_brief_from_facts)."""
    return [{c: getattr(r, c) for c in TABLE_COLUMNS} for r in bdf.itertuples()]


def decision_facts(cdm_event: int) -> dict:
    """Phase 2 decision on a historical ESA test event. Never mixed up with the live conjunction."""
    import pandas as pd

    from orbitguard.decision.decision import decide
    from orbitguard.decision.train import DATA

    test = pd.read_csv(DATA / "test_data.csv")
    rows = test[test["event_id"] == cdm_event]
    if rows.empty:
        raise ValueError(f"CDM event {cdm_event} not in the ESA test set")
    d = decide(rows)
    return {"label": "historical CDM example", "cdm_event_id": int(cdm_event), "latest_risk_log10_pc": d.latest_risk,
            "predicted_risk_log10_pc": d.predicted_risk, "p_high": d.p_high, "interval_log10_pc": list(d.interval),
            "action": d.action, "reasons": list(d.reasons)}


def collect_facts(primary_norad: int, threat_norad: int | None = None, cdm_event: int | None = None, *,
                  days: float = 3.0, target_km: float = 10.0, workers: int | None = None,
                  records: list | None = None) -> dict:
    """Run screener + consequence engine (+ network lookup, + optional decision) for one primary."""
    workers = workers or default_workers()
    tim: dict[str, float] = {}
    t = time.perf_counter()
    records = records or load_catalog()
    by_id = {r.norad: r for r in records}
    if primary_norad not in by_id:
        raise ValueError(f"primary NORAD {primary_norad} not in the catalogue")
    primary = by_id[primary_norad]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    period_min = period_min_from_tle(primary.line2)
    start = now + timedelta(minutes=0.5 * period_min + 2)
    found = find_approach(primary, records, start, days, only_norad=threat_norad)
    tim["find_approach_s"] = time.perf_counter() - t
    tca = found["tca"].replace(microsecond=0)
    threat = found["record"]

    burns = burn_grid(tca, period_min, earliest=now + timedelta(seconds=60))
    ctx = prepare(primary.tle, records, tca, burns, target_km=target_km, r_km=5.0, threat_norad=threat.norad)
    df = run_burns(ctx, burns, workers)
    tim["screen_s"] = df.attrs["timings"]["burns_s"]
    bdf = df[df["direction"] != "none"]
    top = [{"burn_id": r.burn_id, "direction": r.direction, "dv_mps": r.dv_mps,
            "burn_time_utc": str(r.burn_time_utc), "lead_periods": r.lead_periods,
            "miss_km_threat": r.miss_km_threat, "new_conjunctions": int(r.new_conjunctions),
            "feasible": bool(r.feasible), "along_track": bool(r.analytic_seed), "score": r.score,
            "threat_pc": r.threat_pc, "worst_pc": r.worst_pc, "worst_other_norad": r.worst_other_norad,
            "accepted": bool(r.accepted)}
           for r in bdf.head(N_TOP_BURNS).itertuples()]

    t = time.perf_counter()
    res = assess(primary, threat, tca, found["miss_km"], records, Params(), workers)
    tim["consequence_s"] = time.perf_counter() - t
    p = res["params"]
    cons = {k: res[k] for k in ("catastrophic", "ejected_mass_kg", "fragments_true", "reentered_fraction", "pc",
                                "n_sats_ge1_encounter", "n_sats_any_exposure", "n_sats_considered",
                                "total_expected_encounters", "expected_harm", "exposed_by_constellation",
                                "v_rel_kms", "parent_alt_km")}
    cons["top_satellites"] = [{"name": s["name"], "expected_encounters": s["expected_encounters"]}
                              for s in res["top_satellites"][:3]]
    cons["assumptions"] = {"min_fragment_cm": MIN_FRAGMENT_CM, "horizon_days": p["n_days"],
                           "encounter_radius_km": p["r_km"], "tle_sigma_rtn_m": list(TLE_SIGMA_RTN_M),
                           "hbr_m": p["hbr_m"],
                           "mass_note": ASSUMPTIONS["note"]}

    facts = {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "event": {"primary": {"name": primary.name, "norad": primary.norad, "type": object_type(primary),
                              "mass_kg": object_mass_kg(primary)},
                  "threat": {"name": threat.name, "norad": threat.norad, "type": object_type(threat),
                             "mass_kg": object_mass_kg(threat)},
                  "tca_utc": tca.isoformat(), "miss_km": found["miss_km"], "search_window_days": days},
        "risk": {"live_pc": res["pc"], "live_pc_worst": res["pc_worst_scale"],
                 "pc_note": "encounter-plane Gaussian with assumed TLE errors (no published covariance); "
                            "worst case over 0.5x-2x sigma", "decision": None},
        "burns": {"baseline_miss_km": ctx.baseline_miss_km, "target_km": target_km, "n_screened": len(bdf),
                  "n_feasible": int(bdf["feasible"].sum()), "n_accepted": int(bdf["accepted"].sum()),
                  "pc_threshold": ctx.pc_threshold, "n_objects_screened": len(ctx.tles), "top": top,
                  "policies": df.attrs["policies"]},
        "burn_table": burn_table(bdf),
        "consequence": cons,
        "network": network_facts(primary.norad, threat.norad),
        "timings_s": tim,
    }
    if cdm_event is not None:
        facts["risk"]["decision"] = decision_facts(cdm_event)
    return _clean(facts)


# ---------------------------------------------------------------- cache used by the dashboard
def facts_path(norad: int) -> Path:
    return data_dir() / "out" / f"facts_{norad}.json"


def save_facts(facts: dict) -> Path:
    path = facts_path(facts["event"]["primary"]["norad"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(facts, indent=1), encoding="utf-8")
    return path


def load_cached_facts(norad: int) -> dict | None:
    path = facts_path(norad)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
