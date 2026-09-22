from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .cache import CompileCache
from .models import CompiledStep


def precompile(cache_path: Path, compiled_steps: Iterable[CompiledStep]) -> None:
    """Write hand-compiled steps directly into the compile cache.

    This is the offline counterpart to `StepCompiler.compile()`: instead of a live
    Anthropic call turning a raw step into a CompiledStep, a coding agent (or a human)
    does that reasoning once and writes the result here. `StepCompiler` then treats
    each entry as an ordinary cache hit and never touches ANTHROPIC_API_KEY for it -
    see the SYSTEM_PROMPT in compiler.py for the exact field semantics to follow.
    """
    cache = CompileCache(cache_path)
    for compiled in compiled_steps:
        cache.set(compiled.raw_text, compiled)
