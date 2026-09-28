from __future__ import annotations

from typing import Optional

from typesafe_sdk import Choice, Noul, TypeSafeClient

from .models import Element

NONE_OF_THESE = "none_of_these"


class GroundAndCheckResult:
    def __init__(
        self,
        target_index: Optional[str],
        target_confidence: Optional[float],
        assertion_probability: Optional[float],
        is_loading: float,
    ):
        self.target_index = target_index
        self.target_confidence = target_confidence
        self.assertion_probability = assertion_probability
        self.is_loading = is_loading


class Jev:
    """Thin wrapper around TypeSafeClient for the two judgments this runner needs:
    grounding a fuzzy element description against the current screen, and checking
    a natural-language assertion against it. Batches both into one request per screen
    alongside a speculative "is the screen still settling" check, since independent
    questions over the same state run in parallel for free.
    """

    def __init__(self, model: Optional[str] = None):
        self._client = TypeSafeClient(model=model)  # reads TYPESAFE_API_KEY from env

    def close(self) -> None:
        self._client.close()

    def ground_and_check(
        self,
        elements: list[Element],
        target_description: Optional[str],
        assertion_text: Optional[str],
        screen_text: Optional[list[str]] = None,
    ) -> GroundAndCheckResult:
        state: dict[str, object] = {"screen_elements": {el.index: el.to_criteria() for el in elements}}
        # Assertions need to judge the screen's overall meaning, not just what's
        # tappable - `elements` only carries interactive candidates (grounding never
        # needs more), so a separate all-visible-text view is included only when
        # there's an assertion to check against it.
        if assertion_text and screen_text:
            state["screen_text"] = screen_text

        questions: dict[str, Noul | Choice] = {
            "is_loading": Noul(
                instructions=(
                    "The screen appears to be in a loading or transitional state "
                    "(spinner, blank screen, skeleton placeholders) rather than settled content."
                ),
            ),
        }

        if target_description:
            criteria: dict[str, object] = {el.index: el.to_criteria() for el in elements}
            criteria[NONE_OF_THESE] = "No element on the current screen matches the target description."
            questions["target"] = Choice(
                instructions=(
                    f"Which entry in `screen_elements` is the element described as: "
                    f"{target_description!r}?"
                ),
                criteria=criteria,
            )

        if assertion_text:
            questions["assertion"] = Noul(
                instructions=(
                    "Given the current screen (`screen_text` for all visible text, "
                    f"`screen_elements` for interactive controls), is the following "
                    f"true: {assertion_text!r}"
                ),
            )

        result = self._client.system_one(state=state, questions=questions)

        target_index = None
        target_confidence = None
        if target_description:
            choice_answer = result.choices["target"]
            target_confidence = choice_answer.confidence
            if choice_answer.choice != NONE_OF_THESE:
                target_index = choice_answer.choice

        assertion_probability = result.nouls["assertion"].noul if assertion_text else None
        is_loading = result.nouls["is_loading"].noul

        return GroundAndCheckResult(target_index, target_confidence, assertion_probability, is_loading)
