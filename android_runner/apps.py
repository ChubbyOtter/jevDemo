from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_REGISTRY_PATH = Path(__file__).parent / "apps.json"


@lru_cache(maxsize=1)
def _registry() -> dict[str, str]:
    return json.loads(_REGISTRY_PATH.read_text())


def resolve_package(app_name: str) -> str:
    """Look up a friendly app name (as a test step would name it) to its package id.

    Deterministic dict lookup, not a judgment - launching an app by name is a known
    fact about the device, not something that needs Jev or an LLM to figure out.
    """
    registry = _registry()
    key = app_name.strip().lower()
    if key in registry:
        return registry[key]
    raise KeyError(
        f"No package registered for app {app_name!r}. Add it to "
        f"{_REGISTRY_PATH} (e.g. {{\"{key}\": \"com.example.app\"}}) and rerun."
    )
