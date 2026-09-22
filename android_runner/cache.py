from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .models import CompiledStep


class CompileCache:
    """Persists compiled steps keyed by a hash of the raw step text, so an unchanged
    test file recompiles nothing on rerun - only Jev calls happen at runtime.
    """

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            self._data = json.loads(path.read_text())

    @staticmethod
    def _key(step_text: str) -> str:
        return hashlib.sha256(step_text.encode("utf-8")).hexdigest()

    def get(self, step_text: str) -> Optional[CompiledStep]:
        raw = self._data.get(self._key(step_text))
        if raw is None:
            return None
        return CompiledStep(**raw)

    def set(self, step_text: str, compiled: CompiledStep) -> None:
        self._data[self._key(step_text)] = asdict(compiled)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2))
