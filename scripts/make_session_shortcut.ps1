<#
.SYNOPSIS
    Put a "PulseNest Session" shortcut on the desktop: double-click opens tools/pulsenest_session.py.

.DESCRIPTION
    The launcher is the one window a person opens to run a campaign (docs/hospital_runbook.md
    section 2). This creates the icon so that no terminal is needed on the day: the shortcut runs
    pythonw.exe (no console behind the window) with the repo as working directory, which is what
    every tool expects. Run once per laptop; running it again just rewrites the shortcut.

.EXAMPLE
    .\scripts\make_session_shortcut.ps1
#>
$root = Split-Path -Parent $PSScriptRoot
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "pythonw.exe not on PATH -- install Python 3.11+ (tomllib) with the 'add to PATH' option" }
$target = Join-Path $root 'tools\pulsenest_session.py'
if (-not (Test-Path $target)) { throw "not found: $target" }
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desktop 'PulseNest Session.lnk'

$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnk)
$s.TargetPath = $py
$s.Arguments = '"' + $target + '"'
$s.WorkingDirectory = $root
$s.Description = 'PulseNest session launcher: the cots, what is on the air, START per cot'
$s.Save()
Write-Host "Shortcut written: $lnk"
Write-Host "  $py `"$target`"  (working directory $root)"
