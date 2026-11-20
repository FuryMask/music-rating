"""Start a verified track through desktop accessibility on Windows."""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from threading import Event
from time import monotonic

from app.services.desktop_playback import PlaybackTrack
from app.services.spotify_playback import spotify_executable_paths
from app.services.yandex_playback import yandex_executable_paths

_TIMEOUT = 7.0

_TRACK_UIA = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$type = [Windows.Automation.AutomationElement]::ControlTypeProperty
$buttonType = [Windows.Automation.ControlType]::Button
$buttonFilter = New-Object Windows.Automation.PropertyCondition($type,$buttonType)
$linkFilter = New-Object Windows.Automation.PropertyCondition($type,[Windows.Automation.ControlType]::Hyperlink)
$descendants = [Windows.Automation.TreeScope]::Descendants
$walker = [Windows.Automation.TreeWalker]::ControlViewWalker

function Normalize-Label([string] $text) {
    $folded = $text.Normalize([Text.NormalizationForm]::FormKC).ToLowerInvariant().Replace('ё','е')
    return ($folded -replace '[^\p{L}\p{N}_]+',' ').Trim()
}

$titles = @($request.titles | ForEach-Object { Normalize-Label $_ })
$artists = @($request.artists | ForEach-Object { Normalize-Label $_ } | Where-Object { $_ })
$album = Normalize-Label $request.album
if (-not $album -or $artists.Count -eq 0) { exit 1 }

function Test-Artist([string] $name) {
    $artistText = ' ' + (Normalize-Label $name) + ' '
    return [bool]($artists | Where-Object { $artistText.Contains(' ' + $_ + ' ') })
}

function Test-SpotifyTrack($button, [string] $name) {
    # Only the named control in the album's track grid can start this track.
    if ($name -notmatch '^(?:Включить|Воспроизвести) трек «(.+)» исполнител(?:я|ей) (.+)$' -and
        $name -notmatch '^Play (?:track )?(.+) by (.+)$') { return $false }
    if ($titles -notcontains (Normalize-Label $Matches[1]) -or -not (Test-Artist $Matches[2])) { return $false }
    $row = $false
    $parent = $walker.GetParent($button)
    for ($level = 0; $parent -and $level -lt 8; $level++) {
        $control = $parent.Current.ControlType
        if ($control -eq [Windows.Automation.ControlType]::DataItem) { $row = $true }
        if ($control -eq [Windows.Automation.ControlType]::DataGrid) {
            return $row -and (Normalize-Label $parent.Current.Name) -eq $album
        }
        $parent = $walker.GetParent($parent)
    }
    return $false
}

function Test-YandexTrack($button, [string] $name) {
    if ($name -notin @('Воспроизведение','Воспроизвести','Play','Playback')) { return $false }
    # Yandex Music exposes the title as a link inside the row with the Play button.
    $row = $walker.GetParent($button)
    if (-not $row -or -not (Test-Artist $row.Current.Name)) { return $false }
    $group = $walker.GetParent($row)
    if (-not $group) { return $false }
    $listName = Normalize-Label $group.Current.Name
    if ($listName -notin @("список треков альбома $album","album $album track list","track list of album $album")) {
        return $false
    }
    foreach ($link in $row.FindAll($descendants,$linkFilter)) {
        $label = (Normalize-Label $link.Current.Name) -replace '^(?:трек|track) ', ''
        if ($titles -contains $label) { return $true }
    }
    return $false
}

function Find-TrackButton($root) {
    foreach ($button in $root.FindAll($descendants,$buttonFilter)) {
        $info = $button.Current
        if (-not $info.IsEnabled -or $info.IsOffscreen) { continue }
        if ($request.provider -eq 'spotify') {
            if (Test-SpotifyTrack $button $info.Name) { $button }
        } elseif (Test-YandexTrack $button $info.Name) { $button }
    }
}

$names = if ($request.provider -eq 'spotify') { 'Spotify' } else { 'Яндекс Музыка','YandexMusic' }
$storePath = Join-Path $env:ProgramFiles 'WindowsApps\SpotifyAB.SpotifyMusic_*\Spotify.exe'
$deadline = [DateTime]::UtcNow.AddSeconds(5)
do {
    $candidates = @(
        foreach ($proc in Get-Process -Name $names -ErrorAction SilentlyContinue) {
            if ($proc.MainWindowHandle -eq [IntPtr]::Zero) { continue }
            $path = $proc.Path
            if ($request.paths -notcontains $path -and
                ($request.provider -ne 'spotify' -or $path -notlike $storePath)) { continue }
            try { Find-TrackButton ([Windows.Automation.AutomationElement]::FromHandle($proc.MainWindowHandle)) }
            catch { continue }
        }
    )
    if ($candidates.Count -gt 1) { exit 1 }
    if ($candidates.Count -eq 1) {
        $invoke = $null
        if ($candidates[0].TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern,[ref] $invoke)) {
            $invoke.Invoke()
            exit 0
        }
        exit 1
    }
    if (-not $request.waitForWindow) { exit 1 }
    Start-Sleep -Milliseconds 180
} while ([DateTime]::UtcNow -lt $deadline)
exit 1
"""
_TRACK_COMMAND = base64.b64encode(_TRACK_UIA.encode("utf-16-le")).decode("ascii")


def try_start_desktop_track(
    provider: str, track: PlaybackTrack, album: str, cancelled: Event, *, wait_for_window: bool = True,
) -> bool:
    if sys.platform != "win32" or cancelled.is_set():
        return False
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    powershell = windows / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    request = json.dumps({
        "provider": provider,
        "waitForWindow": wait_for_window,
        "titles": [track.title, track.base_title],
        "artists": track.artists,
        "album": album,
        "paths": [str(path) for path in (
            spotify_executable_paths() if provider == "spotify" else yandex_executable_paths()
        )],
    }).encode("ascii")
    try:
        with subprocess.Popen(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Mta", "-EncodedCommand", _TRACK_COMMAND],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ) as process:
            deadline = monotonic() + (_TIMEOUT if wait_for_window else 2.5)
            pending = request
            while not cancelled.is_set() and monotonic() < deadline:
                try:
                    process.communicate(input=pending, timeout=0.15)
                    return process.returncode == 0
                except subprocess.TimeoutExpired:
                    pending = None
            process.kill()
            process.communicate()
    except OSError:
        return False
    return False
