"""Information-flow boundaries, enforced statically (AST) so a judge can read them. See docs/DATA_BOUNDARIES.md."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "orbitguard"

LABEL_READERS = {"read_labels", "read_labels_after_freeze", "unseal_labels"}
# Evaluation entry points that may open the sealed label member (after their artefact is frozen).
EVAL_ENTRY_POINTS = {
    "decision/evaluate.py", "decision/workload.py",
    "ml/accuracy.py", "ml/guard.py", "ml/model.py", "ml/triage.py",
}
GATE_FILES = ["physics/*.py", "catalog/screen.py", "catalog/collision.py", "catalog/propagate.py",
              "catalog/catalog.py", "catalog/burns.py", "catalog/parallel.py"]
GATE_FORBIDDEN = ("orbitguard.brief", "orbitguard.ml", "orbitguard.decision", "orbitguard.optimise",
                  "orbitguard.zai", "orbitguard.live", "orbitguard.api", "orbitguard.audit")
NO_LLM_FILES = ["decision/*.py", "ml/*.py", "physics/*.py", "catalog/screen.py", "optimise/*.py"]
SERVING_FILES = ["api.py", "live.py", "ml/service.py", "decision/predict.py", "brief/*.py",
                 "catalog/*.py", "physics/*.py", "optimise/*.py"]
NETWORK_MODULES = ("urllib", "requests", "socket", "http", "httpx", "ftplib", "smtplib", "aiohttp")


def files(patterns):
    out = set()
    for pat in patterns:
        out.update(PKG.glob(pat))
    return sorted(out)


def rel(path: Path) -> str:
    return path.relative_to(PKG).as_posix()


def imports(path: Path):
    """Yield (absolute module, imported name or None, lineno) for every import, relative ones resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg_parts = ["orbitguard", *path.relative_to(PKG).parent.parts]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, None, node.lineno
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                base = ".".join(parent + ([node.module] if node.module else []))
            for a in node.names:
                yield base, a.name, node.lineno


def full_names(path: Path):
    for mod, name, line in imports(path):
        yield mod, line
        if name and name != "*":
            yield f"{mod}.{name}", line


def hits(paths, prefixes):
    bad = []
    for p in paths:
        for full, line in full_names(p):
            if any(full == q or full.startswith(q + ".") for q in prefixes):
                bad.append(f"{rel(p)}:{line} imports {full}")
    return sorted(set(bad))


def label_uses(path: Path):
    """Line numbers where a label reader is imported or called."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            lines += [node.lineno for a in node.names if a.name in LABEL_READERS]
        elif isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name in LABEL_READERS:
                lines.append(node.lineno)
    return lines


def calls_name(fn_node, name):
    for c in ast.walk(fn_node):
        if isinstance(c, ast.Call):
            f = c.func
            if (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name):
                return True
    return False


def test_only_ml_data_names_sealed_label_member():
    bad = [rel(p) for p in PKG.rglob("*.py")
           if rel(p) != "ml/data.py" and "test_labels_member" in p.read_text(encoding="utf-8")]
    assert not bad, f"sealed label member named outside orbitguard/ml/data.py: {bad}"
    assert "test_labels_member.bin" in (PKG / "ml/data.py").read_text(encoding="utf-8")


def test_label_readers_called_only_from_evaluation_entry_points():
    bad = []
    for p in PKG.rglob("*.py"):
        r = rel(p)
        if r == "ml/data.py" or r in EVAL_ENTRY_POINTS:
            continue
        bad += [f"{r}:{n}" for n in label_uses(p)]
    assert not bad, f"label reader used outside evaluation entry points {sorted(EVAL_ENTRY_POINTS)}: {bad}"


def test_serving_code_never_imports_or_calls_label_readers():
    bad = []
    for p in files(SERVING_FILES):
        bad += [f"{rel(p)}:{n} uses a label reader" for n in label_uses(p)]
    assert not bad, "serving code reaches sealed labels:\n" + "\n".join(sorted(set(bad)))


def test_evaluation_allow_list_is_not_stale():
    stale = [r for r in sorted(EVAL_ENTRY_POINTS) if not label_uses(PKG / r)]
    assert not stale, f"allow-listed evaluation files no longer open labels (shrink the list): {stale}"


def test_label_reader_refuses_unfrozen_artifact(tmp_path):
    from orbitguard.ml.data import read_labels_after_freeze
    with pytest.raises(ValueError, match="Freeze"):
        read_labels_after_freeze(tmp_path, tmp_path / "missing.joblib")


def test_forecast_service_rejects_labels_and_late_cdms(tmp_path):
    # Fuller coverage: tests/test_ml.py::test_inference_rejects_mixed_events_labels_and_sparse_failures.
    from orbitguard.ml.service import MLService
    svc = MLService(tmp_path)
    with pytest.raises(ValueError, match="Evaluation labels"):
        svc.forecast([{"event_id": 1, "risk": -5, "time_to_tca": 3, "true_risk": -4}])
    with pytest.raises(ValueError, match="at least 2"):
        svc.forecast([{"event_id": 1, "risk": -5, "time_to_tca": 1.9}])


def test_physics_gate_imports_nothing_learned_or_generated():
    bad = hits(files(GATE_FILES), GATE_FORBIDDEN)
    assert not bad, "physics safety gate depends on non-physics code:\n" + "\n".join(bad)


def test_no_llm_in_decision_path():
    bad = hits(files(NO_LLM_FILES), ["orbitguard.brief", "llama_cpp"])
    assert not bad, "decision path imports the LLM layer:\n" + "\n".join(bad)


def test_brief_never_imports_label_readers():
    paths = files(["brief/*.py"])
    bad = hits(paths, ["orbitguard.ml.data"])
    bad += [f"{rel(p)}:{n} calls a label reader" for p in paths for n in label_uses(p)]
    assert not bad, "Granite layer can reach sealed labels:\n" + "\n".join(bad)


def test_brief_network_code_is_only_the_openai_compatible_backend():
    bad = [b for b in hits(files(["brief/*.py"]), NETWORK_MODULES) if not b.startswith("brief/backends.py:")]
    assert not bad, "network-capable import outside brief/backends.py:\n" + "\n".join(bad)
    assert hits([PKG / "brief/backends.py"], ["urllib"]), "backends.py no longer uses urllib; update this boundary"


def test_granite_prompt_facts_come_from_facts_module():
    # The narrator only receives a facts dict; facts.py computes it, and the runners wire the two together.
    tree = ast.parse((PKG / "brief/brief.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "make_brief_from_facts")
    assert fn.args.args[0].arg == "facts", "brief.py:make_brief_from_facts no longer takes computed facts first"
    assert hits([PKG / "brief/run.py"], ["orbitguard.brief.facts"]), "brief/run.py no longer sources facts from facts.py"


def test_learned_search_only_returns_physics_verified_burns():
    tree = ast.parse((PKG / "optimise/search.py").read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    # select_verified re-checks every candidate with problem.verify before it can be returned.
    assert calls_name(funcs["select_verified"], "verify"), "search.py: select_verified no longer calls problem.verify"
    assert calls_name(funcs["_finish"], "select_verified"), "search.py: _finish does not use select_verified"
    # Every run_* strategy builds its Result through _finish.
    for name, fn in funcs.items():
        if name.startswith("run_"):
            assert calls_name(fn, "_finish"), f"search.py:{fn.lineno} {name} returns without _finish/select_verified"


def test_live_problem_uses_the_all_object_physics_rule():
    # Runtime feasibility is covered by tests/test_optimise.py::test_bo_recommendation_is_physics_feasible.
    p = PKG / "optimise/run.py"
    names = {n for n, _ in full_names(p)}
    assert "orbitguard.catalog.screen.run_burns" in names, "optimise/run.py no longer uses catalog.screen.run_burns"
    assert any(n.startswith("orbitguard.physics.planner") for n in names), \
        "optimise/run.py no longer uses physics.planner for the synthetic problem"
