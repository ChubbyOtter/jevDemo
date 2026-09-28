from __future__ import annotations

import os
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Optional

from appium import webdriver
from appium.options.ios import XCUITestOptions

from .. import bounds as b
from ..models import Element

# XCUITest signals interactivity purely through element `type` (there's no
# clickable/focusable attribute like UiAutomator2) - confirmed live against a real
# Settings screen: a row's actual tap target is an XCUIElementTypeCell whose own
# `accessible` attribute is "false" (accessibility delegates to a child StaticText),
# but it carries traits="Button" and its own name/label - so `traits` is checked as
# a fallback signal, the same role INTERACTIVE_CLASS_SUFFIXES plays for Android.
INTERACTIVE_TYPE_SUFFIXES = (
    "Button",
    "Cell",
    "Icon",
    "TextField",
    "SecureTextField",
    "SearchField",
    "Switch",
    "Link",
    "Tab",
    "Key",
    "MenuItem",
    "RadioButton",
    "CheckBox",
    "Slider",
    "Stepper",
    "PickerWheel",
)

DEFAULT_MAX_ELEMENTS = 200

_SIMULATOR_BOOTED_RE = re.compile(r"\(([0-9A-Fa-f-]{36})\)\s*\(Booted\)")


def connected_simulator_udid() -> str:
    out = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "booted"], capture_output=True, text=True, check=True
    ).stdout
    match = _SIMULATOR_BOOTED_RE.search(out)
    if not match:
        raise RuntimeError(
            "No booted iOS simulator found. Boot one first, e.g. "
            "`xcrun simctl boot <udid>` (see `xcrun simctl list devices` for udids)."
        )
    return match.group(1)


def _is_simulator_udid(udid: str) -> bool:
    # simctl only knows about Simulators, never real devices - listing them (any
    # state, not just booted) and checking membership is the cheapest reliable way
    # to tell which kind of udid we were given.
    out = subprocess.run(["xcrun", "simctl", "list", "devices"], capture_output=True, text=True).stdout
    return udid in out


class IOSDriver:
    """Thin wrapper over an Appium XCUITest session - same shape as AndroidDriver,
    with the platform's real differences (gesture commands, no hardware back button).
    """

    def __init__(self, udid: Optional[str] = None, appium_server_url: str = "http://127.0.0.1:4723"):
        self._udid = udid or connected_simulator_udid()
        self._is_simulator = _is_simulator_udid(self._udid)
        options = XCUITestOptions()
        options.udid = self._udid
        options.no_reset = True
        options.new_command_timeout = 300
        # Real devices need WDA (re-)signed with the tester's own identity on every
        # session start; the Simulator needs none of this (no code signing at all),
        # so these stay unset - and Appium untouched - unless the env vars are
        # present. IOS_XCODE_ORG_ID is the Apple Developer Team ID (a free Personal
        # Team's ID works); IOS_WDA_BUNDLE_ID is whatever unique bundle id the
        # WebDriverAgentRunner target was given in Xcode (Facebook's default,
        # com.facebook.WebDriverAgentRunner, isn't yours to sign).
        xcode_org_id = os.environ.get("IOS_XCODE_ORG_ID")
        if xcode_org_id:
            options.xcode_org_id = xcode_org_id
            options.xcode_signing_id = os.environ.get("IOS_XCODE_SIGNING_ID", "iPhone Developer")
            wda_bundle_id = os.environ.get("IOS_WDA_BUNDLE_ID")
            if wda_bundle_id:
                options.updated_wda_bundle_id = wda_bundle_id
        # Escape hatch for a stuck/stale WDA session on a real device (testmanagerd
        # sometimes gets into a state where every session fails with "Not
        # authorized for performing UI testing actions" until WDA is fully
        # uninstalled and reinstalled) - off by default since it adds a real
        # rebuild/reinstall delay to every session start.
        if os.environ.get("IOS_USE_NEW_WDA", "").lower() in ("1", "true"):
            options.use_new_wda = True
        self.driver = webdriver.Remote(appium_server_url, options=options)

    def page_source(self) -> str:
        return self.driver.page_source

    def tap(self, bounds: str) -> None:
        x, y = b.bounds_center(bounds)
        self.driver.execute_script("mobile: tap", {"x": x, "y": y})

    def type_text(self, bounds: str, text: str) -> None:
        x, y = b.bounds_center(bounds)
        self.driver.execute_script("mobile: tap", {"x": x, "y": y})
        self.driver.execute_script("mobile: keys", {"keys": [text]})

    def swipe_up(self) -> None:
        self.driver.execute_script("mobile: swipe", {"direction": "up"})

    def swipe_down(self) -> None:
        self.driver.execute_script("mobile: swipe", {"direction": "down"})

    def back(self) -> None:
        # iOS has no hardware/software back button equivalent to Android's - a step
        # authored with the `back` verb against an iOS suite is an authoring bug
        # (it should target the screen's actual back control instead), not a runtime
        # state to paper over.
        raise NotImplementedError(
            "iOS has no universal 'back' action - target the screen's actual back "
            "button/control with a tap step instead."
        )

    def go_home(self) -> None:
        self.driver.execute_script("mobile: pressButton", {"name": "home"})

    def reset_for_isolation(self) -> None:
        # Deliberately a no-op, NOT go_home(): confirmed live that pressing Home
        # backgrounds whatever's in the foreground, and iOS writes that screen's
        # UIKit state-restoration snapshot at that exact moment - a later hard kill
        # (see launch_app) can't un-write it, so backgrounding-then-relaunching
        # reliably resumed on the previous test's last screen instead of the app's
        # root. iOS isolation instead relies entirely on launch_app's simctl-based
        # reset, which never backgrounds the app first. A test case that doesn't
        # start with launch_app has no isolation guarantee on iOS.
        pass

    def launch_app(self, app_id: str) -> None:
        if self._is_simulator:
            # `driver.terminate_app`/`activate_app` go through WebDriverAgent's
            # springboard-mediated app lifecycle, which iOS's state restoration
            # survives (confirmed live: Settings resumed on its last-viewed screen
            # instead of its root). `simctl terminate`/`launch` are OS-level and
            # reliably land on the app's true initial screen - Simulator-only,
            # since simctl has no real-device equivalent.
            subprocess.run(["xcrun", "simctl", "terminate", self._udid, app_id], capture_output=True)
            subprocess.run(
                ["xcrun", "simctl", "launch", self._udid, app_id], capture_output=True, check=True
            )
        else:
            # Real devices have no simctl equivalent, so this falls back to
            # Appium's own WDA-mediated lifecycle - which does NOT carry the
            # Simulator's state-restoration fix (see reset_for_isolation). A
            # real-device suite-isolation strategy is still an open gap.
            self.driver.terminate_app(app_id)
            self.driver.activate_app(app_id)

    def quit(self) -> None:
        self.driver.quit()


def parse_elements(page_source: str, max_elements: int = DEFAULT_MAX_ELEMENTS) -> list[Element]:
    """Turn a raw XCUITest XML dump into a compact, deduped candidate list.

    Mirrors platforms/android.py's parse_elements: filter to real tap targets in
    code, so Jev only ever chooses among genuine candidates.
    """
    root = ET.fromstring(page_source)

    def is_interactive(attrib: dict[str, str]) -> bool:
        type_name = attrib.get("type", "")
        if any(type_name.endswith(suffix) for suffix in INTERACTIVE_TYPE_SUFFIXES):
            return True
        traits = attrib.get("traits", "")
        return "Button" in traits or "Link" in traits

    seen: set[tuple[str, str, str, str]] = set()
    elements: list[Element] = []

    for node in root.iter():
        attrib = node.attrib
        if attrib.get("enabled") != "true" or attrib.get("visible") != "true":
            continue
        if not is_interactive(attrib):
            continue

        try:
            width = int(attrib.get("width", "0"))
            height = int(attrib.get("height", "0"))
        except ValueError:
            continue
        # Zero-size entries are duplicate/off-screen tree nodes (confirmed live: an
        # unopened folder's icons appear this way alongside the real, sized ones) -
        # never a real tap target.
        if width <= 0 or height <= 0:
            continue

        left = int(attrib.get("x", "0"))
        top = int(attrib.get("y", "0"))
        elem_bounds = b.format_bounds(left, top, left + width, top + height)

        name = attrib.get("name", "")
        label = attrib.get("label", "")
        value = attrib.get("value", "")
        text = label or value or name
        class_name = attrib.get("type", "")

        key = (name, text, class_name, elem_bounds)
        if key in seen:
            continue
        seen.add(key)

        elements.append(
            Element(
                index=f"e{len(elements)}",
                resource_id="",
                text=text,
                content_desc=name,
                class_name=class_name,
                bounds=elem_bounds,
            )
        )
        if len(elements) >= max_elements:
            break

    return elements


def parse_screen_text(page_source: str, max_items: int = 300) -> list[str]:
    """All visible text on screen, deduped, interactive or not - see
    platforms/android.py's parse_screen_text for why assertions need this
    separately from the tap-target-only candidate list.
    """
    root = ET.fromstring(page_source)
    seen: set[str] = set()
    items: list[str] = []

    for node in root.iter():
        attrib = node.attrib
        if attrib.get("enabled") != "true" or attrib.get("visible") != "true":
            continue
        for value in (attrib.get("label", ""), attrib.get("value", ""), attrib.get("name", "")):
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                items.append(value)
                if len(items) >= max_items:
                    return items

    return items


def make_driver(udid: Optional[str], appium_server_url: str) -> IOSDriver:
    return IOSDriver(udid=udid, appium_server_url=appium_server_url)
