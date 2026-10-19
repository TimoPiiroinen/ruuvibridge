"""Shared Finnish-to-English catalog for browser, API messages and Windows tray."""

import json
from pathlib import Path

ENGLISH = json.loads((Path(__file__).parent / "static/i18n.json").read_text(encoding="utf-8"))


def translate(message, language="en"):
    if language == "fi":
        return message
    if message in ENGLISH:
        return ENGLISH[message]
    # These status messages append a hostname or an MQTT reason supplied at runtime.
    for prefix in ("Yhdistetty: ", "MQTT-yhteys hylättiin: "):
        if message.startswith(prefix):
            return ENGLISH[prefix] + message[len(prefix) :]
    return message
