# Board inventory

Every physical board used with PulseNest, with the one thing that identifies it unambiguously:
its **MAC address**. Until 2026-09-10 this list lived only in an assistant memory file outside the
repository, which is why nobody could find it. This file is the authoritative listing.

| MAC | Board rev. | Silkscreen | Build preset | Delivered | Status |
|---|---|---|---|---|---|
| `10:51:DB:50:7F:AC` | V15 | 15.A | `sdkconfig.board.V15` | Feb–Mar 2026 | IN3ATOR, the first board. Possibly damaged, out of use since 2026-09-09 |
| `10:51:DB:50:48:F8` | V16 | 16.A | `sdkconfig.board.V16` | Apr 2026 | **DEAD — 2026-09-11.** Probably incorrect power supply; smoke was seen. Was the main working board until then |
| `10:20:BA:14:75:60` | V17 | 17.A | `sdkconfig.board.V17` | — | Dropped off the WiFi three times on 2026-09-09/10 while still powered; cause not established |
| `10:51:DB:50:88:50` | V18 | 18.A | `sdkconfig.board.V18` | 2026-09-18 | OTA 2026-09-18 to `build=7770c6c`, `elfsha=a60928ae2b710aab`. Previously flashed and verified 2026-09-10 |
| `10:51:DB:50:87:B8` | V18 | 18.A | `sdkconfig.board.V18` | 2026-09-10 | **RETURNED TO THE WORKSHOP — 2026-09-18.** Not on the bench any more; do not target it for OTA. Flashed and verified 2026-09-10. It was the board carrying the non-default build with the `Serial.print()` guard for the 500 Hz acquisition stall, so that experiment lost its subject when it left |
| `10:51:DB:50:87:A4` | V18 | 18.A | `sdkconfig.board.V18` | not recorded | Third V18, first seen 2026-09-18 on COM19. Flashed and verified that day: `board=incunest_V18`, fw 0.13, lib 0.93, build `6e6d036`. The revision is Alex's reading of the silkscreen, not measured — this firmware cannot tell V16/V17/V18 apart (see below). OTA 2026-09-18 to `build=7770c6c`, `elfsha=a60928ae2b710aab` |
| `10:51:DB:50:82:5C` | V18 | 18.A | `sdkconfig.board.V18` | 2026-09-18 | Fourth V18, new board flashed 2026-09-18 on COM20. Chip: ESP32-S3 QFN56 rev v0.2, USB-Serial/JTAG. Verified: `board=incunest_V18`, fw 0.13, lib 0.93, build `6e6d036-dirty` (documentation-only changes in the tree, see *Provenance* below). OTA 2026-09-18 to `build=7770c6c`, `elfsha=a60928ae2b710aab` |
| `98:88:E0:11:CC:64` | — | — | — | — | Display HMI. Not a PulseNest target. Its own WiFi client: MQTT, OTA, web, mDNS |

**The silkscreen marks the revision, not the unit.** `18.A` is printed on the board so you can tell
it is a V18, and every V18 board carries it — so it cannot name a unit. The same applies to `15.A`,
`16.A` and `17.A`; those read like unit names in earlier session logs only because there happened to
be one board per revision. **A unit is identified by its MAC.**

Session logs up to 2026-09-11 call the two V18 boards *18.A* and *18.B*; those are Alex's own
suffixes for two units that both read `18.A` on the silkscreen, not markings. Four V18 boards have
existed since 2026-09-18, so the suffixes have run out of usefulness: **use the last three bytes of
the MAC**. On the bench today: `88:50`, `87:A4` and `82:5C` — `87:B8` went back to the workshop on
2026-09-18.

`87:B8` and `87:A4` differ by a single byte and are **different boards, not a typo for each other**.
That still matters now that only one of the two is on the bench: the session log before 2026-09-18
is full of `87:B8`, and reading one of those entries as the board in your hand would attribute its
measurements to the wrong unit.

## Provenance: what `build=` in a capture header really tells you

Every `$CFG` frame carries `build=<git hash>`, and it reaches the header of every capture. A `-dirty`
suffix means the working tree had uncommitted changes when the image was built — but **it does not
say what changed**. On 2026-09-18 the board `87:A4` was flashed as `6e6d036` and, minutes later,
`82:5C` as `6e6d036-dirty`, with identical firmware: in between, only `docs/boards.md` and
`conversation_log.md` had been edited. Same binary, different provenance label.

So `-dirty` was a question, not a verdict.

**Fixed on 2026-09-18 (lab v1.66), and these same three boards are the proof.** Three things
changed:

- `build=` now hashes **only the paths that end up inside the image** (`main/`, the root
  `CMakeLists.txt`, `sdkconfig.defaults`, `sdkconfig.board.*`, this partition CSV), so editing a
  `.md`, the lab script or `tools/` no longer moves it and no longer marks it `-dirty`. The same
  applies to `libsha` against the library's own repository, where the spec sits next to the code.
- The build is reproducible: `CONFIG_APP_REPRODUCIBLE_BUILD=y`, plus the removal of
  `__DATE__`/`__TIME__` from the firmware's startup banner, which a byte-diff proved was the only
  remaining source of non-determinism (68 bytes between two clean builds of identical sources).
  Two builds from scratch now produce byte-identical images.
- `$CFG` carries **`elfsha=`**, the first 8 bytes of the image's own ELF SHA-256, and `idfver=`.

What that buys, and it is the point: after the OTA round of 2026-09-18 the three boards report
`build=7770c6c` **and `elfsha=a60928ae2b710aab`, all three identical**, matching the
`ELF file SHA256` that `esptool image-info build_V18/pulsenest.bin` prints for the file on disk.
`build=` says which commit; `elfsha=` says whether two boards run the same binary — which no
repository hash can, because `build_V18/sdkconfig` is not versioned and `include/wifi_config.h`
is gitignored, and both compile in. Moving the bench to another network edits that header and
produces a different image under an unchanged `build=`; `elfsha` is what notices.

Still worth committing documentation before a flashing session — but now only because a tidy
history is easier to read, not because the label depends on it.

There is also a second per-unit identifier that Alex has seen, whose origin is not yet established
(2026-09-10). One lead, unconfirmed: IncuNest's motherBoard firmware carries a serial number
(`in3.serialNumber`), stored in NVS under `NS_CFG`/`KEY_SERIAL` and described in its own code as
*flasher-provisioned* — written during provisioning at flash time, read back at boot and preserved
across a settings reset, so it is assigned by the flashing process rather than derived from the
hardware. PulseNest's firmware has no equivalent field: its `$CFG` reports only `board=` (the build
string) and `mac=`. To be resolved.

## ⚠️ BATTERY connector: the polarity is MIRRORED between V17 and V18

| Revision | Wire at the board's edge (corner) |
|---|---|
| **V17** | **black**, negative |
| **V18** | **red**, positive |

So a battery cable that seats correctly on a V17 is **reversed** if plugged into a V18 the same way
round, and the other way round too. With boards of more than one revision on the same bench this is
a destructive mistake waiting to happen: **check the wire colour against the board's corner every
time, on every board, however many times you have done it before.**

Recorded 2026-09-11, the same day the V16 board died of what looked like incorrect power, with
smoke. The two are not established as connected — the V16's exact cause was not determined — but a
polarity that changes between revisions is one way that kind of failure happens, and it is worth
knowing before it happens again.

## Identifying a board

**Always by MAC, never by IP.** The hotspot's DHCP hands out new addresses constantly — four
different sets in a single day on 2026-09-09. Worse, `arp -a` and `Get-NetNeighbor` list hotspot
clients as `Permanent`, so **an ARP entry does not prove the board is present**: a stale address
stayed listed for hours after the board had moved.

Two reliable ways:

| Over the network | `python tools/udp_fw_versions.py` — lists every board streaming, with `board=`, `mac=`, firmware and library versions, and the git hashes of the build |
|---|---|
| Over USB | the ESP32-S3's native USB reports the **MAC as its USB serial number**, so `serial.tools.list_ports` attributes a COM port to a board *without opening it*. `VID:PID = 303A:1001` is the ESP32-S3 USB-Serial-JTAG |

## What differs between board revisions

For **this** firmware, almost nothing. The AFE4490 pins are defined once in IncuNest's board
dictionary (`motherBoard/include/config/board.h`) **outside every `#if (HW_NUM ...)` branch**:

```
AFE_MISO 37   AFE_MOSI 35   AFE_SCK 36   AFE_ADC_READY 17 (DRDY)   AFE44XX_CS 21
```

So V16, V17 and V18 are electrically identical from the AFE's point of view. Only **V15 differs**,
with DRDY on GPIO 45. What HW18 changes in that dictionary is shunt resistors, the heater current
reference and phototherapy, none of which this firmware touches.

**Then why one build preset per revision?** For **provenance**. `BOARD_VERSION` travels in every
`$CFG` frame and therefore into the header of every capture, so a V18 board flashed with the V17
build would label its captures as V17 for ever. Use the preset that matches the board
(`scripts/build.ps1 V18` → `sdkconfig.board.V18` → `CONFIG_PULSENEST_BOARD_V18`, `main/Kconfig.projbuild`).

## Flashing

The firmware is an **ESP-IDF v6.0.1** project since 2026-09-15 (Arduino/PlatformIO removed after the
port reached parity on the bench). `scripts/build.ps1 <Board>` builds the preset for one revision
into `build_<Board>/`; `-Ota <ip>` flashes it over the air, `-Usb COMxx` over USB.

**Over the air**, for a board already running PulseNest — the normal case:

```powershell
python tools/udp_fw_versions.py             # lists every board streaming: IP, MAC, fw, lib, hashes
.\scripts\build.ps1 V18 -Ota <ip>           # build, then POST the raw image to http://<ip>/update
```

`-Ota` sends the image as a **raw body** (`curl --data-binary`), which is what the ESP-IDF firmware's
`/update` handler expects. A board still running the **Arduino** firmware (fw ≤ 0.11 built with
PlatformIO) expects a multipart form instead — once, to move it over:

```powershell
curl.exe -sS -m 120 -w "%{http_code}`n" -F update=@build_V18/pulsenest.bin http://<ip>/update
```

**Without any tooling**, from a browser: open `http://<ip>/`, choose `build_V18/pulsenest.bin`, press
*Flash*. The page sends the file the same way (`XMLHttpRequest.send(file)` = raw body) and shows `OK`
or `FAILED`. This is the path to give someone who only has the `.bin`.

The .bin itself is always the same ESP32 application image; what differs is how the HTTP request wraps
it (raw body vs multipart form). Using the wrong wrapping fails safely in both directions: a multipart form to an ESP-IDF board is
rejected on the first chunk (the body starts with the form boundary, not the image magic byte) and
the board answers `FAIL` with the flash untouched; a raw body to an Arduino board finds no `update`
form field and nothing is written either.

The bootloader is not touched by OTA; the Arduino-era bootloader (IDF 4.4) boots the IDF v6 image
without complaint (verified on both V18 boards and the V17, 2026-09-15). The board answers `OK`,
restarts 300 ms later and is back on the WiFi in 15–25 s. `tools/udp_fw_versions.py` needs UDP port
5005, so close `pulsenest_lab.py` before running it (`taskkill /F /IM pythonw.exe`).

Verify the MAC before every OTA. A board was flashed with the wrong build on 2026-06-12 by
targeting an IP without checking.

**Over USB**, for a blank board (native USB port, labelled AIR SENSOR, or a UART0 adapter):

```powershell
.\scripts\build.ps1 V18 -Usb COM15          # idf.py flash: bootloader + partition table + app
```

Building by hand, without the script (from a shell where `export.ps1` has run):

```powershell
idf.py -B build_V18 -DSDKCONFIG=build_V18/sdkconfig -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.board.V18" set-target esp32s3 build
```

### Gotcha: after a USB flash the board can stay in download mode

esptool ends an upload with a reset over the RTS pin, and on these USB-Serial-JTAG boards that can
leave the chip in the **ROM download bootloader** instead of running the application. The symptoms
are silent and misleading: the flash verifies, the COM port is present, and the board never joins
the WiFi and never prints anything. Learned with PlatformIO's esptool 4.5.1 (two board bring-ups on
2026-09-10, the first misdiagnosed as a WiFi problem); not yet re-checked with the esptool that
ESP-IDF v6 ships.

Diagnosing it takes one command — if esptool connects **without** performing a reset, the chip is
sitting in download mode (`esptool` here is the one in the IDF Python environment):

```powershell
esptool --port COM15 --before no_reset read_mac
```

The cure is a reset that does not touch the EN/GPIO0 lines (*"Hard resetting with RTC WDT"*):

```powershell
esptool --port COM15 --after hard_reset read_mac
```

A pyserial RTS pulse is **not** a valid substitute: on these boards it lands the chip in download
mode about as often as not.

### Getting a console on a bare board

The console is **UART0**, the physical pins (`CONFIG_ESP_CONSOLE_UART_DEFAULT`, 921600 baud set by
`console_init()`), exactly where it was under Arduino. On a board with no UART0 wiring there is
therefore no console at all: the native USB port flashes and debugs, but carries no firmware output.
Since fw 0.11 the `$TIMING`/`$TASK` diagnostics also travel over UDP, so the bench needs no console
for them; since fw 0.12 they ride in datagrams of their own, never as slots of a measurement batch
(`# STAT … diag_dropped=` counts the ones that did not fit their queue), and since fw 0.13 `# STAT`
itself takes that queue too — no measurement task calls the network stack.

For a bring-up you can move the console onto the native USB port with a temporary build:
`idf.py -B build_V18 menuconfig` → *Component config → ESP System Settings → Channel for console
output → USB Serial/JTAG*, then rebuild and flash. **Not yet exercised** with this firmware
(2026-09-15); the Arduino-era equivalent (`ARDUINO_USB_CDC_ON_BOOT=1`) worked, with the caveat that
the USB console discards anything written while the host has the port closed — open the port first,
reset the board afterwards. Reflash the standard build when finished.

## Power

The IncuNest board can be powered from the USB connector labelled **AIR SENSOR**, which goes to the
ESP32-S3's native USB — that is where the COM port comes from. A laptop USB port is enough: a board
streams normally on it, at 100 datagrams/s and ~1.07 Mbit/s. Note that it then shares ground with
the PC.

The V17 board (`10:20:BA:14:75:60`) dropped off the WiFi while powered both from 12 V and from
USB, so the supply is not what explains it.
