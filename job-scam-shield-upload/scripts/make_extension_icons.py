"""Draw the extension's shield icons (16/48/128 px) into extension/icons/.

Usage: python scripts/make_extension_icons.py   (needs Pillow, installed with reportlab)
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "extension" / "icons"
BLUE = (36, 87, 214, 255)
WHITE = (255, 255, 255, 255)
SCALE = 8  # draw large, then downsample for smooth edges


def shield(size: int) -> Image.Image:
    s = size * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    outline = [(0.5, 0.04), (0.92, 0.18), (0.88, 0.55), (0.5, 0.96), (0.12, 0.55), (0.08, 0.18)]
    draw.polygon([(x * s, y * s) for x, y in outline], fill=BLUE)
    tick = [(0.30, 0.50), (0.45, 0.65), (0.72, 0.36)]
    draw.line([(x * s, y * s) for x, y in tick], fill=WHITE, width=int(0.1 * s), joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 48, 128):
        shield(size).save(OUT / f"icon{size}.png")
        print(f"wrote extension/icons/icon{size}.png")


if __name__ == "__main__":
    main()
