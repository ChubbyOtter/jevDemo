from __future__ import annotations

import re
import subprocess
from typing import Optional

from appium import webdriver
from appium.options.android import UiAutomator2Options

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def connected_device_udid() -> str:
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True).stdout
    candidates = [line.split("\t")[0] for line in out.splitlines()[1:] if line.strip().endswith("\tdevice")]
    if not candidates:
        raise RuntimeError("No authorized Android device found. Run `adb devices` to check.")
    return candidates[0]


def _bounds_center(bounds: str) -> tuple[int, int]:
    match = _BOUNDS_RE.match(bounds)
    if not match:
        raise ValueError(f"Unrecognized bounds format: {bounds!r}")
    left, top, right, bottom = (int(v) for v in match.groups())
    return (left + right) // 2, (top + bottom) // 2


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
        x, y = _bounds_center(bounds)
        self.driver.execute_script("mobile: clickGesture", {"x": x, "y": y})

    def type_text(self, bounds: str, text: str) -> None:
        x, y = _bounds_center(bounds)
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

    def launch_app(self, package: str) -> None:
        # Force a clean cold start rather than resuming wherever the app was last
        # left mid-navigation - a test case's starting state should be deterministic,
        # not dependent on what a previous run (or manual exploration) did.
        self.driver.terminate_app(package)
        self.driver.activate_app(package)

    def quit(self) -> None:
        self.driver.quit()
