"""Decode Ruuvi RAWv2 manufacturer data (company ID 0x0499)."""

import struct

COMPANY_ID = 0x0499


def decode(data: bytes, address: str) -> dict | None:
    """Decode an exact RAWv2 packet, mapping unavailable sentinels to None.

    Layout and scales follow Ruuvi's public data-format-5 specification.
    The embedded address stays stable when a platform reports a different BLE ID.
    """
    if len(data) != 24 or data[0] != 5:
        return None
    _, temp, humidity, pressure, _ax, _ay, _az, power, movement, sequence, mac = struct.unpack(
        ">BhHHhhhHBH6s", data
    )
    identity = address if mac == b"\xff" * 6 else mac.hex(":")
    identity = identity.replace(":", "").replace("-", "").lower()
    if len(identity) != 12 or any(c not in "0123456789abcdef" for c in identity):
        return None
    voltage = power >> 5  # Upper 11 bits encode voltage; lower 5 encode transmit power.
    return {
        "id": identity,
        "temperature": None if temp == -32768 else round(temp * 0.005, 3),
        "humidity": None if humidity == 65535 else round(humidity * 0.0025, 4),
        "pressure": None if pressure == 65535 else round((pressure + 50000) / 100, 2),
        "battery": None if voltage == 2047 else round((voltage + 1600) / 1000, 3),
        "movement": None if movement == 255 else movement,
        "sequence": None if sequence == 65535 else sequence,
    }
