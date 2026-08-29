from rich.table import Table

from workbell.cli import utils
from workbell.core.utils import format_hms


def run(limit: int = 20, *, core: utils.InjectedCore) -> None:
    """Show per-day completed totals for the most recent recorded days, newest first.

    Parameters
    ----------
    limit
        Maximum number of days to show.
    core
        Injected by the launcher.

    """
    stats = core.list_daily_stats(limit)
    if not stats:
        utils.console.print("No intervals.")
        return
    table = Table("Date", "Completed", "Worked")
    for entry in stats:
        table.add_row(entry.day, str(entry.completed), format_hms(entry.worked_sec) if entry.completed else "-")
    utils.console.print(table)
