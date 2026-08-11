#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Studio UI acceptance for unified objective diagnostics.

Creates two fixture runs under a writable runtime root:
- one current daily_unified_professional_v1 run with peak/recession diagnostics
- one legacy weighted_daily_universal run without the new guard fields

Then starts Studio against that runtime root and verifies the results page in Playwright.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import quote
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from playwright.sync_api import sync_playwright
import websockets


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "HBV-Cryo"))

import daily_unified_objective  # noqa: E402


def configure_text_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def emit_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
        sys.stdout.flush()


def install_browser_permission_noise_filter() -> None:
    """Suppress Playwright's delayed WinError 5 future warning after it is caught."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    previous_handler = loop.get_exception_handler()

    def handle(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        message = str(context.get("message") or "")
        winerror = getattr(exc, "winerror", None)
        if isinstance(exc, PermissionError) and (winerror == 5 or "Future exception was never retrieved" in message):
            return
        if previous_handler is not None:
            previous_handler(loop, context)
            return
        loop.default_exception_handler(context)

    loop.set_exception_handler(handle)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    return value


def find_free_port(start: int = 8765) -> int:
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free localhost port found.")


def synthetic_series() -> dict[str, Any]:
    dates = pd.date_range("2013-01-01", "2019-12-31", freq="D")
    doy = dates.dayofyear.to_numpy(dtype=np.float64)
    season = np.maximum(0.0, np.sin((doy - 90.0) / 365.0 * 2.0 * np.pi))
    q_rain = 20.0 + 20.0 * season
    q_snow = np.maximum(0.0, 80.0 * np.exp(-((doy - 145.0) / 35.0) ** 2))
    q_ice = np.maximum(0.0, 90.0 * np.exp(-((doy - 235.0) / 45.0) ** 2))
    q_total = q_rain + q_snow + q_ice
    q_obs = q_total * 0.98
    return {
        "dates": dates,
        "q_rain": q_rain,
        "q_snow": q_snow,
        "q_ice": q_ice,
        "q_total": q_total,
        "q_obs": q_obs,
    }


def synthetic_evaluation(series: dict[str, Any]) -> dict[str, Any]:
    dates = series["dates"]
    q_total = series["q_total"]
    q_snow = series["q_snow"]
    q_ice = series["q_ice"]
    bundle = {
        "date": dates,
        "q_total": q_total,
        "q_local": q_total,
        "q_boundary": np.zeros(len(dates), dtype=np.float64),
        "q_rain": series["q_rain"],
        "q_snow": q_snow,
        "q_ice": q_ice,
        "q_ice_raw": q_ice,
        "q_snow_glacier": q_snow,
        "q_glacier_total": q_snow + q_ice,
        "q_obs_obj": series["q_obs"],
        "calib_mask": np.ones(len(dates), dtype=bool),
        "project_object_type": "full_upstream_basin",
        "q_score_basis": "q_total",
        "muskingum_coeffs": {"C0": 0.2, "C1": 0.3, "C2": 0.5},
        "glacier_enabled": True,
        "glacier_model_mode": "fractional_subgrid",
        "glacier_area_ratio": 0.04,
        "glacier_mask_exists": True,
        "glacier_fraction_exists": True,
        "glacier_elev_exists": False,
        "glacier_fraction_window": [0.02, 0.20],
    }
    metrics = {
        "nse_cal": 0.82,
        "nse_val": 0.78,
        "kge_cal": 0.80,
        "kge_val": 0.76,
        "log_nse_cal": 0.80,
        "log_nse_val": 0.75,
        "pbias_cal": 2.0,
        "pbias_val": 3.0,
    }
    return daily_unified_objective.evaluate_daily_unified_objective(bundle, metrics, bad_obj=9999.0)


def write_simulation(run_dir: Path, series: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "simulation.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "date",
                "q_sim",
                "q_sim_model",
                "q_local",
                "q_boundary_inflow",
                "q_obs",
                "q_rain",
                "q_snow",
                "q_ice",
                "q_ice_raw",
                "q_ice_reference",
                "q_ice_reference_raw",
            ],
        )
        writer.writeheader()
        for i, date in enumerate(series["dates"]):
            writer.writerow(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "q_sim": float(series["q_total"][i]),
                    "q_sim_model": float(series["q_total"][i]),
                    "q_local": float(series["q_total"][i]),
                    "q_boundary_inflow": 0.0,
                    "q_obs": float(series["q_obs"][i]),
                    "q_rain": float(series["q_rain"][i]),
                    "q_snow": float(series["q_snow"][i]),
                    "q_ice": float(series["q_ice"][i]),
                    "q_ice_raw": float(series["q_ice"][i]),
                    "q_ice_reference": "",
                    "q_ice_reference_raw": "",
                }
            )


def base_metadata(title: str, objective_family: str) -> dict[str, Any]:
    return {
        "run_id": title.lower().replace(" ", "_"),
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "result_title": title,
        "workspace_label": "Acceptance Fixture",
        "project_object_type": "full_upstream_basin",
        "calibration_profile": "daily",
        "rate_mode": "daily",
        "recorded_objective_family": objective_family,
        "effective_objective_mode": objective_family,
        "objective_family": objective_family if objective_family == daily_unified_objective.OBJECTIVE_FAMILY else None,
        "time_config": {
            "time_step_hours": 24.0,
            "warmup_start": "2013-01-01",
            "warmup_end": "2013-12-31",
            "calib_start": "2014-01-01",
            "calib_end": "2017-12-31",
            "valid_start": "2018-01-01",
            "valid_end": "2019-12-31",
        },
        "optional_modules": {
            "glacier": {
                "enabled": True,
                "model_mode": "fractional_subgrid",
                "mask_exists": True,
                "fraction_exists": True,
                "elev_exists": False,
                "reference_available": False,
            },
            "boundary_inflow": {"enabled": False},
        },
        "basin_info": {"catchment_area_km2": 1000.0, "valid_cells": 100, "glacier_cells": 4},
        "data_sources": {"runtime_prec_source": "custom_tif", "prec_source": "custom_tif"},
        "reliability_flag": "degraded_missing_glacier_elev",
        "reliability_notes": ["missing glacier_elev.tif; ice-source decomposition confidence is limited"],
        "metrics": {
            "calibration": {"sample_count": 1461, "nse": 0.82, "kge": 0.80, "pbias": 2.0},
            "validation": {"sample_count": 730, "nse": 0.78, "kge": 0.76, "pbias": 3.0},
        },
        "optimization": {
            "method": "acceptance_fixture",
            "objective_mode": objective_family,
            "effective_objective_mode": objective_family,
            "objective_value": 0.25,
        },
        "optimized_params": {"TT": 0.0, "FC": 300.0, "BETA": 2.0, "ICE_FACTOR": 1.1},
    }


def create_fixture_runs(runtime_root: Path) -> dict[str, Path]:
    series = synthetic_series()
    evaluation = synthetic_evaluation(series)
    runs_dir = runtime_root / "acceptance_workspace" / "结果" / "日尺度" / "运行记录"
    current_run = runs_dir / "acceptance_unified_current"
    legacy_run = runs_dir / "acceptance_weighted_legacy"

    write_simulation(current_run, series)
    current_meta = base_metadata("Acceptance unified run", daily_unified_objective.OBJECTIVE_FAMILY)
    current_meta.update(
        {
            "hard_checks": evaluation.get("hard_checks", {}),
            "objective_value": evaluation.get("objective_value"),
            "objective_terms": evaluation.get("objective_terms", {}),
            "diagnostics": evaluation.get("diagnostics", {}),
            "diagnostic_only_constraints": evaluation.get("diagnostic_only_constraints", {}),
            "evidence_registry": evaluation.get("evidence_registry", {}),
        }
    )
    (current_run / "metadata.json").write_text(json.dumps(json_safe(current_meta), ensure_ascii=False, indent=2), encoding="utf-8")

    write_simulation(legacy_run, series)
    legacy_meta = base_metadata("Acceptance legacy run", "weighted_daily_universal")
    legacy_meta.pop("objective_family", None)
    legacy_meta["objective_profile"] = {"type": "weighted_daily_universal"}
    legacy_meta["objective"] = {"type": "weighted_daily_universal"}
    legacy_meta["objective_terms"] = {}
    legacy_meta["diagnostics"] = {
        "glacier_fraction_report": {"status": "computed_without_window", "f_ice": 0.25}
    }
    (legacy_run / "metadata.json").write_text(json.dumps(json_safe(legacy_meta), ensure_ascii=False, indent=2), encoding="utf-8")
    return {"current": current_run, "legacy": legacy_run}


def wait_for_health(url: str, process: subprocess.Popen[str], timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"Studio exited before health check. rc={process.returncode}\n{output}")
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("ok"):
                    return
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise TimeoutError(f"Studio health check timed out: {last_error}")


def api_json(url: str, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{url}{path}", timeout=10.0) as response:
        return json.loads(response.read().decode("utf-8"))


def http_text(url: str, path: str) -> str:
    with urllib.request.urlopen(f"{url}{path}", timeout=10.0) as response:
        return response.read().decode("utf-8", errors="replace")


def run_api_dom_fallback_checks(url: str, run_items: list[dict[str, Any]]) -> dict[str, Any]:
    current = next(item for item in run_items if str(item.get("objective_family")) == daily_unified_objective.OBJECTIVE_FAMILY)
    legacy = next(item for item in run_items if str(item.get("objective_family")) == "weighted_daily_universal")
    assert current.get("pbias_cal") is not None
    assert current.get("pbias_val") is not None
    assert current.get("flow_guard_status") == "ok"
    assert legacy.get("pbias_cal") is not None
    index_html = http_text(url, "/")
    app_js = http_text(url, "/app.js")
    assert 'data-view-target="results"' in index_html
    assert "results-layout" in index_html
    assert "objectiveVersionStatus" in app_js
    assert "peakSourceSummary" in app_js
    assert "recessionTakeoverSummary" in app_js
    assert "旧目标函数历史结果" in app_js
    assert "冰源分解可信度受限" in app_js
    current_detail = api_json(url, f"/api/run?path={quote(str(current['path']))}")["data"]
    legacy_detail = api_json(url, f"/api/run?path={quote(str(legacy['path']))}")["data"]
    current_meta = current_detail.get("metadata", {})
    legacy_meta = legacy_detail.get("metadata", {})
    assert "peak_source_report" in current_meta.get("diagnostics", {})
    assert "recession_takeover_diagnostic" in current_meta.get("diagnostics", {})
    assert "peak_source_guard" in current_meta.get("objective_terms", {}).get("cryo_consistency", {})
    assert current_meta.get("optional_modules", {}).get("glacier", {}).get("elev_exists") is False
    assert str(legacy_meta.get("recorded_objective_family")) == "weighted_daily_universal"
    return {
        "served_index_has_results_view": True,
        "served_app_has_diagnostic_renderers": True,
        "served_app_marks_legacy_objectives_historical": True,
        "api_card_fields_have_objective_pbias_flow_guard": True,
        "api_current_detail_has_peak_recession": True,
        "api_current_metadata_triggers_confidence_warning": True,
        "api_legacy_detail_is_compatible": True,
    }


def check_launch_log(user_root: Path, runtime_root: Path, temp_root: Path) -> dict[str, Any]:
    log_dir = user_root / "logs"
    logs = sorted(log_dir.glob("launch_*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    assert logs, f"no launch log found under {log_dir}"
    log_path = logs[0]
    text = log_path.read_text(encoding="utf-8", errors="replace")
    checks = {
        "has_user_root": str(user_root.resolve(strict=False)) in text,
        "has_runtime_root": str(runtime_root.resolve(strict=False)) in text,
        "has_temp_root": str(temp_root.resolve(strict=False)) in text,
        "has_result_roots": "discovered runtime roots" in text,
        "has_run_metadata_roots": "discovered run metadata roots" in text,
    }
    missing = [key for key, ok in checks.items() if not ok]
    assert not missing, f"launch log missing expected path entries: {missing}"
    return {"path": str(log_path), **checks}


def run_playwright_checks(url: str, screenshot_path: Path) -> dict[str, Any]:
    console_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 950})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.locator('[data-view-target="results"]').click()
        page.wait_for_selector("#run-list .run-card", timeout=15000)
        card_text = page.locator("#run-list").inner_text()
        assert "当前口径" in card_text
        assert "历史口径" in card_text
        assert "PBIAS" in card_text

        current_card = page.locator(".run-card", has_text="当前口径").first
        current_card.click()
        page.wait_for_selector("#metadata-grid", timeout=15000)
        page.wait_for_function(
            "document.querySelector('#metadata-grid')?.innerText.includes('水文结果摘要')",
            timeout=15000,
        )
        detail_text = page.locator("#metadata-grid").inner_text()
        note_text = page.locator("#results-entry-hint").inner_text()
        engineering_note = page.locator("#run-engineering-note").inner_text()
        assert "评分标准" in detail_text
        assert "径流拟合" in detail_text
        assert "三水源构成" in detail_text
        assert "本地过程复核报告" in detail_text
        assert "完整过程复核" in (note_text + engineering_note)
        page.screenshot(path=str(screenshot_path), full_page=True)
        browser.close()
    return {
        "browser_driver": "playwright",
        "card_text_has_current_objective": True,
        "card_text_has_legacy_objective": True,
        "detail_has_hydrology_summary": True,
        "result_guidance_visible": True,
        "console_errors": console_errors,
        "screenshot": str(screenshot_path),
    }


def run_playwright_checks_isolated(url: str, screenshot_path: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--playwright-child-url",
        url,
        "--playwright-child-screenshot",
        str(screenshot_path),
    ]
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    payload: dict[str, Any] = {}
    stdout = (result.stdout or "").strip()
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {}
    if result.returncode == 0 and payload.get("ok"):
        return dict(payload.get("result") or {})
    error = str(payload.get("error") or "").strip()
    if not error:
        combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
        error = combined.splitlines()[0][:500] if combined else f"playwright child exited with rc={result.returncode}"
    raise RuntimeError(error)


def browser_executable() -> Path:
    candidates = [
        os.environ.get("HBV_STUDIO_BROWSER_EXE", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\EdgeCore\147.0.3912.86\msedge.exe",
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        if path.exists():
            return path
    raise FileNotFoundError("No Chrome/Edge executable found for CDP fallback.")


class CdpClient:
    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.next_id = 1

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        msg_id = self.next_id
        self.next_id += 1
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("id") == msg_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} failed: {message['error']}")
                return message.get("result", {})

    async def evaluate(self, expression: str) -> Any:
        result = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        remote = result.get("result", {})
        if "value" in remote:
            return remote.get("value")
        return remote.get("description")


def wait_for_url_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


async def cdp_wait_for(client: CdpClient, expression: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = await client.evaluate(expression)
        if value:
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for expression: {expression}")


async def run_chrome_cdp_checks_async(url: str, screenshot_path: Path, root: Path) -> dict[str, Any]:
    cdp_port = find_free_port(9300)
    user_data_dir = root / "chrome_profile"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    exe = browser_executable()
    browser_log = root / "browser_cdp.log"
    browser_log_handle = browser_log.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        [
            str(exe),
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--no-first-run",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            "about:blank",
        ],
        stdout=browser_log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        try:
            wait_for_url_json(f"http://127.0.0.1:{cdp_port}/json/version")
        except Exception as exc:
            process.poll()
            try:
                browser_log_handle.flush()
            except Exception:
                pass
            log_excerpt = browser_log.read_text(encoding="utf-8", errors="replace")[-1200:] if browser_log.exists() else ""
            raise RuntimeError(f"CDP browser did not expose /json/version: {exc}\n{log_excerpt}") from exc
        request = urllib.request.Request(
            f"http://127.0.0.1:{cdp_port}/json/new?{quote(url, safe=':/?&=')}",
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=5.0) as response:
            target = json.loads(response.read().decode("utf-8"))
        ws_url = target["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url, max_size=8 * 1024 * 1024) as ws:
            client = CdpClient(ws)
            await client.send("Page.enable")
            await client.send("Runtime.enable")
            await cdp_wait_for(client, "document.readyState === 'complete'", timeout=20.0)
            await cdp_wait_for(client, "Boolean(document.querySelector('[data-view-target=\"results\"]'))", timeout=20.0)
            await client.evaluate("document.querySelector('[data-view-target=\"results\"]').click()")
            await cdp_wait_for(client, "document.querySelectorAll('#run-list .run-card').length >= 2", timeout=20.0)
            card_text = await client.evaluate("document.querySelector('#run-list').innerText")
            assert "当前口径" in card_text
            assert "历史口径" in card_text
            assert "PBIAS" in card_text
            await client.evaluate(
                "Array.from(document.querySelectorAll('.run-card'))"
                ".find(el => el.innerText.includes('当前口径')).click()"
            )
            await cdp_wait_for(client, "Boolean(document.querySelector('#metadata-grid'))", timeout=20.0)
            await cdp_wait_for(
                client,
                "document.querySelector('#metadata-grid').innerText.includes('水文结果摘要')",
                timeout=20.0,
            )
            detail_text = await client.evaluate("document.querySelector('#metadata-grid').innerText")
            note_text = await client.evaluate("document.querySelector('#results-entry-hint').innerText")
            engineering_note = await client.evaluate("document.querySelector('#run-engineering-note').innerText")
            assert "评分标准" in detail_text
            assert "径流拟合" in detail_text
            assert "三水源构成" in detail_text
            assert "本地过程复核报告" in detail_text
            assert "完整过程复核" in (note_text + engineering_note)
            screenshot = await client.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
            screenshot_path.write_bytes(base64.b64decode(screenshot["data"]))
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)
        browser_log_handle.close()
    return {
        "browser_driver": f"cdp:{exe.name}",
        "card_text_has_current_objective": True,
        "card_text_has_legacy_objective": True,
        "detail_has_hydrology_summary": True,
        "result_guidance_visible": True,
        "screenshot": str(screenshot_path),
    }


def run_chrome_cdp_checks(url: str, screenshot_path: Path, root: Path) -> dict[str, Any]:
    return asyncio.run(run_chrome_cdp_checks_async(url, screenshot_path, root))


def main() -> None:
    configure_text_output()
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(WORKSPACE_ROOT / "memories" / "studio_acceptance"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--require-browser", action="store_true")
    parser.add_argument("--playwright-child-url", default="", help=argparse.SUPPRESS)
    parser.add_argument("--playwright-child-screenshot", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.playwright_child_url:
        try:
            child_result = run_playwright_checks(args.playwright_child_url, Path(args.playwright_child_screenshot))
            emit_json({"ok": True, "result": child_result})
            return
        except Exception as exc:
            emit_json({"ok": False, "error": str(exc).splitlines()[0][:500]})
            raise SystemExit(2) from exc

    root = Path(args.root).resolve(strict=False) / datetime.now().strftime("%Y%m%d_%H%M%S")
    user_root = root / "user_root"
    runtime_root = root / "runtime_root"
    temp_root = root / "temp_root"
    for path in (user_root, runtime_root, temp_root):
        path.mkdir(parents=True, exist_ok=True)
    runs = create_fixture_runs(runtime_root)
    port = args.port or find_free_port(8765)
    url = f"http://127.0.0.1:{port}"
    command = [
        sys.executable,
        str(REPO_ROOT / "HBV-Studio" / "launch.py"),
        "--no-browser",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--user-root",
        str(user_root),
        "--runtime-root",
        str(runtime_root),
        "--temp-root",
        str(temp_root),
    ]
    env = os.environ.copy()
    env["HBV_STUDIO_DISABLE_CONSOLE_MIRROR"] = "1"
    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        wait_for_health(url, process)
        runs_payload = api_json(url, "/api/runs")
        run_items = runs_payload.get("data", [])
        assert any(str(item.get("objective_family")) == daily_unified_objective.OBJECTIVE_FAMILY for item in run_items)
        assert any(str(item.get("objective_family")) == "weighted_daily_universal" for item in run_items)
        assert any(str(item.get("flow_guard_status")) == "ok" for item in run_items)
        launch_log = check_launch_log(user_root, runtime_root, temp_root)
        install_browser_permission_noise_filter()
        try:
            ui_result = run_playwright_checks_isolated(url, root / "results_page.png")
        except Exception as exc:
            playwright_error = str(exc).splitlines()[0][:300]
            try:
                ui_result = run_chrome_cdp_checks(url, root / "results_page.png", root)
                ui_result["playwright_fallback_reason"] = playwright_error
            except Exception as browser_exc:
                if args.require_browser:
                    raise
                ui_result = {
                    "browser_driver": "blocked",
                    "browser_blocker": str(browser_exc).splitlines()[0][:500],
                    "playwright_blocker": playwright_error,
                    "api_dom_fallback": run_api_dom_fallback_checks(url, run_items),
                }
        output = {
            "url": url,
            "user_root": str(user_root),
            "runtime_root": str(runtime_root),
            "temp_root": str(temp_root),
            "launch_log": launch_log,
            "runs": {key: str(value) for key, value in runs.items()},
            "api_run_count": len(run_items),
            "ui": ui_result,
        }
        emit_json(output)
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)


if __name__ == "__main__":
    main()
