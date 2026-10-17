"""Reproducible command-line entry point for OrbitGuard."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="orbitguard",
        description="Historical encounter forecasts and synthetic manoeuvre screening.",
    )
    parser.add_argument("command", nargs="?", choices=[
        "fetch-data", "prepare-data", "train", "evaluate", "validate-physics",
        "benchmark-planner", "benchmark-runtime", "serve", "environment",
    ])
    args, remaining = parser.parse_known_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command in {"fetch-data", "prepare-data", "train", "evaluate"}:
        from orbitguard.ml.cli import main as ml_main
        return ml_main([args.command, *remaining]) or 0
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
