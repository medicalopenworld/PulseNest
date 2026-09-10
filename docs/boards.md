# Board inventory

Every physical board used with PulseNest, with the one thing that identifies it unambiguously:
its **MAC address**. Until 2026-09-10 this list lived only in an assistant memory file outside the
repository, which is why nobody could find it. This file is the authoritative listing.

| MAC | Board rev. | Silkscreen | PlatformIO env | Delivered | Status |
|---|---|---|---|---|---|
| `10:51:DB:50:7F:AC` | V15 | 15.A | `incunest_V15` | Feb–Mar 2026 | IN3ATOR, the first board. Possibly damaged, out of use since 2026-09-09 |
| `10:51:DB:50:48:F8` | V16 | 16.A | `incunest_V16` | Apr 2026 | **DEAD — 2026-09-11.** Probably incorrect power supply; smoke was seen. Was the main working board until then |
| `10:20:BA:14:75:60` | V17 | 17.A | `incunest_V17` | — | Dropped off the WiFi three times on 2026-09-09/10 while still powered; cause not established |
| `10:51:DB:50:88:50` | V18 | 18.A | `incunest_V18` | 2026-09-10 | Flashed and verified 2026-09-10 |
| `10:51:DB:50:87:B8` | V18 | 18.A | `incunest_V18` | 2026-09-10 | Flashed and verified 2026-09-10 |
| `98:88:E0:11:CC:64` | — | — | — | — | Display HMI. Not a PulseNest target. Its own WiFi client: MQTT, OTA, web, mDNS |

**The silkscreen marks the revision, not the unit.** `18.A` is printed on the board so you can tell
it is a V18, and both V18 boards carry it — so it cannot name a unit. The same applies to `15.A`,
`16.A` and `17.A`; those read like unit names in earlier session logs only because there happened to
be one board per revision. **A unit is identified by its MAC.**

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

**Then why one environment per revision?** For **provenance**. `BOARD_VERSION` travels in every
`$CFG` frame and therefore into the header of every capture, so a V18 board flashed with the V17
build would label its captures as V17 for ever. Use the env that matches the board.

## Flashing

**Over the air**, for a board already running PulseNest — the normal case:

```bash
arp -a | grep -i <mac>                     # find its current IP, verify the MAC
pio run -e incunest_V18
curl -sS -m 90 -w "%{http_code}\n" -F update=@.pio/build/incunest_V18/firmware.bin http://<ip>/update
```

Verify the MAC before every OTA. A board was flashed with the wrong build on 2026-06-12 by
targeting an IP without checking.

**Over USB**, for a blank board:

```bash
pio run -e incunest_V18 -t upload --upload-port COM15
# then force a proper reset - see the gotcha below
python ~/.platformio/packages/tool-esptoolpy/esptool.py --port COM15 --after hard_reset read_mac
```

### Gotcha: after a USB flash the board can stay in download mode

PlatformIO's bundled esptool (v4.5.1) ends an upload with *"Hard resetting via RTS pin"*, and on
these USB-Serial-JTAG boards that can leave the chip in the **ROM download bootloader** instead of
running the application. The symptoms are silent and misleading: the flash verifies, the COM port
is present, and the board never joins the WiFi and never prints anything.

Diagnosing it takes one command — if esptool connects **without** performing a reset, the chip is
sitting in download mode:

```bash
python ~/.platformio/packages/tool-esptoolpy/esptool.py --port COM15 --before no_reset read_mac
```

The cure is a reset that does not touch the EN/GPIO0 lines. The standalone esptool (v4.8.5) uses
*"Hard resetting with RTC WDT"* and gets it right:

```bash
python ~/.platformio/packages/tool-esptoolpy/esptool.py --port COM15 --after hard_reset read_mac
```

A pyserial RTS pulse is **not** a valid substitute: on these boards it lands the chip in download
mode about as often as not. Cost of learning this: two board bring-ups on 2026-09-10, the first
misdiagnosed as a WiFi problem.

### Getting a console on a bare board

`Serial` goes to **UART0**, the physical pins, because the build defines `ARDUINO_USB_MODE=1`
without `ARDUINO_USB_CDC_ON_BOOT`. On a board with no UART0 wiring there is therefore no console at
all: the native USB port flashes and debugs, but carries no firmware output.

For a bring-up, move the console onto that same USB port with a temporary build:

```bash
PLATFORMIO_BUILD_FLAGS="-DARDUINO_USB_CDC_ON_BOOT=1" pio run -e incunest_V18 -t upload --upload-port COM15
```

Two things to know. The USB console **discards anything written while the host has the port
closed**, so open the port first and reset the board afterwards, or the banner is lost. And reflash
the standard build when finished: this one moves `Serial` off UART0, which is not where the rest of
the project expects it.

## Power

The IncuNest board can be powered from the USB connector labelled **AIR SENSOR**, which goes to the
ESP32-S3's native USB — that is where the COM port comes from. A laptop USB port is enough: a board
streams normally on it, at 100 datagrams/s and ~1.07 Mbit/s. Note that it then shares ground with
the PC.

The V17 board (`10:20:BA:14:75:60`) dropped off the WiFi while powered both from 12 V and from
USB, so the supply is not what explains it.
