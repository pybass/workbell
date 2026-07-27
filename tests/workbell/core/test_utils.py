"""Tests for the shared core helpers: duration formatting, the crash header, and the PID-stamped flock."""

import fcntl
import os
import re

import pytest

from workbell.core.utils import acquire_pid_lock, format_hms, lock_holder_pid, print_crash_header


class TestFormatHms:
    """Second counts as M:SS below an hour, H:MM:SS from one hour up."""

    @pytest.mark.parametrize(
        ("sec", "expected"),
        [
            (0, "0:00"),
            (5, "0:05"),
            (59, "0:59"),
            (60, "1:00"),
            (1500, "25:00"),
            (3599, "59:59"),
            (3600, "1:00:00"),
            (3661, "1:01:01"),
            (36000, "10:00:00"),
        ],
    )
    def test_formats(self, sec, expected):
        """Boundary values on both sides of the minute and hour switches."""
        assert format_hms(sec) == expected


class TestCrashHeader:
    """The header a detached process stamps on stderr before its traceback."""

    def test_crash_header(self, capsys):
        """The header goes to stderr and carries a timestamp and the process name."""
        print_crash_header("timer")
        assert re.fullmatch(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] timer crashed:\n", capsys.readouterr().err)


class TestPidLock:
    """The PID-stamped flock: acquisition, probing, and release."""

    def test_acquire_and_probe(self, tmp_path):
        """A held lock reports the holder's PID; closing the handle frees it."""
        path = tmp_path / "test.lock"
        handle = acquire_pid_lock(path)
        assert handle is not None
        assert lock_holder_pid(path) == os.getpid()
        handle.close()
        assert lock_holder_pid(path) is None

    def test_second_acquire_fails(self, tmp_path):
        """A second non-blocking acquire on a held lock yields None (flock conflicts across open file descriptions)."""
        path = tmp_path / "test.lock"
        handle = acquire_pid_lock(path)
        assert handle is not None
        try:
            assert acquire_pid_lock(path) is None
        finally:
            handle.close()

    def test_missing_file_is_free(self, tmp_path):
        """Probing a path that was never locked reports it free."""
        assert lock_holder_pid(tmp_path / "never.lock") is None

    def test_leftover_file_is_free(self, tmp_path):
        """A leftover file whose writer died reads as free — truth is the flock probe, not the file content."""
        path = tmp_path / "stale.lock"
        path.write_text("12345")
        assert lock_holder_pid(path) is None

    def test_holder_mid_write_reads_free(self, tmp_path):
        """A held lock whose PID is not yet written reads as free — the staleness guard covers this startup window."""
        path = tmp_path / "test.lock"
        with path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert lock_holder_pid(path) is None
