<#
.SYNOPSIS
    Build PulseNest for one board revision with ESP-IDF; optionally flash it over the air or over USB.

.DESCRIPTION
    One build directory and one sdkconfig per board (build_V18/, build_V17/ ...), generated from
    sdkconfig.defaults + sdkconfig.board.<Board>. The first build of a board runs `set-target`;
    later builds are incremental. Replaces `pio run -e incunest_Vxx` (PlatformIO, removed 2026-09-15).

    Needs ESP-IDF v6.0.1 installed (default C:\esp\v6.0.1\esp-idf; see docs/boards.md). The script
    exports the IDF environment itself when IDF_PATH is not already set, and drops MSYSTEM because
    idf_tools refuses to run from an MSYS-flavoured shell (Git Bash sets that variable).

.PARAMETER Board
    V15, V16, V17 or V18 — must match the physical board (BOARD_VERSION travels in every $CFG frame
    and into every capture header).
.PARAMETER Ota
    IP of a board already running PulseNest (ESP-IDF firmware, fw >= 0.11 IDF): POST the raw image to
    http://<ip>/update, then wait for the board to come back and verify through the hub that it reports
    the elfsha of the image just built (tools/udp_fw_versions.py), found by its MAC whatever
    address it comes back on (it may choose another network after the restart); exit code 2 if it does not within
    ~65 s. Verify the MAC first (tools/udp_fw_versions.py). A board still on the Arduino
    firmware needs the multipart form once instead: curl -F update=@build_V18/pulsenest.bin http://<ip>/update
.PARAMETER Usb
    COM port of a blank board: `idf.py flash` (bootloader + partition table + app).

.EXAMPLE
    .\scripts\build.ps1 V18
.EXAMPLE
    .\scripts\build.ps1 V18 -Ota 192.168.137.14
.EXAMPLE
    .\scripts\build.ps1 V17 -Usb COM15
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('V15', 'V16', 'V17', 'V18')]
    [string]$Board,
    [string]$Ota,
    [string]$Usb,
    [string]$IdfPath = 'C:\esp\v6.0.1\esp-idf'
)

# No 'Stop' here: export.ps1 and idf.py print progress on stderr, which Windows PowerShell would turn
# into a terminating error. Exit codes are checked by hand below.
$ErrorActionPreference = 'Continue'
Remove-Item Env:MSYSTEM -ErrorAction SilentlyContinue
if (-not $env:IDF_PATH) {
    if (-not (Test-Path "$IdfPath\export.ps1")) { throw "ESP-IDF not found at $IdfPath (use -IdfPath)" }
    & "$IdfPath\export.ps1" *> $null
}

$root  = Split-Path -Parent $PSScriptRoot
$build = "build_$Board"
Set-Location $root

$idfArgs = @('-B', $build, "-DSDKCONFIG=$build/sdkconfig",
          "-DSDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.board.$Board")
if (-not (Test-Path "$build/sdkconfig")) { $idfArgs += @('set-target', 'esp32s3') }
$idfArgs += 'build'

idf.py @idfArgs
if ($LASTEXITCODE) { exit $LASTEXITCODE }

$bin = Join-Path $root "$build/pulsenest.bin"
Write-Host ("`n{0}  {1:N0} bytes" -f $bin, (Get-Item $bin).Length)
Get-Content "$build/build_version.h" | Where-Object { $_ -match '#define' }

if ($Ota) {
    Write-Host "`nOTA -> http://$Ota/update (raw body)"
    curl.exe -sS -m 120 -w "`nhttp=%{http_code} t=%{time_total}s`n" --data-binary "@$bin" "http://$Ota/update"
    if ($LASTEXITCODE) { exit $LASTEXITCODE }

    # Verify, do not trust the HTTP 200: the board's $CFG carries elfsha=, the first 8 bytes of the
    # image's own ELF SHA-256, which sits in the app descriptor at 0x20 + 0x90 of the .bin. The board
    # restarts in ~0.3 s and is back on the WiFi in 15-25 s; the hub asks it $CFG? again when it
    # returns, and tools/udp_fw_versions.py (a read-only hub subscriber, works with the lab open)
    # reports it. Three looks over ~65 s, then give up with exit code 2 -- docs/boards.md records
    # the elfsha of every OTA, so a flash that cannot be verified must not look like one that was.
    $want = (([IO.File]::ReadAllBytes($bin))[0xB0..0xB7] | ForEach-Object { $_.ToString('x2') }) -join ''
    # By MAC, not by IP (2026-10-16): the board reboots and chooses its network again, and on
    # 2026-10-16 the three V18 came back on in3wifi after an OTA sent over the home router --
    # verified by hand, "NOT VERIFIED" by this script, which waited on the old address. The MAC
    # is read from the board's own $CFG before the restart, and the report is searched for it
    # whatever address it carries now. No MAC known (no $CFG in the hub's cache): by IP, as before.
    $who = $Ota
    $report = (& python (Join-Path $root 'tools/udp_fw_versions.py') --discover 3 2>&1 | Out-String) -split "`r?`n"
    $line = $report | Where-Object { $_ -match ('^\s*' + [regex]::Escape($Ota) + '\s') -and $_ -match 'mac=' } | Select-Object -First 1
    if ($line -and $line -match 'mac=([0-9A-Fa-f:]{17})') { $who = "mac=$($Matches[1])" }
    else { Write-Host "  (no MAC known for $Ota before the restart: verifying by IP)" }
    Write-Host "`nWaiting for $who to come back with elfsha=$want ..."
    $verified = $false
    foreach ($wait in 20, 15, 15) {
        Start-Sleep -Seconds $wait
        $report = (& python (Join-Path $root 'tools/udp_fw_versions.py') --discover 5 2>&1 | Out-String) -split "`r?`n"
        if ($who -like 'mac=*') { $line = $report | Where-Object { $_ -match [regex]::Escape($who) -and $_ -match 'elfsha=' } | Select-Object -First 1 }
        else { $line = $report | Where-Object { $_ -match ('^\s*' + [regex]::Escape($Ota) + '\s') -and $_ -match 'elfsha=' } | Select-Object -First 1 }
        if ($line) {
            Write-Host $line.TrimEnd()
            if ($line -match ('elfsha=' + $want)) { $verified = $true; break }
        } else {
            Write-Host "  $who not reporting yet"
        }
    }
    if ($verified) {
        Write-Host "OTA VERIFIED: $who runs the image just built (elfsha=$want). Record it in docs/boards.md."
    } else {
        Write-Host "OTA NOT VERIFIED: $who did not report elfsha=$want. Check by hand: python tools/udp_fw_versions.py"
        exit 2
    }
}
if ($Usb) {
    idf.py -B $build -p $Usb flash
    exit $LASTEXITCODE
}
