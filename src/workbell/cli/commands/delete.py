from workbell.cli import utils


def run(interval_id: int, *, core: utils.InjectedCore) -> None:
    """Delete an interval, whatever its status.

    Parameters
    ----------
    interval_id
        Id of the interval to delete (ids are shown by history).
    core
        Injected by the launcher.

    """
    core.delete_interval(interval_id)
    utils.console.print(f"Interval #{interval_id} deleted.")
