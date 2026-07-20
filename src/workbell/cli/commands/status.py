"""The status command: show the active interval's progress."""

from datetime import UTC, datetime

from workbell.cli import utils
from workbell.core.models import IntervalStatus
from workbell.core.utils import format_hms, unix_now


def run(*, core: utils.InjectedCore) -> None:
    """Show the active interval."""
    active = core.get_active_interval()
    if active is None:
        utils.console.print("No active interval.")
        return
    now = unix_now()
    worked = active.effective_worked(now)
    left = active.duration_sec - worked
    rings_at = ""
    if active.status is IntervalStatus.RUNNING:  # an absolute ring time exists only while running
        rings_at = f", rings at {datetime.fromtimestamp(now + left, tz=UTC).astimezone():%H:%M}"
    utils.console.print(
        f"Interval [{utils.STATUS_STYLE[active.status]}]{active.status}[/]:"
        f" {format_hms(worked)} of {format_hms(active.duration_sec)} worked, {format_hms(left)} left{rings_at}."
    )
