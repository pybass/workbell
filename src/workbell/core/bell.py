"""The bell: macOS system-sound enumeration and the completion alert (notification + sound).

Part of core, not a client: the bell is the application's guarantee and must ring even when
no client is open — the timer process calls ring() on completion.
"""

import subprocess
from pathlib import Path

SYSTEM_SOUNDS_DIR = Path("/System/Library/Sounds")  # the installed macOS system sounds — the only valid bell choices
DEFAULT_SOUND = "Glass"  # matches the value seeded by the settings migration; also the ring-time fallback


def available_sounds() -> list[str]:
    """Names of the installed macOS system sounds (sorted stems of the .aiff files).

    Enumerated fresh on every call — no hardcoded list, so the choices can never desync
    from what the OS actually has.
    """
    return sorted(path.stem for path in SYSTEM_SOUNDS_DIR.glob("*.aiff"))


def play_sound(name: str) -> None:
    """Play a system sound by name through the main output volume, blocking until it finishes.

    Falls back to DEFAULT_SOUND when the named file is gone (removed since it was chosen):
    a misconfigured bell must still ring.
    """
    path = SYSTEM_SOUNDS_DIR / f"{name}.aiff"
    if not path.exists():
        path = SYSTEM_SOUNDS_DIR / f"{DEFAULT_SOUND}.aiff"
    # S603 suppressed: no shell — argv is an absolute binary and a path under the system sounds
    # dir; worst case afplay fails to play it and exits non-zero, which check=False ignores.
    subprocess.run(["/usr/bin/afplay", str(path)], check=False)  # noqa: S603


def ring(sound: str) -> None:
    """Alert the user that the interval completed: post a macOS notification, then play the bell sound.

    The sound goes through afplay and the main output volume, not the notification's
    `sound name`: notification sounds use the separate alert-volume channel and Notification
    Center delivery rules (Focus, per-app settings), any of which can silence them — and the
    bell must ring unconditionally.
    """
    script = 'display notification "Work interval completed." with title "workbell"'
    # S603 suppressed: absolute path, fully static argv, no shell — nothing user-controlled.
    subprocess.run(["/usr/bin/osascript", "-e", script], check=False)  # noqa: S603
    play_sound(sound)
