"""Responsive layout check in a real browser.

Loads every page at a range of screen sizes and fails if anything overflows
sideways, overlaps, or shows an error. Uses the Chrome already installed.

    uvicorn app.main:app --port 8000        # in one terminal
    python tests/ui_check.py                # in another (pip install playwright)
    python tests/ui_check.py --base https://flatfair-nine.vercel.app --shots docs/screenshots
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROUTES = ["overview", "market", "forecast", "afford", "value", "compare"]
VIEWPORTS = [
    ("phone-small", 360, 740),
    ("phone", 390, 844),
    ("phone-large", 430, 932),
    ("tablet", 768, 1024),
    ("tablet-wide", 1024, 768),
    ("laptop", 1280, 800),
    ("desktop", 1440, 900),
    ("desktop-hd", 1920, 1080),
    ("desktop-2k", 2560, 1440),
]

# Elements allowed to be wider than the screen because they scroll inside themselves.
SCROLLERS = ".chips, .table-wrap, .tabs, .modal__body, .townlist"

OVERFLOW_JS = """
(scrollers) => {
  const vw = document.documentElement.clientWidth;
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest(scrollers) || el.closest('svg') || el.closest('.sr-only, .skip-link')) continue;
    const style = getComputedStyle(el);
    if (style.position === 'fixed' || style.display === 'none' || style.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > vw + 1 || r.left < -1) out.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 40)} [${Math.round(r.left)}..${Math.round(r.right)}]`);
  }
  return { vw, scrollWidth: document.documentElement.scrollWidth, offenders: out.slice(0, 6) };
}
"""

OVERLAP_JS = """
() => {
  const boxes = (sel) => [...document.querySelectorAll(sel)].map((el) => ({ el, r: el.getBoundingClientRect() })).filter((b) => b.r.width && b.r.height);
  const hit = (a, b) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
  const problems = [];
  // Cards inside the same grid must never sit on top of each other.
  for (const grid of document.querySelectorAll('.grid, .stack, .mapcard')) {
    const kids = [...grid.children].map((el) => el.getBoundingClientRect()).filter((r) => r.width && r.height);
    for (let i = 0; i < kids.length; i++) for (let j = i + 1; j < kids.length; j++) if (hit(kids[i], kids[j])) problems.push(`${grid.className}: child ${i} overlaps child ${j}`);
  }
  // Labels on the value range bar and the repayment meter must not collide.
  for (const group of ['.range-bar__label', '.meter__mark span', '.townmap__label']) {
    const items = boxes(group);
    for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) if (hit(items[i].r, items[j].r)) problems.push(`${group}: "${items[i].el.textContent}" overlaps "${items[j].el.textContent}"`);
  }
  return problems.slice(0, 6);
}
"""

SMALL_TARGETS_JS = """
() => [...document.querySelectorAll('button, a.btn, select, input, .chip, .tabbar__item, .townlist__item')]
  .filter((el) => !el.closest('.footer') && el.offsetParent !== null)
  .map((el) => ({ el, r: el.getBoundingClientRect() }))
  .filter(({ r }) => r.height > 0 && r.height < 36)
  .map(({ el, r }) => `${el.tagName.toLowerCase()}.${String(el.className).slice(0, 30)} ${Math.round(r.width)}x${Math.round(r.height)}`)
  .slice(0, 5)
"""


def settle(page: Page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(350)


def check_page(page: Page, name: str, width: int, route: str) -> list[str]:
    problems: list[str] = []
    banner = page.locator(".error-banner")
    if banner.count():
        problems.append(f"error banner: {banner.first.inner_text()[:120]}")

    for position in ("top", "middle", "bottom"):
        height = page.evaluate("document.documentElement.scrollHeight")
        page.evaluate(f"window.scrollTo(0, {dict(top=0, middle=height // 2, bottom=height)[position]})")
        page.wait_for_timeout(120)
        overflow = page.evaluate(OVERFLOW_JS, SCROLLERS)
        if overflow["scrollWidth"] > overflow["vw"] + 1:
            problems.append(f"page scrolls sideways at {position}: {overflow['scrollWidth']} > {overflow['vw']} {overflow['offenders']}")
        elif overflow["offenders"]:
            problems.append(f"content past the screen edge at {position}: {overflow['offenders']}")
        overlaps = page.evaluate(OVERLAP_JS)
        if overlaps:
            problems.append(f"overlap at {position}: {overlaps}")

    if width <= 900:
        stuck = page.evaluate("[...document.querySelectorAll('.side-sticky')].filter((el) => getComputedStyle(el).position === 'sticky').length")
        if stuck:
            problems.append("side form is sticky in a one-column layout, so results would slide over it")

    phone = width <= 760
    tabbar = page.locator(".tabbar").is_visible()
    tabs = page.locator(".tabs").is_visible()
    if phone and (not tabbar or tabs):
        problems.append(f"phone nav wrong: tabbar={tabbar} tabs={tabs}")
    if not phone and (tabbar or not tabs):
        problems.append(f"desktop nav wrong: tabbar={tabbar} tabs={tabs}")
    if phone:
        small = page.evaluate(SMALL_TARGETS_JS)
        if small:
            problems.append(f"tap targets under 36px: {small}")
    return problems


def check_interactions(page: Page, base: str, width: int) -> list[str]:
    """The map and the town picker actually work."""
    problems: list[str] = []
    page.goto(f"{base}/#/overview")
    settle(page)
    towns = page.locator(".townmap__town")
    if towns.count() != 26:
        return [f"overview map has {towns.count()} towns, expected 26"]
    page.locator('.townmap__town[data-town="PASIR RIS"]').click(force=True)
    page.wait_for_timeout(250)
    name = page.locator(".mappanel__name").inner_text()
    if name != "Pasir Ris":
        problems.append(f"clicking Pasir Ris on the map showed '{name}'")
    if page.locator(".townmap__town.is-selected").get_attribute("data-town") != "PASIR RIS":
        problems.append("Pasir Ris is not highlighted after clicking it")

    page.goto(f"{base}/#/market")
    settle(page)
    page.locator("#f-town").click()
    page.wait_for_selector(".modal__panel")
    page.wait_for_timeout(300)
    panel = page.locator(".modal__panel").bounding_box()
    viewport = page.viewport_size
    if panel["x"] < -1 or panel["x"] + panel["width"] > viewport["width"] + 1 or panel["y"] < -1 or panel["y"] + panel["height"] > viewport["height"] + 1:
        problems.append(f"picker does not fit the screen: {panel} in {viewport}")
    if page.locator(".modal .townmap__town").count() != 26:
        problems.append("picker map is missing towns")
    page.locator('.modal .townlist__item[data-town="BEDOK"]').click()
    page.wait_for_timeout(600)
    if page.locator(".modal").count():
        problems.append("picker stayed open after choosing a town")
    if page.locator("#f-town").inner_text().strip() != "Bedok":
        problems.append(f"town field shows '{page.locator('#f-town').inner_text().strip()}' after choosing Bedok")
    settle(page)
    if "Bedok" not in page.locator(".insight").inner_text():
        problems.append("market page did not update to Bedok")

    page.locator('.chip:has-text("5-room")').click()
    settle(page)
    if "5-room" not in page.locator(".insight").inner_text():
        problems.append("flat type chip did not update the page")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--shots", help="folder for full-page screenshots (desktop and phone)")
    parser.add_argument("--only", help="comma-separated viewport names")
    args = parser.parse_args()
    only = set(args.only.split(",")) if args.only else None

    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for name, width, height in VIEWPORTS:
            if only and name not in only:
                continue
            # Reduced motion: measure the settled layout, not a frame mid-animation.
            context = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce", device_scale_factor=2 if width <= 760 else 1, has_touch=width <= 760)
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc, errors=errors: errors.append(str(exc)))
            page.on("console", lambda msg, errors=errors: errors.append(msg.text) if msg.type == "error" else None)
            for route in ROUTES:
                page.goto(f"{args.base}/#/{route}")
                page.reload()
                settle(page)
                problems = check_page(page, name, width, route)
                if args.shots and name in ("desktop", "phone"):
                    folder = Path(args.shots)
                    folder.mkdir(parents=True, exist_ok=True)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(path=str(folder / (f"{route}.png" if name == "desktop" else f"{route}-phone.png")), full_page=name == "desktop")
                status = "ok  " if not problems else "FAIL"
                print(f"{status} {name:<12} {width:>4}px  {route}")
                for problem in problems:
                    print(f"       - {problem}")
                failures += len(problems)
            problems = check_interactions(page, args.base, width)
            print(f"{'ok  ' if not problems else 'FAIL'} {name:<12} {width:>4}px  map and picker")
            for problem in problems:
                print(f"       - {problem}")
            failures += len(problems)
            if errors:
                print(f"FAIL {name:<12} {width:>4}px  browser errors: {errors[:3]}")
                failures += len(errors)
            context.close()
        browser.close()
    print("\nAll layouts pass." if not failures else f"\n{failures} problem(s) found.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
