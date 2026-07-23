# Data Model

Two tables: `intervals` — one row per work interval — and `settings` — a
single row of user settings. No audit log.

## Schema (SQL)

```sql
CREATE TABLE intervals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    status        TEXT NOT NULL CHECK (status IN ('running', 'paused', 'completed')),
    duration_sec  INTEGER NOT NULL CHECK (duration_sec > 0),  -- planned length
    worked_sec    INTEGER NOT NULL DEFAULT 0,                 -- accumulated work, sans the current segment
    started_at    INTEGER NOT NULL,                           -- unix seconds; when the interval was started
    checkpointed_at INTEGER,                                  -- unix seconds; the last checkpoint (start/resume stamp it too)
    completed_at  INTEGER,                                    -- unix seconds; when the interval completed
    CHECK (worked_sec >= 0 AND worked_sec <= duration_sec),
    CHECK ((status = 'running') = (checkpointed_at IS NOT NULL)),
    CHECK ((status = 'completed') = (completed_at IS NOT NULL)),
    -- No early completion. One-way on purpose: a *paused* interval may also
    -- reach full time (crash recovery pauses a running interval whose timer
    -- had just elapsed).
    CHECK (status != 'completed' OR worked_sec = duration_sec)
) STRICT;

-- The database itself refuses a second active (not yet completed) interval.
CREATE UNIQUE INDEX idx_intervals_one_active ON intervals ((1)) WHERE status != 'completed';
```

```sql
CREATE TABLE settings (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),                -- exactly one row, ever
    default_duration_sec INTEGER NOT NULL CHECK (default_duration_sec > 0), -- default interval length
    bell_sound           TEXT NOT NULL CHECK (bell_sound != ''),            -- macOS system-sound name the bell plays
    -- how the bell shows the completion notification
    notification_style   TEXT NOT NULL DEFAULT 'banner' CHECK (notification_style IN ('banner', 'dialog'))
) STRICT;
```

The invariants live in the database, not in code discipline. Beyond what the
SQL already says: `checkpointed_at`/`completed_at` are NULL when the state has
no such thing — NULL plus a status-tied CHECK is SQL's discriminated union,
stricter than NOT NULL with a fake `0`. And there is no `cancelled` status: a
mistaken interval is simply deleted (any row can be, including completed junk).

Settings are one typed row, not a key-value store: the database keeps
enforcing types and ranges, same as for intervals. The row is seeded by the
migration (so reads never need a fallback), and a future setting is just a
new column with a default. The one settings invariant the database cannot
pin is `bell_sound` naming an *installed* sound — existence is a filesystem
fact — so core validates the name against the installed system sounds at
set time, and the bell falls back to the default at ring time if the file
has vanished since.

## Time accounting

An interval's worked time is `worked_sec` (all past work, already banked)
plus the tail since the last checkpoint (`now − checkpointed_at`, exists
only while `running`):

```
effective worked = min(worked_sec + (now − checkpointed_at), duration_sec)
```

Every ~10 s the timer banks the tail and stamps a fresh checkpoint (start
and resume stamp the initial one):

```sql
UPDATE intervals
SET worked_sec = min(worked_sec + (:now - checkpointed_at), duration_sec),
    checkpointed_at = :now
WHERE id = :id AND status = 'running';
```

One guarded UPDATE, per the concurrency rule in
[architecture.md](architecture.md). Checkpointing doubles as crash insurance:
`worked_sec` is stale by at most one checkpoint after any crash. Timer
liveness itself is probed via the timer's `timer.lock` flock (see
[architecture.md](architecture.md)); `checkpointed_at` staleness only guards
the timer's startup window before it takes the lock.
