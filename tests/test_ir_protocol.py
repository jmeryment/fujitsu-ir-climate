"""Tests for the Fujitsu ARRAH2E frame builder (no Home Assistant needed)."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ir_protocol", ROOT / "custom_components/fujitsu_ir_climate/ir_protocol.py"
)
p = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p)

FIXTURE = json.loads((ROOT / "tests/fixtures/smartir_1292_frames.json").read_text())
SMARTIR_FAN = {"med": "medium"}


def _decode(timings: list[int]) -> bytes:
    """Decode the encoder's own timings back to bytes (LSB first)."""
    assert timings[:2] == [p.HDR_MARK, -p.HDR_SPACE]
    assert timings[-2:] == [p.BIT_MARK, -p.FRAME_GAP]
    timings = timings[:-1]
    spaces = timings[3:-1:2]
    assert set(spaces) <= {-p.ZERO_SPACE, -p.ONE_SPACE}
    bits = [s == -p.ONE_SPACE for s in spaces]
    return bytes(sum(bits[k * 8 + j] << j for j in range(8)) for k in range(len(bits) // 8))


@pytest.mark.parametrize("name", sorted(FIXTURE))
def test_matches_smartir_1292(name):
    if name == "off":
        frame = p.short_frame(p.CMD_TURN_OFF)
    else:
        mode, fan, swing, temp = name.split("/")
        frame = p.long_frame(mode, int(temp), SMARTIR_FAN.get(fan, fan), swing)
    assert frame.hex() == FIXTURE[name]


def test_fixture_covers_every_mode_fan_swing():
    seen = {tuple(k.split("/")[:3]) for k in FIXTURE if k != "off"}
    assert len(seen) == 5 * 5 * 4


@pytest.mark.parametrize(
    "frame",
    [
        p.long_frame("cool", 24, "auto", "off"),
        p.long_frame("heat", 16, "quiet", "both"),
        p.short_frame(p.CMD_STEP_VERT),
    ],
)
def test_timings_round_trip(frame):
    command = p.FujitsuIRCommand(frame)
    assert command.modulation == 38_000
    assert _decode(command.get_raw_timings()) == frame


def test_checksum():
    frame = p.long_frame("heat", 21, "low", "vertical")
    assert sum(frame[7:]) & 0xFF == 0


def test_short_frames():
    assert p.short_frame(p.CMD_TURN_OFF).hex() == "146300101002fd"
    assert p.short_frame(p.CMD_STEP_VERT).hex() == "1463001010" + "6c93"


def test_mode_rules():
    # fan_only always sends 30 C, dry always sends fan auto (as the remote does)
    assert p.long_frame("fan_only", 20, "high", "off") == p.long_frame(
        "fan_only", 30, "high", "off"
    )
    assert p.long_frame("dry", 24, "high", "off") == p.long_frame("dry", 24, "auto", "off")


@pytest.mark.parametrize(
    ("mode", "requested", "expected"),
    [
        ("heat", 16, 16),
        ("cool", 16, 18),
        ("heat_cool", 17, 18),
        ("cool", 31, 30),
        ("heat", 21.6, 22),
    ],
)
def test_clamp_temperature(mode, requested, expected):
    assert p.clamp_temperature(mode, requested) == expected
    assert p.long_frame(mode, requested, "auto", "off")[8] >> 4 == expected - 16


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        p.long_frame("auto", 24, "auto", "off")


def test_broadlink_packet_ends_like_a_learned_code():
    """The trailing gap encodes as Broadlink's 0x00 0x0d 0x05 terminator (3333 ticks)."""
    ticks = int(p.FRAME_GAP // 32.84)  # python-broadlink pulses_to_data
    assert divmod(ticks, 256) == (0x0D, 0x05)
