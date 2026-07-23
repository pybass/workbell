"""The timer process: counts one running interval down and rings the bell when its time is up.

Part of core, not a client: the bell is the application's guarantee and must ring even when
no client is open. Spawned detached by Core.start_interval as `python -m workbell.core.timer
<db_path> <interval_id>`. Exits as soon as the interval is gone or no longer running; every
write is guarded by `status = 'running'` in SQL, so racing with pause/delete/recovery is safe.

For its whole life the timer holds an exclusive flock on timer.lock: the kernel keeps the
lock through system sleep and drops it the moment the process dies, which is how crash
recovery tells a frozen timer (sleep — the gap counts as work) from a dead one (crash —
the gap is dropped).
"""

import sys
import time
from pathlib import Path

from workbell.core import bell
from workbell.core.core import Core
from workbell.core.models import TickResult
from workbell.core.utils import TIMER_LOCK_FILENAME, acquire_pid_lock, print_crash_header

POLL_SEC = 1.0  # how often the interval row is re-read


def main() -> None:
    """Entry point for `python -m workbell.core.timer <db_path> <interval_id>`."""
    db_path = Path(sys.argv[1])
    interval_id = int(sys.argv[2])
    # Blocking acquire: the predecessor timer of the same interval (pause→resume within a
    # second) may still be finishing its last poll; waiting out its exit is the correct move.
    lock = acquire_pid_lock(db_path.parent / TIMER_LOCK_FILENAME, blocking=True)
    if lock is None:  # a real flock error, not a held lock (blocking waits those out); heal will pause the interval
        return
    core = Core(db_path)
    try:
        # Poll the interval until it completes or stops being ours to supervise.
        while True:
            result = core.timer_tick(interval_id)
            if result is TickResult.COMPLETED:
                settings = core.get_settings()  # settings are read at ring time, not at spawn
                bell.ring(settings.bell_sound, settings.notification_style)
            if result is not TickResult.CONTINUE:
                return
            time.sleep(POLL_SEC)
    finally:
        core.close()
        lock.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # stderr is errors.log (the spawn redirected it): stamp the traceback so the user can date it
        print_crash_header("timer")
        raise
