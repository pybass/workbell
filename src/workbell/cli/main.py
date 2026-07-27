"""CLI client: control workbell from the shell."""

import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from workbell.cli.commands import cancel, config, delete, history, pause, raycast, resume, start, stats, status, tray
from workbell.core.core import Core
from workbell.core.errors import AppError

app = App(name="workbell", help="Work-interval timer.")
# Explicit sort_key on every command fixes the help order (cyclopts sorts alphabetically without
# it): the interval lifecycle in the order it happens, then inspection, records, setup.
app.command(start.run, name="start", sort_key=1)
app.command(pause.run, name="pause", sort_key=2)
app.command(resume.run, name="resume", sort_key=3)
app.command(cancel.run, name="cancel", sort_key=4)
app.command(status.run, name="status", sort_key=5)
app.command(history.run, name="history", sort_key=6)
app.command(stats.run, name="stats", sort_key=7)
app.command(delete.run, name="delete", sort_key=8)
app.command(config.app)
app.command(tray.app)
app.command(raycast.app)
config.app.sort_key = 9  # sub-apps cannot take sort_key at registration time
tray.app.sort_key = 10
raycast.app.sort_key = 11
app["--help"].show = False  # both flags keep working; they are just noise in the command list
app["--version"].show = False


@app.meta.default
def launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    data_dir: Path | None = None,
) -> None:
    """Run the selected command, opening (and closing) the Core only when it asks for one.

    Parameters
    ----------
    tokens
        Raw CLI tokens, forwarded to the selected command.
    data_dir
        Data directory (default: ~/.local/share/workbell).

    """
    command, bound, ignored = app.parse_args(tokens)
    if "core" not in ignored:  # --help and --version run without a database
        command(*bound.args, **bound.kwargs)
        return
    core = Core(data_dir if data_dir is not None else Core.DEFAULT_DATA_DIR)
    try:
        command(*bound.args, **bound.kwargs, core=core)
    finally:
        core.close()


def main() -> None:
    """Console-script entry point: map AppError to a clean one-line exit."""
    try:
        app.meta()
    except AppError as e:
        sys.exit(f"error: {e}")
