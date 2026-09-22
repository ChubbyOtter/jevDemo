from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

ActionVerb = Literal["tap", "type", "swipe_up", "swipe_down", "scroll_to", "wait", "back", "launch_app"]
StepKind = Literal["action", "assertion"]


@dataclass(frozen=True)
class CompiledStep:
    """One natural-language test step, compiled once (and cached) into a typed record.

    Jev only ever sees `target_description` / `assertion_text` at runtime - never the
    raw step text - since it can select among candidates but can't extract free text.
    """

    raw_text: str
    kind: StepKind
    verb: Optional[ActionVerb] = None
    literal_param: Optional[str] = None
    target_description: Optional[str] = None
    assertion_text: Optional[str] = None


@dataclass(frozen=True)
class Element:
    """A candidate interactive element from the current a11y tree."""

    index: str
    resource_id: str
    text: str
    content_desc: str
    class_name: str
    bounds: str

    def to_criteria(self) -> dict:
        return {
            "resource_id": self.resource_id or None,
            "text": self.text or None,
            "content_desc": self.content_desc or None,
            "class": self.class_name or None,
        }
