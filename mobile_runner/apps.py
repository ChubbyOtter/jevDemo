from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_REGISTRY_PATH = Path(__file__).parent / "apps.json"


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict[str, str]]:
    return json.loads(_REGISTRY_PATH.read_text())


def resolve_app_id(app_name: str, platform: str) -> str:
    """Look up a friendly app name (as a test step would name it) to its platform-
    specific app id (Android package id, or iOS bundle id).

    Deterministic dict lookup, not a judgment - launching an app by name is a known
    fact about the device, not something that needs Jev or an LLM to figure out.
    """
    registry = _registry()
    key = app_name.strip().lower()
    entry = registry.get(key)
    if entry is None:
        raise KeyError(
            f"No app registered for {app_name!r}. Add it to {_REGISTRY_PATH} "
            f"(e.g. {{\"{key}\": {{\"android\": \"com.example.app\", "
            f"\"ios\": \"com.example.app\"}}}}) and rerun."
        )
    app_id = entry.get(platform)
    if app_id is None:
        raise KeyError(
            f"App {app_name!r} is registered but has no {platform!r} entry in "
            f"{_REGISTRY_PATH}. Add one and rerun."
        )
    return app_id
