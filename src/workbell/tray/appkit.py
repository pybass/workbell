"""Pythonic wrapper around pyobjc for macOS menu bar (tray) apps.

Hides all ObjC method names, NSObject subclassing, and NSTimer boilerplate
behind typed Python classes. Exports: TrayApp, MenuItem, MenuSeparator.
Everything runs on the main thread — the wrapper has no cross-thread plumbing.
"""

from collections.abc import Callable
from typing import Any, Self

# pyobjc injects framework names lazily at runtime and ships no stubs; mypy's
# missing-stub errors for these modules are silenced in pyproject.toml.
import objc
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSMenu, NSMenuItem, NSStatusBar
from Foundation import NSDate, NSDefaultRunLoopMode, NSObject, NSRunLoop, NSTimer
from PyObjCTools import AppHelper


class MenuSeparator:
    """A separator line in the menu."""


class MenuItem:
    """A menu item with mutable properties that sync to the underlying NSMenuItem."""

    def __init__(
        self,
        title: str,
        *,
        callback: Callable[[MenuItem], None] | None = None,
        enabled: bool = True,
        hidden: bool = False,
    ) -> None:
        """Create a menu item.

        Args:
            title: Display text.
            callback: Called when the item is clicked, receives the MenuItem.
            enabled: Whether the item is clickable.
            hidden: Whether the item is visible.

        """
        self._title = title
        self._callback = callback
        self._enabled = enabled
        self._hidden = hidden
        self.ns_item: Any = None  # NSMenuItem, attached by TrayApp.set_menu()

    @property
    def callback(self) -> Callable[[MenuItem], None] | None:
        """Click callback, or None for non-interactive items."""
        return self._callback

    @property
    def title(self) -> str:
        """Display text."""
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value
        if self.ns_item is not None:
            self.ns_item.setTitle_(value)

    @property
    def hidden(self) -> bool:
        """Whether the item is visible."""
        return self._hidden

    @hidden.setter
    def hidden(self, value: bool) -> None:
        self._hidden = value
        if self.ns_item is not None:
            self.ns_item.setHidden_(value)

    @property
    def enabled(self) -> bool:
        """Whether the item is clickable."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if self.ns_item is not None:
            self.ns_item.setEnabled_(value)


class _Dispatcher(NSObject):  # type: ignore[misc]
    """Internal NSObject that routes ObjC callbacks to Python callables.

    Bridges ObjC target-action and NSTimer to plain Python callbacks.
    Uses NSMenuItem.tag() (integer) for callback dispatch.
    """

    def init(self) -> Self:
        """Initialize callback storage."""
        self = objc.super(_Dispatcher, self).init()  # noqa: PLW0642  # reassigning self is the documented pyobjc init pattern
        self.callbacks: dict[int, tuple[Callable[[MenuItem], None], MenuItem]] = {}
        self.timer_callback: Callable[[], None] | None = None
        return self

    # ObjC selectors — names must follow Objective-C conventions

    def menuItemClicked_(self, sender: object) -> None:  # noqa: N802  — ObjC selector
        """Dispatch menu item click to the registered Python callback."""
        ns_sender: Any = sender  # NSMenuItem — need dynamic access for .tag()
        tag: int = ns_sender.tag()
        if tag in self.callbacks:
            callback, menu_item = self.callbacks[tag]
            callback(menu_item)

    def timerFired_(self, _timer: object) -> None:  # noqa: N802  — ObjC selector
        """NSTimer callback — invoke the stored Python timer callback."""
        if self.timer_callback is not None:
            self.timer_callback()


class TrayApp:
    """macOS menu bar (tray) application."""

    def __init__(self, title: str = "") -> None:
        """Create the NSApplication, status bar item, and internal dispatcher.

        Args:
            title: Initial menu bar text.

        """
        self._nsapp = NSApplication.sharedApplication()
        self._nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
        self._status_item.setTitle_(title)
        self._dispatcher: _Dispatcher = _Dispatcher.alloc().init()
        self._timer: Any = None  # NSTimer
        self._next_tag = 0  # monotonically incrementing, never reused

    @property
    def title(self) -> str:
        """Menu bar text."""
        result: str = self._status_item.title()
        return result

    @title.setter
    def title(self, value: str) -> None:
        self._status_item.setTitle_(value)

    def set_menu(self, items: list[MenuItem | MenuSeparator]) -> None:
        """Build an NSMenu from the given items and attach it to the status bar.

        Clears all previous callback/tag mappings and creates a fresh menu.

        Args:
            items: Menu items and separators in display order.

        """
        self._dispatcher.callbacks.clear()
        self._next_tag = 0

        menu = NSMenu.alloc().init()
        for item in items:
            if isinstance(item, MenuSeparator):
                menu.addItem_(NSMenuItem.separatorItem())
                continue

            if item.callback is not None:
                ns_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(item.title, "menuItemClicked:", "")
                ns_item.setTarget_(self._dispatcher)
                tag = self._next_tag
                self._next_tag += 1
                ns_item.setTag_(tag)
                self._dispatcher.callbacks[tag] = (item.callback, item)
            else:
                ns_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(item.title, None, "")

            ns_item.setEnabled_(item.enabled)
            ns_item.setHidden_(item.hidden)
            item.ns_item = ns_item
            menu.addItem_(ns_item)

        self._status_item.setMenu_(menu)

    def start_timer(self, interval_sec: float, callback: Callable[[], None]) -> None:
        """Start a repeating timer on the main run loop: fires immediately, then every interval_sec.

        Invalidates any previously running timer.

        Args:
            interval_sec: Interval between firings in seconds.
            callback: Called on each timer tick (on the main thread).

        """
        self.stop_timer()
        self._dispatcher.timer_callback = callback
        self._timer = NSTimer.alloc().initWithFireDate_interval_target_selector_userInfo_repeats_(
            NSDate.date(),
            interval_sec,
            self._dispatcher,
            "timerFired:",
            None,
            True,
        )
        NSRunLoop.currentRunLoop().addTimer_forMode_(self._timer, NSDefaultRunLoopMode)

    def stop_timer(self) -> None:
        """Invalidate the current timer, if any."""
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def quit(self) -> None:
        """Stop the timer and terminate the application."""
        self.stop_timer()
        self._nsapp.terminate_(None)

    def run(self) -> None:
        """Install signal handlers and start the NSApplication event loop.

        Handles SIGTERM/SIGINT for clean shutdown.
        """
        AppHelper.installMachInterrupt()
        AppHelper.runEventLoop()
