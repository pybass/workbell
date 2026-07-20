"""The resume command: continue a paused interval."""

from workbell.cli import utils
from workbell.core.utils import format_hms


def run(*, core: utils.InjectedCore) -> None:
    """Resume the paused interval."""
    interval = core.resume_interval()
    left = interval.duration_sec - interval.worked_sec
    utils.console.print(f"Interval resumed: {format_hms(left)} left.")
