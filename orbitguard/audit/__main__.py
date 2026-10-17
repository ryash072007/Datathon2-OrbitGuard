"""python -m orbitguard.audit verify [path]"""
import sys

from .log import DEFAULT_PATH, verify_log

if len(sys.argv) < 2 or sys.argv[1] != "verify":
    sys.exit("usage: python -m orbitguard.audit verify [path]")
path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PATH
ok, bad = verify_log(path)
if ok:
    print(f"OK: audit chain intact ({path})")
else:
    print(f"TAMPERED: first bad record seq={bad} ({path})")
    sys.exit(1)
