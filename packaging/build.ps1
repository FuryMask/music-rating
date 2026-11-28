param(
    [string]$Python = "python",
    [string]$Iscc,
    [switch]$AppOnly
)

$ErrorActionPreference = "Stop"
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $releaseValues = @(& $Python -c 'from app.version import VERSION, INSTALLER_NAME; print(VERSION); print(INSTALLER_NAME)')
    if ($LASTEXITCODE -ne 0 -or $releaseValues.Count -ne 2 -or
        $releaseValues[0] -notmatch '^\d+\.\d+\.\d+$' -or
        $releaseValues[1] -notmatch '^[a-zA-Z0-9-]+\.exe$') {
        throw "Could not read the release version and installer name from app/version.py."
    }
    $version = $releaseValues[0]
    $installerBase = [IO.Path]::GetFileNameWithoutExtension($releaseValues[1])
    & $Python -c "import platform, sys; sys.exit(not (sys.platform == 'win32' and platform.machine().lower() == 'amd64' and sys.maxsize > 2**32))"
    if ($LASTEXITCODE -ne 0) { throw "Build with 64-bit Windows Python on x64." }

    New-Item -ItemType Directory -Path build -Force | Out-Null
    $pythonExe = & $Python -c 'import sys; print(sys.executable)'
    if ($LASTEXITCODE -ne 0) { throw "Could not resolve the Python executable." }
    $priorConfig = $env:PYINSTALLER_CONFIG_DIR
    $priorPath = $env:Path
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $PWD "build/pyinstaller-cache"
    # Avoid collecting unrelated DLLs from IDEs or other tools on PATH.
    $env:Path = @((Split-Path -Parent $pythonExe), "$env:SystemRoot/System32", $env:SystemRoot) -join ';'
    try {
        & $pythonExe -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/MusicRating.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
    } finally {
        $env:Path = $priorPath
        $env:PYINSTALLER_CONFIG_DIR = $priorConfig
    }

    if ($AppOnly) { return }
    if (-not $Iscc) {
        $compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($compiler) {
            $Iscc = $compiler.Source
        } else {
            $compilerRoots = @(${env:ProgramFiles(x86)}, $env:ProgramFiles, (Join-Path $env:LOCALAPPDATA 'Programs'))
            $Iscc = $compilerRoots | Where-Object { $_ } |
                ForEach-Object { Join-Path $_ "Inno Setup 6/ISCC.exe" } |
                Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
                Select-Object -First 1
        }
    }
    if (-not $Iscc) { throw "Install Inno Setup 6 or pass -Iscc with the path to ISCC.exe." }

    & $Iscc "/DAppVersion=$version" "/DInstallerBase=$installerBase" "packaging/MusicRating.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }
} finally {
    Pop-Location
}
