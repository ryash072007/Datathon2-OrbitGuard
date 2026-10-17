"""JSON-facing physics service. Construction never generates evidence."""

from __future__ import annotations

import json
from pathlib import Path

from .planner import scenario_detail, screen_scenario
from .scenarios import ASSUMPTIONS, get_scenario, summaries


class PhysicsService:
    def __init__(self, root):
        self.root = Path(root)

    def list_scenarios(self) -> list[dict]:
        return summaries()

    def get_scenario(self, scenario_id: str) -> dict:
        return scenario_detail(get_scenario(scenario_id))

    def screen(self, scenario_id: str, overrides: dict | None = None) -> dict:
        return screen_scenario(get_scenario(scenario_id), overrides)

    def evidence(self) -> dict:
        directory = self.root / "artifacts" / "physics"
        output = {"source": "synthetic", "assumptions": ASSUMPTIONS}
        for key, filename in (("validation", "validation.json"), ("benchmark", "benchmark.json"), ("runtime", "runtime.json")):
            path = directory / filename
            if path.exists():
                try:
                    output[key] = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError) as exc:
                    output[key] = {"status": "error", "message": f"Unable to read evidence: {exc}"}
            else:
                output[key] = {"status": "missing", "message": f"Run {'validate-physics' if key == 'validation' else 'benchmark-planner'} to generate this evidence."}
        output["ready"] = bool(output["validation"].get("passed") and output["benchmark"].get("status") == "complete")
        output["readiness"] = "ready" if output["ready"] else "evidence_incomplete"
        return output
