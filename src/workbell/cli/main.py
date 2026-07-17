"""CLI client: control workbell from the shell."""

import os
import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from workbell.cli.commands import config, delete, history, pause, raycast, resume, start, status, tray
from workbell.core.core import Core
from workbell.core.errors import AppError

app = App(name="workbell", help="Work-interval timer.")
app.command(start.run, name="start")
app.command(status.run, name="status")
app.command(pause.run, name="pause")
app.command(resume.run, name="resume")
app.command(history.run, name="history")
app.command(delete.run, name="delete")
app.command(config.app)
app.command(raycast.app)
app.command(tray.app)


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
    if data_dir is None:  # default: the XDG data dir (deliberate cross-tool convention; usually ~/.local/share)
        data_dir = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "workbell"
    core = Core(data_dir / "workbell.db")
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
