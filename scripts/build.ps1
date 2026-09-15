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
    http://<ip>/update. Verify the MAC first (tools/udp_fw_versions.py). A board still on the Arduino
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

$ErrorActionPreference = 'Stop'
Remove-Item Env:MSYSTEM -ErrorAction SilentlyContinue
if (-not $env:IDF_PATH) {
    if (-not (Test-Path "$IdfPath\export.ps1")) { throw "ESP-IDF not found at $IdfPath (use -IdfPath)" }
    & "$IdfPath\export.ps1" *> $null
}

$root  = Split-Path -Parent $PSScriptRoot
$build = "build_$Board"
Set-Location $root

$args = @('-B', $build, "-DSDKCONFIG=$build/sdkconfig",
          "-DSDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.board.$Board")
if (-not (Test-Path "$build/sdkconfig")) { $args += @('set-target', 'esp32s3') }
$args += 'build'

idf.py @args
if ($LASTEXITCODE) { exit $LASTEXITCODE }

$bin = Join-Path $root "$build/pulsenest.bin"
Write-Host ("`n{0}  {1:N0} bytes" -f $bin, (Get-Item $bin).Length)
Get-Content "$build/build_version.h" | Where-Object { $_ -match '#define' }

if ($Ota) {
    Write-Host "`nOTA -> http://$Ota/update (raw body)"
    curl.exe -sS -m 120 -w "`nhttp=%{http_code} t=%{time_total}s`n" --data-binary "@$bin" "http://$Ota/update"
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    Write-Host "The board restarts in ~0.3 s and joins the WiFi again in ~15-25 s; check with tools/udp_fw_versions.py"
}
if ($Usb) {
    idf.py -B $build -p $Usb flash
    exit $LASTEXITCODE
}
