"""Generate the native-player-only Windows and Qt icon assets.

The player intentionally has its own taskbar mark: a gold play triangle in
the Cinema Paradiso frame. Do not derive these assets from the main CP icon.
"""

from pathlib import Path
import struct

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
PNG_PATH = RESOURCES / "cp-player-icon.png"
ICO_PATH = RESOURCES / "cp-player.ico"
SCALE = 4
CANVAS = 256
GOLD = (225, 181, 42, 255)
BACKGROUND = (11, 12, 17, 255)


def scaled(value):
    return int(value * SCALE)


def generate_icon():
    image = Image.new("RGBA", (scaled(CANVAS), scaled(CANVAS)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (scaled(18), scaled(18), scaled(238), scaled(238)),
        radius=scaled(42),
        fill=BACKGROUND,
        outline=GOLD,
        width=scaled(8),
    )
    draw.polygon(
        [(scaled(101), scaled(76)), (scaled(101), scaled(180)), (scaled(184), scaled(128))],
        fill=GOLD,
    )
    return image.resize((CANVAS, CANVAS), Image.Resampling.LANCZOS)


def main():
    icon = generate_icon()
    icon.save(PNG_PATH, format="PNG", optimize=True)
    icon.save(
        ICO_PATH,
        format="ICO",
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)],
        bitmap_format="bmp",
    )
    # Pillow writes zero in ICO directory plane fields. Windows accepts that,
    # but the native resource contract uses explicit one-plane 32-bit entries.
    data = bytearray(ICO_PATH.read_bytes())
    _reserved, _kind, image_count = struct.unpack_from("<HHH", data)
    for index in range(image_count):
        struct.pack_into("<H", data, 6 + (index * 16) + 4, 1)
    ICO_PATH.write_bytes(data)


if __name__ == "__main__":
    main()
