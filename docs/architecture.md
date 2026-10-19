# Architecture

Modeled on [tasko](https://github.com/pybass/tasko): a full-featured core, thin clients.

## Layers

`core/` is the whole application minus interactive UI: the SQLite connection,
all business operations, domain models, migrations, errors — and the timer
process that counts the interval down and rings the bell. Clients (`cli/`,
`tray/`, later `tui/`) are thin adapters: each calls the shared `Core` object
in-process and renders the result. Dependencies are one-way: clients import
core, never the reverse, never each other. Core raises `AppError` on
business-rule violations; each client shows the message its own way. The bell
lives in core because it is the application's guarantee: it must ring even
when no client is open.

## State: two columns carry the whole algorithm

One SQLite row per interval ([schema](data-model.md)); `status` is `running`,
`paused` or `completed`. `start` creates a running interval (the DB refuses a
second active one), `pause`/`resume` toggle it, and completion is the only
ending: it always means the full planned time was worked and the bell rang.
A mistaken interval is deleted — `cancel` is a guarded delete of the
active interval, not a fourth status.

All time accounting sits in two columns of that row:

- `worked_sec` — seconds of work already banked;
- `checkpointed_at` — the last checkpoint: the moment `worked_sec` was last
  exact (start/resume stamp it too); NULL unless running.

An interval's worked time at any instant is the banked part plus the live
segment, capped at the plan:

```
worked(now) = min(worked_sec + (now − checkpointed_at), duration_sec)
```

## The timer process

`Core.start_interval` and `Core.resume_interval` spawn one detached process per running
interval — `sys.executable -m workbell.core.timer <interval_id> [<data_dir>]` —
with its own DB connection. The data dir is omitted when it is the default one,
so the common case stays readable in `ps`; the child then resolves the default
itself. Core spawns it, not clients, so every client gets identical behavior;
`-m` needs no PATH, no binary, no hidden CLI command. The timer forks once
more and the spawned process exits, so the timer proper is a child of launchd
and a long-lived client never has to reap it. The
whole algorithm ([timer.py](../src/workbell/core/timer.py)):

```
every 1 s:
    re-read the interval row
    if gone or status ≠ 'running':   exit                    # paused or deleted by someone else
    if worked(now) = duration_sec:   complete + ring; exit   # guarded UPDATE; ring only if it won
    if now − checkpointed_at ≥ 10 s:   checkpoint              # worked_sec = worked(now); checkpointed_at = now
```

The checkpoint is the load-bearing detail: it banks the live segment into
`worked_sec` every ~10 s, so the value in the DB is never more than one
checkpoint stale. At startup the timer also takes an exclusive flock on
`timer.lock` (blocking — the predecessor it replaces may be mid-poll) and
holds it for life; that lock is the liveness signal crash recovery probes.

The bell (`core/bell.py`): a macOS notification (osascript) plus a
user-chosen system sound (afplay) — zero dependencies. The notification
style is a settings value: a Notification Center banner (default,
fire-and-forget) or a modal dialog that stays on screen until dismissed.
The dialog is spawned without waiting — the timer holds `timer.lock` for
life, and a successor timer blocks acquiring it, so ring must not outlive
the click. The sound is a settings value too; the valid choices are exactly
the files in `/System/Library/Sounds`, enumerated live, so a nonexistent
sound cannot be chosen — and if the chosen file vanishes later, ring time
falls back to the default, because the bell must ring.

## Crash recovery

If the timer dies (kill, crash, OOM, power loss), its interval is stuck
`running`. Death is detected by two signals together, checked at the top of
every status read (`Core.get_active_interval`) and of `pause_interval`/`resume_interval`; nothing runs
at boot — the state heals on the next look:

- **`timer.lock` is free.** The kernel drops the timer's flock exactly when
  the process dies and keeps it through system sleep, so a held lock means a
  live (possibly frozen) timer — never healed, per the sleep rule below.
- **`checkpointed_at` is 30 s stale** (3 missed checkpoints). This guards
  the startup window: a just-spawned timer has not taken the lock yet, but
  its interval's checkpoint is still fresh.

The lock is probed in code; recovery itself stays one guarded UPDATE:

```sql
UPDATE intervals SET status = 'paused', checkpointed_at = NULL
WHERE status = 'running' AND checkpointed_at <= :now - 30;
```

The dead gap is not credited — no work happened; at most one checkpoint
(~10 s) of real work is lost. `resume_interval` then continues the interval with a
fresh timer.

## The errors log

The timer and the detached tray have no terminal, so their stdout/stderr go
to `errors.log` next to the DB (append mode, so concurrent writers are
safe). Nothing writes to it in normal operation; an unhandled crash leaves
a timestamped `<process> crashed:` header plus the traceback, and stderr
from the spawned system tools (afplay, osascript) lands there too. The
file grows only when something breaks, so it needs no rotation.

## Concurrency: one rule

The timer and any number of clients share the database (WAL, busy timeout)
with no other coordination. Every state-changing write carries its expected
state in the WHERE clause (`… WHERE status = 'running'`) and does all time
math inside that single UPDATE — never read → compute in Python → write. Any
two racing writers therefore resolve to exactly one winner; the losing UPDATE
matches zero rows and is a harmless no-op. Pause racing the timer's
completion, delete racing a checkpoint, two `start_interval`s racing (the second
INSERT is rejected by the unique active index) — each ends with one winner
and no torn state, and the timer notices any lost race within one poll and
exits.

## The tray client

`tray/` is the macOS menu bar client: an icon plus Start/Pause/Resume/Cancel/Quit
menu items. Cancel asks for confirmation in a native alert (default answer:
keep), like the CLI `cancel`; it sits at the bottom next to Quit, below the
progress lines and away from Pause, so a routine click cannot land on the
destructive item. The icon shows exactly two things — today's interval ordinal and
a status glyph: `4▶` means the day's 4th interval is running, `4⏸` paused;
when idle it shows the day's completed count and a diamond (`3◇`, bare `◇`
at zero). It never ticks a countdown — deliberate, see
[non-goals](non-goals.md); time details live inside the menu, visible only
when opened: `Left: 20:02 — rings at 14:15` (the ring time only while
running — paused has no bell scheduled), `Worked: 24:58 of 45:00`, and
`Today: 3 completed` (kept visible when idle too; an interval counts
toward the day it was started — the convention shared with `stats`).
It obeys the same rule as everything else — the DB is the single
source of truth, no IPC: an
AppKit timer polls `Core.get_active_interval` once a second and redraws,
and menu clicks call `Core` in-process on the main thread, so the whole
client is single-threaded. A click that loses a race to another client is
simply dropped — the next redraw shows whatever state won.
Side effect of the 1 s poll: an open tray heals a crashed timer within a
second. The pyobjc boilerplate is isolated in `tray/appkit.py`, a
self-contained generic wrapper.

`workbell tray` launches the icon as a detached process — the CLI runs
`sys.executable -m workbell.tray [<data_dir>]` (the timer-spawn pattern;
`--foreground` runs the same command attached), so clients stay independent:
the CLI never imports the tray. One icon per data dir is enforced by
`tray.lock`, an flock'ed file holding the owner's PID. The kernel drops the
lock the instant the holder dies, so unlike a plain PID file it cannot go
stale; the PID inside is the SIGTERM target for `workbell tray stop`, and
Quit in the menu is the same exit from the icon itself. The tray and the
bell are independent: the bell rings from the timer process whether or not
an icon is open.

## Machine sleep vs. crash: who owns the gap

Two rules, decided:

- **Sleep does not stop the clock.** A running interval measures wall time,
  machine state included — the user may legitimately be working away from
  this machine (another computer, a meeting, paper) while it sleeps. An
  interval that completed while nobody actually worked is handled the
  normal way: delete it.
- **A dead timer stops the clock.** After a crash (power loss, kill, OOM)
  the interval must come back paused with the work done before the crash —
  correct to within one checkpoint — and the dead gap not credited.

One invariant covers both: **a gap counts iff the timer process survived
it.** Sleep freezes the timer but keeps it alive, so the gap counts and the
timer completes (and rings) on wake; a crash kills the timer, so the gap is
dropped.

Staleness alone cannot honor this: a slept timer and a dead one leave the
same stale `checkpointed_at`. The liveness probe that survives sleep but
not death is `timer.lock` (see crash recovery above): while the machine
sleeps the timer's flock stays held, so no reader heals the interval, and
on wake the timer's next poll completes it and rings. After a crash the
lock is free, and the same staleness heals the interval to paused.
