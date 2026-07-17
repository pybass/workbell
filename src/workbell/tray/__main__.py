"""Foreground tray entry point: `python -m workbell.tray <db_path>`, spawned detached by the CLI."""

import sys
from pathlib import Path

from workbell.core.core import Core
from workbell.core.utils import TRAY_LOCK_FILENAME, acquire_pid_lock
from workbell.tray.controller import TrayController


def main() -> None:
    """Open the Core, take the single-instance lock, and run the tray until quit; a second instance exits with one line."""
    core = Core(Path(sys.argv[1]))
    try:
        # One icon per data dir: tray.lock records our PID (the SIGTERM target for `workbell tray
        # stop`) under an flock the kernel drops with the process, so it cannot go stale.
        lock = acquire_pid_lock(core.db_path.parent / TRAY_LOCK_FILENAME)
        if lock is None:
            sys.exit("error: Tray is already running.")
        try:
            TrayController(core).run()
        finally:
            lock.close()  # normally moot — quitting AppKit exits the process and the kernel drops the lock
    finally:
        core.close()


if __name__ == "__main__":
    main()
