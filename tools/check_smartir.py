#!/usr/bin/env python3
"""Compare the encoder with a SmartIR Broadlink climate code file (e.g. 1292.json).

Usage:
  tools/check_smartir.py 1292.json                 # report identical / mismatched frames
  tools/check_smartir.py 1292.json --fixture out.json  # also write the decoded frames

Needs the `infrared-protocols` package (pip install infrared-protocols).
"""

import argparse
import base64
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ir_protocol", ROOT / "custom_components/fujitsu_ir_climate/ir_protocol.py"
)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

BROADLINK_TICK_US = 269 / 8192 * 1000
SMARTIR_FAN = {"med": "medium"}


def broadlink_pulses(b64: str) -> list[float]:
    raw = base64.b64decode(b64)
    data = raw[4 : 4 + (raw[2] | raw[3] << 8)]
    out, i = [], 0
    while i < len(data):
        v = data[i]
        i += 1
        if v == 0:
            v, i = data[i] << 8 | data[i + 1], i + 2
        out.append(v * BROADLINK_TICK_US)
    return out


def decode(pulses: list[float]) -> bytes | None:
    """Decode one LSB-first frame; None when the capture has no header."""
    if not (pulses[0] > 2500 and 1200 < pulses[1] < 2200):
        return None
    bits = []
    for i in range(2, len(pulses) - 1, 2):
        if pulses[i + 1] > 3000:
            break
        bits.append(pulses[i + 1] > 800)
    return bytes(sum(bits[k * 8 + j] << j for j in range(8)) for k in range(len(bits) // 8))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("smartir_json")
    ap.add_argument("--fixture")
    args = ap.parse_args()
    codes = json.loads(Path(args.smartir_json).read_text())["commands"]

    cases = {"off": (codes["off"], p.short_frame(p.CMD_TURN_OFF))}
    for mode, fans in codes.items():
        if mode == "off":
            continue
        for fan, swings in fans.items():
            for swing, temps in swings.items():
                for temp, code in temps.items():
                    want = p.long_frame(mode, int(temp), SMARTIR_FAN.get(fan, fan), swing)
                    cases[f"{mode}/{fan}/{swing}/{temp}"] = (code, want)

    fixture, ok, bad = {}, 0, 0
    for name, (code, want) in cases.items():
        got = decode(broadlink_pulses(code))
        if got is None:
            print(f"capture without header, skipped: {name}")
            continue
        fixture[name] = got.hex()
        if got == want:
            ok += 1
        else:
            bad += 1
            print(f"MISMATCH {name}: smartir {got.hex()} encoder {want.hex()}")
    print(f"{ok} identical, {bad} mismatches")
    if args.fixture:
        Path(args.fixture).write_text(json.dumps(fixture, indent=0) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
