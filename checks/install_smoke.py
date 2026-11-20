"""Проверить установку готового EXE, запуск и сохранение базы при переустановке."""

import hashlib
import os
import sqlite3
import subprocess
import tempfile
import time
import winreg
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicRating.FuryMask_is1"


def file_hash(path: Path) -> bytes:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").digest()


def main() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY):
            raise SystemExit("A registered Music Rating installation already exists.")
    except FileNotFoundError:
        pass
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Music Rating.lnk"
    if shortcut.exists():
        raise SystemExit("A Music Rating shortcut already exists.")
    dist = ROOT / "dist"
    setup = dist / "MusicRating-Setup.exe"
    if not setup.is_file():
        raise SystemExit("Build MusicRating-Setup.exe first.")

    log = ROOT / "checks/logs/task54-setup.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-smoke-", dir=build, ignore_cleanup_errors=True) as temp:
        install = Path(temp) / "program"
        data = Path(temp) / "test-documents"
        env = {**os.environ, "MUSICRATING_DATA_DIR": str(data), "QT_QPA_PLATFORM": "offscreen"}
        silent = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]

        def run_setup() -> None:
            subprocess.run([str(setup), *silent, "/SP-", f"/DIR={install}", f"/LOG={log}"],
                           env=env, check=True, timeout=75, creationflags=subprocess.CREATE_NO_WINDOW)

        try:
            run_setup()
            exe = install / "MusicRating.exe"
            assert file_hash(exe) == file_hash(dist / exe.name)
            database = data / "library.db"
            app = subprocess.Popen([str(exe)], cwd=install, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 25
                while not database.exists() and app.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.2)
                time.sleep(0.75)
                assert app.poll() is None, f"Music Rating exited during startup ({app.returncode})."
                assert database.is_file(), "Music Rating did not create its database during startup."
                with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True)) as db:
                    assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    for name in ("users", "albums", "artists"):
                        assert db.execute(f"SELECT count(*) FROM {name}").fetchone() == (0,)
                    with db:
                        db.execute("INSERT INTO meta(key, value) VALUES (?, ?)", ("setup_smoke", "persistent"))
            finally:
                if app.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(app.pid), "/T", "/F"],
                                   capture_output=True, check=True, timeout=10)
                    app.wait(timeout=10)
            run_setup()
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                assert db.execute("SELECT value FROM meta WHERE key='setup_smoke'").fetchone() == ("persistent",)
            print("Setup installed the executable. A clean database was created and survived reinstallation.")
        finally:
            for uninstaller in install.glob("unins*.exe"):
                subprocess.run([str(uninstaller), *silent], check=True, timeout=40,
                               creationflags=subprocess.CREATE_NO_WINDOW)
                break


if __name__ == "__main__":
    main()
