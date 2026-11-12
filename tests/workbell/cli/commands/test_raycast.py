import shlex
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from workbell.cli.commands import raycast
from workbell.core.core import Core


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    """Core on a fresh temporary database; its data directory is where the default install lands."""
    instance = Core(tmp_path / "data")
    yield instance
    instance.close()


class TestRender:
    def test_golden(self) -> None:
        script = raycast._Script(
            "start.sh", "Start Work Interval", "Start a work interval with the default duration", "🔔", "silent", "start"
        )
        expected = (
            "#!/bin/bash\n"
            "# @raycast.schemaVersion 1\n"
            "# @raycast.title Start Work Interval\n"
            "# @raycast.mode silent\n"
            "# @raycast.icon 🔔\n"
            "# @raycast.packageName workbell\n"
            "# @raycast.description Start a work interval with the default duration\n"
            "\n"
            "exec /usr/local/bin/workbell --data-dir /data start 2>&1\n"
        )
        assert raycast._render(script, "/usr/local/bin/workbell --data-dir /data") == expected


class TestInstall:
    def test_default_target_and_set(self, core: Core, tmp_path: Path) -> None:
        """Without a target the scripts land in raycast/ inside the data directory, one per command."""
        raycast.install(core=core)
        dest = tmp_path / "data" / "raycast"
        assert {path.name for path in dest.iterdir()} == {"start.sh", "pause.sh", "resume.sh", "status.sh", "tray.sh"}

    def test_scripts_executable(self, core: Core, tmp_path: Path) -> None:
        """Raycast executes the scripts directly, so every one is written 0755."""
        raycast.install(core=core)
        for path in (tmp_path / "data" / "raycast").iterdir():
            assert path.stat().st_mode & 0o777 == 0o755

    def test_bakes_paths(self, core: Core, tmp_path: Path) -> None:
        """Every script execs the resolved binary with --data-dir baked in, stderr folded into stdout."""
        raycast.install(core=core)
        content = (tmp_path / "data" / "raycast" / "status.sh").read_text(encoding="utf-8")
        binary = shlex.quote(str(Path(sys.argv[0]).resolve()))
        data_dir = shlex.quote(str((tmp_path / "data").resolve()))
        assert content.endswith(f"exec {binary} --data-dir {data_dir} status 2>&1\n")

    def test_explicit_target_dir(self, core: Core, tmp_path: Path) -> None:
        """An explicit target directory is created (parents included) and used instead of the data dir."""
        dest = tmp_path / "scripts" / "raycast"
        raycast.install(dest, core=core)
        assert (dest / "start.sh").exists()
        assert not (tmp_path / "data" / "raycast").exists()

    def test_overwrites_stale_scripts(self, core: Core, tmp_path: Path) -> None:
        """Re-running install restores tampered content and permissions — the generated output is canonical."""
        raycast.install(core=core)
        path = tmp_path / "data" / "raycast" / "pause.sh"
        canonical = path.read_text(encoding="utf-8")
        path.write_text("#!/bin/bash\necho stale\n", encoding="utf-8")
        path.chmod(0o644)
        raycast.install(core=core)
        assert path.read_text(encoding="utf-8") == canonical
        assert path.stat().st_mode & 0o777 == 0o755
