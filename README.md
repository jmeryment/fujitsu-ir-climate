# Fujitsu IR Climate

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/jmeryment/fujitsu-ir-climate/actions/workflows/validate.yml/badge.svg)](https://github.com/jmeryment/fujitsu-ir-climate/actions/workflows/validate.yml)
[![Tests](https://github.com/jmeryment/fujitsu-ir-climate/actions/workflows/tests.yml/badge.svg)](https://github.com/jmeryment/fujitsu-ir-climate/actions/workflows/tests.yml)

Control a **Fujitsu General** split-system air conditioner from Home Assistant over infrared,
using Home Assistant's native [`infrared`](https://www.home-assistant.io/integrations/infrared/)
platform. Any infrared emitter entity works (Broadlink, ESPHome and others), and no code
files or learned remotes are needed: the integration builds each Fujitsu IR frame itself.

It creates a climate entity and two buttons per air conditioner, all set up from the UI.

## Compatibility

The integration speaks the Fujitsu **ARRAH2E** protocol (name from
[IRremoteESP8266](https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Fujitsu.h)):
16-byte state frames starting `14 63 00 10 10 FE 09 30`. IRremoteESP8266 lists these remotes
for it: **AR-RAH2E, AR-RAH2U, AR-RAE1E, AR-RAC1E, AR-RCE1E, AR-REG1U, AR-RCL1E** (O General),
plus units such as ASYG30LFCA, ASHG09LLCA, AOHG09LLC and AGTV14LAC.

Tested on:

| Indoor unit | Remote | Emitter |
|---|---|---|
| ASTH09KNCA (Comfort, R32) | supplied Fujitsu remote | Broadlink (HA Broadlink integration) |

The frames are bit-identical to SmartIR climate code **1292** (ASYG18LF / AR-RY12): the test
suite checks all 1,298 valid codes in that file. **If SmartIR 1292 works for your unit, this
integration will too.**

> [!WARNING]
> Fujitsu has several IR protocol variants (ARDB1, ARJW2, ARREB1E, ARREW4E, ARRY4). They are
> **not** supported. IRremoteESP8266 notes that some units lock up until a power cycle when they
> receive a swing command from the wrong variant. If your remote is not in the list above,
> test on/off and temperature first, then swing.

## Requirements

- Home Assistant **2026.6** or newer.
- An infrared emitter entity (`infrared.*`) facing the indoor unit, e.g. from the Broadlink or
  ESPHome integration.

## Installation

**HACS:** HACS > ⋮ > Custom repositories > add `https://github.com/jmeryment/fujitsu-ir-climate`
as an *Integration*. Install **Fujitsu IR Climate**, then restart Home Assistant.

**Manual:** copy `custom_components/fujitsu_ir_climate` into your `config/custom_components/`
and restart Home Assistant.

## Configuration

Settings > Devices & services > Add integration > **Fujitsu IR Climate**:

- **Name**: the device and entity name, e.g. "Bedroom AC".
- **Infrared emitter**: the `infrared.*` entity that faces the unit.
- **Room temperature / humidity sensor** (optional): shown as the climate entity's current
  temperature and humidity. Fahrenheit sensors are converted.

Add one entry per air conditioner, each with its own emitter (a second unit in view of the same
emitter would obey the same frames). Later changes:

- **Configure** changes the room sensors.
- **Reconfigure** points the entry at a different emitter. Do this after renaming the emitter
  entity, because the entry stores its entity ID.
- To rename the air conditioner, rename the device.

## Entities

**Climate**

| Feature | Values |
|---|---|
| HVAC modes | off, heat_cool (auto), cool, dry, fan_only, heat |
| Target temperature | 16-30 °C in 1 °C steps (16-17 °C in heat only; other modes clamp to 18 °C) |
| Fan modes | auto, high, medium, low, quiet (dry always runs, and shows, auto) |
| Swing modes | off, vertical, horizontal, both |

- **While the unit is on**, every change sends the full state.
- **While it is off**, temperature, fan and swing changes are stored and sent with the next
  turn-on.
- **Explicit commands** (turn on, turn off, set mode) are always sent, even if the entity already
  shows that state, because the unit may have been changed with its own remote.
- **Turn-on** resumes the last mode.
- **Failed sends:** if the emitter fails to send, the entity keeps its previous state.
- **Availability:** the entity is unavailable while its emitter is.

**Buttons**

- *Force send IR command*: re-sends the current state (useful if the unit missed a command).
- *Step vertical vane*: moves the vertical louvre one position, like the remote's SET button.

## Limitations

- **Infrared is one-way.** The entity is optimistic (`assumed_state`): if someone uses the
  physical remote, Home Assistant does not know. Press *Force send* to bring the unit back in
  line with Home Assistant.
- Every state frame sets the protocol's power-on bit, as SmartIR 1292 does. Units accept it
  while already running.
- **POWERFUL and ECONOMY are not offered.** IRremoteESP8266 only sends them for ARREB1E/ARREW4E
  remotes, and they have not been tested on an ARRAH2E unit. If your unit has them and you can
  confirm the codes, please open an issue.
- Outdoor-unit low noise, the 10 °C heat mode and timers are not implemented.

## How it works

`ir_protocol.py` builds the frames. Long frame (16 bytes, LSB first):

```
14 63 00 10 10 | FE 09 30 | (temp-16)<<4 | 1 | mode | swing | fan | 00 00 00 | 20 | checksum
```

- **Mode:** auto 0, cool 1, dry 2, fan 3, heat 4.
- **Fan:** auto 0, high 1, med 2, low 3, quiet 4.
- **Swing:** off/vertical/horizontal/both = 0x00/0x10/0x20/0x30, ORed with the fan value.
- **Checksum:** −(sum of bytes 7..14) mod 256.
- **Short commands:** `14 63 00 10 10 cmd ~cmd`, where cmd is off 0x02 or vertical vane step 0x6C.

The carrier is 38 kHz. The header is 3500/1750 µs, the bit mark 460 µs, and a 0 or 1 is a
430 or 1280 µs space. These timings are the medians of the SmartIR 1292 Broadlink captures.

`tools/check_smartir.py` decodes a SmartIR Broadlink code file and compares every frame with
the encoder. Use it to check whether another SmartIR Fujitsu code file matches this protocol.

## Development

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt \
  pytest-homeassistant-custom-component==0.13.372 infrared-protocols==10.1.0
pytest -q                     # protocol tests + config flow / entity tests in a real HA
ruff check . && ruff format --check .
```

CI runs the tests against the oldest supported Home Assistant release (2026.6.0) and the newest
tested one; see `.github/workflows/tests.yml`.

## Credits

- Protocol layout: [IRremoteESP8266](https://github.com/crankyoldgit/IRremoteESP8266) (`ir_Fujitsu`).
- Reference frames: [SmartIR](https://github.com/smartHomeHub/SmartIR) climate code 1292 (MIT).
  The test fixture holds frames decoded from it.
- Integration shape: [MHI-IR-Climate](https://github.com/mattbyte/MHI-IR-Climate) and Home
  Assistant's `samsung_infrared`.

Not affiliated with Fujitsu General Limited. MIT licensed.
