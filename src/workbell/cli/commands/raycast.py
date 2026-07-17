"""The raycast command group: generate Raycast script commands that drive the CLI."""

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from cyclopts import App

from workbell.cli import utils

app = App(name="raycast", help="Raycast integration.")


@dataclass(frozen=True, slots=True)
class _Script:
    """One Raycast script command: the metadata Raycast reads plus the CLI call it runs."""

    filename: str  # file name inside the target directory
    title: str  # command title shown in Raycast's search bar
    description: str  # one-line description shown in Raycast
    icon: str  # emoji shown next to the title
    mode: str  # Raycast output mode: 'silent' (brief HUD) or 'compact' (single result line)
    command: str  # workbell subcommand appended to the baked base command


# The generated command set. Deliberately no delete script: deletion always takes an explicit
# interval id (docs/non-goals.md), and picking an id is not a search-bar interaction.
_SCRIPTS = (
    _Script("start.sh", "Start Work Interval", "Start a work interval with the default duration", "🔔", "silent", "start"),
    _Script("pause.sh", "Pause Work Interval", "Pause the running work interval", "⏸️", "silent", "pause"),
    _Script("resume.sh", "Resume Work Interval", "Resume the paused work interval", "▶️", "silent", "resume"),
    _Script("status.sh", "Work Interval Status", "Show the active work interval", "📊", "compact", "status"),
    _Script("tray.sh", "Open Workbell Tray", "Open the workbell menu bar icon", "🖥️", "silent", "tray"),
)


def _render(script: _Script, base_command: str) -> str:
    """Render one script: the @raycast metadata header plus a one-line exec of the workbell CLI."""
    header = [
        "#!/bin/bash",
        "# @raycast.schemaVersion 1",
        f"# @raycast.title {script.title}",
        f"# @raycast.mode {script.mode}",
        f"# @raycast.icon {script.icon}",
        "# @raycast.packageName workbell",
        f"# @raycast.description {script.description}",
    ]
    # 2>&1: AppError lands on stderr, and Raycast's HUD / result line shows only stdout.
    return "\n".join([*header, "", f"exec {base_command} {script.command} 2>&1", ""])


@app.command(name="install")
def install(target_dir: Path | None = None, *, core: utils.InjectedCore) -> None:
    """Generate the Raycast script commands into a directory.

    Idempotent: always writes the current canonical set, so re-running it (e.g. after
    upgrading workbell) refreshes the scripts in place — Raycast notices file changes in
    an already-added directory by itself.

    Parameters
    ----------
    target_dir
        Where to write the scripts (default: raycast/ inside the data directory).
    core
        Injected by the launcher.

    """
    data_dir = core.db_path.parent.resolve()
    dest = (target_dir if target_dir is not None else data_dir / "raycast").resolve()
    # The absolute binary path and the data dir are baked into every script: Raycast runs
    # scripts with a minimal environment, so neither PATH nor the user's XDG_DATA_HOME can be
    # trusted at run time. sys.argv[0] resolved covers uv tool installs and dev venvs alike.
    binary = Path(sys.argv[0]).resolve()
    base_command = f"{shlex.quote(str(binary))} --data-dir {shlex.quote(str(data_dir))}"
    dest.mkdir(parents=True, exist_ok=True)
    for script in _SCRIPTS:
        path = dest / script.filename
        path.write_text(_render(script, base_command), encoding="utf-8")
        path.chmod(0o755)  # Raycast executes the scripts directly, so they must be executable
    utils.console.print(f"Installed {len(_SCRIPTS)} Raycast script commands into {dest}.")
    utils.console.print("One-time setup: Raycast Settings → Extensions → Script Commands → Add Directories.")
