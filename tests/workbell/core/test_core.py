"""Tests for Core: every business operation against a real temporary SQLite database.

Only Core._spawn_timer is replaced (see the `core` fixture) — real detached timer
processes would checkpoint concurrently with the backdating helper below and ring the
real bell whenever a test interval completes. Everything else runs for real.

Time-dependent behavior (crediting, healing, today-counting) is exercised by backdating
the persisted timestamps, never by waiting.
"""

import sqlite3
from datetime import UTC, datetime

import pytest

from workbell.core import bell
from workbell.core.core import CHECKPOINT_EVERY_SEC, TIMER_STALE_SEC, Core
from workbell.core.errors import AppError
from workbell.core.migrations import MIGRATIONS
from workbell.core.models import IntervalStatus, Settings, TickResult
from workbell.core.utils import TIMER_LOCK_FILENAME, acquire_pid_lock

DURATION = 1500  # planned length used where the value itself does not matter (an ordinary 25-minute interval)
FRESH_BACKDATE_SEC = TIMER_STALE_SEC - 10  # backdate that credits measurable work yet stays below the dead-timer threshold
STALE_BACKDATE_SEC = TIMER_STALE_SEC + 60  # backdate that makes the timer look dead
NOW = 1_700_000_000  # synthetic 'now' for count_today_completed, which takes now explicitly — no real clock involved
# Local midnight opening NOW's calendar day, per the same OS timezone rules SQLite's 'localtime' modifier consults.
MIDNIGHT = int(datetime.fromtimestamp(NOW, tz=UTC).astimezone().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


@pytest.fixture
def spawned():
    """Interval ids the Core asked to spawn a timer for (recorded by the `core` fixture's patch)."""
    return []


@pytest.fixture
def core(tmp_path, monkeypatch, spawned):
    """Core on a fresh temporary database, with _spawn_timer stubbed to a recorder.

    The stub is the one sanctioned test double: a real spawn would launch background
    processes that race these tests and ring the real bell.
    """
    monkeypatch.setattr(Core, "_spawn_timer", lambda _self, interval_id: spawned.append(interval_id))
    instance = Core(tmp_path / "workbell.db")
    yield instance
    instance.close()


@pytest.fixture
def db(core):
    """Second connection to the same database, for backdating timestamps and raw inspection."""
    conn = sqlite3.connect(core.db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def backdate_checkpointed_at(db: sqlite3.Connection, seconds: int) -> None:
    """Shift the last checkpoint into the past — simulated elapsed time, no real waiting."""
    db.execute("UPDATE intervals SET checkpointed_at = checkpointed_at - ?", (seconds,))
    db.commit()


class TestMigrations:
    """Schema creation and versioning on open."""

    def test_fresh_database(self, core, db):
        """Opening a missing file creates it and applies every migration."""
        assert core.db_path.exists()
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)

    def test_reopen(self, core, db):
        """A second Core on an already-migrated database finds the schema current and re-runs nothing."""
        Core(core.db_path).close()
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


class TestStart:
    """Starting a new interval."""

    def test_starts_running(self, core):
        """A new interval is running, with zero banked work and the initial checkpoint stamped at start."""
        interval = core.start_interval(DURATION)
        assert interval.status is IntervalStatus.RUNNING
        assert interval.duration_sec == DURATION
        assert interval.worked_sec == 0
        assert interval.checkpointed_at == interval.started_at
        assert interval.completed_at is None

    def test_spawns_timer(self, core, spawned):
        """Start launches the timer for the new interval."""
        interval = core.start_interval(DURATION)
        assert spawned == [interval.id]

    @pytest.mark.parametrize("duration", [0, -60])
    def test_rejects_nonpositive_duration(self, core, duration):
        """Zero and negative durations are refused."""
        with pytest.raises(AppError, match="positive"):
            core.start_interval(duration)

    @pytest.mark.parametrize("state", ["running", "paused"])
    def test_refuses_second_active(self, core, state):
        """The database's one-active rule surfaces as AppError while any interval is active."""
        core.start_interval(DURATION)
        if state == "paused":
            core.pause_interval()
        with pytest.raises(AppError, match="already exists"):
            core.start_interval(DURATION)

    def test_allows_start_after_completion(self, core):
        """A completed interval no longer occupies the active slot."""
        first = core.start_interval(DURATION)
        assert core._complete_interval(first.id)
        second = core.start_interval(DURATION)
        assert second.id != first.id


class TestPause:
    """Pausing the running interval."""

    def test_credits_live_segment(self, core, db):
        """Pause banks the unbanked tail into worked_sec and clears checkpointed_at."""
        core.start_interval(DURATION)
        backdate_checkpointed_at(db, FRESH_BACKDATE_SEC)
        interval = core.pause_interval()
        assert interval.status is IntervalStatus.PAUSED
        assert interval.worked_sec == pytest.approx(FRESH_BACKDATE_SEC, abs=2)
        assert interval.checkpointed_at is None

    def test_caps_at_duration(self, core, db):
        """A tail longer than the plan credits at most the planned duration."""
        core.start_interval(5)
        backdate_checkpointed_at(db, FRESH_BACKDATE_SEC)
        interval = core.pause_interval()
        assert interval.worked_sec == 5

    def test_nothing_active(self, core):
        """Pause with no interval at all is an error."""
        with pytest.raises(AppError, match="No active interval"):
            core.pause_interval()

    def test_already_paused(self, core):
        """Pausing twice is an error, not a silent no-op."""
        core.start_interval(DURATION)
        core.pause_interval()
        with pytest.raises(AppError, match="already paused"):
            core.pause_interval()

    def test_heals_dead_timer(self, core, db):
        """Pausing an interval whose timer died succeeds; the dead gap is deliberately not credited."""
        core.start_interval(DURATION)
        backdate_checkpointed_at(db, STALE_BACKDATE_SEC)
        interval = core.pause_interval()
        assert interval.status is IntervalStatus.PAUSED
        assert interval.worked_sec == 0

    def test_credits_gap_while_timer_alive(self, core, db):
        """Pausing across a long gap with a live timer (machine sleep) credits the whole gap as work."""
        core.start_interval(DURATION)
        backdate_checkpointed_at(db, STALE_BACKDATE_SEC)
        lock = acquire_pid_lock(core.db_path.parent / TIMER_LOCK_FILENAME)
        assert lock is not None  # nothing else holds the timer lock in tests (_spawn_timer is stubbed)
        try:
            interval = core.pause_interval()
        finally:
            lock.close()
        assert interval.worked_sec == pytest.approx(STALE_BACKDATE_SEC, abs=2)


class TestResume:
    """Resuming the paused interval."""

    def test_resumes(self, core):
        """Resume turns the paused interval back into a running one with a fresh segment."""
        core.start_interval(DURATION)
        core.pause_interval()
        interval = core.resume_interval()
        assert interval.status is IntervalStatus.RUNNING
        assert interval.checkpointed_at is not None

    def test_spawns_fresh_timer(self, core, spawned):
        """Resume spawns a new timer for the same interval."""
        interval = core.start_interval(DURATION)
        core.pause_interval()
        core.resume_interval()
        assert spawned == [interval.id, interval.id]

    def test_nothing_active(self, core):
        """Resume with no interval at all is an error."""
        with pytest.raises(AppError, match="No active interval"):
            core.resume_interval()

    def test_already_running(self, core):
        """Resuming a running interval is an error, not a silent no-op."""
        core.start_interval(DURATION)
        with pytest.raises(AppError, match="already running"):
            core.resume_interval()

    def test_revives_dead_timer(self, core, db, spawned):
        """Resume heals a crashed running interval, credits nothing for the gap, and re-spawns the timer."""
        interval = core.start_interval(DURATION)
        backdate_checkpointed_at(db, STALE_BACKDATE_SEC)
        resumed = core.resume_interval()
        assert resumed.status is IntervalStatus.RUNNING
        assert resumed.worked_sec == 0
        assert resumed.checkpointed_at is not None
        assert resumed.checkpointed_at >= interval.started_at  # a fresh stamp, not the stale one
        assert spawned == [interval.id, interval.id]


class TestGetInterval:
    """Fetching a single interval by id."""

    def test_by_id(self, core):
        """An existing interval comes back field-for-field."""
        interval = core.start_interval(DURATION)
        assert core._get_interval(interval.id) == interval

    def test_missing(self, core):
        """A nonexistent id yields None, not an error (the timer polls a possibly-deleted row)."""
        assert core._get_interval(999) is None


class TestGetActive:
    """Reading the single active interval."""

    def test_none_when_empty(self, core):
        """No intervals at all — no active one."""
        assert core.get_active_interval() is None

    @pytest.mark.parametrize("state", ["running", "paused"])
    def test_returns_active(self, core, state):
        """Both running and paused intervals count as active."""
        interval = core.start_interval(DURATION)
        if state == "paused":
            core.pause_interval()
        active = core.get_active_interval()
        assert active is not None
        assert active.id == interval.id

    def test_none_when_completed(self, core):
        """A completed interval is not active."""
        interval = core.start_interval(DURATION)
        core._complete_interval(interval.id)
        assert core.get_active_interval() is None

    def test_heals_stale_running(self, core, db):
        """A crashed running interval reads as paused."""
        core.start_interval(DURATION)
        backdate_checkpointed_at(db, STALE_BACKDATE_SEC)
        active = core.get_active_interval()
        assert active is not None
        assert active.status is IntervalStatus.PAUSED

    def test_heals_at_exact_threshold(self, core, db):
        """checkpointed_at exactly TIMER_STALE_SEC old already counts as dead (inclusive boundary)."""
        core.start_interval(DURATION)
        backdate_checkpointed_at(db, TIMER_STALE_SEC)
        active = core.get_active_interval()
        assert active is not None
        assert active.status is IntervalStatus.PAUSED

    def test_keeps_fresh_running(self, core, db):
        """A recently checkpointed interval proves its timer alive and stays running."""
        core.start_interval(DURATION)
        backdate_checkpointed_at(db, 5)
        active = core.get_active_interval()
        assert active is not None
        assert active.status is IntervalStatus.RUNNING

    def test_no_heal_while_timer_lock_held(self, core, db):
        """A held timer.lock (live timer frozen by machine sleep) blocks the heal despite staleness."""
        core.start_interval(DURATION)
        backdate_checkpointed_at(db, STALE_BACKDATE_SEC)
        lock = acquire_pid_lock(core.db_path.parent / TIMER_LOCK_FILENAME)
        assert lock is not None  # nothing else holds the timer lock in tests (_spawn_timer is stubbed)
        try:
            active = core.get_active_interval()
            assert active is not None
            assert active.status is IntervalStatus.RUNNING
        finally:
            lock.close()
        healed = core.get_active_interval()  # lock released: the same staleness now proves the timer dead
        assert healed is not None
        assert healed.status is IntervalStatus.PAUSED


class TestListRecent:
    """Listing recent intervals."""

    def test_newest_first(self, core):
        """Intervals come back newest first, the active one included."""
        first = core.start_interval(DURATION)
        core._complete_interval(first.id)
        second = core.start_interval(DURATION)
        core._complete_interval(second.id)
        third = core.start_interval(DURATION)
        assert [interval.id for interval in core.list_recent_intervals(10)] == [third.id, second.id, first.id]

    def test_limit(self, core):
        """The limit truncates the list."""
        for _ in range(3):
            interval = core.start_interval(DURATION)
            core._complete_interval(interval.id)
        assert len(core.list_recent_intervals(2)) == 2

    @pytest.mark.parametrize("limit", [0, -1])
    def test_rejects_nonpositive_limit(self, core, limit):
        """Zero and negative limits are refused."""
        with pytest.raises(AppError, match="positive"):
            core.list_recent_intervals(limit)

    def test_heals_stale_running(self, core, db):
        """A crashed running interval must not be listed as running."""
        core.start_interval(DURATION)
        backdate_checkpointed_at(db, STALE_BACKDATE_SEC)
        assert core.list_recent_intervals(10)[0].status is IntervalStatus.PAUSED


class TestCheckpoint:
    """The timer's periodic fold of the live segment into worked_sec."""

    def test_folds_segment(self, core, db):
        """Checkpoint banks the elapsed tail and stamps a fresh checkpoint at now."""
        interval = core.start_interval(DURATION)
        backdate_checkpointed_at(db, FRESH_BACKDATE_SEC)
        core._checkpoint_interval(interval.id)
        checked = core._get_interval(interval.id)
        assert checked is not None
        assert checked.worked_sec == pytest.approx(FRESH_BACKDATE_SEC, abs=2)
        assert checked.checkpointed_at is not None
        assert checked.checkpointed_at >= interval.started_at  # restamped, no longer backdated

    def test_caps_at_duration(self, core, db):
        """Banked work never exceeds the plan; completion stays the timer's separate decision."""
        interval = core.start_interval(5)
        backdate_checkpointed_at(db, FRESH_BACKDATE_SEC)
        core._checkpoint_interval(interval.id)
        checked = core._get_interval(interval.id)
        assert checked is not None
        assert checked.worked_sec == 5
        assert checked.status is IntervalStatus.RUNNING

    def test_noop_when_paused(self, core):
        """A checkpoint racing a pause loses and changes nothing."""
        interval = core.start_interval(DURATION)
        paused = core.pause_interval()
        core._checkpoint_interval(interval.id)
        assert core._get_interval(interval.id) == paused

    def test_noop_for_missing_id(self, core):
        """A checkpoint racing a delete loses silently — not raising is the assertion."""
        core._checkpoint_interval(999)


class TestComplete:
    """Completing a running interval (the timer's endgame)."""

    def test_completes(self, core):
        """Completion credits the full plan and stamps completed_at."""
        interval = core.start_interval(DURATION)
        assert core._complete_interval(interval.id) is True
        completed = core._get_interval(interval.id)
        assert completed is not None
        assert completed.status is IntervalStatus.COMPLETED
        assert completed.worked_sec == completed.duration_sec
        assert completed.completed_at is not None
        assert completed.checkpointed_at is None

    def test_false_when_not_running(self, core):
        """A completion racing a pause (or a delete) reports the lost race instead of raising."""
        interval = core.start_interval(DURATION)
        core.pause_interval()
        assert core._complete_interval(interval.id) is False
        assert core._complete_interval(999) is False


class TestTimerTick:
    """One timer poll: complete when the time is worked, checkpoint on cadence, stop when not running."""

    def test_continue_untouched_before_cadence(self, core, db):
        """A live segment younger than the cadence is left unbanked: CONTINUE with the row untouched."""
        interval = core.start_interval(DURATION)
        backdate_checkpointed_at(db, CHECKPOINT_EVERY_SEC // 2)
        assert core.timer_tick(interval.id) is TickResult.CONTINUE
        after = core._get_interval(interval.id)
        assert after is not None
        assert after.worked_sec == 0
        assert after.checkpointed_at == interval.started_at - CHECKPOINT_EVERY_SEC // 2  # not restamped

    def test_continue_checkpoints_on_cadence(self, core, db):
        """A segment past the cadence is banked and restamped, and the tick still says CONTINUE."""
        interval = core.start_interval(DURATION)
        backdate_checkpointed_at(db, FRESH_BACKDATE_SEC)  # over one cadence old, far under the plan
        assert core.timer_tick(interval.id) is TickResult.CONTINUE
        after = core._get_interval(interval.id)
        assert after is not None
        assert after.worked_sec == pytest.approx(FRESH_BACKDATE_SEC, abs=2)
        assert after.checkpointed_at is not None
        assert after.checkpointed_at >= interval.started_at  # restamped, no longer backdated

    def test_completed_when_time_worked(self, core, db):
        """When the live tail covers the plan, the tick completes the interval — the ring-the-bell signal."""
        interval = core.start_interval(5)
        backdate_checkpointed_at(db, FRESH_BACKDATE_SEC)
        assert core.timer_tick(interval.id) is TickResult.COMPLETED
        after = core._get_interval(interval.id)
        assert after is not None
        assert after.status is IntervalStatus.COMPLETED

    @pytest.mark.parametrize("state", ["paused", "completed", "deleted"])
    def test_stop_when_not_running(self, core, state):
        """Paused, completed, or deleted: the interval is no longer the timer's to supervise."""
        interval = core.start_interval(DURATION)
        if state == "paused":
            core.pause_interval()
        elif state == "completed":
            assert core._complete_interval(interval.id)
        else:
            core.delete_interval(interval.id)
        assert core.timer_tick(interval.id) is TickResult.STOP


class TestDelete:
    """Removing intervals of any status."""

    @pytest.mark.parametrize("status", [IntervalStatus.RUNNING, IntervalStatus.PAUSED, IntervalStatus.COMPLETED])
    def test_deletes_any_status(self, core, status):
        """Any row can be deleted, whatever its lifecycle state."""
        interval = core.start_interval(DURATION)
        if status is IntervalStatus.PAUSED:
            core.pause_interval()
        elif status is IntervalStatus.COMPLETED:
            core._complete_interval(interval.id)
        core.delete_interval(interval.id)
        assert core._get_interval(interval.id) is None

    def test_missing(self, core):
        """Deleting a nonexistent id is an error."""
        with pytest.raises(AppError, match="does not exist"):
            core.delete_interval(999)

    def test_frees_the_active_slot(self, core):
        """Deleting the active interval allows a new start."""
        interval = core.start_interval(DURATION)
        core.delete_interval(interval.id)
        assert core.start_interval(DURATION).status is IntervalStatus.RUNNING


class TestCountTodayCompleted:
    """Counting intervals completed in the local calendar day of a given now."""

    def test_empty(self, core):
        """No intervals — zero completed today."""
        assert core.count_today_completed(NOW) == 0

    @pytest.mark.parametrize(
        ("completed_at", "expected"),
        [(NOW, 1), (MIDNIGHT, 1), (MIDNIGHT - 1, 0), (NOW + 86_400, 0)],
        ids=["now", "midnight", "before-midnight", "next-day"],
    )
    def test_local_day_boundary(self, core, db, completed_at, expected):
        """Day equality in local time, not a 24-hour window: midnight is the inclusive edge."""
        interval = core.start_interval(DURATION)
        assert core._complete_interval(interval.id)
        db.execute("UPDATE intervals SET completed_at = ?", (completed_at,))
        db.commit()
        assert core.count_today_completed(NOW) == expected

    def test_counts_each_completion(self, core, db):
        """Every interval completed today counts once; other days' completions do not."""
        ids = []
        for _ in range(3):
            interval = core.start_interval(DURATION)
            assert core._complete_interval(interval.id)
            ids.append(interval.id)
        db.execute("UPDATE intervals SET completed_at = ?", (NOW,))
        db.execute("UPDATE intervals SET completed_at = ? WHERE id = ?", (MIDNIGHT - 1, ids[0]))
        db.commit()
        assert core.count_today_completed(NOW) == 2


class TestSettings:
    """The single settings row: seeded defaults, updates, validation."""

    def test_seeded_defaults(self, core):
        """A fresh database is seeded with 25 minutes and the bell's fallback sound."""
        assert core.get_settings() == Settings(default_duration_sec=1500, bell_sound=bell.DEFAULT_SOUND)

    def test_set_default_duration(self, core):
        """The new default duration is returned and persisted."""
        assert core.set_default_duration(2700).default_duration_sec == 2700
        assert core.get_settings().default_duration_sec == 2700

    @pytest.mark.parametrize("duration", [0, -60])
    def test_rejects_nonpositive_duration(self, core, duration):
        """Zero and negative default durations are refused."""
        with pytest.raises(AppError, match="positive"):
            core.set_default_duration(duration)

    def test_set_bell_sound_case_insensitive(self, core):
        """The name matches case-insensitively against the installed sounds and is stored canonically."""
        canonical = next(s for s in bell.available_sounds() if s != s.lower())  # a name whose spelling can be mangled
        assert core.set_bell_sound(canonical.lower()).bell_sound == canonical
        assert core.get_settings().bell_sound == canonical

    def test_set_bell_sound_unknown(self, core):
        """A name outside the installed system sounds is refused."""
        with pytest.raises(AppError, match="Unknown sound"):
            core.set_bell_sound("NoSuchSound")
