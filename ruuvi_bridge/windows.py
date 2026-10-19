"""Windows shell integration; imported lazily to keep BLE on its own MTA thread."""

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from .i18n import translate


def set_autostart(enabled, directory):
    """Manage only this app's per-user Run entry; no administrator rights needed."""
    if sys.platform != "win32":
        if enabled:
            raise ValueError("Automaattikäynnistys toimii vain Windowsissa")
        return
    import winreg

    launcher = Path(__file__).resolve().parent.parent / "run.py"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    command = subprocess.list2cmdline(
        [str(pythonw), str(launcher), "--data-dir", str(directory), "--no-open"]
    )
    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
    ) as key:
        if enabled:
            winreg.SetValueEx(key, "RuuviBridge", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "RuuviBridge")
            except FileNotFoundError:
                pass


def tray_image(text, fresh=True):
    """Use the mascot at startup, then a legible integer measurement in the tray."""
    from PIL import Image, ImageDraw, ImageFont

    if text == "R":
        logo = Path(__file__).parent / "static/assets/ruuvi-bridge-logo-256.png"
        with Image.open(logo) as image:
            return image.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 63, 63), radius=12, fill="#176454" if fresh else "#666b71")
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeuib.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    font = next(
        (ImageFont.truetype(str(p), 42 if len(text) < 3 else 30) for p in candidates if p.exists()),
        ImageFont.load_default(),
    )
    draw.text((32, 31), text, anchor="mm", font=font, fill="white")
    return image


class Tray:
    """Keep the Windows icon and metric radio choices in sync with saved settings."""

    def __init__(self, bridge, stop):
        import pystray

        self.bridge = bridge
        self.done = threading.Event()
        self.icon = pystray.Icon(
            "RuuviBridge",
            tray_image("R"),
            "Ruuvi Bridge",
            menu=pystray.Menu(
                pystray.MenuItem(
                    self.menu_text("Avaa mittaukset ja historia"),
                    lambda: webbrowser.open(bridge.url),
                    default=True,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    self.menu_text("Näytä kosteus (%)"),
                    self.select_metric("humidity"),
                    checked=self.metric_selected("humidity"),
                    radio=True,
                ),
                pystray.MenuItem(
                    self.menu_text("Näytä lämpötila (°C)"),
                    self.select_metric("temperature"),
                    checked=self.metric_selected("temperature"),
                    radio=True,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self.menu_text("Lopeta Ruuvi Bridge"), lambda: stop()),
            ),
        )

    def menu_text(self, message):
        return lambda item: translate(message, self.bridge.store.settings()["language"])

    def select_metric(self, metric):
        """Use the same validated settings path as the browser, including persistence."""

        def select(icon, item):
            self.bridge.update_settings({"tray_metric": metric})
            icon.update_menu()

        return select

    def metric_selected(self, metric):
        # Evaluate on demand: changing the browser setting also updates the tray menu.
        return lambda item: self.bridge.store.settings()["tray_metric"] == metric

    def run(self):
        def setup(icon):
            icon.visible = True
            previous = None
            previous_metric = None
            while not self.done.wait(2):
                state = self.bridge.snapshot()
                cfg = state["settings"]
                menu_state = (cfg["tray_metric"], cfg["language"])
                if menu_state != previous_metric:
                    icon.update_menu()
                    previous_metric = menu_state
                sensor = next(
                    (s for s in state["sensors"] if s["id"] == cfg["tray_tag"] and s["enabled"]),
                    None,
                )
                fresh = sensor is not None and sensor["fresh"]
                value = sensor.get(cfg["tray_metric"]) if fresh else None
                text = str(round(value)) if value is not None else "–"
                title = translate(
                    "Ruuvi Bridge – valitse anturi käyttöliittymässä", cfg["language"]
                )
                if sensor:
                    if fresh:
                        temp = sensor.get("temperature")
                        humidity = sensor.get("humidity")
                        separator = "," if cfg["language"] == "fi" else "."
                        temp_text = (
                            f"{temp:.1f}".replace(".", separator) if temp is not None else "–"
                        )
                        humidity_text = (
                            f"{humidity:.1f}".replace(".", separator)
                            if humidity is not None
                            else "–"
                        )
                        title = f"{sensor['name']}: {temp_text} °C / {humidity_text} %"
                    else:
                        title = (
                            sensor["name"]
                            + " – "
                            + translate("ei tuoretta mittausta", cfg["language"])
                        )
                current = (text, fresh, title)
                if current != previous:
                    icon.icon = tray_image(text, fresh)
                    icon.title = title[:127]
                    previous = current

        self.icon.run(setup=setup)

    def stop(self):
        self.done.set()
        self.icon.stop()
