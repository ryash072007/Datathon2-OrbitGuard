"""Finite candidate screening with explicit rejection and abstention."""

from __future__ import annotations

import math
import time

import numpy as np

from .orbits import apply_burn, closest_approaches, propagate
from .risk import collision_probability, rtn_covariance

RISK_THRESHOLD = 1e-4
UNCERTAINTY_SCALES = (0.5, 1.0, 2.0)
DELTA_V_OPTIONS = (-1.0, -0.5, -0.25, -0.1, -0.05, -0.01, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0)
BURN_TIMES = (300.0, 900.0, 1500.0)


def candidate_grid(max_delta_v_mps=1.0):
    return [(None, 0.0)] + [(t, dv) for t in BURN_TIMES for dv in DELTA_V_OPTIONS if abs(dv) <= max_delta_v_mps]


def encounter_risk(a_path, b_path, a, b, horizon, *, tight=False):
    times = closest_approaches(a_path, b_path, horizon, 15.0 if tight else 30.0)
    details = []
    for t in times:
        s1, s2 = a_path(t), b_path(t)
        relative = s2 - s1
        speed = float(np.linalg.norm(relative[3:]))
        if speed < 1:
            raise ValueError(f"Unsupported slow co-orbital encounter with {b.object_id}")
        # An encounter-plane projection is only meaningful near TCA. Avoid
        # treating a far-future extrapolation at a horizon endpoint as an
        # in-horizon encounter. Fixtures deliberately avoid partial encounters.
        if t == 0 or t == horizon:
            linear_offset = abs(float(relative[:3] @ relative[3:])) / speed ** 2
            if linear_offset > 1e-3:
                continue
        probabilities = []
        for scale in UNCERTAINTY_SCALES:
            pc = collision_probability(s1[:3], s1[3:], rtn_covariance(s1, a.sigma_rtn_m, scale),
                                       s2[:3], s2[3:], rtn_covariance(s2, b.sigma_rtn_m, scale),
                                       a.radius_m + b.radius_m)
            probabilities.append(pc)
        details.append({"object_id": b.object_id, "time_seconds": float(t),
                        "miss_distance_m": float(np.linalg.norm(relative[:3])),
                        "relative_speed_mps": speed, "pc": probabilities[1],
                        "sensitivity_worst_pc": max(probabilities),
                        "pc_by_uncertainty_scale": dict(zip((str(v) for v in UNCERTAINTY_SCALES), probabilities))})
    return {"pc": max((d["pc"] for d in details), default=0.0),
            "sensitivity_worst_pc": max((d["sensitivity_worst_pc"] for d in details), default=0.0),
            "encounters": details}


def primary_only_candidate(nominal, controlled, primary, horizon):
    other = propagate(primary.state, horizon)
    choices = []
    for burn, dv in candidate_grid():
        path = nominal if burn is None else apply_burn(nominal, burn, dv, horizon)
        result = encounter_risk(path, other, controlled, primary, horizon)
        if result["sensitivity_worst_pc"] <= RISK_THRESHOLD:
            choices.append((abs(dv), result["sensitivity_worst_pc"], burn or 0, burn, dv))
    if not choices:
        return None
    selected = min(choices)
    return selected[3], selected[4]


def validate_overrides(overrides):
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be an object")
    unknown = set(overrides) - {"risk_threshold", "max_delta_v_mps"}
    if unknown:
        raise ValueError(f"Unsupported screening overrides: {', '.join(sorted(unknown))}")
    threshold = overrides.get("risk_threshold", RISK_THRESHOLD)
    max_dv = overrides.get("max_delta_v_mps", 1.0)
    for name, value in (("risk_threshold", threshold), ("max_delta_v_mps", max_dv)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
    if not 0 < threshold <= 1:
        raise ValueError("risk_threshold must be greater than zero and no greater than one")
    if not 0 <= max_dv <= 1:
        raise ValueError("max_delta_v_mps must be between zero and one")
    return float(threshold), float(max_dv)


def _candidate(scenario, paths, burn, dv, threshold, *, tight=False):
    a = scenario.objects[0]
    nominal = paths[a.object_id]
    path = nominal if burn is None else apply_burn(nominal, burn, dv, scenario.horizon_seconds, tight=tight)
    encounters, by_object, errors = [], {}, []
    for obj in scenario.objects[1:]:
        try:
            result = encounter_risk(path, paths[obj.object_id], a, obj, scenario.horizon_seconds, tight=tight)
            by_object[obj.object_id] = result["sensitivity_worst_pc"]
            encounters.extend(result["encounters"])
        except (ValueError, FloatingPointError) as exc:
            errors.append(f"{obj.object_id}: {exc}")
    primary = by_object.get("B")
    secondary = max((risk for oid, risk in by_object.items() if oid != "B"), default=0.0)
    worst = max(by_object.values(), default=0.0)
    reasons = [f"{oid} exceeds risk threshold" for oid, risk in by_object.items() if risk > threshold]
    reasons.extend(errors)
    valid = not errors
    return {"candidate_id": "no-action" if burn is None else f"burn-{burn:g}-{dv:+g}",
            "burn_time_seconds": burn, "delta_v_mps": dv,
            "primary_pc": primary if valid else None,
            "worst_secondary_pc": secondary if valid else None,
            "worst_pc": worst if valid else None,
            "accepted": valid and worst <= threshold,
            "primary_accepted": valid and primary is not None and primary <= threshold,
            "valid": valid, "rejection_reasons": reasons, "encounters": encounters,
            "risk_definition": "maximum across evaluated uncertainty scales"}, path


def _choose(candidates, key):
    acceptable = [c for c in candidates if c[key]]
    return min(acceptable, key=lambda c: (abs(c["delta_v_mps"]), c["worst_pc"], c["burn_time_seconds"] or 0)) if acceptable else None


def _policy(candidate, name, threshold):
    if candidate is None:
        return {"policy": name, "accepted": False, "delta_v_mps": None, "burn_time_seconds": None,
                "primary_pc": None, "worst_secondary_pc": None, "worst_pc": None,
                "reason": "No acceptable manoeuvre in the evaluated candidate set.", "candidate_id": None,
                "abstained": True, "introduced_secondary_hazard": False}
    output = {key: candidate[key] for key in ("candidate_id", "accepted", "delta_v_mps", "burn_time_seconds",
                                             "primary_pc", "worst_secondary_pc", "worst_pc", "encounters")}
    output.update(policy=name, abstained=False)
    if not candidate["valid"]:
        output["reason"] = "Rejected: numerical or applicability failure: " + "; ".join(candidate["rejection_reasons"])
    elif not candidate["accepted"]:
        output["reason"] = "Original-pair constraint is met, but a surrounding object exceeds the threshold." if candidate["primary_accepted"] else "A hazardous encounter remains within the simulated horizon."
    elif candidate["delta_v_mps"] == 0:
        output["reason"] = "No hazardous encounter found within the simulated horizon; no burn required."
    else:
        output["reason"] = "Lowest delta-v among evaluated candidates meeting all object and uncertainty constraints." if name == "orbitguard" else "Lowest delta-v satisfying the original-pair constraint."
    output["introduced_secondary_hazard"] = bool(candidate["worst_secondary_pc"] is not None and candidate["worst_secondary_pc"] > threshold)
    return output


def _trajectory_data(paths, scenario, selected_paths=None, *, local=False, focus="primary"):
    # A short encounter window makes separation visible in SVG. Absolute
    # tracks are also included for a full orbital overview.
    if local:
        center = scenario.primary_tca_seconds if focus == "primary" else scenario.secondary_tca_seconds
        times = np.linspace(max(0, center - 4), min(scenario.horizon_seconds, center + 4), 81)
    else:
        times = np.linspace(0, scenario.horizon_seconds, 181)
    reference_states = paths["A"](times)
    reference = reference_states[:3]
    if local:
        radial = reference / np.linalg.norm(reference, axis=0)
        normal = np.cross(reference.T, reference_states[3:].T).T
        normal /= np.linalg.norm(normal, axis=0)
        transverse = np.cross(normal.T, radial.T).T
    entries = [(obj.object_id, obj.name, obj.role, paths[obj.object_id], None) for obj in scenario.objects]
    for name, path in (selected_paths or {}).items():
        if path is not None:
            entries.append((f"A_{name}", f"A: {name.replace('_', ' ')}", "controlled", path, name))
    output = []
    for oid, name, role, path, policy in entries:
        relevant_object = "B" if focus == "primary" else "C"
        if local and oid not in {"A", relevant_object, "A_pair_only", "A_orbitguard"}:
            continue
        positions = path(times)[:3] - (reference if local else 0)
        if local:
            positions = np.vstack([np.sum(positions * axis, axis=0) for axis in (transverse, normal, radial)])
        points = [{"t_seconds": float(t), "x_m": float(p[0]), "y_m": float(p[1]), "z_m": float(p[2])}
                  for t, p in zip(times, positions.T)]
        output.append({"object_id": oid, "name": name, "role": role, "policy": policy, "points": points})
    return output


def _encounter_views(paths, scenario, selected_paths=None):
    return {focus: {"frame": "relative to unmanoeuvred A; X along-track, Y cross-track, Z radial", "units": "m",
                    "focus": focus, "object_id": "B" if focus == "primary" else "C",
                    "trajectories": _trajectory_data(paths, scenario, selected_paths, local=True, focus=focus)}
            for focus in ("primary", "secondary")}


def scenario_detail(scenario):
    from .scenarios import ASSUMPTIONS
    paths = {obj.object_id: propagate(obj.state, scenario.horizon_seconds) for obj in scenario.objects}
    views = _encounter_views(paths, scenario)
    return {"scenario_id": scenario.scenario_id, "name": scenario.name, "description": scenario.description,
            "kind": scenario.kind, "source": "synthetic", "seed": scenario.seed,
            "horizon_seconds": scenario.horizon_seconds,
            "primary_tca_seconds": scenario.primary_tca_seconds,
            "secondary_tca_seconds": scenario.secondary_tca_seconds,
            "objects": [{"object_id": o.object_id, "name": o.name, "role": o.role,
                         "position_m": o.state[:3].tolist(), "velocity_mps": o.state[3:].tolist(),
                         "radius_m": o.radius_m, "sigma_rtn_m": list(o.sigma_rtn_m)} for o in scenario.objects],
            "assumptions": ASSUMPTIONS, "construction": scenario.metadata,
            "trajectories": _trajectory_data(paths, scenario),
            "encounter_view": views["primary"], "encounter_views": views}


def screen_scenario(scenario, overrides=None, *, include_trajectories=True, verify=True):
    from .scenarios import ASSUMPTIONS
    started = time.perf_counter()
    threshold, max_dv = validate_overrides(overrides)
    paths = {obj.object_id: propagate(obj.state, scenario.horizon_seconds) for obj in scenario.objects}
    candidates, candidate_paths = [], {}
    for burn, dv in candidate_grid(max_dv):
        result, path = _candidate(scenario, paths, burn, dv, threshold)
        candidates.append(result)
        candidate_paths[result["candidate_id"]] = path
    # Pair-only tie-break must use original-pair risk: otherwise the baseline
    # would inadvertently use information about surrounding objects.
    pair_options = [c for c in candidates if c["primary_accepted"]]
    pair = min(pair_options, key=lambda c: (abs(c["delta_v_mps"]), c["primary_pc"], c["burn_time_seconds"] or 0)) if pair_options else None
    selected = _choose(candidates, "accepted")
    choices = {"no_action": candidates[0], "pair_only": pair, "orbitguard": selected}
    policies = {name: _policy(candidate, name, threshold) for name, candidate in choices.items()}
    selected_paths = {name: candidate_paths[choice["candidate_id"]] if choice else None
                      for name, choice in choices.items() if name != "no_action"}
    if verify:
        tight_paths = {obj.object_id: propagate(obj.state, scenario.horizon_seconds, tight=True) for obj in scenario.objects}
        for name, choice in choices.items():
            if choice is None:
                policies[name]["verification"] = {"status": "abstained", "accepted": False}
                continue
            checked, checked_path = _candidate(scenario, tight_paths, choice["burn_time_seconds"], choice["delta_v_mps"], threshold, tight=True)
            checked_valid = checked["valid"]
            policies[name] = _policy(checked, name, threshold)
            policies[name]["verification"] = {"status": "failed" if not checked_valid else "passed" if checked["accepted"] else "rejected",
                                                "accepted": checked["accepted"], "worst_pc": checked["worst_pc"],
                                                "grid_seconds": 15, "rtol": 1e-11}
            if name == "orbitguard" and not checked["accepted"]:
                policies[name]["reason"] = "Recommendation withheld: the tighter numerical verification did not pass."
                policies[name]["abstained"] = True
                selected = None
                selected_paths[name] = None
            elif name != "no_action":
                selected_paths[name] = checked_path
    no_action_secondary = policies["no_action"]["worst_secondary_pc"]
    for policy in policies.values():
        policy["introduced_secondary_hazard"] = bool(policy["introduced_secondary_hazard"] and
                                                     no_action_secondary is not None and no_action_secondary <= threshold)
    recommendation = None if selected is None else {**policies["orbitguard"], "status": "recommended"}
    output = {"scenario_id": scenario.scenario_id, "source": "synthetic", "kind": scenario.kind,
              "status": "recommended" if recommendation else "abstained", "candidates_evaluated": len(candidates),
              "elapsed_ms": (time.perf_counter() - started) * 1000,
              "risk_threshold": threshold, "max_delta_v_mps": max_dv, "uncertainty_scales": list(UNCERTAINTY_SCALES),
              "recommendation": recommendation, "policies": policies, "candidates": candidates,
              "assumptions": ASSUMPTIONS, "construction": scenario.metadata,
              "horizon_seconds": scenario.horizon_seconds,
              "risk_definition": "maximum single-encounter probability across the three prescribed uncertainty scales"}
    if include_trajectories:
        output["trajectories"] = _trajectory_data(paths, scenario, selected_paths)
        output["encounter_views"] = _encounter_views(paths, scenario, selected_paths)
        output["encounter_view"] = output["encounter_views"]["primary"]
    return output
