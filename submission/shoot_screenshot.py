"""Capture the fair value result cards for slide 2 of the deck.

    uvicorn app.main:app --port 8000
    python submission/shoot_screenshot.py [base-url]
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
LINK = "/#/value?town=TAMPINES&type=4%20ROOM&area=95&storey=10%20TO%2012&lease=72&ask=690000"
OUT = Path(__file__).with_name("value-crop.png")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_context(viewport={"width": 1440, "height": 1400}, device_scale_factor=2, reduced_motion="reduce").new_page()
    page.goto(BASE + LINK)
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".range-bar__ask")
    page.wait_for_timeout(500)
    box = page.locator(".grid--side > .stack").bounding_box()
    pad = 10
    page.screenshot(path=str(OUT), clip={"x": box["x"] - pad, "y": box["y"] - pad, "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad})
    print(f"Wrote {OUT} ({round(box['width'])} x {round(box['height'])} css px)")
    browser.close()
