from dataclasses import replace

from workbell.core.models import Interval, IntervalStatus

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
    def test_running_adds_live_segment(self):
        assert RUNNING.effective_worked(1_000_250) == 150  # 100 banked + 50 live

    def test_capped_at_duration(self):
        assert RUNNING.effective_worked(2_000_000) == 1500

    def test_paused_returns_banked(self):
        paused = replace(RUNNING, status=IntervalStatus.PAUSED, checkpointed_at=None)
        assert paused.effective_worked(2_000_000) == 100
