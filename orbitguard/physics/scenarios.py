"""Reproducible synthetic stress tests; not an orbital catalogue."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from .orbits import MU_EARTH, apply_burn, integrate, propagate

HORIZON_SECONDS = 10800.0
SIGMA_CONTROLLED = (20.0, 100.0, 20.0)
SIGMA_OTHER = (30.0, 150.0, 30.0)


@dataclass
class OrbitalObject:
    object_id: str
    name: str
    role: str
    state: np.ndarray
    sigma_rtn_m: tuple = SIGMA_OTHER
    radius_m: float = 5.0


@dataclass
class Scenario:
    scenario_id: str
    name: str
    description: str
    kind: str
    objects: list[OrbitalObject]
    seed: int
    primary_tca_seconds: float
    secondary_tca_seconds: float = 6000.0
    horizon_seconds: float = HORIZON_SECONDS
    metadata: dict = field(default_factory=dict)


ASSUMPTIONS = [
    "Synthetic neighbourhood: one controlled satellite and seven surrounding objects; not ESA-reconstructed or live orbits.",
    "Earth-centred inertial coordinates, SI units, two-body gravity, instantaneous tangential burns, three-hour horizon.",
    "Collision probability uses a circular hard body and Gaussian independent position errors in a short, rectilinear encounter approximation.",
    "Local RTN position standard deviations are prescribed at each encounter, not propagated orbit-determination covariances.",
    "Controlled satellite RTN uncertainty: 20/100/20 m; surrounding objects: 30/150/30 m; each object radius: 5 m.",
    "Screening repeats calculations at 0.5, 1 and 2 times the prescribed standard deviations; this finite sensitivity test is not a guarantee.",
    "Acceptance threshold is 1e-4 per encounter and differs from ESA's 1e-6 forecast classification threshold.",
    "Only the controlled satellite may manoeuvre; delta-v is a fuel-use proxy, not kilograms of propellant.",
    "No J2, drag, debris fragmentation, cooperative manoeuvres, velocity uncertainty, or operational safety certification.",
    "Probability is evaluated at interior closest approaches; partial encounters at horizon boundaries and slow co-orbital cases are outside this scenario suite.",
]


def _rotation_z(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _crossing_state(reference, time, miss_m, angle=0.18):
    state = reference(time).copy()
    radial = state[:3] / np.linalg.norm(state[:3])
    normal = np.cross(state[:3], state[3:])
    normal /= np.linalg.norm(normal)
    # The miss lies normal to both radial and the relative crossing velocity.
    state[:3] += float(miss_m) * radial
    # A small energy difference separates other nodal passages in time. Equal
    # circular periods would otherwise create repeated close passes every
    # half orbit, including before the first permitted burn.
    state[3:] = 1.003 * (np.cos(angle) * state[3:] + np.sin(angle) * np.linalg.norm(state[3:]) * normal)
    return integrate(state, time, 0)(0)


def summaries() -> list[dict]:
    return [
        {"scenario_id": "chain-reaction", "name": "Avoid B without endangering C", "kind": "secondary",
         "description": "A cheap original-pair manoeuvre creates a second encounter; compare all-object screening.", "source": "synthetic"},
        {"scenario_id": "primary-only", "name": "One encounter, minimal burn", "kind": "primary",
         "description": "An isolated hazardous approach with several feasible avoidance options.", "source": "synthetic"},
        {"scenario_id": "clear-neighbourhood", "name": "No unnecessary manoeuvre", "kind": "clear",
         "description": "A clear neighbourhood: preserve fuel by selecting no action.", "source": "synthetic"},
        {"scenario_id": "no-feasible-burn", "name": "Too late for the permitted burn window", "kind": "blocked",
         "description": "The primary encounter occurs before the first permitted burn. Report an explicit abstention.", "source": "synthetic"},
    ]


def _build(scenario_id: str, kind: str, seed: int, *, illustrative=False) -> Scenario:
    rng = np.random.default_rng(seed)
    radius = 7_078_000.0 + (0 if illustrative else rng.uniform(-20000, 20000))
    speed = np.sqrt(MU_EARTH / radius)
    initial = np.array([radius, 0, 0, 0, speed, 0], dtype=float)
    nominal = propagate(initial, HORIZON_SECONDS)
    primary_time = 3600.0 if illustrative else float(rng.uniform(3300, 3900))
    if kind == "blocked":
        primary_time = float(rng.uniform(100, 220))
    miss = 8000.0 if kind == "clear" else float(rng.uniform(5, 25))
    objects = [OrbitalObject("A", "Controlled satellite A", "controlled", initial, SIGMA_CONTROLLED),
               OrbitalObject("B", "Original encounter B", "primary", _crossing_state(nominal, primary_time, miss))]
    secondary_time = 6000.0 if illustrative else float(rng.uniform(5400, 6400))
    if kind == "secondary":
        # Construct C around the exact primary-only decision before C exists.
        # This is deliberate scenario construction, disclosed in all reports.
        # Evaluation measures policies on fixed stress tests, not real-world
        # event prevalence, and never changes this fixture based on results.
        from .planner import primary_only_candidate
        burn = primary_only_candidate(nominal, objects[0], objects[1], HORIZON_SECONDS)
        target = nominal if burn is None else apply_burn(nominal, burn[0], burn[1], HORIZON_SECONDS)
        c_state = _crossing_state(target, secondary_time, float(rng.uniform(5, 25)), angle=-0.23)
        construction = {"secondary_construction": "C crosses the original-pair-selected trajectory; deliberate stress scenario",
                        "target_burn_time_seconds": None if burn is None else burn[0],
                        "target_delta_v_mps": None if burn is None else burn[1]}
    else:
        c_state = _crossing_state(nominal, secondary_time, 15000.0, angle=-0.23)
        construction = {}
    objects.append(OrbitalObject("C", "Secondary encounter C", "secondary", c_state))
    for index, phase in enumerate(np.linspace(0.45, 2.45, 5), start=3):
        rotation = _rotation_z(float(phase))
        neighbour_radius = radius + index * 30000
        state = np.r_[rotation @ np.array([neighbour_radius, 0, 0]),
                      rotation @ np.array([0, np.sqrt(MU_EARTH / neighbour_radius), 0])]
        # Phase-separated, altitude-separated circular objects stay distant.
        objects.append(OrbitalObject(chr(65 + index), f"Neighbour {chr(65 + index)}", "secondary", state))
    summary = next((s for s in summaries() if s["kind"] == kind), {})
    return Scenario(scenario_id, summary.get("name", scenario_id), summary.get("description", "Synthetic fixed stress test"),
                    kind, objects, seed, primary_time, secondary_time, metadata=construction)


@lru_cache(maxsize=64)
def get_scenario(scenario_id: str) -> Scenario:
    for summary in summaries():
        if summary["scenario_id"] == scenario_id:
            return _build(scenario_id, summary["kind"], 20261017, illustrative=True)
    if scenario_id.startswith("eval-"):
        try:
            index = int(scenario_id[5:])
        except ValueError:
            raise KeyError(scenario_id) from None
        if 0 <= index < 50:
            kind = "clear" if index < 10 else "primary" if index < 20 else "secondary" if index < 40 else "blocked"
            return _build(scenario_id, kind, 42000 + index)
    raise KeyError(scenario_id)


def suite_ids() -> list[str]:
    return [f"eval-{i:02d}" for i in range(50)]
