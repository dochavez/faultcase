"""Capture README screenshots of the three screens (EN + ES) plus a flow GIF.

Usage: python scripts/screenshots.py

Starts the app locally with uvicorn, drives it with Playwright through the
precomputed demo case only (no model calls, no personal data) and writes:
  docs/img/collect-en.png, diagnosis-en.png, action-en.png (and -es)
  docs/img/flow.gif (under 5 MB)

Requires (dev tools only, not in requirements.txt):
  pip install playwright pillow && playwright install chromium
"""

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "docs" / "img"
BASE = "http://127.0.0.1:8123"
MAX_GIF_BYTES = 5 * 1024 * 1024


def _wait_for_server(timeout_seconds=30):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("app did not start in time")


def _capture_flow(page, lang, gif_frames):
    page.goto(f"{BASE}/?lang={lang}")
    page.wait_for_selector("#demo-btn")
    page.screenshot(path=str(IMG_DIR / f"collect-{lang}.png"), full_page=True)
    if gif_frames is not None:
        gif_frames.append(page.screenshot())
    page.click("#demo-btn")
    page.wait_for_url("**/case/*")
    page.wait_for_selector("a.btn-big")
    page.screenshot(path=str(IMG_DIR / f"diagnosis-{lang}.png"), full_page=True)
    if gif_frames is not None:
        gif_frames.append(page.screenshot())
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(300)
        gif_frames.append(page.screenshot())
    page.click("a.btn-big")
    page.wait_for_url("**/action*")
    page.wait_for_selector("#serial")
    page.screenshot(path=str(IMG_DIR / f"action-{lang}.png"), full_page=True)
    if gif_frames is not None:
        page.evaluate("window.scrollTo(0, 0)")
        gif_frames.append(page.screenshot())
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(300)
        gif_frames.append(page.screenshot())


def _save_gif(frames):
    from io import BytesIO

    from PIL import Image

    images = []
    for raw in frames:
        image = Image.open(BytesIO(raw)).convert("RGB")
        images.append(image)
    width = 800
    path = IMG_DIR / "flow.gif"
    while True:
        resized = [
            img.resize((width, int(img.height * width / img.width))) for img in images
        ]
        resized[0].save(
            path, save_all=True, append_images=resized[1:], duration=1000,
            loop=0, optimize=True,
        )
        if path.stat().st_size <= MAX_GIF_BYTES or width <= 400:
            return width
        width -= 80


def main():
    from playwright.sync_api import sync_playwright

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "faultcase.app:app",
         "--host", "127.0.0.1", "--port", "8123"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_server()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_default_timeout(30000)
            gif_frames: list = []
            _capture_flow(page, "en", gif_frames)
            _capture_flow(page, "es", None)
            browser.close()
        width = _save_gif(gif_frames)
    finally:
        server.terminate()
        server.wait(timeout=15)
    for path in sorted(IMG_DIR.iterdir()):
        print(f"{path.name}: {path.stat().st_size // 1024} KB")
    print(f"flow.gif rendered at {width}px wide")


if __name__ == "__main__":
    main()
