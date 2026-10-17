"""Keep every test away from the real audit log and live-catalogue cache."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_runtime_files(tmp_path, monkeypatch):
    import orbitguard.audit.log as audit
    monkeypatch.setattr(audit, "DEFAULT_PATH", tmp_path / "audit" / "decisions.jsonl")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "live"))
