from __future__ import annotations

import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Optional

from appium import webdriver
from appium.options.android import UiAutomator2Options

from .. import bounds as b
from ..models import Element

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


def connected_device_udid() -> str:
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True).stdout
    candidates = [line.split("\t")[0] for line in out.splitlines()[1:] if line.strip().endswith("\tdevice")]
    if not candidates:
        raise RuntimeError("No authorized Android device found. Run `adb devices` to check.")
    return candidates[0]


class AndroidDriver:
    """Thin wrapper over an Appium UiAutomator2 session: a11y tree dump + gestures.

    Attaches to whatever app is currently in the foreground (no `app`/`appPackage`
    capability set) - this MVP drives whatever screen is already open on the device.
    """

    def __init__(self, udid: Optional[str] = None, appium_server_url: str = "http://127.0.0.1:4723"):
        options = UiAutomator2Options()
        options.udid = udid or connected_device_udid()
        options.no_reset = True
        options.new_command_timeout = 300
        self.driver = webdriver.Remote(appium_server_url, options=options)

    def page_source(self) -> str:
        return self.driver.page_source

    def tap(self, bounds: str) -> None:
        x, y = b.bounds_center(bounds)
        self.driver.execute_script("mobile: clickGesture", {"x": x, "y": y})

    def type_text(self, bounds: str, text: str) -> None:
        x, y = b.bounds_center(bounds)
        self.driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
        self.driver.execute_script("mobile: type", {"text": text})

    def swipe_up(self) -> None:
        size = self.driver.get_window_size()
        self.driver.execute_script(
            "mobile: swipeGesture",
            {
                "left": int(size["width"] * 0.1),
                "top": int(size["height"] * 0.2),
                "width": int(size["width"] * 0.8),
                "height": int(size["height"] * 0.6),
                "direction": "up",
                "percent": 0.8,
            },
        )

    def swipe_down(self) -> None:
        size = self.driver.get_window_size()
        self.driver.execute_script(
            "mobile: swipeGesture",
            {
                "left": int(size["width"] * 0.1),
                "top": int(size["height"] * 0.2),
                "width": int(size["width"] * 0.8),
                "height": int(size["height"] * 0.6),
                "direction": "down",
                "percent": 0.8,
            },
        )

    def back(self) -> None:
        self.driver.back()

    def go_home(self) -> None:
        self.driver.press_keycode(3)  # KEYCODE_HOME

    def reset_for_isolation(self) -> None:
        # A fresh process start (see launch_app) already lands Android apps on their
        # launcher activity, so Home alone is a sufficient "known starting state"
        # between test files.
        self.go_home()
        time.sleep(0.5)

    def launch_app(self, app_id: str) -> None:
        # Force a clean cold start rather than resuming wherever the app was last
        # left mid-navigation - a test case's starting state should be deterministic,
        # not dependent on what a previous run (or manual exploration) did.
        self.driver.terminate_app(app_id)
        self.driver.activate_app(app_id)

    def quit(self) -> None:
        self.driver.quit()


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
    labeled_rects: list[tuple[b.Rect, str, str]] = []
    for node in root.iter():
        attrib = node.attrib
        text = attrib.get("text", "")
        content_desc = attrib.get("content-desc", "")
        if not text and not content_desc:
            continue
        rect = b.parse_bounds(attrib.get("bounds", ""))
        if rect is not None:
            labeled_rects.append((rect, text, content_desc))

    def fallback_label(candidate_rect: b.Rect) -> tuple[str, str]:
        contained = [
            (rect, text, content_desc)
            for rect, text, content_desc in labeled_rects
            if b.contains(candidate_rect, rect)
        ]
        if not contained:
            return "", ""
        # Smallest contained label first: the most specific match, in case a bigger
        # region containing multiple labels also happens to fit inside.
        rect, text, content_desc = min(contained, key=lambda item: b.area(item[0]))
        return text, content_desc

    def is_natively_interactive(attrib: dict[str, str]) -> bool:
        return any(attrib.get(a) == "true" for a in INTERACTIVE_ATTRS)

    def is_class_interactive(attrib: dict[str, str]) -> bool:
        class_name = attrib.get("class", "")
        return any(class_name.endswith(suffix) for suffix in INTERACTIVE_CLASS_SUFFIXES)

    seen: set[tuple[str, str, str, str]] = set()
    elements: list[Element] = []

    for node in root.iter():
        attrib = node.attrib
        if attrib.get("enabled") == "false":
            continue
        if attrib.get("displayed") == "false":
            continue

        natively_interactive = is_natively_interactive(attrib)
        if not natively_interactive and not is_class_interactive(attrib):
            continue

        resource_id = attrib.get("resource-id", "")
        text = attrib.get("text", "")
        content_desc = attrib.get("content-desc", "")
        class_name = attrib.get("class", "")
        elem_bounds = attrib.get("bounds", "")

        if not elem_bounds:
            continue

        # Only borrow a label for the "silent custom control" case (see module
        # docstring above) - never for a natively-interactive element like a
        # scrollable container, whose bounds would contain many unrelated labels.
        if not text and not content_desc and not natively_interactive:
            rect = b.parse_bounds(elem_bounds)
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
                bounds=elem_bounds,
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


def make_driver(udid: Optional[str], appium_server_url: str) -> AndroidDriver:
    return AndroidDriver(udid=udid, appium_server_url=appium_server_url)
