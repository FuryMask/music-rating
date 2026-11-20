"""Run regression scripts with a fresh project copy and temporary settings."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    checks = Path(__file__).resolve().parent
    project = checks.parent
    scripts = {int(path.stem.removeprefix("verify_task")): path
               for path in checks.glob("verify_task*.py")}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs="*", type=int, metavar="TASK")
    tasks = parser.parse_args().tasks or sorted(scripts)
    for task in tasks:
        if task not in scripts:
            parser.error(f"Unknown task {task}. Available: {', '.join(map(str, sorted(scripts)))}")

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONIOENCODING": "utf-8"}
    env.pop("MUSICRATING_SPOTIFY_CREDENTIALS", None)
    env.pop("MUSICRATING_SPOTIFY_CLIENT_ID", None)
    env.pop("MUSICRATING_SPOTIFY_CLIENT_SECRET", None)
    env.pop("MUSICRATING_GENIUS_TOKEN", None)
    if sys.platform == "win32":
        env.setdefault("QT_QPA_FONTDIR", str(Path(os.environ["WINDIR"]) / "Fonts"))
    failed = []
    for task in tasks:
        script = scripts[task]
        print(f"\n=== {script.name} ===", flush=True)
        with tempfile.TemporaryDirectory(prefix="music-rating-check-") as directory:
            copy = Path(directory).resolve()
            env["MUSICRATING_DATA_DIR"] = str(copy / "data")
            env["MUSICRATING_CHECK_ROOT"] = str(copy)
            shutil.copytree(project / "app", copy / "app", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy2(project / "main.py", copy)
            shutil.copytree(checks / "fixtures", copy / "checks" / "fixtures")
            target = shutil.copy2(script, copy / "checks")
            bootstrap = (
                "import runpy, sys; from PySide6.QtCore import QSettings; "
                "QSettings.setDefaultFormat(QSettings.Format.IniFormat); "
                "QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, sys.argv[2]); "
                "runpy.run_path(sys.argv[1], run_name='__main__')"
            )
            result = subprocess.run([sys.executable, "-c", bootstrap, target, str(copy / "settings")],
                                    cwd=copy, env=env)
            if result.returncode:
                failed.append(task)
    if failed:
        print("Failed suites:", ", ".join(map(str, failed)))
    return int(bool(failed))


if __name__ == "__main__":
    sys.exit(main())
