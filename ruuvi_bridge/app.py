"""Start the per-user app and coordinate scanner, HTTP and tray shutdown."""

import argparse
import logging
import os
import signal
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .bridge import Bridge
from .server import create_server
from .storage import Store


def main():
    """Run the Windows background app or an isolated cross-platform demo."""
    parser = argparse.ArgumentParser(description="Ruuvi Bridge – Windows BLE to MQTT")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument(
        "--demo", action="store_true", help="Separate sample history, no BLE or MQTT"
    )
    args = parser.parse_args()
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "RuuviBridge"
    directory = args.data_dir or base / "data"
    if args.demo:
        directory = directory / "demo"
    directory.mkdir(parents=True, exist_ok=True)
    handlers = [
        RotatingFileHandler(
            directory / "bridge.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    ]
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    url = f"http://127.0.0.1:{args.port}/"
    done = threading.Event()
    store = Store(directory)
    bridge = Bridge(store, directory, url, args.demo)
    tray = None

    def shutdown(*_):
        done.set()
        if tray:
            tray.stop()

    try:
        server = create_server(bridge, args.port, shutdown)
    except OSError:
        logging.error(
            "Port %s is occupied. Existing app or another service is using it.", args.port
        )
        store.close()
        if not args.no_open:
            webbrowser.open(url)
        return
    bridge.start()
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    logging.info("Ruuvi Bridge started at %s (demo=%s)", url, args.demo)
    if not args.no_open:
        webbrowser.open(url)
    try:
        if sys.platform == "win32" and not args.no_tray:
            from .windows import Tray

            tray = Tray(bridge, shutdown)
            tray.run()
        else:
            done.wait()
    finally:
        server.shutdown()
        server.server_close()
        bridge.stop()
        store.close()
        logging.info("Ruuvi Bridge stopped")


if __name__ == "__main__":
    main()
