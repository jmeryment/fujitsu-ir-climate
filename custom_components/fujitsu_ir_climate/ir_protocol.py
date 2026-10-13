"""Fujitsu General A/C IR frames (IRremoteESP8266 model ARRAH2E).

Long frame (16 bytes, LSB first):
  14 63 00 10 10 | FE 09 30 | temp<<4|power | mode | swing|fan | 00 00 00 | 20 | checksum
Short frame (7 bytes): 14 63 00 10 10 | cmd | ~cmd

The frames are bit-identical to SmartIR climate code 1292 (ASYG18LF / AR-RY12), see
tests/fixtures/smartir_1292_frames.json, including its conventions: the power bit is always
set (re-asserting "on" with every state frame), fan_only sends 30 C and dry sends fan auto.
"""

from __future__ import annotations

from typing import Final

from infrared_protocols.commands import Command

HEADER: Final = bytes.fromhex("1463001010")
LONG_CMD: Final = 0xFE
REST_LENGTH: Final = 0x09
PROTOCOL: Final = 0x30
BYTE14: Final = 0x20  # "unknown" bit IRremoteESP8266 sets for ARRAH2E

CMD_TURN_OFF: Final = 0x02
CMD_STEP_VERT: Final = 0x6C
# POWERFUL (0x39) and ECONO (0x09) exist only on ARREB1E / ARREW4E remotes
# (IRremoteESP8266), so they are deliberately not offered for ARRAH2E.

MODE_CODES: Final = {"heat_cool": 0, "cool": 1, "dry": 2, "fan_only": 3, "heat": 4}
FAN_CODES: Final = {"auto": 0, "high": 1, "medium": 2, "low": 3, "quiet": 4}
SWING_CODES: Final = {"off": 0x00, "vertical": 0x10, "horizontal": 0x20, "both": 0x30}

MIN_TEMP: Final = 16  # heat only; the unit's other modes start at 18
MIN_TEMP_NON_HEAT: Final = 18
MAX_TEMP: Final = 30

# Medians of the 1,300 Broadlink captures in SmartIR 1292, i.e. timings real units accept
# (IRremoteESP8266's nominal values are ~5-10 % shorter; receivers tolerate both).
CARRIER_HZ: Final = 38_000
HDR_MARK: Final = 3_500
HDR_SPACE: Final = 1_750
BIT_MARK: Final = 460
ZERO_SPACE: Final = 430
ONE_SPACE: Final = 1_280
# Silence after the final mark. Learned Broadlink codes (and every SmartIR 1292 capture) end
# with this ~109 ms gap (3333 Broadlink ticks, the 0x0d05 terminator). Without it a Broadlink
# RM4 pro was seen to send frames the unit ignored: a trailing unpaired mark is not emitted,
# which loses the last bit of the checksum.
FRAME_GAP: Final = 109_470


class FujitsuIRCommand(Command):
    """Raw IR command for the HA infrared platform."""

    def __init__(self, frame: bytes) -> None:
        super().__init__(modulation=CARRIER_HZ, repeat_count=0)
        self.frame = frame

    def get_raw_timings(self) -> list[int]:
        """Return signed timings in microseconds (+mark, -space)."""

        timings = [HDR_MARK, -HDR_SPACE]
        for byte in self.frame:
            for bit in range(8):
                timings += [BIT_MARK, -(ONE_SPACE if byte >> bit & 1 else ZERO_SPACE)]
        timings += [BIT_MARK, -FRAME_GAP]
        return timings


def clamp_temperature(mode: str, temperature: float) -> int:
    """Clamp a target temperature to what the unit accepts in a mode."""

    low = MIN_TEMP if mode == "heat" else MIN_TEMP_NON_HEAT
    return max(low, min(MAX_TEMP, round(temperature)))


def long_frame(mode: str, temperature: float, fan: str, swing: str) -> bytes:
    """Build the 16-byte state frame (this also turns the unit on)."""

    if mode not in MODE_CODES:
        raise ValueError(f"unsupported mode {mode!r}")
    if mode == "fan_only":
        temperature = MAX_TEMP
    if mode == "dry":
        fan = "auto"
    temp = clamp_temperature(mode, temperature)
    frame = bytearray(HEADER)
    frame += bytes(
        (
            LONG_CMD,
            REST_LENGTH,
            PROTOCOL,
            (temp - 16) << 4 | 0x01,
            MODE_CODES[mode],
            SWING_CODES[swing] | FAN_CODES[fan],
            0,
            0,
            0,
            BYTE14,
        )
    )
    frame.append(-sum(frame[7:15]) & 0xFF)
    return bytes(frame)


def short_frame(cmd: int) -> bytes:
    """Build a 7-byte command frame (off, vertical vane step)."""

    return HEADER + bytes((cmd, ~cmd & 0xFF))
