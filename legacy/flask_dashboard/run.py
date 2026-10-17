"""Entry point: python -m legacy.flask_dashboard.run   (PORT env, default 8080, bound to 0.0.0.0)"""
from __future__ import annotations

import os

from .app import create_app


def main() -> int:
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
