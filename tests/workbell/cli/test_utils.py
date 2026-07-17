"""Tests for the CLI helpers: duration parsing and timestamp formatting."""

import contextlib
import os
import time
from collections.abc import Iterator

import pytest

from workbell.cli.utils import format_timestamp, parse_duration
from workbell.core.errors import AppError


@contextlib.contextmanager
def pinned_tz(tz: str) -> Iterator[None]:
    """Temporarily pin the process timezone (TZ plus tzset), restoring the real one on exit."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


class TestParseDuration:
    """Duration strings: bare minutes or exact h/m/s units."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("25", 1500),
            ("1", 60),
            ("0", 0),
            ("10s", 10),
            ("90m", 5400),
            ("2h", 7200),
            ("1h20m10s", 4810),
            ("1h10s", 3610),
            ("0s", 0),
        ],
    )
    def test_parses(self, text, expected):
        """A bare number is minutes; h/m/s components are exact and any of them may be skipped."""
        assert parse_duration(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "abc",
            "-5",
            "2.5",
            "10x",
            "h",
            "1m2h",  # units out of order
            "10S",  # units are lowercase only
            " 25",
            "٢٥",  # non-ASCII digits: int() would accept them, the isascii guard refuses
        ],
    )
    def test_rejects(self, text):
        """Anything that is not a bare number or an ordered h/m/s string is refused."""
        with pytest.raises(AppError, match="not a duration"):
            parse_duration(text)


class TestFormatTimestamp:
    """Unix seconds rendered as local 'YYYY-MM-DD HH:MM'."""

    @pytest.mark.parametrize(
        ("tz", "ts", "expected"),
        [
            ("UTC", 1_700_000_000, "2023-11-14 22:13"),
            ("Europe/Berlin", 1_700_000_000, "2023-11-14 23:13"),  # CET: UTC+1 in winter
            ("Europe/Berlin", 1_689_000_000, "2023-07-10 16:40"),  # CEST: the DST offset of that instant
        ],
    )
    def test_localizes(self, tz, ts, expected):
        """The rendering follows the local timezone of the moment, DST included."""
        with pinned_tz(tz):
            assert format_timestamp(ts) == expected
