"""Domain models: work intervals and user settings."""

import sqlite3
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any, Self


class IntervalStatus(StrEnum):
    """Interval lifecycle state; values match the TEXT stored in SQLite."""

    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class TickResult(Enum):
    """What the timer process should do after one poll of its interval."""

    CONTINUE = "continue"  # still running — sleep and poll again
    COMPLETED = "completed"  # this tick completed the interval — ring the bell, then exit
    STOP = "stop"  # gone, paused, or lost the completion race — exit silently


@dataclass(frozen=True, slots=True)
class Interval:
    """A single work interval."""

    id: int  # stable id, never reused (AUTOINCREMENT)
    status: IntervalStatus  # current lifecycle state
    duration_sec: int  # planned length
    worked_sec: int  # work banked so far; exact as of checkpointed_at
    started_at: int  # unix seconds; when the interval was started
    checkpointed_at: int | None  # unix seconds; the last checkpoint (start/resume stamp it too); set exactly when running
    completed_at: int | None  # unix seconds; set exactly when completed

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Build an Interval from a database row, coercing the TEXT status into the enum."""
        data: dict[str, Any] = dict(row)
        data["status"] = IntervalStatus(data["status"])
        return cls(**data)

    def effective_worked(self, now: int) -> int:
        """Worked time including the tail since the last checkpoint, capped at the planned duration."""
        if self.checkpointed_at is not None:
            return min(self.worked_sec + (now - self.checkpointed_at), self.duration_sec)
        return self.worked_sec


@dataclass(frozen=True, slots=True)
class Settings:
    """User settings, stored as the single row of the settings table."""

    default_duration_sec: int  # default interval length when start is given no duration
    bell_sound: str  # macOS system-sound name the bell plays on completion (e.g. 'Glass')

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Build Settings from the settings row, dropping the fixed single-row id."""
        data: dict[str, Any] = dict(row)
        del data["id"]
        return cls(**data)
