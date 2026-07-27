"""Foreground tray entry point: `python -m workbell.tray [<data_dir>]`, spawned detached by the CLI."""

import sys
from pathlib import Path

from workbell.core.core import Core
from workbell.core.utils import acquire_pid_lock, print_crash_header
from workbell.tray.controller import TrayController


def main() -> None:
    """Open the Core, take the single-instance lock, and run the tray until quit; a second instance exits with one line."""
    core = Core(Path(sys.argv[1]) if len(sys.argv) > 1 else Core.DEFAULT_DATA_DIR)
    try:
        # One icon per data dir: tray.lock records our PID (the SIGTERM target for `workbell tray
        # stop`) under an flock the kernel drops with the process, so it cannot go stale.
        lock = acquire_pid_lock(core.tray_lock)
        if lock is None:
            sys.exit("error: Tray is already running.")
        try:
            TrayController(core).run()
        finally:
            lock.close()  # normally moot — quitting AppKit exits the process and the kernel drops the lock
    finally:
        core.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # stderr is errors.log (the detached spawn redirected it): stamp the traceback so the user can date it
        print_crash_header("tray")
        raise
