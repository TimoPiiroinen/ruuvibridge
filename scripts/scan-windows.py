"""Optional read-only 20-second Ruuvi scan. Run with Windows Python."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bleak import BleakScanner

from ruuvi_bridge.decoder import COMPANY_ID, decode


async def main():
    found = {}

    def callback(device, advertisement):
        data = advertisement.manufacturer_data.get(COMPANY_ID)
        if data:
            reading = decode(data, device.address)
            if reading:
                found[reading["id"]] = {**reading, "rssi": advertisement.rssi}

    async with BleakScanner(detection_callback=callback):
        await asyncio.sleep(20)
    print(json.dumps(list(found.values()), ensure_ascii=True, indent=2))


asyncio.run(main())
