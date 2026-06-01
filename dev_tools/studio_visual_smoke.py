#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Playwright smoke checks for HBV-Studio visual changes."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}

VIEWS = ("dashboard", "wizard", "calibration", "forecast", "results")


def overflow_report(page: Page) -> list[dict[str, Any]]:
    return page.evaluate(
        """
        () => Array.from(document.querySelectorAll(
          '.nav-item, .ghost-button, .primary-button, .service-pill, .panel-head h3, .brand-title'
        )).filter((el) => {
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        }).map((el) => {
          const rect = el.getBoundingClientRect();
          return {
            tag: el.tagName,
            text: (el.textContent || '').trim().slice(0, 80),
            width: Math.round(rect.width),
            scrollWidth: el.scrollWidth,
            clientWidth: el.clientWidth,
            overflowing: el.scrollWidth > el.clientWidth + 2,
          };
        }).filter((item) => item.overflowing)
        """
    )


def visible_summary(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => ({
          title: document.querySelector('#page-title')?.textContent?.trim() || '',
          service: document.querySelector('#service-pill')?.textContent?.trim() || '',
          activeView: document.querySelector('.view.active')?.getAttribute('data-view') || '',
          navCount: document.querySelectorAll('.nav-item').length,
          panelCount: document.querySelectorAll('.view.active .panel').length,
          bodyWidth: document.body.scrollWidth,
          viewportWidth: window.innerWidth,
          horizontalOverflow: document.body.scrollWidth > window.innerWidth + 2,
        })
        """
    )


def check_view(page: Page, name: str, viewport_name: str, output_dir: Path) -> dict[str, Any]:
    page.click(f'[data-view-target="{name}"]')
    page.wait_for_function(
        """(name) => document.querySelector('.view.active')?.getAttribute('data-view') === name""",
        arg=name,
    )
    page.wait_for_timeout(300)
    screenshot_path = output_dir / f"hbvstudio_{viewport_name}_{name}.png"
    page.screenshot(path=str(screenshot_path), full_page=True)
    summary = visible_summary(page)
    overflows = overflow_report(page)
    if summary["activeView"] != name:
        raise RuntimeError(f"{viewport_name}/{name}: active view mismatch: {summary['activeView']!r}")
    if summary["horizontalOverflow"]:
        raise RuntimeError(f"{viewport_name}/{name}: body has horizontal overflow: {summary}")
    if overflows:
        raise RuntimeError(f"{viewport_name}/{name}: text overflow detected: {overflows[:5]}")
    return {
        "screenshot": str(screenshot_path),
        "summary": summary,
    }


def check_viewport(page: Page, url: str, name: str, viewport: dict[str, int], output_dir: Path) -> dict[str, Any]:
    page.set_viewport_size(viewport)
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#service-pill", timeout=10000)
    page.wait_for_timeout(800)
    summary = visible_summary(page)
    if summary["navCount"] < 5:
        raise RuntimeError(f"{name}: expected at least 5 nav items, got {summary['navCount']}")
    if not summary["service"]:
        raise RuntimeError(f"{name}: service pill did not render text")
    return {
        "viewport": viewport,
        "views": {view: check_view(page, view, name, output_dir) for view in VIEWS},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HBV-Studio visual smoke checks.")
    parser.add_argument("--url", default="http://127.0.0.1:8765/")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else Path(tempfile.gettempdir()) / "hbvstudio_visual_smoke"
    output_dir.mkdir(parents=True, exist_ok=True)

    console_errors: list[str] = []
    results: dict[str, Any] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        try:
            for name, viewport in VIEWPORTS.items():
                results[name] = check_viewport(page, args.url, name, viewport, output_dir)
        finally:
            browser.close()

    if console_errors:
        raise RuntimeError("Browser console errors:\n" + "\n".join(console_errors[-10:]))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
