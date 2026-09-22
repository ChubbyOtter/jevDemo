from __future__ import annotations

from typing import Literal, Optional

import anthropic
from pydantic import BaseModel

from .cache import CompileCache
from .models import CompiledStep

SYSTEM_PROMPT = """\
You compile one natural-language UI test step into a typed record for a mobile test \
runner. The runner later matches `target_description` against real screen elements \
using a separate judgment model (Jev) that can only SELECT among candidates it is \
given - it cannot invent or extract free text. So any literal value the step names \
(text to type, a search query, etc.) must come from you now, in `literal_param`.

Fields:
- kind: "action" if the step performs an action on the UI (tap, type, swipe, wait, \
  go back, launch an app). "assertion" if it only checks that something is \
  true/visible, without acting.
- verb (action steps only): one of tap, type, swipe_up, swipe_down, scroll_to, wait, \
  back, launch_app.
- literal_param: for verb="type", the literal text to type (e.g. the step \
  `Type "hunter2" into the password field` -> literal_param="hunter2"; for an \
  unquoted value like `enter the confirmation code 482913`, still extract the literal \
  "482913"). For verb="launch_app", the app's name exactly as named in the step \
  (e.g. `Open the ExampleApp app` -> literal_param="ExampleApp") - this is looked up in a \
  registry by the runner, not matched by Jev, so use the plain name the step gives, \
  not a package id. Null for every other verb.
- target_description: a natural-language description of the UI element being acted \
  on, for tap / type / scroll_to (e.g. "the login button", "the username field"). \
  Null for swipe_up / swipe_down / wait / back / launch_app and for assertion steps.
- assertion_text: for assertion steps only, the natural-language condition to verify \
  against the current screen (e.g. "an error message about invalid credentials is \
  shown"). Null for action steps.

Only one of target_description / assertion_text is ever set, matching kind.
"""


class _CompiledStepSchema(BaseModel):
    kind: Literal["action", "assertion"]
    verb: Optional[
        Literal["tap", "type", "swipe_up", "swipe_down", "scroll_to", "wait", "back", "launch_app"]
    ] = None
    literal_param: Optional[str] = None
    target_description: Optional[str] = None
    assertion_text: Optional[str] = None


class StepCompiler:
    """Turns each raw step into a CompiledStep once, then never again.

    The Anthropic client is constructed lazily, on the first actual cache miss -
    a test file compiled entirely offline (e.g. by a coding agent writing straight
    into the CompileCache, see `precompile.py`) never touches ANTHROPIC_API_KEY.
    """

    def __init__(self, cache: CompileCache, model: str = "claude-opus-5"):
        self._client: Optional[anthropic.Anthropic] = None
        self._cache = cache
        self._model = model

    def compile(self, step_text: str) -> CompiledStep:
        cached = self._cache.get(step_text)
        if cached is not None:
            return cached

        if self._client is None:
            try:
                self._client = anthropic.Anthropic()
            except Exception as exc:
                raise RuntimeError(
                    f"No compiled record for step {step_text!r} and no Anthropic "
                    "credentials available to compile it live. Either set "
                    "ANTHROPIC_API_KEY, or pre-compile this test file offline "
                    "(e.g. have a coding agent write the record via "
                    "android_runner.precompile) and rerun."
                ) from exc

        response = self._client.messages.parse(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": step_text}],
            output_format=_CompiledStepSchema,
        )
        parsed = response.parsed_output

        compiled = CompiledStep(
            raw_text=step_text,
            kind=parsed.kind,
            verb=parsed.verb,
            literal_param=parsed.literal_param,
            target_description=parsed.target_description,
            assertion_text=parsed.assertion_text,
        )
        self._cache.set(step_text, compiled)
        return compiled
