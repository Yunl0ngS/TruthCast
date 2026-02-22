import os
from pathlib import Path


def load_project_env(override: bool = False) -> None:
    root_env = Path(__file__).resolve().parents[2] / ".env"
    if not root_env.exists():
        return

    for raw_line in root_env.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        if override or key not in os.environ:
            os.environ[key] = value
