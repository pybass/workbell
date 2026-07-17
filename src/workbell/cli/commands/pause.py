"""The pause command: suspend the active interval."""

from workbell.cli import utils
from workbell.core.utils import format_hms


def run(*, core: utils.InjectedCore) -> None:
    """Pause the active interval."""
    interval = core.pause_interval()
    left = interval.duration_sec - interval.worked_sec
    utils.console.print(
        f"Interval #{interval.id} paused:"
        f" {format_hms(interval.worked_sec)} of {format_hms(interval.duration_sec)} worked,"
        f" {format_hms(left)} left."
    )
