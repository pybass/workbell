from workbell.cli import utils
from workbell.core.utils import format_hms


def run(duration: str | None = None, *, core: utils.InjectedCore) -> None:
    """Start a work interval.

    Parameters
    ----------
    duration
        Minutes when bare ('25'), or exact with h/m/s units ('10s', '90m', '1h20m').
        Omitted: the configured default duration (see 'workbell config').
    core
        Injected by the launcher.

    """
    duration_sec = utils.parse_duration(duration) if duration is not None else core.get_settings().default_duration_sec
    interval = core.start_interval(duration_sec)
    utils.console.print(f"Interval started for {format_hms(interval.duration_sec)}.")
