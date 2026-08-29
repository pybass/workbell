import subprocess
import sys


class TestCrashLogging:
    """The real `python -m workbell.core.timer`, spawned the way Core._spawn_timer wires it."""

    def test_crash_lands_in_errors_log(self, tmp_path):
        """A crashing timer (non-numeric interval id) leaves the crash header and the traceback in errors.log.

        The bad argv makes the timer die before it touches the lock or the database.
        """
        argv = [sys.executable, "-m", "workbell.core.timer", "not-a-number", str(tmp_path)]
        errors_log = tmp_path / "errors.log"
        with errors_log.open("ab") as log:
            rc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, check=False, timeout=30).returncode
        assert rc == 1
        content = errors_log.read_text()
        assert "] timer crashed:\n" in content
        assert "ValueError" in content
        assert content.index("timer crashed:") < content.index("ValueError")  # the header dates the traceback below it
