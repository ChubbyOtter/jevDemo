from __future__ import annotations

import time
from pathlib import Path

from . import apps
from .compiler import StepCompiler
from .driver import AndroidDriver
from .elements import parse_elements, parse_screen_text
from .typesafe_client import Jev

GROUNDING_CONFIDENCE_THRESHOLD = 0.6
ASSERTION_PROBABILITY_THRESHOLD = 0.5
LOADING_PROBABILITY_THRESHOLD = 0.7
LOADING_RETRY_DELAY_SECONDS = 1.5
# Fixed settle delay after any action, on top of the is_loading-triggered retry:
# a screen can still be populating content (e.g. async suggestions with no spinner)
# in a way the loading judgment doesn't catch.
POST_ACTION_SETTLE_SECONDS = 0.8
# Cold app starts are slower than an in-app UI transition.
POST_LAUNCH_SETTLE_SECONDS = 2.5
# When an action's target isn't found on the current screen, most real-world misses
# are "not scrolled into view yet," not "doesn't exist" - try scrolling to find it
# before giving up, rather than making every test author hand-tune swipe steps.
MAX_SCROLL_ATTEMPTS = 4
ASSERTION_RETRY_DELAY_SECONDS = 1.5


def load_steps(test_file: Path) -> list[str]:
    lines = test_file.read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _dump_and_ground(driver: AndroidDriver, jev: Jev, target_desc, assertion):
    """One page_source dump, parsed both ways: interactive candidates for grounding,
    full visible text for assertions (only computed when there's an assertion to
    check - grounding-only steps don't pay for it).
    """
    source = driver.page_source()
    elements = parse_elements(source)
    screen_text = parse_screen_text(source) if assertion else None
    result = jev.ground_and_check(elements, target_desc, assertion, screen_text)
    return elements, result


def run_test(test_file: Path, driver: AndroidDriver, jev: Jev, compiler: StepCompiler) -> bool:
    steps = load_steps(test_file)

    for i, step_text in enumerate(steps, start=1):
        compiled = compiler.compile(step_text)
        detail = compiled.verb if compiled.kind == "action" else compiled.assertion_text
        print(f"[{i}/{len(steps)}] {step_text}\n    -> {compiled.kind}: {detail}")

        # launch_app is a known, deterministic lookup+launch - no screen state to read,
        # nothing for Jev to judge, so it skips the grounding call entirely.
        if compiled.verb == "launch_app":
            package = apps.resolve_package(compiled.literal_param or "")
            print(f"    launching {compiled.literal_param!r} ({package})")
            driver.launch_app(package)
            time.sleep(POST_LAUNCH_SETTLE_SECONDS)
            continue

        target_desc = compiled.target_description if compiled.kind == "action" else None
        assertion = compiled.assertion_text if compiled.kind == "assertion" else None

        elements, result = _dump_and_ground(driver, jev, target_desc, assertion)

        if result.is_loading >= LOADING_PROBABILITY_THRESHOLD:
            print(f"    screen looks like it's still loading (p={result.is_loading:.2f}), waiting...")
            time.sleep(LOADING_RETRY_DELAY_SECONDS)
            elements, result = _dump_and_ground(driver, jev, target_desc, assertion)

        if compiled.kind == "action" and compiled.verb in ("tap", "type", "scroll_to"):
            previous_source = None
            attempts = 0
            while (
                result.target_index is None or (result.target_confidence or 0) < GROUNDING_CONFIDENCE_THRESHOLD
            ) and attempts < MAX_SCROLL_ATTEMPTS:
                source = driver.page_source()
                if source == previous_source:
                    # Scrolling had no effect (already at the end of the list) -
                    # further attempts can't find anything new.
                    break
                previous_source = source
                print(f"    not found on screen, scrolling to look ({attempts + 1}/{MAX_SCROLL_ATTEMPTS})...")
                driver.swipe_up()
                time.sleep(POST_ACTION_SETTLE_SECONDS)
                elements, result = _dump_and_ground(driver, jev, target_desc, assertion)
                attempts += 1

        if compiled.kind == "assertion":
            passed = (
                result.assertion_probability is not None
                and result.assertion_probability >= ASSERTION_PROBABILITY_THRESHOLD
            )
            if not passed:
                # Confirmed live: a page can still be settling (async content, no
                # spinner) in a way is_loading doesn't catch - e.g. a membership
                # page whose plan details rendered a beat after the tap. One retry
                # after a longer wait avoids flaking on that exact race.
                print(f"    assertion probability={result.assertion_probability:.2f} -> retrying after settle...")
                time.sleep(ASSERTION_RETRY_DELAY_SECONDS)
                _, result = _dump_and_ground(driver, jev, target_desc, assertion)
                passed = (
                    result.assertion_probability is not None
                    and result.assertion_probability >= ASSERTION_PROBABILITY_THRESHOLD
                )
            print(f"    assertion probability={result.assertion_probability:.2f} -> {'PASS' if passed else 'FAIL'}")
            if not passed:
                return False
            continue

        if compiled.verb in ("tap", "type", "scroll_to"):
            if result.target_index is None or (result.target_confidence or 0) < GROUNDING_CONFIDENCE_THRESHOLD:
                print(
                    f"    FAIL: could not confidently locate '{target_desc}' "
                    f"(confidence={result.target_confidence})"
                )
                return False
            element = next(e for e in elements if e.index == result.target_index)
            print(f"    grounded to {element.index} (confidence={result.target_confidence:.2f}): {element}")
            if compiled.verb == "tap":
                driver.tap(element.bounds)
            elif compiled.verb == "type":
                driver.type_text(element.bounds, compiled.literal_param or "")
            elif compiled.verb == "scroll_to":
                driver.tap(element.bounds)
        elif compiled.verb == "swipe_up":
            driver.swipe_up()
        elif compiled.verb == "swipe_down":
            driver.swipe_down()
        elif compiled.verb == "back":
            driver.back()
        elif compiled.verb == "wait":
            time.sleep(2)

        if compiled.verb != "wait":
            time.sleep(POST_ACTION_SETTLE_SECONDS)

    return True
