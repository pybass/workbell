"""Typed wrapper around pyobjc for menu bar apps. Everything runs on the main thread — no cross-thread plumbing."""

from collections.abc import Callable
from typing import Any, Self

# pyobjc injects framework names lazily at runtime and ships no stubs; mypy's
# missing-stub errors for these modules are silenced in pyproject.toml.
import objc
from AppKit import (
    NSAlert,
    NSAlertSecondButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
)
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
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value
        if self.ns_item is not None:
            self.ns_item.setTitle_(value)

    @property
    def hidden(self) -> bool:
        return self._hidden

    @hidden.setter
    def hidden(self, value: bool) -> None:
        self._hidden = value
        if self.ns_item is not None:
            self.ns_item.setHidden_(value)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if self.ns_item is not None:
            self.ns_item.setEnabled_(value)


class _Dispatcher(NSObject):  # type: ignore[misc]
    """NSObject target routing menu-item clicks (keyed by NSMenuItem tag) and NSTimer fires to Python callables."""

    def init(self) -> Self:
        self = objc.super(_Dispatcher, self).init()  # noqa: PLW0642  # reassigning self is the documented pyobjc init pattern
        self.callbacks: dict[int, tuple[Callable[[MenuItem], None], MenuItem]] = {}
        self.timer_callback: Callable[[], None] | None = None
        return self

    # ObjC selectors — names must follow Objective-C conventions

    def menuItemClicked_(self, sender: object) -> None:  # noqa: N802  — ObjC selector
        ns_sender: Any = sender  # NSMenuItem — need dynamic access for .tag()
        tag: int = ns_sender.tag()
        if tag in self.callbacks:
            callback, menu_item = self.callbacks[tag]
            callback(menu_item)

    def timerFired_(self, _timer: object) -> None:  # noqa: N802  — ObjC selector
        if self.timer_callback is not None:
            self.timer_callback()


class TrayApp:
    def __init__(self, title: str = "") -> None:
        self._nsapp = NSApplication.sharedApplication()
        self._nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
        self._status_item.setTitle_(title)
        self._dispatcher: _Dispatcher = _Dispatcher.alloc().init()
        self._timer: Any = None  # NSTimer
        self._next_tag = 0

    @property
    def title(self) -> str:
        """Menu bar text."""
        result: str = self._status_item.title()
        return result

    @title.setter
    def title(self, value: str) -> None:
        self._status_item.setTitle_(value)

    def confirm(self, message: str, detail: str, *, ok_title: str, cancel_title: str) -> bool:
        """Show a modal two-button alert and return True when ok_title was chosen; blocks the run loop until dismissed.

        cancel_title is the default (Return) button, so the safe answer is the easy one.
        """
        alert = NSAlert.alloc().init()
        alert.setMessageText_(message)
        alert.setInformativeText_(detail)
        alert.addButtonWithTitle_(cancel_title)  # the first button added is the default
        alert.addButtonWithTitle_(ok_title)
        self._nsapp.activateIgnoringOtherApps_(True)  # accessory app: without this the alert opens behind other windows
        return bool(alert.runModal() == NSAlertSecondButtonReturn)

    def set_menu(self, items: list[MenuItem | MenuSeparator]) -> None:
        """Replace the status bar menu with one built from items; earlier callback registrations are dropped."""
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
        """Start a repeating main-run-loop timer: fires immediately, then every interval_sec; replaces any running timer."""
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
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def quit(self) -> None:
        self.stop_timer()
        self._nsapp.terminate_(None)

    def run(self) -> None:
        """Run the event loop until quit. installMachInterrupt turns SIGINT into a clean stop; SIGTERM just kills the process."""
        AppHelper.installMachInterrupt()
        AppHelper.runEventLoop()
