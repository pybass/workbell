"""Tests for the Interval domain model's pure logic."""

from dataclasses import replace

from workbell.core.models import Interval, IntervalStatus

# Template interval: running, 100s banked, last checkpoint at t=1_000_200.
RUNNING = Interval(
    id=1,
    status=IntervalStatus.RUNNING,
    duration_sec=1500,
    worked_sec=100,
    started_at=1_000_000,
    checkpointed_at=1_000_200,
    completed_at=None,
)


class TestEffectiveWorked:
    """Worked time including the tail since the last checkpoint."""

    def test_running_adds_live_segment(self):
        """While running, the banked work plus the tail since the last checkpoint counts."""
        assert RUNNING.effective_worked(1_000_250) == 150  # 100 banked + 50 live

    def test_capped_at_duration(self):
        """The live tail never pushes worked time past the plan."""
        assert RUNNING.effective_worked(2_000_000) == 1500

    def test_paused_returns_banked(self):
        """Paused: no checkpoint stamp, only the banked work counts."""
        paused = replace(RUNNING, status=IntervalStatus.PAUSED, checkpointed_at=None)
        assert paused.effective_worked(2_000_000) == 100
