# workbell

A work-interval timer with a bell. Start an interval and work; when the
planned time is fully worked, the bell rings — even if no UI is open (a
background timer process is the app's guarantee). macOS only: the bell
and the menu bar icon rely on macOS system tools.

> **Status: early development.**

Docs: [architecture](docs/architecture.md) · [data model](docs/data-model.md) · [raycast](docs/raycast.md) · [non-goals](docs/non-goals.md)

## Usage

```
workbell start [duration]            # start a work interval (default: from config)
workbell pause                       # pause the active interval
workbell resume                      # resume the paused interval
workbell cancel                      # delete the active interval (asks to confirm; --yes skips)
workbell status                      # show the active interval
workbell history [limit]             # list recent intervals (default: 20)
workbell stats [limit]               # per-day totals for recent days (default: 20)
workbell delete <id>                 # delete an interval, whatever its status
workbell config                      # show settings
workbell config default-duration 30  # set the default interval length (initially 25 minutes)
workbell config bell-sound Ping      # set the bell sound (no argument: list the choices)
workbell tray                        # open the menu bar icon (macOS)
workbell tray stop                   # close the menu bar icon
workbell raycast install             # generate the Raycast script commands (see docs/raycast.md)
```

A bare duration is minutes (`25`); with `h`/`m`/`s` units it is exact
(`10s`, `90m`, `1h20m10s`).

Data lives in `~/.local/share/workbell` (override with `--data-dir`).

## License

[MIT](LICENSE)
