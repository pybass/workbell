"""Tray controller: the menu model, a 1 s DB poll, and direct in-process Core calls."""

import contextlib
from collections.abc import Callable
from datetime import UTC, datetime

from workbell.core.core import Core
from workbell.core.errors import AppError
from workbell.core.models import IntervalStatus
from workbell.core.utils import format_hms, unix_now
from workbell.tray.appkit import MenuItem, MenuSeparator, TrayApp

POLL_SEC = 1.0  # keeps the menu info fresh and heals a dead timer within ~1 s; the title itself rarely changes
IDLE_ICON = "◇"  # idle glyph; prefixed with today's completed count when non-zero
STATUS_ICON = {IntervalStatus.RUNNING: "▶", IntervalStatus.PAUSED: "⏸"}  # title icon per active status


class TrayController:
    """Owns the menu bar app: builds the menu once, then keeps it in sync with the DB."""

    def __init__(self, core: Core) -> None:
        """Build the static menu; the first poll tick sets real titles and visibility."""
        self._core = core  # shared application core; every call runs in-process on the main thread
        self._app = TrayApp(title=IDLE_ICON)  # AppKit status item + event loop
        # Menu items: action visibility tracks the active interval's status on every refresh.
        # The start title shows the configured default duration; the first refresh fills it in,
        # and the click re-reads settings so a config change applies without restarting the tray.
        self._start_item = MenuItem(
            "Start",
            callback=lambda _: self._invoke(lambda: self._core.start_interval(self._core.get_settings().default_duration_sec)),
        )
        self._pause_item = MenuItem("Pause", callback=lambda _: self._invoke(self._core.pause_interval), hidden=True)
        self._resume_item = MenuItem("Resume", callback=lambda _: self._invoke(self._core.resume_interval), hidden=True)
        # Info lines (grey, non-clickable). Left comes first — it is the number the menu is opened
        # for — and while running it also names the bell's wall-clock moment. Today stays visible
        # even when idle, so the menu never changes shape between states more than it must.
        self._left_item = MenuItem("Left: -", enabled=False, hidden=True)  # e.g. "Left: 20:02 — rings at 14:15"
        self._worked_item = MenuItem("Worked: -", enabled=False, hidden=True)  # e.g. "Worked: 24:58 of 45:00"
        self._today_item = MenuItem("Today: -", enabled=False)  # e.g. "Today: 3 completed"
        self._app.set_menu(
            [
                self._start_item,
                self._pause_item,
                self._resume_item,
                MenuSeparator(),
                self._left_item,
                self._worked_item,
                self._today_item,
                MenuSeparator(),
                MenuItem("Quit", callback=lambda _: self._app.quit()),
            ]
        )

    def run(self) -> None:
        """Start the poll timer and enter the event loop; blocks until Quit or a signal."""
        self._app.start_timer(POLL_SEC, self._refresh)
        self._app.run()

    def _refresh(self) -> None:
        """Poll the DB and sync the title and menu to the active interval."""
        # get_active_interval also heals a dead timer, so an open tray doubles as a ~1 s recovery watchdog.
        interval = self._core.get_active_interval()
        now = unix_now()
        today_completed = self._core.count_today_completed(now)
        # Title: today's interval ordinal plus a status glyph ("4▶" = working the day's 4th interval),
        # or the completed count plus the idle diamond ("3◇"; bare "◇" at zero). Never a ticking
        # countdown — deliberate, see docs/non-goals.md.
        if interval is None:
            self._app.title = f"{today_completed}{IDLE_ICON}" if today_completed else IDLE_ICON
        else:
            self._app.title = f"{today_completed + 1}{STATUS_ICON[interval.status]}"
        self._start_item.hidden = interval is not None
        if interval is None:  # settings are re-read each tick, so a config change shows up within a second
            self._start_item.title = f"Start ({format_hms(self._core.get_settings().default_duration_sec)})"
        self._pause_item.hidden = interval is None or interval.status is not IntervalStatus.RUNNING
        self._resume_item.hidden = interval is None or interval.status is not IntervalStatus.PAUSED
        self._left_item.hidden = interval is None
        self._worked_item.hidden = interval is None
        if interval is not None:
            worked = interval.effective_worked(now)
            left = interval.duration_sec - worked
            if interval.status is IntervalStatus.RUNNING:
                rings_at = datetime.fromtimestamp(now + left, tz=UTC).astimezone().strftime("%H:%M")
                self._left_item.title = f"Left: {format_hms(left)} — rings at {rings_at}"
            else:  # paused: no bell is scheduled, so no ring time
                self._left_item.title = f"Left: {format_hms(left)}"
            self._worked_item.title = f"Worked: {format_hms(worked)} of {format_hms(interval.duration_sec)}"
        self._today_item.title = f"Today: {today_completed} completed"

    def _invoke(self, operation: Callable[[], object]) -> None:
        """Run a Core operation, then refresh.

        AppError is dropped deliberately: it means the click raced another client (e.g. the
        interval was paused from the CLI while the menu was open), and the refresh right after
        shows whatever state won.
        """
        with contextlib.suppress(AppError):
            operation()
        self._refresh()
