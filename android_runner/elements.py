from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .models import Element

# Any of these being "true" marks a node as something a step could plausibly target.
INTERACTIVE_ATTRS = ("clickable", "long-clickable", "scrollable", "checkable", "focusable")

# Fallback for apps that under-report accessibility flags: a custom-touch row often
# renders as one of these widget classes without ever setting clickable="true" (seen
# live in a real app's Settings screen - a Button row whose own clickable attr is false).
INTERACTIVE_CLASS_SUFFIXES = (
    "Button",
    "EditText",
    "CheckBox",
    "Switch",
    "RadioButton",
    "CompoundButton",
    "Spinner",
)

# Choice questions cap at 255 options; leave room for the "none_of_these" fallback.
DEFAULT_MAX_ELEMENTS = 200

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
Rect = tuple[int, int, int, int]


def _parse_bounds(bounds: str) -> Rect | None:
    match = _BOUNDS_RE.match(bounds)
    if not match:
        return None
    left, top, right, bottom = (int(v) for v in match.groups())
    return left, top, right, bottom


def _area(rect: Rect) -> int:
    left, top, right, bottom = rect
    return max(0, right - left) * max(0, bottom - top)


def _contains(outer: Rect, inner: Rect) -> bool:
    ol, ot, orr, ob = outer
    il, it, ir, ib = inner
    return ol <= il and ot <= it and ir <= orr and ib <= ob


def _is_natively_interactive(attrib: dict[str, str]) -> bool:
    return any(attrib.get(a) == "true" for a in INTERACTIVE_ATTRS)


def _is_class_interactive(attrib: dict[str, str]) -> bool:
    class_name = attrib.get("class", "")
    return any(class_name.endswith(suffix) for suffix in INTERACTIVE_CLASS_SUFFIXES)


def parse_elements(page_source: str, max_elements: int = DEFAULT_MAX_ELEMENTS) -> list[Element]:
    """Turn a raw UiAutomator XML dump into a compact, deduped candidate list.

    Filtering/deduping happens here in code (cheap, deterministic) so the Jev grounding
    call only has to choose among real candidates, per the "select instead of generate"
    pattern - never send the raw XML as state.
    """
    root = ET.fromstring(page_source)

    # Collect every labeled node's rectangle up front, for the bounds-containment
    # fallback below. Some apps (confirmed live in a real app's Settings screen) put
    # a row's label as a DOM SIBLING of its touchable container, not a descendant -
    # so tree-based lookup can't find it. Position on screen is the reliable signal.
    labeled_rects: list[tuple[Rect, str, str]] = []
    for node in root.iter():
        attrib = node.attrib
        text = attrib.get("text", "")
        content_desc = attrib.get("content-desc", "")
        if not text and not content_desc:
            continue
        rect = _parse_bounds(attrib.get("bounds", ""))
        if rect is not None:
            labeled_rects.append((rect, text, content_desc))

    def fallback_label(candidate_rect: Rect) -> tuple[str, str]:
        contained = [
            (rect, text, content_desc)
            for rect, text, content_desc in labeled_rects
            if _contains(candidate_rect, rect)
        ]
        if not contained:
            return "", ""
        # Smallest contained label first: the most specific match, in case a bigger
        # region containing multiple labels also happens to fit inside.
        rect, text, content_desc = min(contained, key=lambda item: _area(item[0]))
        return text, content_desc

    seen: set[tuple[str, str, str, str]] = set()
    elements: list[Element] = []

    for node in root.iter():
        attrib = node.attrib
        if attrib.get("enabled") == "false":
            continue
        if attrib.get("displayed") == "false":
            continue

        natively_interactive = _is_natively_interactive(attrib)
        if not natively_interactive and not _is_class_interactive(attrib):
            continue

        resource_id = attrib.get("resource-id", "")
        text = attrib.get("text", "")
        content_desc = attrib.get("content-desc", "")
        class_name = attrib.get("class", "")
        bounds = attrib.get("bounds", "")

        if not bounds:
            continue

        # Only borrow a label for the "silent custom control" case (see module
        # docstring above) - never for a natively-interactive element like a
        # scrollable container, whose bounds would contain many unrelated labels.
        if not text and not content_desc and not natively_interactive:
            rect = _parse_bounds(bounds)
            if rect is not None:
                text, content_desc = fallback_label(rect)

        key = (resource_id, text, content_desc, class_name)
        if key in seen:
            continue
        seen.add(key)

        elements.append(
            Element(
                index=f"e{len(elements)}",
                resource_id=resource_id,
                text=text,
                content_desc=content_desc,
                class_name=class_name,
                bounds=bounds,
            )
        )
        if len(elements) >= max_elements:
            break

    return elements


def parse_screen_text(page_source: str, max_items: int = 300) -> list[str]:
    """All visible text/content-desc on screen, deduped, interactive or not.

    Assertions need to judge the screen's overall meaning, not just what's tappable -
    `parse_elements` deliberately excludes plain labels (e.g. a TextView showing
    "Complimentary" or a price), since grounding only ever needs real tap targets.
    Confirmed live: an assertion about a membership/plan page read near-zero
    probability when checked against interactive-only elements, because every
    informative string on that screen was a non-interactive TextView.
    """
    root = ET.fromstring(page_source)
    seen: set[str] = set()
    items: list[str] = []

    for node in root.iter():
        attrib = node.attrib
        if attrib.get("enabled") == "false" or attrib.get("displayed") == "false":
            continue
        for value in (attrib.get("text", ""), attrib.get("content-desc", "")):
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                items.append(value)
                if len(items) >= max_items:
                    return items

    return items
