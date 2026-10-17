"""Reproducible command-line entry point for OrbitGuard."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import runpy
import sys

# Catalogue / decision / GenAI stages, run as their own module entry points with the remaining arguments.
MODULE_COMMANDS = {
    "decision-fit": ("orbitguard.decision.decision", ["fit"]),
    "decision-eval": ("orbitguard.decision.decision", ["eval"]),
    "screen-live": ("orbitguard.catalog.run", []),
    "consequence": ("orbitguard.consequence.run", []),
    "validate-breakup": ("orbitguard.consequence.validate", []),
    "network": ("orbitguard.network.run", []),
    "brief": ("orbitguard.brief.run", []),
    "audit-verify": ("orbitguard.audit", ["verify"]),
    "nnpa-bench": ("orbitguard.nnpa.bench", []),
    "nnpa-report": ("orbitguard.nnpa.report", []),
}


def _run_module(name: str, args: list[str]) -> int:
    sys.argv = [name, *args]
    try:
        runpy.run_module(name, run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="orbitguard",
        description="Collision-avoidance decision support: ESA forecasts and decision layer, validated Pc, "
                    "synthetic and real-catalogue manoeuvre screening, consequence, network, grounded brief.",
    )
    parser.add_argument("command", nargs="?", choices=[
        "fetch-data", "prepare-data", "train", "evaluate", "validate-physics",
        "benchmark-planner", "benchmark-runtime", "audit-accuracy", "train-triage", "evaluate-triage", "train-guard", "evaluate-guard", "serve", "environment",
        *MODULE_COMMANDS,
    ])
    args, remaining = parser.parse_known_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command in MODULE_COMMANDS:
        module, fixed = MODULE_COMMANDS[args.command]
        return _run_module(module, [*fixed, *remaining])
    if args.command in {"fetch-data", "prepare-data", "train", "evaluate"}:
        from orbitguard.ml.cli import main as ml_main
        return ml_main([args.command, *remaining]) or 0
    if args.command == "audit-accuracy":
        import json
        from orbitguard.ml.accuracy import audit_accuracy
        audit_parser = argparse.ArgumentParser(prog="orbitguard audit-accuracy")
        audit_parser.add_argument("--root", type=Path, default=Path(os.environ.get("ORBITGUARD_ROOT", ".")))
        audit_parser.add_argument("--bootstrap-repeats", type=int, default=1000)
        options = audit_parser.parse_args(remaining)
        if options.bootstrap_repeats < 1:
            audit_parser.error("--bootstrap-repeats must be positive")
        result = audit_accuracy(options.root, options.bootstrap_repeats)
        print(json.dumps({key: result[key] for key in ("status", "methods", "shrinkage_loss_difference")}, indent=2))
        return 0
    if args.command in {"train-triage", "evaluate-triage", "train-guard", "evaluate-guard"}:
        import json
        from orbitguard.ml.triage import train_triage, evaluate_triage
        triage_parser = argparse.ArgumentParser(prog=f"orbitguard {args.command}")
        triage_parser.add_argument("--root", type=Path, default=Path(os.environ.get("ORBITGUARD_ROOT", ".")))
        triage_parser.add_argument("--bootstrap-repeats", type=int, default=1000)
        options = triage_parser.parse_args(remaining)
        if options.bootstrap_repeats < 1:
            triage_parser.error("--bootstrap-repeats must be positive")
        if args.command in {"train-guard", "evaluate-guard"}:
            from orbitguard.ml.guard import train_guard, evaluate_guard
            result = train_guard(options.root) if args.command == "train-guard" else evaluate_guard(options.root, options.bootstrap_repeats)
        else:
            result = train_triage(options.root) if args.command == "train-triage" else evaluate_triage(options.root, options.bootstrap_repeats)
        print(json.dumps(result, indent=2))
        return 0
    if args.command in {"validate-physics", "benchmark-planner"}:
        from orbitguard.physics.cli import main as physics_main
        return physics_main([args.command, *remaining]) or 0
    if args.command == "benchmark-runtime":
        from orbitguard.runtime import main as runtime_main
        return runtime_main(remaining)
    if args.command == "environment":
        import json
        from orbitguard.runtime import environment_info
        print(json.dumps(environment_info(), indent=2))
        return 0
    server = argparse.ArgumentParser(prog="orbitguard serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    server.add_argument("--root", type=Path, default=Path(os.environ.get("ORBITGUARD_ROOT", ".")))
    options = server.parse_args(remaining)
    from orbitguard.api import create_app
    create_app(options.root).run(host=options.host, port=options.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
