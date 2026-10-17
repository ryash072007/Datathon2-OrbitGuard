from pathlib import Path
import shutil
import subprocess


def test_evidence_pipeline_stops_before_evaluating_a_failed_training_run(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    source = Path(__file__).resolve().parents[1] / 'scripts/run-linuxone-pipeline.sh'
    shutil.copyfile(source, scripts / source.name)
    executable = tmp_path / '.venv/bin/python'
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> invoked.txt\nexit 9\n')
    executable.chmod(0o755)
    result = subprocess.run(['bash', str(scripts / source.name)], capture_output=True, text=True)
    assert result.returncode == 9
    assert len((tmp_path / 'invoked.txt').read_text().splitlines()) == 1
    assert 'FAIL train' in result.stdout
    assert 'DONE' not in result.stdout
