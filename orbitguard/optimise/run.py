"""CLI: compare the constrained-BO burn search with equal-budget non-learned baselines.

    python -m orbitguard.optimise.run synthetic --count 50 --budget 37 --seed 0
    python -m orbitguard.optimise.run live --primary 25544 --budget 40

Writes ``artifacts/optimise/evidence.json`` (or ``evidence_<mode>_<budget>.json`` with ``--tag``). All numbers are
computed from the physics rule here; nothing is typed by hand.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
from pathlib import Path

import numpy as np

from . import search as S

SYNTH_T_MIN, SYNTH_T_MAX = 300.0, 1500.0   # hull of the planner's BURN_TIMES
TIE_RTOL = 1e-6


# ------------------------------------------------------------------------------------------------ synthetic

class SyntheticProblem(S.Problem):
    """Single tangential burn on a frozen synthetic scenario; feasibility = the planner's all-object rule."""
    name = "synthetic"

    def __init__(self, scenario, threshold=None):
        from orbitguard.physics import planner
        from orbitguard.physics.orbits import propagate
        self._planner = planner
        self.scenario = scenario
        self.threshold = planner.RISK_THRESHOLD if threshold is None else threshold
        self.t_min, self.t_max, self.dv_max = SYNTH_T_MIN, SYNTH_T_MAX, 1.0
        horizon = scenario.horizon_seconds
        self.paths = {o.object_id: propagate(o.state, horizon) for o in scenario.objects}
        self._tight = None

    def _eval(self, paths, t, dv, tight):
        try:
            cand, _ = self._planner._candidate(self.scenario, paths, t, dv, self.threshold, tight=tight)
        except (ValueError, FloatingPointError):
            return None
        return cand

    def evaluate(self, t, dv):
        cand = self._eval(self.paths, t, dv, False)
        if cand is None or not cand["valid"]:
            return S.Point(t, dv, S.IMPOSSIBLE, False)
        return S.Point(t, dv, S.margin_from_pc(cand["worst_pc"], self.threshold), bool(cand["accepted"]))

    def verify(self, point):
        from orbitguard.physics.orbits import propagate
        if self._tight is None:
            self._tight = {o.object_id: propagate(o.state, self.scenario.horizon_seconds, tight=True)
                           for o in self.scenario.objects}
        cand = self._eval(self._tight, point.t, point.dv, True)
        return bool(cand is not None and cand["valid"] and cand["accepted"])

    def grid(self):
        return self._planner.candidate_grid(self.dv_max)


# ------------------------------------------------------------------------------------------------ comparison

def run_methods(problem: S.Problem, budget: int, seed: int) -> dict:
    """All methods on one problem. Equal-budget methods get ``budget`` physics evaluations (no-action included)."""
    grid = S.run_grid(problem)
    warm = grid.point if grid.point is not None and grid.point.t is not None else None
    results = {
        "grid": grid,
        "random": S.run_random(problem, budget, seed),
        "random_log": S.run_random(problem, budget, seed, log_dv=True),
        "fine_grid": S.run_fine_grid(problem, budget),
        "bo": S.run_bo(problem, budget, seed),
        "random_warm": S.run_random(problem, budget, seed, log_dv=True, warm=warm),
        "bo_warm": S.run_bo(problem, budget, seed, warm=warm),
    }
    out = {}
    for name, r in results.items():
        out[name] = {"dv_mps": r.dv_abs, "signed_dv_mps": None if r.point is None else r.point.dv,
                     "burn_param": None if r.point is None else r.point.t, "found": r.point is not None,
                     "evaluations": r.evaluations, "verifications": r.verifications,
                     "seconds": r.seconds}
    return out


def compare(per_scenario: list[dict], methods: tuple[str, ...], seed: int) -> dict:
    """Per-method summary against the grid, paired by scenario."""
    summary = {}
    for m in methods:
        ratios, wins, ties, losses = [], 0, 0, 0
        found = 0
        grid_abstain_found, grid_found_abstain = [], []
        evals, secs = [], []
        for sc in per_scenario:
            g, r = sc["methods"]["grid"], sc["methods"][m]
            found += r["found"]
            evals.append(r["evaluations"])
            secs.append(r["seconds"])
            if not g["found"] and r["found"]:
                grid_abstain_found.append(sc["scenario_id"])
            if g["found"] and not r["found"]:
                grid_found_abstain.append(sc["scenario_id"])
            if g["found"] and r["found"]:
                gd, rd = g["dv_mps"], r["dv_mps"]
                if abs(rd - gd) <= TIE_RTOL * max(gd, 1e-12):
                    ties += 1
                elif rd < gd:
                    wins += 1
                else:
                    losses += 1
                if gd > 0:
                    ratios.append(rd / gd)
        both = [x for x in ratios]
        summary[m] = {
            "feasible_found": found, "feasible_found_rate": found / len(per_scenario),
            "wins_vs_grid": wins, "ties_vs_grid": ties, "losses_vs_grid": losses,
            "dv_ratio_vs_grid": {"mean": float(np.mean(both)) if both else None,
                                 "median_ci95": S.bootstrap_median_ci(both, seed)},
            "grid_abstains_method_finds": grid_abstain_found,
            "grid_finds_method_abstains": grid_found_abstain,
            "mean_evaluations": float(np.mean(evals)), "total_seconds": float(np.sum(secs)),
            "mean_dv_mps_when_found": float(np.mean([sc["methods"][m]["dv_mps"] for sc in per_scenario
                                                     if sc["methods"][m]["found"]])) if found else None,
        }
    return summary


def platform_info() -> dict:
    return {"hostname": socket.gethostname(), "machine": platform.machine(), "byteorder": sys.byteorder,
            "system": platform.system(), "python": platform.python_version(), "numpy": np.__version__,
            "processor": platform.processor()}


def summary_line(summary: dict, n: int, budget: int, grid_count: int) -> str:
    def f(m):
        s = summary[m]
        ci = s["dv_ratio_vs_grid"]["median_ci95"]
        med = "n/a" if ci["median"] is None else f"{ci['median']:.3f} [{ci['lo']:.3f}, {ci['hi']:.3f}]"
        return (f"{m}: median dv ratio {med}, W/T/L {s['wins_vs_grid']}/{s['ties_vs_grid']}/{s['losses_vs_grid']}, "
                f"found {s['feasible_found']}/{n}")
    return (f"{n} scenarios, budget {budget} evaluations per method (grid uses {grid_count}). "
            + "; ".join(f(m) for m in ("bo", "bo_warm", "random", "random_log", "fine_grid")))


def _scenario_job(args):
    sid, budget, seed = args
    from orbitguard.physics.scenarios import get_scenario
    scenario = get_scenario(sid)
    problem = SyntheticProblem(scenario)
    return {"scenario_id": sid, "kind": scenario.kind, "methods": run_methods(problem, budget, seed)}


def run_synthetic(count: int, budget: int, seed: int, workers: int = 1, out_dir: Path | None = None,
                  tag: str | None = None, progress: bool = True) -> dict:
    from orbitguard.physics.planner import candidate_grid
    from orbitguard.physics.scenarios import suite_ids
    ids = suite_ids()[:count]
    jobs = [(sid, budget, seed + i) for i, sid in enumerate(ids)]
    started = time.perf_counter()
    if workers > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(workers) as pool:
            per = pool.map(_scenario_job, jobs)
    else:
        per = []
        for i, job in enumerate(jobs):
            per.append(_scenario_job(job))
            if progress:
                print(f"scenario {i + 1}/{len(jobs)} {job[0]}", flush=True)
    methods = tuple(per[0]["methods"])
    summary = compare(per, methods, seed)
    grid_count = len(candidate_grid(1.0))
    blocked = [sc for sc in per if sc["kind"] == "blocked"]
    impossible_flags = {m: [sc["scenario_id"] for sc in blocked if sc["methods"][m]["found"]] for m in methods}
    evidence = {
        "mode": "synthetic", "scenarios": count, "budget_evaluations": budget, "seed": seed,
        "grid_evaluations": grid_count, "workers": workers,
        "search_space": {"burn_time_seconds": [SYNTH_T_MIN, SYNTH_T_MAX], "delta_v_mps": [-1.0, 1.0],
                         "direction": "tangential (the only direction the synthetic planner supports)"},
        "platform": platform_info(), "elapsed_seconds": time.perf_counter() - started,
        "summary": summary, "designed_impossible_found_by": impossible_flags,
        "designed_impossible_all_abstain": all(not v for v in impossible_flags.values()),
        "notes": [
            "Feasibility is the planner's exact all-object rule (worst-case Pc over 0.5x/1x/2x sigma <= 1e-4); every "
            "recommendation is an evaluated point that also passes the planner's tighter numerical verification.",
            "Safety margin learned by the GP: clip(log10(1e-4) - log10(worst Pc), -8, 8); invalid evaluation = -8.",
            "Evaluations counted include the no-action probe; verification re-propagations are reported separately.",
            "bo and random* are cold (no grid knowledge). bo_warm and random_warm seed the grid's best burn, which "
            "needs the grid's own evaluations first (grid_evaluations), so their total cost is budget + grid_evaluations.",
            "random = uniform in signed dv; random_log = uniform in the log-warped dv used by BO; fine_grid = regular "
            "time x log-spaced dv grid sized to the budget.",
            "dv ratio = method dv / grid dv over scenarios where both find a burn and the grid needs dv > 0.",
            "Wall time is single-process unless workers > 1.",
        ],
        "per_scenario": per,
    }
    evidence["one_line_summary"] = summary_line(summary, count, budget, grid_count)
    out_dir = out_dir or Path(os.environ.get("ORBITGUARD_ROOT", Path.cwd())) / "artifacts" / "optimise"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("evidence.json" if tag is None else f"evidence_{tag}.json")
    path.write_text(json.dumps(evidence, indent=1, allow_nan=False))
    evidence["path"] = str(path)
    return evidence


# ------------------------------------------------------------------------------------------------ live

class LiveProblem(S.Problem):
    """Single along-track burn (+T for dv > 0, -T for dv < 0) before a real-catalogue TCA, screened by
    ``catalog.screen.run_burns`` (miss target AND every encounter's worst-case Pc <= threshold). The burn
    parameter is the lead time in orbital periods. Verification is a deterministic re-screen; the catalogue
    screener has no tighter numerical mode."""
    name = "live"

    def __init__(self, ctx, tca, period_min, lead_min, lead_max, dv_max, pc_threshold, target_km):
        from datetime import timedelta
        self._td = timedelta
        self.ctx, self.tca, self.period_min = ctx, tca, period_min
        self.t_min, self.t_max, self.dv_max = lead_min, lead_max, dv_max
        self.threshold, self.target_km = pc_threshold, target_km

    def _burn(self, lead, dv):
        from orbitguard.catalog.burns import Burn
        when = (self.tca - self._td(minutes=lead * self.period_min)).replace(microsecond=0)
        return Burn(f"{'+' if dv >= 0 else '-'}T_{abs(dv):.5g}_{lead:.4g}P", "+T" if dv >= 0 else "-T", abs(dv), when, lead)

    def _row(self, burn):
        from orbitguard.catalog.screen import run_burns
        return run_burns(self.ctx, [burn], 1).iloc[0]

    def evaluate(self, t, dv):
        from orbitguard.catalog.burns import Burn
        if t is None:
            row = self._row(Burn("none", "none", 0.0, self.ctx.t0, 0.0))
        else:
            row = self._row(self._burn(t, dv))
        if not bool(row["pc_valid"]) or not np.isfinite(row["worst_pc"]):
            return S.Point(t, dv, S.IMPOSSIBLE, False)
        pc_margin = S.margin_from_pc(float(row["worst_pc"]), self.threshold)
        miss_margin = float(np.clip((row["miss_km_threat"] - self.target_km) / self.target_km, -S.MARGIN_CLIP, S.MARGIN_CLIP))
        return S.Point(t, dv, min(pc_margin, miss_margin), bool(row["accepted"]))

    def verify(self, point):
        return self.evaluate(point.t, point.dv).feasible

    def grid(self):
        from orbitguard.catalog.burns import DV_MPS_GRID, LEAD_PERIODS
        leads = [x for x in LEAD_PERIODS if self.t_min <= x <= self.t_max]
        return [(None, 0.0)] + [(lead, sign * dv) for lead in leads for dv in DV_MPS_GRID for sign in (1.0, -1.0)]


def run_live(primary: int, budget: int, seed: int, *, threat: int | None = None, target_km: float = 10.0,
             tag: str | None = None, days: float = 3.0, out_dir: Path | None = None) -> dict:
    """Same comparison on one real conjunction found in the current CelesTrak catalogue."""
    from datetime import datetime, timedelta, timezone

    from orbitguard.catalog.burns import Burn, DV_MPS_GRID, LEAD_PERIODS
    from orbitguard.catalog.catalog import load_catalog, period_min_from_tle
    from orbitguard.catalog.screen import find_approach, prepare
    started = time.perf_counter()
    records = load_catalog()
    by_id = {r.norad: r for r in records}
    if primary not in by_id:
        raise ValueError(f"primary NORAD {primary} not in the catalogue")
    prim = by_id[primary]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    period = period_min_from_tle(prim.line2)
    found = find_approach(prim, records, now + timedelta(minutes=0.5 * period + 2), days, only_norad=threat)
    tca = found["tca"].replace(microsecond=0)
    lead_max = min(max(LEAD_PERIODS), ((tca - now).total_seconds() - 60.0) / (period * 60.0))
    lead_min = min(LEAD_PERIODS)
    if lead_max <= lead_min:
        raise ValueError("no burn lead time fits between now and the TCA")
    earliest = Burn("seed", "+T", 0.01, (tca - timedelta(minutes=lead_max * period)).replace(microsecond=0), lead_max)
    ctx = prepare(prim.tle, records, tca, [earliest], target_km=target_km, r_km=5.0, threat_norad=found["record"].norad)
    problem = LiveProblem(ctx, tca, period, lead_min, lead_max, max(DV_MPS_GRID), ctx.pc_threshold, target_km)
    methods = run_methods(problem, budget, seed)
    evidence = {
        "mode": "live", "primary_norad": primary, "threat_norad": found["record"].norad, "tca_utc": tca.isoformat(),
        "budget_evaluations": budget, "seed": seed, "grid_evaluations": len(problem.grid()),
        "search_space": {"lead_periods": [lead_min, lead_max], "delta_v_mps": [-problem.dv_max, problem.dv_max],
                         "direction": "along-track (+T / -T) only; R and N are not searched"},
        "target_km": target_km, "pc_threshold": ctx.pc_threshold, "platform": platform_info(),
        "elapsed_seconds": time.perf_counter() - started, "methods": methods,
        "notes": ["Single conjunction: no statistics. Feasibility = catalogue screener 'accepted' (miss target and "
                  "all-object worst-case Pc). Margin = min(Pc decades, (miss-target)/target), clipped.",
                  "Burn time is quantised to the screener's 60 s ephemeris grid."],
    }
    g = methods["grid"]["dv_mps"]
    evidence["one_line_summary"] = (f"live NORAD {primary} vs {found['record'].norad}: dv_mps by method "
                                    + ", ".join(f"{k}={'abstain' if v['dv_mps'] is None else format(v['dv_mps'], '.4g')}"
                                                for k, v in methods.items())
                                    + f" (grid {'abstains' if g is None else format(g, '.4g')})")
    out_dir = out_dir or Path(os.environ.get("ORBITGUARD_ROOT", Path.cwd())) / "artifacts" / "optimise"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (f"evidence_live_{primary}.json" if tag is None else f"evidence_{tag}.json")
    path.write_text(json.dumps(evidence, indent=1, allow_nan=False))
    evidence["path"] = str(path)
    return evidence


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("synthetic")
    s.add_argument("--count", type=int, default=50)
    s.add_argument("--budget", type=int, default=37)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--workers", type=int, default=1)
    s.add_argument("--tag", default=None, help="write evidence_<tag>.json instead of evidence.json")
    lv = sub.add_parser("live")
    lv.add_argument("--primary", type=int, required=True)
    lv.add_argument("--threat", type=int, default=None)
    lv.add_argument("--budget", type=int, default=40)
    lv.add_argument("--seed", type=int, default=0)
    lv.add_argument("--target-km", type=float, default=10.0)
    lv.add_argument("--tag", default=None)
    args = ap.parse_args(argv)
    if args.mode == "synthetic":
        if not 1 <= args.count <= 50:
            ap.error("--count must be in 1..50")
        ev = run_synthetic(args.count, args.budget, args.seed, args.workers, tag=args.tag)
    else:
        ev = run_live(args.primary, args.budget, args.seed, threat=args.threat, target_km=args.target_km, tag=args.tag)
    print(ev["one_line_summary"])
    print("wrote", ev["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
