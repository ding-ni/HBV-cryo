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
            for (const name of ["filterTasks", "hasRunningTasks", "newlyCompletedTask", "newlyFinishedTaskIds", "renderTaskCard", "renderTaskFilterToolbar", "renderTaskList", "taskById", "taskListDataState", "taskListQueryState", "taskListState", "taskProgressChartData"]) {
              if (typeof taskView?.[name] !== "function") {
                throw new Error(`missing task view export: ${name}`);
              }
            }
            const taskQuery = taskView.taskListQueryState();
            if (taskQuery.tasksPath !== "/api/tasks") {
              throw new Error(`task list query mismatch: ${JSON.stringify(taskQuery)}`);
            }
            const normalizedTasks = taskView.taskListDataState([{ id: "task-1" }]);
            if (normalizedTasks.tasks[0].id !== "task-1" || normalizedTasks.statePatch.tasks !== normalizedTasks.tasks) {
              throw new Error(`task list data state mismatch: ${JSON.stringify(normalizedTasks)}`);
            }
            const emptyTasks = taskView.taskListDataState({ bad: true });
            if (emptyTasks.tasks.length !== 0 || emptyTasks.statePatch.tasks.length !== 0) {
              throw new Error(`invalid task list data should normalize to empty array: ${JSON.stringify(emptyTasks)}`);
            }

            const taskLookupItems = [{ id: 7, label: "numeric" }, { id: "task-8", label: "string" }];
            if (taskView.taskById(taskLookupItems, "7")?.label !== "numeric") {
              throw new Error("taskById should match numeric ids by string value");
            }
            if (taskView.taskById(taskLookupItems, "task-8")?.label !== "string") {
              throw new Error("taskById should match string ids");
            }
            if (taskView.taskById(taskLookupItems, "missing") !== null || taskView.taskById({ bad: true }, "7") !== null) {
              throw new Error("taskById should return null for missing or invalid task lists");
            }
            if (!taskView.hasRunningTasks([{ status: "completed" }, { status: "running" }])) {
              throw new Error("hasRunningTasks should detect running tasks");
            }
            if (taskView.hasRunningTasks([{ status: "completed" }, { status: "failed" }]) || taskView.hasRunningTasks({ bad: true })) {
              throw new Error("hasRunningTasks should be false without running tasks");
            }

            const taskTransitions = [
              { id: "manual", task_type: "manual_start", status: "completed" },
              { id: "calibration", task_type: "calibration", status: "completed" },
              { id: "forecast", task_type: "forecast_restart", status: "failed" },
              { id: "running", task_type: "calibration", status: "running" },
              { id: "new-complete", task_type: "manual_start", status: "completed" },
            ];
            const previousTaskMap = new Map([
              ["manual", { id: "manual", status: "running" }],
              ["calibration", { id: "calibration", status: "running" }],
              ["forecast", { id: "forecast", status: "running" }],
              ["running", { id: "running", status: "running" }],
            ]);
            const finishedIds = taskView.newlyFinishedTaskIds(taskTransitions, previousTaskMap);
            if (finishedIds.join("|") !== "manual|calibration|forecast") {
              throw new Error(`newly finished task ids mismatch: ${finishedIds.join("|")}`);
            }
            const newlyCompletedCalibration = taskView.newlyCompletedTask(taskTransitions, previousTaskMap, "calibration");
            if (newlyCompletedCalibration?.id !== "calibration") {
              throw new Error(`newly completed calibration mismatch: ${newlyCompletedCalibration?.id}`);
            }
            const newlyCompletedForecast = taskView.newlyCompletedTask(taskTransitions, previousTaskMap, "forecast_restart");
            if (newlyCompletedForecast !== null) {
              throw new Error("failed forecast task should not count as newly completed");
            }
            const previousTaskObject = {
              manual: { id: "manual", status: "running" },
              "new-complete": { id: "new-complete", status: "completed" },
            };
            const newlyCompletedManual = taskView.newlyCompletedTask(taskTransitions, previousTaskObject, "manual_start");
            if (newlyCompletedManual?.id !== "manual") {
              throw new Error(`plain-object previous task lookup mismatch: ${newlyCompletedManual?.id}`);
            }
            const previousTaskArray = [{ id: "manual", status: "running" }];
            const arraySnapshotManual = taskView.newlyCompletedTask(taskTransitions, previousTaskArray, "manual_start");
            if (arraySnapshotManual?.id !== "manual") {
              throw new Error(`array previous task lookup mismatch: ${arraySnapshotManual?.id}`);
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

            const toolbar = taskView.renderTaskFilterToolbar({
              tasks,
              workspaceMode: "all",
              workspacePath: "C:/ws/A.json",
              status: "failed",
              type: "simulate",
            }, {
              ...helpers,
              workspaceLabelByPath() { return "流域<A>"; },
            });
            for (const attr of ["data-task-filter-workspace", "data-task-filter-status", "data-task-filter-type"]) {
              if (!toolbar.toolbarHtml.includes(attr)) throw new Error(`missing toolbar action ${attr}`);
            }
            if (!toolbar.toolbarHtml.includes("当前工作区：流域&lt;A&gt;")) {
              throw new Error(`workspace label should be escaped: ${toolbar.toolbarHtml}`);
            }
            if ((toolbar.toolbarHtml.match(/class="phase-chip active"/g) || []).length !== 3) {
              throw new Error(`expected three active chips: ${toolbar.toolbarHtml}`);
            }
            if (toolbar.hintText !== "当前显示 1/4 个任务 · 运行中 0 · 失败 1 · 范围：全部工作区" || toolbar.hintClassName !== "hint-box status-warn") {
              throw new Error(`unexpected toolbar hint: ${toolbar.hintClassName} ${toolbar.hintText}`);
            }
            const toolbarDom = Object.fromEntries(toolbar.domUpdates.map(update => [update.selector, update]));
            if (toolbarDom["#task-filter-toolbar"].html !== toolbar.toolbarHtml ||
                toolbarDom["#task-filter-hint"].text !== "当前显示 1/4 个任务 · 运行中 0 · 失败 1 · 范围：全部工作区" ||
                toolbarDom["#task-filter-hint"].className !== "hint-box status-warn") {
              throw new Error(`unexpected toolbar DOM updates: ${JSON.stringify(toolbarDom)}`);
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
            const listState = taskView.taskListState(currentActive, helpers);
            const listDom = Object.fromEntries(listState.domUpdates.map(update => [update.selector, update]));
            if (listState.html !== html || listDom["#task-list"].html !== html) {
              throw new Error(`unexpected task list DOM updates: ${JSON.stringify(listState)}`);
            }

            if (taskView.taskProgressChartData([{ gen: 1 }]) !== null) {
              throw new Error("single progress row should not create a chart");
            }
            const chart = taskView.taskProgressChartData([
              { gen: 1, nse_cal: 0.5, nse_val: 0.4, obj: 1.2 },
              { gen: 2, nse_cal: "bad", nse_val: 0.45, obj: null },
              { gen: "skip", nse_cal: 0.9, nse_val: 0.9, obj: 0.2 },
              { gen: 3, nse_cal: 0.7, nse_val: undefined, obj: 0.8 },
            ], "精细搜索", {
              colors: { qSim: "#111111", qRain: "#222222", residual: "#333333" },
            });
            if (!chart || chart.traces.length !== 3) throw new Error(`unexpected chart payload: ${JSON.stringify(chart)}`);
            if (chart.traces[0].x.join(",") !== "1,2,3") throw new Error(`unexpected chart x values: ${chart.traces[0].x}`);
            if (chart.traces[0].y[1] !== null || chart.traces[1].y[2] !== null || chart.traces[2].y[1] !== 0) {
              throw new Error(`unexpected metric coercion in chart data: ${JSON.stringify(chart.traces)}`);
            }
            if (chart.traces[0].line.color !== "#111111" || chart.traces[1].line.color !== "#222222" || chart.traces[2].line.color !== "#333333") {
              throw new Error(`chart colors were not applied: ${JSON.stringify(chart.traces.map(trace => trace.line))}`);
            }
            if (chart.layout.title.text !== "精细搜索" || chart.layout.yaxis2.overlaying !== "y") {
              throw new Error(`unexpected chart layout: ${JSON.stringify(chart.layout)}`);
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
