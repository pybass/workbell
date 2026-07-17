"""The history command: list recent intervals."""

from rich.table import Table

from workbell.cli import utils
from workbell.core.utils import format_hms, unix_now


def run(limit: int = 20, *, core: utils.InjectedCore) -> None:
    """List recent intervals, newest first.

    Parameters
    ----------
    limit
        Maximum number of intervals to show.
    core
        Injected by the launcher.

    """
    intervals = core.list_recent_intervals(limit)
    if not intervals:
        utils.console.print("No intervals.")
        return
    now = unix_now()
    table = Table("ID", "Status", "Worked", "Duration", "Started", "Completed")
    for interval in intervals:
        table.add_row(
            str(interval.id),
            f"[{utils.STATUS_STYLE[interval.status]}]{interval.status}[/]",
            format_hms(interval.effective_worked(now)),
            format_hms(interval.duration_sec),
            utils.format_timestamp(interval.started_at),
            utils.format_timestamp(interval.completed_at) if interval.completed_at is not None else "-",
        )
    utils.console.print(table)
