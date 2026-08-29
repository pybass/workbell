import re
from datetime import UTC, datetime
from typing import Annotated

from cyclopts import Parameter
from rich.console import Console

from workbell.core.core import Core
from workbell.core.errors import AppError
from workbell.core.models import IntervalStatus

type InjectedCore = Annotated[Core, Parameter(parse=False)]  # a Core injected by the launcher, invisible to CLI parsing

DURATION_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")  # h/m/s components, each optional, in this order
# rich color per status; completed intervals keep the terminal's default color
STATUS_STYLE = {IntervalStatus.RUNNING: "green", IntervalStatus.PAUSED: "yellow", IntervalStatus.COMPLETED: "default"}

# The one console every command prints through. highlight=False (no auto-colored numbers) and
# soft_wrap=True (no hard wrapping in pipes) make console.print behave like print() until a style is asked for.
console = Console(highlight=False, soft_wrap=True)


def parse_duration(text: str) -> int:
    """Parse a duration into seconds: a bare number means minutes ('25'), h/m/s units are exact ('10s', '1h20m')."""
    if text.isascii() and text.isdigit():
        return int(text) * 60
    match = DURATION_RE.fullmatch(text)
    if match is None or not any(match.groups()):
        raise AppError(f"{text!r} is not a duration (expected e.g. 25, 10s, 90m or 1h20m10s).")
    hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def format_timestamp(ts: int) -> str:
    """Format unix seconds as local time, 'YYYY-MM-DD HH:MM'."""
    return datetime.fromtimestamp(ts, tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M")
