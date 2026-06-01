#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for the HBV-Studio task view frontend module."""

from __future__ import annotations

import argparse
import json

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HBV-Studio task view smoke checks.")
    parser.add_argument("--url", default="http://127.0.0.1:8765/")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        console_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        try:
            page.goto(args.url, wait_until="networkidle")
            page.wait_for_function(
                "() => !!window.HBVStudioTaskView && typeof window.taskSummaryLine === 'function'",
                timeout=10000,
            )
            result = page.evaluate(
                """
                () => {
                  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
                    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
                  }[ch]));
                  const shortPath = (value) => String(value || '').replace(/\\\\/g, '/').replace(/^.*\\/([^/]+)$/, '$1');
                  const samePath = (a, b) => String(a || '').replace(/\\\\/g, '/').toLowerCase() === String(b || '').replace(/\\\\/g, '/').toLowerCase();
                  const formatNumber = (value, digits = 3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
                  const helpers = {
                    escapeHtml,
                    shortPath,
                    samePath,
                    profileLabel: (value) => value === 'hourly' ? '小时尺度' : '日尺度',
                    workspaceLabelByPath: () => '沱沱河',
                    formatNumber,
                    formatDurationSeconds: (value) => `${Math.round(Number(value) || 0)} 秒`,
                    optimizationResultLabel: () => '精细搜索结果',
                    optimizationRefineSummary: () => '已执行',
                  };
                  const taskView = window.HBVStudioTaskView;
                  const calibrationTask = {
                    id: 'cal-1',
                    task_type: 'calibration',
                    status: 'running',
                    method: 'mc_screen_de',
                    refine_maxiter: 2,
                    profile: 'daily',
                    progress: {
                      stage: 'global',
                      gen: 2,
                      maxiter: 10,
                      nse_cal: 0.81234,
                      nse_val: 0.74567,
                      obj: 0.12345,
                      elapsed_sec: 65,
                      eta_sec: 120,
                    },
                  };
                  const forwardTask = {
                    id: 'forward-1',
                    task_type: 'forward_sim',
                    status: 'completed',
                    label: '保存并重算 | 源结果 A',
                    config_path: 'F:/workspace/tuotuohe.json',
                    run_path: 'F:/runs/source',
                    result: { run_path: 'F:/runs/manual_new', metrics: { nse_cal: 0.8, nse_val: 0.7 } },
                  };
                  const failedTask = {
                    id: 'failed-1',
                    task_type: 'meteo_import',
                    status: 'failed',
                    output: ['[扫描] F:/data/raw/precipitation', '[失败] 缺少降水文件'],
                  };
                  return {
                    stage: taskView.taskStageLabel('refine'),
                    statusClass: taskView.taskStatusClass('failed'),
                    typeLabel: taskView.taskTypeLabel('forecast_restart'),
                    context: taskView.taskContextSummary(forwardTask, helpers),
                    summary: taskView.taskSummaryLine(calibrationTask, helpers),
                    milestones: taskView.renderTaskMilestones(calibrationTask, helpers),
                    actions: taskView.renderTaskActions(forwardTask, helpers),
                    debug: taskView.taskDebugDetails(failedTask, { lines: 2 }, { escapeHtml, taskDebugOpen: {} }),
                    wrapperSummary: window.taskSummaryLine(calibrationTask),
                  };
                }
                """
            )
        finally:
            browser.close()

    if console_errors:
        raise RuntimeError("Browser console errors:\n" + "\n".join(console_errors[-10:]))

    expectations = {
        "stage": "局部精修",
        "statusClass": "status-fail",
        "typeLabel": "连续状态预报",
    }
    for key, expected in expectations.items():
        if result.get(key) != expected:
            raise RuntimeError(f"{key}: expected {expected!r}, got {result.get(key)!r}")

    contains = {
        "context": ["工作区：沱沱河", "源结果：源结果 A", "新结果：manual_new"],
        "summary": ["精细搜索", "率定纳什效率系数", "预计剩余"],
        "milestones": ["快速筛选", "精细搜索", "局部精修"],
        "actions": ["查看新结果", "打开新结果目录", "查看源结果"],
        "debug": ["运行日志", "缺少降水文件"],
        "wrapperSummary": ["精细搜索", "率定纳什效率系数"],
    }
    for key, expected_parts in contains.items():
        value = str(result.get(key) or "")
        missing = [part for part in expected_parts if part not in value]
        if missing:
            raise RuntimeError(f"{key}: missing {missing!r} in {value!r}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
