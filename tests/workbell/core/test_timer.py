"""Tests for the timer process entry point: a crash must leave a dated traceback in errors.log."""

import subprocess
import sys

from workbell.core.utils import ERRORS_LOG_FILENAME, open_errors_log


class TestCrashLogging:
    """The real `python -m workbell.core.timer`, spawned the way Core._spawn_timer wires it."""

    def test_crash_lands_in_errors_log(self, tmp_path):
        """A crashing timer (non-numeric interval id) leaves the crash header and the traceback in errors.log.

        A real subprocess, not a mock: the point is the exact wiring _spawn_timer sets up —
        stderr redirected into errors.log plus the __main__ crash handler stamping the header.
        The bad argv makes the timer die before it touches the lock or the database.
        """
        argv = [sys.executable, "-m", "workbell.core.timer", str(tmp_path / "workbell.db"), "not-a-number"]
        with open_errors_log(tmp_path) as log:
            rc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, check=False, timeout=30).returncode
        assert rc == 1
        content = (tmp_path / ERRORS_LOG_FILENAME).read_text()
        assert "] timer crashed:\n" in content
        assert "ValueError" in content
        assert content.index("timer crashed:") < content.index("ValueError")  # the header dates the traceback below it
