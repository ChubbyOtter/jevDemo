from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from .cache import CompileCache
from .compiler import StepCompiler
from .platforms import get_platform
from .runner import run_test
from .typesafe_client import Jev


def _discover_test_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.glob("*.txt") if p.is_file())


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="AI-native mobile UI test runner")
    parser.add_argument(
        "path", type=Path, help="A single test step file, or a directory of them (run as a suite)"
    )
    parser.add_argument("--platform", choices=["android", "ios"], default="android")
    parser.add_argument("--appium-url", default="http://127.0.0.1:4723")
    parser.add_argument(
        "--udid",
        default=None,
        help="Device UDID (Android) or simulator UDID (iOS); auto-detected if omitted",
    )
    parser.add_argument("--cache-file", type=Path, default=Path(".cache/compiled_steps.json"))
    args = parser.parse_args()

    test_files = _discover_test_files(args.path)
    if not test_files:
        print(f"No test files found at {args.path}")
        sys.exit(2)

    platform = get_platform(args.platform)

    # Shared across the whole suite: one Appium session, one TypeSafe client, one
    # compile cache - so a suite of many test cases pays for session/client startup
    # once, and every case benefits from every other case's already-compiled steps.
    cache = CompileCache(args.cache_file)
    compiler = StepCompiler(cache)
    driver = platform.make_driver(args.udid, args.appium_url)
    jev = Jev()

    results: dict[Path, bool] = {}
    try:
        for test_file in test_files:
            print(f"\n=== {test_file} ===")
            # Each test case gets a known starting state - one case failing or
            # leaving the device mid-navigation must never corrupt the next case's
            # result. What this actually does differs per platform (see each
            # driver's reset_for_isolation) - launch_app (if the case's own first
            # step uses it) additionally force-restarts its app, so between them
            # this covers cases that don't start with launch_app too.
            driver.reset_for_isolation()
            results[test_file] = run_test(test_file, driver, platform, jev, compiler)
    finally:
        driver.quit()
        jev.close()

    passed_count = sum(results.values())
    print(f"\n{'=' * 40}\n{passed_count}/{len(results)} passed")
    for test_file, passed in results.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {test_file}")

    sys.exit(0 if passed_count == len(results) else 1)


if __name__ == "__main__":
    main()
