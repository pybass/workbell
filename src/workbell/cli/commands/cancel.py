"""The cancel command: discard the active interval."""

from typing import Annotated

from cyclopts import Parameter
from rich.prompt import Confirm

from workbell.cli import utils
from workbell.core.errors import AppError
from workbell.core.utils import format_hms, unix_now


def run(*, yes: Annotated[bool, Parameter(negative="")] = False, core: utils.InjectedCore) -> None:
    """Cancel the active interval: delete it, running or paused.

    Parameters
    ----------
    yes
        Skip the confirmation prompt.
    core
        Injected by the launcher.

    """
    interval = core.get_active_interval()
    if interval is None:
        raise AppError("No active interval.")
    progress = f"{format_hms(interval.effective_worked(unix_now()))} of {format_hms(interval.duration_sec)} worked"
    if not yes:
        try:
            confirmed = Confirm.ask(f"Cancel the {interval.status} interval ({progress})?", console=utils.console, default=False)
        except EOFError:  # stdin closed (a non-interactive run without --yes): the safe answer is no
            confirmed = False
        if not confirmed:
            utils.console.print("Kept the interval.")
            return
    core.cancel_interval(interval.id)
    utils.console.print(f"Interval canceled: {progress}.")
