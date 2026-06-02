import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendTaskViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_task_view_filters_and_renders_task_cards(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/taskView.js", "utf8"), context);

            const taskView = context.window.HBVStudioTaskView;
            for (const name of ["filterTasks", "renderTaskCard", "renderTaskList"]) {
              if (typeof taskView?.[name] !== "function") {
                throw new Error(`missing task view export: ${name}`);
              }
            }

            const helpers = {
              escapeHtml(value) {
                return String(value ?? "").replace(/[&<>"']/g, ch => ({
                  "&": "&amp;",
                  "<": "&lt;",
                  ">": "&gt;",
                  "\"": "&quot;",
                  "'": "&#39;",
                }[ch]));
              },
              formatDateTime(value) { return `时间:${value || ""}`; },
              formatDurationSeconds(value) { return `${Number(value || 0)} 秒`; },
              formatNumber(value, digits = 4) {
                return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
              },
              optimizationRefineSummary() { return "未执行"; },
              optimizationResultLabel() { return "精细搜索结果"; },
              profileLabel(value) { return value === "daily" ? "日尺度" : String(value || ""); },
              samePath(a, b) { return String(a || "").toLowerCase() === String(b || "").toLowerCase(); },
              shortPath(value) { return String(value || "").split(/[\\/]/).pop() || ""; },
              taskDebugOpen: { "task-cal": true },
              workspaceLabelByPath(path) { return path === "C:/ws/A.json" ? "流域A" : "未命名工作区"; },
            };

            const tasks = [
              {
                id: "task-cal",
                task_type: "calibration",
                status: "running",
                label: "测试<率定>|正式方案",
                config_path: "C:/ws/A.json",
                profile: "daily",
                method: "mc_screen_de",
                updated_at: "2026-06-02T08:00:00",
                progress: {
                  stage: "global",
                  gen: 2,
                  maxiter: 10,
                  nse_cal: 0.81,
                  nse_val: 0.72,
                  obj: 0.64,
                  elapsed_sec: 12,
                  eta_sec: 30,
                  stages: {
                    mc: { history: [{ gen: 1 }, { gen: 2 }] },
                    global: { history: [{ gen: 1 }, { gen: 2 }] },
                  },
                },
                output: ["[运行] 正在计算"],
              },
              { id: "task-prep", task_type: "data_prep", status: "completed", config_path: "C:/ws/A.json", label: "资料准备" },
              { id: "task-forecast", task_type: "forecast_restart", status: "failed", config_path: "C:/ws/B.json", label: "预报失败", output: ["缺少未来气象"] },
              { id: "task-self", task_type: "self_check", status: "running", label: "系统自检" },
            ];

            const currentActive = taskView.filterTasks(tasks, {
              workspaceMode: "current",
              workspacePath: "c:/WS/a.JSON",
              status: "active",
              type: "all",
            }, helpers);
            if (currentActive.length !== 1 || currentActive[0].id !== "task-cal") {
              throw new Error(`unexpected current active tasks: ${currentActive.map(t => t.id).join(",")}`);
            }

            const failedForecasts = taskView.filterTasks(tasks, {
              workspaceMode: "all",
              status: "failed",
              type: "simulate",
            }, helpers);
            if (failedForecasts.length !== 1 || failedForecasts[0].id !== "task-forecast") {
              throw new Error("failed simulate task filter did not match forecast task");
            }

            const html = taskView.renderTaskList(currentActive, helpers);
            if (!html.includes("task-card task-running")) throw new Error(html);
            if (!html.includes("测试&lt;率定&gt;")) throw new Error("task title should be escaped");
            if (!html.includes("工作区：流域A")) throw new Error("workspace context missing");
            if (!html.includes("当前阶段：精细搜索")) throw new Error("progress note missing");
            if (!html.includes('data-task-progress-stage="mc"') || !html.includes('data-task-progress-stage="global"')) {
              throw new Error("progress chart placeholders missing");
            }
            if (!html.includes("运行日志（最近 1 行）") || !html.includes("data-copy-task-log")) {
              throw new Error("debug log controls missing");
            }
            if (!taskView.renderTaskList([], helpers).includes("当前筛选下暂无任务")) {
              throw new Error("empty task hint missing");
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
