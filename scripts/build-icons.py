"""Export web and Windows sizes from the original transparent logo."""

from pathlib import Path

from PIL import Image

assets = Path(__file__).resolve().parent.parent / "ruuvi_bridge/static/assets"
with Image.open(assets / "ruuvi-bridge-logo.png") as original:
    image = original.convert("RGBA")
    if image.getchannel("A").getextrema()[0] != 0:
        raise ValueError("The source logo must have a transparent background")
    image.resize((256, 256), Image.Resampling.LANCZOS).save(assets / "ruuvi-bridge-logo-256.png")
    image.save(
        assets / "ruuvi-bridge.ico",
        format="ICO",
        sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)],
    )
    print(f"Exported transparent web PNG and Windows ICO from {image.width}x{image.height} source")
