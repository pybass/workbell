# Raycast Integration

Workbell ships [Raycast script commands](https://github.com/raycast/script-commands)
for controlling the timer from Raycast's search bar (Raycast can also bind a hotkey
to any of them). This is not a fourth client in the
[architecture](architecture.md) sense: every script is a one-line wrapper that
calls the workbell CLI and shows its output.

## Commands

| Command | Does |
|---|---|
| Start Work Interval | Start with the default duration |
| Pause Work Interval | Pause the running interval |
| Resume Work Interval | Resume the paused interval |
| Work Interval Status | Show the active interval |
| Open Workbell Tray | Open the menu bar icon |

There is deliberately no delete command: deletion always takes an explicit
interval id ([non-goals](non-goals.md)), and picking an id is not a search-bar
interaction — use the CLI for that.

## Setup

1. Run `workbell raycast install`. It generates the scripts into
   `<data-dir>/raycast/` (default `~/.local/share/workbell/raycast/`; pass a
   directory argument to install elsewhere). The absolute binary path and the
   data directory are baked in: Raycast runs scripts with a minimal
   environment, so the scripts depend on neither `PATH` nor shell profiles.
2. In Raycast: **Settings → Extensions → Script Commands → Add Directories**,
   add that directory. One-time step.

The install is idempotent — it always writes the current canonical set, so
re-run it after upgrading workbell. Raycast notices file changes in an
already-added directory by itself.

Action commands show the CLI's one-line result (or error) as a brief HUD;
Status shows the same line `workbell status` prints.
