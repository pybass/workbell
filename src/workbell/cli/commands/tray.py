import os
import signal
import subprocess
import sys

from cyclopts import App

from workbell.cli import utils
from workbell.core.errors import AppError
from workbell.core.utils import lock_holder_pid

app = App(name="tray", help="Menu bar icon (macOS).")


@app.default
def run(*, foreground: bool = False, core: utils.InjectedCore) -> None:
    """Launch the tray icon as a detached background process.

    Parameters
    ----------
    foreground
        Run attached to this terminal instead of detached (handy for debugging).
    core
        Injected by the launcher.

    """
    if lock_holder_pid(core.tray_lock) is not None:
        raise AppError("Tray is already running.")
    # S603 suppressed (both spawns): fixed argv built from sys.executable and our own data dir —
    # no shell, nothing user-controlled. The CLI runs the tray as a subprocess rather than
    # importing it, keeping clients independent of each other.
    argv = [sys.executable, "-m", "workbell.tray", *core.data_dir_argv]
    if foreground:
        rc = subprocess.run(argv, check=False).returncode  # noqa: S603
        raise SystemExit(128 - rc if rc < 0 else rc)  # negative = killed by signal; report the shell convention 128+signum
    # stdout/stderr go to errors.log, not DEVNULL: the detached tray has no terminal, and its
    # crash traceback must survive somewhere the user can find.
    with core.errors_log.open("ab") as log:
        subprocess.Popen(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    utils.console.print("Tray started.")


@app.command(name="stop")
def stop(*, core: utils.InjectedCore) -> None:
    """Stop the running tray icon."""
    pid = lock_holder_pid(core.tray_lock)
    if pid is None:
        raise AppError("Tray is not running.")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:  # the tray died between the lock probe and the kill
        raise AppError("Tray is not running.") from None
    utils.console.print("Tray stopped.")
