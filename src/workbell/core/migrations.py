"""Database schema migrations, applied in order by Core."""

# Schema v1: the whole schema — work intervals plus the single settings row.
#
# intervals: one row per work interval; no audit/event log.
# Time accounting: worked_sec accumulates past work; the current running segment is
# (now - checkpointed_at) and exists only while status = 'running'. Effective worked
# time = worked_sec + current segment, capped at duration_sec. The timer process
# checkpoints every ~10s (worked_sec += now - checkpointed_at; checkpointed_at = now),
# which is also the crash-recovery mechanism: no separate heartbeat column, and after
# a crash worked_sec is already correct to within one checkpoint.
#
# checkpointed_at / completed_at are nullable on purpose: NULL means "no such thing in
# this state", and the CHECKs tie them to status — SQL's discriminated union.
#
# settings: user settings as a single typed row — not a key-value store — so the database
# keeps enforcing types and invariants (STRICT, CHECKs), consistent with intervals. Seeded
# here so reads are a plain SELECT with no fallback logic; a future setting is one
# append-only migration: ALTER TABLE settings ADD COLUMN ... NOT NULL DEFAULT ...
# bell_sound is a macOS system-sound name; whether such a sound exists is a filesystem
# fact no CHECK can pin, so the CHECK only rejects the empty string — core validates the
# name against the installed sounds at set time, and the bell falls back to the default
# at ring time if the file has vanished since.
_MIGRATION_V1 = """
CREATE TABLE intervals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    status          TEXT NOT NULL CHECK (status IN ('running', 'paused', 'completed')),
    duration_sec    INTEGER NOT NULL CHECK (duration_sec > 0),              -- planned length
    worked_sec      INTEGER NOT NULL DEFAULT 0,                             -- accumulated work, sans the current segment
    started_at      INTEGER NOT NULL,                                       -- unix seconds; when the interval was started
    checkpointed_at INTEGER,                                                -- unix seconds; when worked_sec was last exact
    completed_at    INTEGER,                                                -- unix seconds; when the interval completed
    CHECK (worked_sec >= 0 AND worked_sec <= duration_sec),
    CHECK ((status = 'running') = (checkpointed_at IS NOT NULL)),
    CHECK ((status = 'completed') = (completed_at IS NOT NULL)),
    -- No early completion: a completed interval always worked its full planned time.
    -- One-way on purpose: a paused interval may also reach worked_sec = duration_sec
    -- (crash recovery pauses a running interval whose timer had just elapsed).
    CHECK (status != 'completed' OR worked_sec = duration_sec)
) STRICT;

-- The database itself refuses a second active (not yet completed) interval.
CREATE UNIQUE INDEX idx_intervals_one_active ON intervals ((1)) WHERE status != 'completed';

CREATE TABLE settings (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),                -- exactly one row, ever
    default_duration_sec INTEGER NOT NULL CHECK (default_duration_sec > 0), -- default interval length
    bell_sound           TEXT NOT NULL CHECK (bell_sound != '')             -- macOS system-sound name
) STRICT;

INSERT INTO settings (id, default_duration_sec, bell_sound) VALUES (1, 1500, 'Glass'); -- 25 minutes
"""

MIGRATIONS = (_MIGRATION_V1,)  # append-only; index+1 = PRAGMA user_version
