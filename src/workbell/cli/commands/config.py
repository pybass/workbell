"""The config command group: show and change user settings."""

from cyclopts import App

from workbell.cli import utils
from workbell.core import bell
from workbell.core.utils import format_hms

app = App(name="config", help="User settings.")


@app.default
def show(*, core: utils.InjectedCore) -> None:
    """Show the current settings."""
    settings = core.get_settings()
    utils.console.print(f"default-duration: {format_hms(settings.default_duration_sec)}")
    utils.console.print(f"bell-sound: {settings.bell_sound}")


@app.command(name="default-duration")
def default_duration(duration: str, *, core: utils.InjectedCore) -> None:
    """Set the default interval duration.

    Parameters
    ----------
    duration
        Minutes when bare ('25'), or exact with h/m/s units ('10s', '90m', '1h20m').
    core
        Injected by the launcher.

    """
    settings = core.set_default_duration(utils.parse_duration(duration))
    utils.console.print(f"Default duration set to {format_hms(settings.default_duration_sec)}.")


@app.command(name="bell-sound")
def bell_sound(name: str | None = None, *, core: utils.InjectedCore) -> None:
    """Set the bell sound, or list the installed sounds when no name is given.

    Parameters
    ----------
    name
        A macOS system-sound name, case-insensitive ('ping'). Omit to list the choices.
    core
        Injected by the launcher.

    """
    if name is None:
        current = core.get_settings().bell_sound
        for sound in bell.available_sounds():
            utils.console.print(f"* {sound}" if sound == current else f"  {sound}")
        return
    settings = core.set_bell_sound(name)
    utils.console.print(f"Bell sound set to {settings.bell_sound}.")
    bell.play_sound(settings.bell_sound)  # preview: the user hears their choice immediately
