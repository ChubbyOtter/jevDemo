from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from ..models import Element


class MobileDriver(Protocol):
    """What runner.py needs from a device session - identical surface for every
    platform. Each platform module (android.py, ios.py) provides its own concrete
    class; runner.py never imports a platform-specific driver type.
    """

    def page_source(self) -> str: ...

    def tap(self, bounds: str) -> None: ...

    def type_text(self, bounds: str, text: str) -> None: ...

    def swipe_up(self) -> None: ...

    def swipe_down(self) -> None: ...

    def back(self) -> None: ...

    def go_home(self) -> None: ...

    def reset_for_isolation(self) -> None: ...

    def launch_app(self, app_id: str) -> None: ...

    def quit(self) -> None: ...


@dataclass(frozen=True)
class Platform:
    """Everything that differs between platforms, bundled behind one name.

    `parse_elements`/`parse_screen_text` differ because Android and iOS a11y trees
    have entirely different shapes (attribute names, how interactivity is signaled)
    - see platforms/android.py and platforms/ios.py. `make_driver` differs because
    each platform needs a different Appium Options class and device-discovery logic.
    Everything downstream (Jev, the compile cache, the run loop) is identical.
    """

    name: str
    make_driver: Callable[[Optional[str], str], MobileDriver]
    parse_elements: Callable[[str], list[Element]]
    parse_screen_text: Callable[[str], list[str]]
