"""Capture README screenshots of the running web app with headless Microsoft Edge (or Chrome).

Usage (server must be running on http://127.0.0.1:8000):
    python scripts/take_screenshots.py

Writes cropped, compressed PNGs to docs/screenshots/.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
BASE = os.environ.get("SHIELD_URL", "http://127.0.0.1:8000")
WIDTH, HEIGHT = 1280, 3600
PADDING = 24  # px kept below the last content row when cropping
# Pages that also get a "<name>-result.png" crop starting at the result box.
RESULT_CROPS = {"chat", "letter"}

FEE_SCAM = ("Dear Candidate, Congratulations! You have been shortlisted for the Data Analyst Internship at "
            "Wipro. To confirm your seat, pay a one-time registration fee of Rs 1,499 (fully refundable) to "
            "wiprohr.desk@ybl within 24 hours. Contact: careers.wipro.hr@gmail.com")

SHOTS = {
    "home": "/",
    "check": "/check#text=" + quote(FEE_SCAM),
    "chat": "/chat#example=1",
    "letter": "/offer-letter#sample=fake_offer_brightwave.pdf",
    "report": "/report",
    "tools": "/tools",
}

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    shutil.which("chromium") or "",
    shutil.which("google-chrome") or "",
]


def find_browser() -> str:
    for path in BROWSERS:
        if path and Path(path).exists():
            return path
    sys.exit("Couldn't find Edge or Chrome.")


def capture(browser: str, url: str, target: Path, profile: str) -> None:
    subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
         f"--user-data-dir={profile}", f"--window-size={WIDTH},{HEIGHT}", "--force-prefers-reduced-motion",
         "--virtual-time-budget=8000", f"--screenshot={target}", url],
        check=True, capture_output=True, timeout=90,
    )


def crop_to_content(path: Path) -> None:
    """Trim the empty page background below the footer, then shrink the file."""
    img = Image.open(path).convert("RGB")
    background = img.getpixel((5, img.height - 5))
    bottom = img.height
    pixels = img.load()
    for y in range(img.height - 1, 0, -1):
        if any(pixels[x, y] != background for x in range(0, img.width, 4)):
            bottom = y
            break
    img = img.crop((0, 0, img.width, min(img.height, bottom + PADDING)))
    img.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)


def crop_result(path: Path) -> Path:
    """Save a crop from the result box (found by its red high-risk left border) to the end."""
    img = Image.open(path).convert("RGB")
    pixels = img.load()

    def red(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        return r > 200 and g < 140 and b < 140

    # The border is a tall red line; an emoji or text is not, so require 60 red rows in a column.
    top = next((y for y in range(img.height - 60) for x in range(200, 300)
                if red(x, y) and all(red(x, y + dy) for dy in range(0, 60, 6))), None)
    if top is None:
        raise SystemExit(f"No result box found in {path.name}")
    target = path.with_name(f"{path.stem}-result.png")
    img.crop((0, max(0, top - PADDING), img.width, img.height)).quantize(
        colors=256, method=Image.Quantize.MEDIANCUT).save(target, optimize=True)
    return target


def main() -> None:
    browser = find_browser()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        for name, path in SHOTS.items():
            target = OUT / f"{name}.png"
            capture(browser, BASE + path, target, profile)
            crop_to_content(target)
            outputs = [target] + ([crop_result(target)] if name in RESULT_CROPS else [])
            for file in outputs:
                with Image.open(file) as img:
                    print(f"{file.stem:<13} {img.width}x{img.height}  {file.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
