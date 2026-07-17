from __future__ import annotations

import sys
from pathlib import Path

# Ensure local src/ imports resolve without requiring editable install.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

try:
    from batchjobs_deploy.compiler import main
except ModuleNotFoundError as exc:
    if exc.name == "croniter":
        raise SystemExit(
            "Missing dependency 'croniter'. Install project dependencies with: "
            "python -m pip install -e '.[dev]'"
        ) from exc
    raise


if __name__ == "__main__":
    raise SystemExit(main())
