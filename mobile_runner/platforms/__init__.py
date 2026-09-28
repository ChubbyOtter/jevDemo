from __future__ import annotations

from . import android, ios
from .base import Platform

PLATFORMS: dict[str, Platform] = {
    "android": Platform(
        name="android",
        make_driver=android.make_driver,
        parse_elements=android.parse_elements,
        parse_screen_text=android.parse_screen_text,
    ),
    "ios": Platform(
        name="ios",
        make_driver=ios.make_driver,
        parse_elements=ios.parse_elements,
        parse_screen_text=ios.parse_screen_text,
    ),
}


def get_platform(name: str) -> Platform:
    try:
        return PLATFORMS[name]
    except KeyError:
        raise KeyError(f"Unknown platform {name!r}. Choose one of {sorted(PLATFORMS)}.") from None
