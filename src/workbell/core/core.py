"""Application core: SQLite storage and business operations in one class."""

import sqlite3
import subprocess
import sys
from pathlib import Path

from workbell.core import bell
from workbell.core.errors import AppError
from workbell.core.migrations import MIGRATIONS
from workbell.core.models import DailyStats, Interval, IntervalStatus, NotificationStyle, Settings, TickResult
from workbell.core.utils import TIMER_LOCK_FILENAME, lock_holder_pid, open_errors_log, unix_now

CHECKPOINT_EVERY_SEC = 10  # a live timer refreshes checkpointed_at at least this often; also max work lost on a crash
# The dead-timer heal fires only when checkpointed_at is this stale AND timer.lock is free; the
# staleness guard covers the timer's startup window before it takes the lock.
TIMER_STALE_SEC = 3 * CHECKPOINT_EVERY_SEC


class Core:
    """The application without interactive UI: owns the SQLite connection and every operation on it.

    Clients (CLI, TUI, tray) and the timer process call these methods; clients show AppError
    messages to the user.
    """

    def __init__(self, db_path: Path) -> None:
        """Open the database (creating the file and its directory if needed) and migrate it."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path  # kept for spawning the timer process, which opens its own connection
        # autocommit: every business mutation is a single guarded statement, so statement = transaction;
        # migrations opt into an explicit BEGIN/COMMIT inside their script.
        self._conn = sqlite3.connect(db_path, autocommit=True)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._migrate()

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()

    def _migrate(self) -> None:
        """Apply pending migrations, tracked via PRAGMA user_version."""
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            # The script and the version bump commit together: a crash mid-migration rolls back
            # cleanly, so a migration is either fully applied and recorded, or not at all.
            self._conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")

    # --- Operations ---

    def start_interval(self, duration_sec: int) -> Interval:
        """Start a new work interval and spawn its timer; refuses while another interval is active.

        Refuses on non-macOS platforms up front: the bell rings via macOS system tools
        (osascript/afplay), so elsewhere the interval would complete silently — the worst
        failure for the app's one guarantee.
        """
        if sys.platform != "darwin":
            raise AppError("workbell requires macOS: the bell rings via macOS system tools.")
        if duration_sec <= 0:
            raise AppError("Duration must be positive.")
        now = unix_now()
        try:
            row = self._conn.execute(
                "INSERT INTO intervals (status, duration_sec, started_at, checkpointed_at)"
                " VALUES ('running', ?, ?, ?) RETURNING *",
                (duration_sec, now, now),
            ).fetchone()
        except sqlite3.IntegrityError as e:  # the one-active partial unique index
            raise AppError("An active interval already exists.") from e
        interval = Interval.from_row(row)
        self._spawn_timer(interval.id)
        return interval

    def pause_interval(self) -> Interval:
        """Pause the running interval, banking the unbanked tail into worked_sec; AppError when nothing is running.

        The dead-timer heal runs first: healing *is* a pause (with the dead gap deliberately
        uncredited), so pausing an interval whose timer died succeeds. The unique active index
        guarantees at most one row matches the status-guarded UPDATE, hence no id parameter.
        """
        healed = self._heal_dead_timer()
        row = self._conn.execute(
            "UPDATE intervals SET status = 'paused',"
            " worked_sec = min(worked_sec + (:now - checkpointed_at), duration_sec), checkpointed_at = NULL"
            " WHERE status = 'running' RETURNING *",
            {"now": unix_now()},
        ).fetchone()
        if row is not None:
            return Interval.from_row(row)
        if healed is not None:
            return healed
        if self.get_active_interval() is None:
            raise AppError("No active interval.")
        raise AppError("The interval is already paused.")

    def resume_interval(self) -> Interval:
        """Resume the paused interval and spawn a fresh timer; AppError when nothing is paused.

        The dead-timer heal runs first, turning a crashed running interval into a paused one — so
        resume also revives intervals whose timer died. A paused interval already at full time
        completes (and rings) within the new timer's first poll: the user gets the bell they missed.
        """
        self._heal_dead_timer()
        row = self._conn.execute(
            "UPDATE intervals SET status = 'running', checkpointed_at = ? WHERE status = 'paused' RETURNING *",
            (unix_now(),),
        ).fetchone()
        if row is None:
            if self.get_active_interval() is None:
                raise AppError("No active interval.")
            raise AppError("The interval is already running.")
        interval = Interval.from_row(row)
        self._spawn_timer(interval.id)
        return interval

    def get_active_interval(self) -> Interval | None:
        """Return the single non-completed interval, or None — healing it first if its timer died."""
        self._heal_dead_timer()
        row = self._conn.execute("SELECT * FROM intervals WHERE status != 'completed'").fetchone()
        return Interval.from_row(row) if row else None

    def list_recent_intervals(self, limit: int) -> list[Interval]:
        """Return the most recent intervals (the active one included), newest first.

        The dead-timer heal runs first — this is a status read like get_active_interval, and a crashed
        interval must not show as running.
        """
        if limit <= 0:
            raise AppError("Limit must be positive.")
        self._heal_dead_timer()
        rows = self._conn.execute("SELECT * FROM intervals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [Interval.from_row(row) for row in rows]

    def count_today_completed(self, now: int) -> int:
        """Count completed intervals belonging to today — started_at falls in the local calendar day of now."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM intervals WHERE status = 'completed'"
            " AND date(started_at, 'unixepoch', 'localtime') = date(:now, 'unixepoch', 'localtime')",
            {"now": now},
        ).fetchone()
        return int(row["cnt"])

    def list_daily_stats(self, limit: int) -> list[DailyStats]:
        """Per-day totals of completed intervals for the most recent `limit` recorded days, newest day first.

        An interval belongs to the local calendar day it was started (the count_today_completed
        convention). A day is recorded when any interval was started in it — one holding only the
        active interval yields a zero row; days without starts do not count toward the limit.
        """
        if limit <= 0:
            raise AppError("Limit must be positive.")
        rows = self._conn.execute(
            "SELECT date(started_at, 'unixepoch', 'localtime') AS day,"
            " COUNT(*) FILTER (WHERE status = 'completed') AS completed,"
            " COALESCE(SUM(worked_sec) FILTER (WHERE status = 'completed'), 0) AS worked_sec"
            " FROM intervals GROUP BY day ORDER BY day DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [DailyStats(**dict(row)) for row in rows]

    def delete_interval(self, interval_id: int) -> None:
        """Delete an interval by id, whatever its status; AppError when it does not exist.

        Deleting a running interval needs no timer coordination: the timer exits on its next
        poll when the row is gone, and its status-guarded writes match nothing until then.
        """
        cur = self._conn.execute("DELETE FROM intervals WHERE id = ?", (interval_id,))
        if cur.rowcount == 0:
            raise AppError(f"Interval #{interval_id} does not exist.")

    def cancel_interval(self, interval_id: int) -> None:
        """Delete a not-yet-completed interval by id; AppError when it completed or vanished meanwhile.

        The status guard protects the caller's confirmation window: if the interval completes
        (bell and all) while the user is deciding, the completed record survives instead of
        being deleted. Timer coordination is the same as delete_interval.
        """
        cur = self._conn.execute("DELETE FROM intervals WHERE id = ? AND status != 'completed'", (interval_id,))
        if cur.rowcount == 0:
            raise AppError("The interval is no longer active.")

    def _heal_dead_timer(self) -> Interval | None:
        """Pause a running interval whose timer is provably dead; return the healed interval, if any.

        Dead means both signals at once: timer.lock is free (the kernel drops the timer's flock
        exactly when the process dies and keeps it through system sleep, so a held lock is a live —
        possibly frozen — timer whose gap legitimately counts as work) AND checkpointed_at is
        ~3 checkpoints old (covers the timer's startup window before it takes the lock). The dead
        gap is deliberately not credited — no work happened; checkpointing keeps worked_sec correct
        to within one checkpoint. Guarded by status = 'running', so racing with a live timer is
        safe. Runs before every status read and state change, so the state heals on the next look
        and nothing needs to run at boot.
        """
        # lock_holder_pid reads a holder mid-PID-write as free (a microsecond window at timer startup);
        # harmless: at startup checkpointed_at is fresh, so the staleness guard below blocks the heal anyway.
        if lock_holder_pid(self.db_path.parent / TIMER_LOCK_FILENAME) is not None:
            return None  # the timer is alive (running or frozen by machine sleep) — nothing to heal
        row = self._conn.execute(
            "UPDATE intervals SET status = 'paused', checkpointed_at = NULL"
            " WHERE status = 'running' AND checkpointed_at <= ? RETURNING *",
            (unix_now() - TIMER_STALE_SEC,),
        ).fetchone()
        return Interval.from_row(row) if row else None

    # --- Settings ---

    def get_settings(self) -> Settings:
        """Return the user settings (the single settings row, seeded by migration)."""
        return Settings.from_row(self._conn.execute("SELECT * FROM settings").fetchone())

    def set_default_duration(self, duration_sec: int) -> Settings:
        """Set the default interval duration; AppError when not positive (the CHECK is the backstop)."""
        if duration_sec <= 0:
            raise AppError("Duration must be positive.")
        row = self._conn.execute("UPDATE settings SET default_duration_sec = ? RETURNING *", (duration_sec,)).fetchone()
        return Settings.from_row(row)

    def set_bell_sound(self, name: str) -> Settings:
        """Set the bell sound by macOS system-sound name, matched case-insensitively.

        The valid names are exactly the installed system-sound files, enumerated fresh on every
        call — a nonexistent sound cannot be chosen. Existence is a filesystem fact, so this one
        settings invariant lives here instead of a CHECK; the ring-time fallback covers a file
        vanishing after it was set.
        """
        sounds = bell.available_sounds()
        canonical = next((s for s in sounds if s.lower() == name.lower()), None)
        if canonical is None:
            raise AppError(f"Unknown sound {name!r}. Available: {', '.join(sounds)}.")
        row = self._conn.execute("UPDATE settings SET bell_sound = ? RETURNING *", (canonical,)).fetchone()
        return Settings.from_row(row)

    def set_notification_style(self, style: str) -> Settings:
        """Set the completion-notification style, matched case-insensitively; AppError on an unknown style."""
        try:
            canonical = NotificationStyle(style.lower())
        except ValueError as e:
            raise AppError(f"Unknown style {style!r}. Available: {', '.join(NotificationStyle)}.") from e
        row = self._conn.execute("UPDATE settings SET notification_style = ? RETURNING *", (canonical.value,)).fetchone()
        return Settings.from_row(row)

    # --- Timer-process plumbing ---

    def timer_tick(self, interval_id: int) -> TickResult:
        """One timer poll: complete the interval when its time is fully worked, checkpoint on cadence."""
        interval = self._get_interval(interval_id)
        if interval is None or interval.status is not IntervalStatus.RUNNING:
            return TickResult.STOP
        now = unix_now()
        if interval.effective_worked(now) >= interval.duration_sec:
            # _complete_interval() returning False = lost the race; whoever won owns the interval now
            return TickResult.COMPLETED if self._complete_interval(interval_id) else TickResult.STOP
        if interval.checkpointed_at is not None and now - interval.checkpointed_at >= CHECKPOINT_EVERY_SEC:
            self._checkpoint_interval(interval_id)
        return TickResult.CONTINUE

    def _get_interval(self, interval_id: int) -> Interval | None:
        """Return an interval by id, or None when it does not exist (the timer's poll target may be deleted)."""
        row = self._conn.execute("SELECT * FROM intervals WHERE id = ?", (interval_id,)).fetchone()
        return Interval.from_row(row) if row else None

    def _checkpoint_interval(self, interval_id: int) -> None:
        """Bank the time since the last checkpoint into worked_sec and stamp a fresh one; no-op unless running.

        Called from tick every ~10s. Doubles as crash recovery (worked_sec is always
        nearly current) and as the liveness signal (a running interval with a stale checkpointed_at
        has a dead timer).
        """
        self._conn.execute(
            "UPDATE intervals SET worked_sec = min(worked_sec + (:now - checkpointed_at), duration_sec),"
            " checkpointed_at = :now WHERE id = :id AND status = 'running'",
            {"now": unix_now(), "id": interval_id},
        )

    def _complete_interval(self, interval_id: int) -> bool:
        """Complete a running interval, crediting the full planned time; False when changed concurrently."""
        cur = self._conn.execute(
            "UPDATE intervals SET status = 'completed', worked_sec = duration_sec, checkpointed_at = NULL,"
            " completed_at = ? WHERE id = ? AND status = 'running'",
            (unix_now(), interval_id),
        )
        return cur.rowcount > 0

    def _spawn_timer(self, interval_id: int) -> None:
        """Launch the detached timer process that counts the interval down and rings the bell."""
        # S603 suppressed: fixed argv built from sys.executable and our own db path/int id — no
        # shell, no user-controlled strings, nothing an attacker can inject into.
        # stdout/stderr go to errors.log, not DEVNULL: the timer has no terminal, and its crash
        # traceback must survive somewhere the user can find. The parent handle closes right
        # after the spawn; the child keeps its inherited descriptor.
        with open_errors_log(self.db_path.parent) as log:
            subprocess.Popen(  # noqa: S603
                [sys.executable, "-m", "workbell.core.timer", str(self.db_path), str(interval_id)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
