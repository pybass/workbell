# Non-goals

These are deliberate product boundaries, not missing features.

- **Duration presets.** Workbell will have one user-configurable default duration stored in the database. Users may still pass an explicit duration when starting an interval, but there will be no named presets.
- **Changing an active interval's duration.** The planned length is fixed at start; there is no `extend` command. No live demand: when the plan turns out wrong, let the bell ring — or delete the interval and start a fresh one.
- **Interval metadata.** Intervals will not have labels, notes, or other task-tracking fields.
- **Worked-time statistics.** The only aggregate workbell shows is today's completed count (tray icon and menu). No summed daily or weekly worked-time totals: there is no live demand for reports; `history` lists the raw intervals for anyone who wants arithmetic.
- **Abandoned intervals.** Stopping an unfinished interval means deleting it. Workbell will not retain it with a separate `abandoned` state.
- **Id-less delete.** `workbell delete` always takes an explicit interval id. There is no shorthand that implicitly deletes the active interval: deletion is irreversible, so the target is always named.
- **Custom bell sound files.** The bell sound is chosen from the installed macOS system sounds, nothing else. An arbitrary file path can move or be deleted, silently breaking the one thing workbell guarantees; the system set is small, always present, and validated at set time.
- **Ticking countdown in the menu bar.** A timer counting down in the corner of the screen is a distraction, the opposite of what a focus tool should add. The tray icon shows only two things: today's interval ordinal and a status glyph (running/paused/idle). Time details live inside the menu, visible only when deliberately opened.
- **Dependency minimization.** Readable code and a convenient CLI matter more than reducing the dependency count. Cyclopts and Rich are intentional choices.
- **Older Python versions.** Workbell targets the latest stable Python. Users can select that interpreter when installing with `uv tool install`.
