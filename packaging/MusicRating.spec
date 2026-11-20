# -*- mode: python ; coding: utf-8 -*-
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve().parent
pyside = Path(find_spec("PySide6").origin).parent
runtime_names = {
    "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll", "vcruntime140.dll",
    "vcruntime140_1.dll", "vcruntime140_threads.dll",
}
runtimes = {dll.name.lower(): dll for dll in pyside.glob("*.dll")
            if dll.name.lower() in runtime_names}

analysis = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "app/resources"), "app/resources")],
    hiddenimports=collect_submodules("winrt"),
)
def keep_binary(name):
    dll = Path(name).name.lower()
    return (dll not in runtimes and dll != "ucrtbase.dll"
            and not dll.startswith(("api-ms-win-", "ext-ms-win-")))


# Use Qt's compiler runtime consistently. Keep the system CRT and API
# contracts out of the archive so the Windows loader can resolve them.
analysis.binaries = [
    (name, source, kind) for name, source, kind in analysis.binaries
    if keep_binary(name)
]
analysis.binaries.extend((name, str(source), "BINARY") for name, source in sorted(runtimes.items()))

archive = PYZ(analysis.pure)
exe = EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas, [],
    name="MusicRating",
    console=False,
    upx=False,
)
