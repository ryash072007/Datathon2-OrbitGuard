"""Explicit SSH operations without transferring local credentials.

Example: python3 scripts/linuxone.py inspect --host VM_IP --key key.pem
Commands: inspect, sync, sync-data, fetch-results, tunnel. Remote project is
always ~/orbitguard. The key is passed only to the local OpenSSH process.
"""

from __future__ import annotations
import argparse
from pathlib import Path
import shlex
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["inspect", "sync", "sync-data", "fetch-results", "tunnel"])
    p.add_argument("--host", required=True)
    p.add_argument("--user", default="linux1")
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--known-hosts", type=Path, default=Path("/tmp/orbitguard-known-hosts"))
    p.add_argument("--local-port", type=int, default=8080)
    a = p.parse_args()
    if not a.key.is_file():
        p.error("SSH private key file does not exist")
    if any(c in a.host + a.user for c in "\n\r \t;|&$`'") or a.host.startswith("-") or a.user.startswith("-"):
        p.error("Host and user must be SSH destination identifiers")
    root = Path(__file__).resolve().parents[1]
    ssh = ["ssh", "-i", str(a.key.resolve()), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
           "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new",
           "-o", f"UserKnownHostsFile={a.known_hosts.resolve()}"]
    destination = f"{a.user}@{a.host}"
    if a.command == "inspect":
        return subprocess.call(ssh + [destination, "uname -m; nproc; free -h; df -h /; python3 --version"])
    if a.command == "tunnel":
        return subprocess.call(ssh + ["-N", "-o", "ExitOnForwardFailure=yes", "-L", f"127.0.0.1:{a.local_port}:127.0.0.1:8000", destination])
    rsync = ["rsync", "-az", "--partial", "-e", shlex.join(ssh)]
    if a.command == "sync":
        # Never --delete: remote native venv and generated scientific evidence
        # belong to the deployment and must survive a source synchronization.
        excluded = [".git", ".venv", "__pycache__", "*.pyc", ".pytest_cache", "*.egg-info", "node_modules",
                    "artifacts", "data", ".env", ".env.*", "*.pem", "*.key", "*.ppk", "*.log", ".orbitguard_known_hosts"]
        for item in excluded:
            rsync.extend(["--exclude", item])
        return subprocess.call(rsync + [str(root) + "/", destination + ":orbitguard/"])
    if a.command == "sync-data":
        subprocess.run(ssh + [destination, "mkdir -p ~/orbitguard/artifacts/ml/data"], check=True)
        names = ["train_data.zip", "test_data.csv", "test_labels_member.bin"]
        sources = [root / "artifacts/ml/data" / name for name in names]
        if any(not path.is_file() for path in sources):
            p.error("Run fetch-data locally before sync-data")
        return subprocess.call(rsync + [str(path) for path in sources] + [destination + ":orbitguard/artifacts/ml/data/"])
    target = root / "artifacts" / "linuxone"
    target.mkdir(parents=True, exist_ok=True)
    return subprocess.call(rsync + ["--exclude", "data", destination + ":orbitguard/artifacts/", str(target) + "/"])


if __name__ == "__main__":
    sys.exit(main())
