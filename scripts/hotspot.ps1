<#
.SYNOPSIS
    in3wifi without internet: turn the laptop's Mobile Hotspot on, off, or show its state.

.DESCRIPTION
    The boards and the VideoNest phones send UDP to the laptop at 192.168.137.1, the address
    Windows gives the Mobile Hotspot. Settings only offers the hotspot when there is an internet
    connection to share; a hospital has none to spare. The way round, measured 2026-10-15 on the
    hospital laptop: share the "Microsoft KM-TEST Loopback Adapter" (a software adapter that is
    always "connected" and has no internet). Windows then starts the hotspot, the boards get
    192.168.137.x by DHCP, and the laptop's own Wi-Fi connection, if any, is left alone.
    No administrator rights are needed once the adapter exists.

    Once per laptop, by hand, before the first use (the script checks and says so if missing):
      1. The loopback adapter. Run hdwwiz.exe as administrator (Win+R, "hdwwiz", Ctrl+Shift+Enter)
         > Next > "Install the hardware that I manually select from a list" > Network adapters >
         manufacturer Microsoft > "Microsoft KM-TEST Loopback Adapter" > Next > Finish. The same
         wizard opens from Device Manager > Action > Add legacy hardware. It needs no address; its
         automatic 169.254.x is enough. It is a root-enumerated device with its driver in the
         driver store: it stays through reboots and Windows updates, and goes only if removed in
         Device Manager or with "Reset this PC".
      2. The hotspot's name and password: Settings > Network & internet > Mobile hotspot: name
         in3wifi, the boards' password, band 2.4 GHz (the boards have no 5 GHz). Remembered.
    The hotspot itself is off after every reboot: 'on' again.

    The phones: VideoNest binds its socket to the Wi-Fi network (since 2026-10-15), so a phone
    sends through in3wifi even with mobile data on and no internet on the Wi-Fi.

.PARAMETER Action
    on      start the hotspot sharing the loopback adapter, wait for it, print the state
    off     stop it
    status  state, name, band, the laptop's address on it and the clients connected (default)

.EXAMPLE
    .\scripts\hotspot.ps1 on
    .\scripts\hotspot.ps1
    .\scripts\hotspot.ps1 off

.NOTES
    Windows PowerShell 5.1 (powershell.exe) is required for the WinRT calls; under PowerShell 7
    (pwsh) the script re-runs itself in powershell.exe.
#>
param([ValidateSet('on', 'off', 'status')][string]$Action = 'status')

if ($PSVersionTable.PSEdition -eq 'Core') {
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath $Action
    exit $LASTEXITCODE
}

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime] | Out-Null
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime] | Out-Null

# WinRT async -> wait for it (PowerShell has no await)
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}

# The loopback adapter, and the connection profile Windows keeps for it
$loop = Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceDescription -like '*KM-TEST*' }   # the description is localised ('Scheda di loopback Microsoft KM-TEST') | Select-Object -First 1
if (-not $loop) {
    Write-Host 'No "Microsoft KM-TEST Loopback Adapter" on this laptop. Install it once (administrator):'
    Write-Host '  run hdwwiz.exe as administrator (or Device Manager > Action > Add legacy hardware) > Next >'
    Write-Host '  "Install the hardware that I manually select from a list" > Network adapters > Microsoft >'
    Write-Host '  "Microsoft KM-TEST Loopback Adapter" > Next > Finish.'
    Write-Host 'Then run this script again. The adapter needs no address: its automatic 169.254.x is enough,'
    Write-Host 'and it stays through reboots.'
    exit 2
}
$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetConnectionProfiles() | Where-Object {
    $_.NetworkAdapter -and ('{' + $_.NetworkAdapter.NetworkAdapterId.ToString() + '}') -eq $loop.InterfaceGuid } | Select-Object -First 1
if (-not $profile) {
    Write-Host "The loopback adapter ($($loop.Name)) is $($loop.Status) but Windows has no connection profile for it."
    Write-Host 'Enable it (Settings > Network & internet > Advanced network settings) and run again.'
    exit 2
}
$tm = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$resultType = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]

function Show-State {
    $cfg = $tm.GetCurrentAccessPointConfiguration()
    $band = if ("$($cfg.Band)" -eq 'TwoPointFourGigahertz') { '2.4 GHz' } elseif ("$($cfg.Band)" -eq 'FiveGigahertz') { '5 GHz (the boards cannot see it)' } else { "$($cfg.Band)" }
    Write-Host "hotspot : $($tm.TetheringOperationalState)   name $($cfg.Ssid)   band $band   shares: $($profile.ProfileName) (loopback)"
    if ("$($tm.TetheringOperationalState)" -eq 'On') {
        $ip = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -ne $loop.Name -and $_.IPAddress -like '192.168.137.*' } | Select-Object -First 1
        if ($ip) { Write-Host "laptop  : $($ip.IPAddress) on '$($ip.InterfaceAlias)'  (the boards' target is 192.168.137.1)" }
        else { Write-Host 'laptop  : no 192.168.137.x address yet -- wait a few seconds and run status again' }
        $clients = $tm.GetTetheringClients()
        Write-Host "clients : $($tm.ClientCount)"
        foreach ($c in $clients) {
            $hosts = ($c.HostNames | ForEach-Object { $_.CanonicalName }) -join ' '
            Write-Host "          $($c.MacAddress)  $hosts"
        }
    }
    if ($cfg.Ssid -ne 'in3wifi' -or "$($cfg.Band)" -ne 'TwoPointFourGigahertz') {
        Write-Host 'NOTE    : the boards expect the name in3wifi on 2.4 GHz -- Settings > Network & internet > Mobile hotspot'
    }
}

switch ($Action) {
    'on' {
        if ("$($tm.TetheringOperationalState)" -eq 'On') { Write-Host 'already on' }
        else {
            $r = Await ($tm.StartTetheringAsync()) $resultType
            if ("$($r.Status)" -ne 'Success') { Write-Host "could not start: $($r.Status) $($r.AdditionalErrorMessage)"; exit 1 }
            $t0 = Get-Date
            while ("$($tm.TetheringOperationalState)" -ne 'On' -and ((Get-Date) - $t0).TotalSeconds -lt 20) { Start-Sleep -Milliseconds 500 }
            Start-Sleep -Seconds 2        # the virtual adapter takes its address a moment later
        }
        Show-State
    }
    'off' {
        if ("$($tm.TetheringOperationalState)" -eq 'Off') { Write-Host 'already off' }
        else {
            $r = Await ($tm.StopTetheringAsync()) $resultType
            if ("$($r.Status)" -ne 'Success') { Write-Host "could not stop: $($r.Status) $($r.AdditionalErrorMessage)"; exit 1 }
        }
        Show-State
    }
    'status' { Show-State }
}
