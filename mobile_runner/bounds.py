from __future__ import annotations

import re

# Both platforms' Element.bounds use this one string shape - Android's a11y dump
# already reports bounds this way natively; the iOS element parser formats its
# native x/y/width/height into the same shape so driver code (tap/type - see
# platforms/android.py and platforms/ios.py) needs exactly one bounds format.
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
Rect = tuple[int, int, int, int]


def format_bounds(left: int, top: int, right: int, bottom: int) -> str:
    return f"[{left},{top}][{right},{bottom}]"


def parse_bounds(bounds: str) -> Rect | None:
    match = _BOUNDS_RE.match(bounds)
    if not match:
        return None
    left, top, right, bottom = (int(v) for v in match.groups())
    return left, top, right, bottom


def bounds_center(bounds: str) -> tuple[int, int]:
    rect = parse_bounds(bounds)
    if rect is None:
        raise ValueError(f"Unrecognized bounds format: {bounds!r}")
    left, top, right, bottom = rect
    return (left + right) // 2, (top + bottom) // 2


def area(rect: Rect) -> int:
    left, top, right, bottom = rect
    return max(0, right - left) * max(0, bottom - top)


def contains(outer: Rect, inner: Rect) -> bool:
    ol, ot, orr, ob = outer
    il, it, ir, ib = inner
    return ol <= il and ot <= it and ir <= orr and ib <= ob
