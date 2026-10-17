"""CLI: python -m orbitguard.brief.run --primary 25544 [--threat ID] [--cdm-event 8]"""
from __future__ import annotations

import argparse

from .facts import collect_facts, save_facts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--primary", type=int, default=25544)
    ap.add_argument("--threat", type=int, default=None)
    ap.add_argument("--cdm-event", type=int, default=None, help="ESA test event id for the decision example")
    ap.add_argument("--days", type=float, default=3.0)
    ap.add_argument("--target-km", type=float, default=10.0)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--backend", default=None, help="template | llamacpp | openai (default: $LLM_BACKEND)")
    args = ap.parse_args(argv)
    facts = collect_facts(args.primary, args.threat, args.cdm_event, days=args.days, target_km=args.target_km,
                          workers=args.workers)
    path = save_facts(facts)
    from orbitguard.live import make_and_cache_brief  # also caches it for the console
    brief = make_and_cache_brief(facts, args.backend)
    print(brief["text"])
    print()
    print(f"[backend: {brief['backend_used']} | grounded: {brief['grounded']} | issues: {brief['issues'] or 'none'}]")
    print(f"facts: {path}; collect timings (s): "
          + ", ".join(f"{k}={v:.1f}" for k, v in facts["timings_s"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
