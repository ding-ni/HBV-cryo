import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendForecastViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_forecast_time_helpers_handle_daily_and_hourly_runs(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            for (const name of ["forecastInputType", "forecastSuggestedStart", "forecastTimeComparable", "formatForecastInputTime", "parseForecastTime"]) {
              if (typeof view?.[name] !== "function") throw new Error(`missing forecast time export: ${name}`);
            }

            const dailyRun = {
              time_step_hours: 24,
              state_snapshot_time: "2026-01-10",
            };
            if (view.forecastInputType(dailyRun) !== "date") throw new Error("daily run should use date input");
            if (view.forecastSuggestedStart(dailyRun) !== "2026-01-11") {
              throw new Error(`daily suggested start wrong: ${view.forecastSuggestedStart(dailyRun)}`);
            }
            if (view.forecastTimeComparable("2026-01-11 00:00", dailyRun) !== "2026-01-11") {
              throw new Error("daily comparable should normalize to date");
            }

            const hourlyRun = {
              time_config: { time_step_hours: 1, valid_end: "2026-01-10T23:00" },
            };
            if (view.forecastInputType(hourlyRun) !== "datetime-local") throw new Error("hourly run should use datetime-local input");
            if (view.forecastSuggestedStart(hourlyRun) !== "2026-01-11T00:00") {
              throw new Error(`hourly suggested start wrong: ${view.forecastSuggestedStart(hourlyRun)}`);
            }
            if (view.forecastTimeComparable("2026-01-11 00:00", hourlyRun) !== "2026-01-11T00:00") {
              throw new Error("hourly comparable should normalize space separator");
            }

            if (view.parseForecastTime("not-a-date") !== null) throw new Error("invalid dates should return null");
            if (view.formatForecastInputTime(null, 24) !== "") throw new Error("missing date should format as empty string");
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

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_forecast_source_candidate_and_readiness_helpers(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            for (const name of ["forecastCandidateRuns", "forecastRunReady", "forecastRunReadinessText"]) {
              if (typeof view?.[name] !== "function") throw new Error(`missing source readiness export: ${name}`);
            }

            const runs = [
              { id: "empty-path", path: "", kind: "calibration", studio_compatible: true },
              { id: "cal-ready", path: "C:/runs/cal", kind: "calibration", studio_compatible: true },
              { id: "manual-ready", path: "C:/runs/manual", kind: "manual_result", forecast_source_ready: true, studio_compatible: false },
              { id: "forecast-missing-param", path: "C:/runs/forecast", kind: "forecast_restart", forecast_source_ready: false, optimized_params_available: false },
              { id: "legacy", path: "C:/runs/legacy", kind: "legacy", studio_compatible: true },
              { id: "starter-missing-state", path: "C:/runs/starter", kind: "manual_starter", state_snapshot_available: false },
            ];

            const candidates = view.forecastCandidateRuns(runs, { runTypeValue: run => run.kind });
            const ids = candidates.map(run => run.id).join(",");
            if (ids !== "cal-ready,manual-ready,forecast-missing-param,starter-missing-state") {
              throw new Error(`unexpected forecast candidates: ${ids}`);
            }

            if (!view.forecastRunReady(runs[1])) throw new Error("studio-compatible calibration result should be ready");
            if (!view.forecastRunReady(runs[2])) throw new Error("explicit forecast_source_ready should make result ready");
            if (view.forecastRunReady(runs[3])) throw new Error("explicit false readiness should block result");
            if (view.forecastRunReadinessText(null) !== "未选择源结果") throw new Error("empty readiness text wrong");
            if (view.forecastRunReadinessText(runs[1]) !== "可起报") throw new Error("ready text wrong");
            if (view.forecastRunReadinessText(runs[3]) !== "缺少率定参数") throw new Error("missing parameter text wrong");
            if (view.forecastRunReadinessText(runs[5]) !== "缺少起报状态") throw new Error("missing state text wrong");
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

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_forecast_archive_summary_and_items(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            if (!view) throw new Error("forecast view module was not exported");
            const archive = {
              manifest_path: "C:/runs/forecast/manifest.json",
              manifest: {
                expected_steps: 4,
                forecast_start: "2026-01-01",
                forecast_end: "2026-01-04",
                variables: {
                  prec: {
                    archived_files: 4,
                    first_time: "2026-01-01",
                    last_time: "2026-01-04",
                    archive_dir: "C:/runs/forecast/prec",
                  },
                  temp: {
                    file_count: 3,
                    out_of_window_files: 1,
                  },
                },
              },
            };
            const items = view.forecastArchiveVariableItems(archive, {
              shortPath: value => String(value).split("/").pop(),
            });
            if (items.length !== 2) throw new Error(`unexpected item count: ${items.length}`);
            if (items[0].label !== "降水" || items[0].value !== "4/4 个时步") {
              throw new Error(`unexpected first item: ${JSON.stringify(items[0])}`);
            }
            if (!items[1].detail.includes("窗口外 1 个文件未纳入")) {
              throw new Error(`unexpected temp detail: ${items[1].detail}`);
            }
            const summary = view.forecastArchiveSummaryText(archive);
            if (summary !== "已归档 4 个预报时步") throw new Error(`unexpected summary: ${summary}`);
            const detail = view.forecastArchiveDetailText(archive);
            if (!detail.includes("输入归档清单已保存") || !detail.includes("降水4/4 个时步")) {
              throw new Error(`unexpected detail: ${detail}`);
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

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_restart_rows_include_parameter_and_archive_context(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            const rows = view.restartStateRows({
              calibration_profile: "daily",
              effective_objective_mode: "daily_unified_professional_v1",
              optimized_params: { TT: 0.1, FC: 120 },
              initial_state: {
                state_snapshot_available: true,
                state_snapshot_time: "2026-01-10",
                state_snapshot_file: "C:/runs/source/state.json",
              },
              forecast_result: {
                enabled: true,
                source_run_name: "hbv_forecast_20260110_000000",
                source_run_path: "C:/runs/source",
                forecast_start: "2026-01-11",
                forecast_end: "2026-01-20",
                source_parameter_summary: { source_run_name: "源结果A", parameter_count: 2 },
                forecast_input_archive: {
                  manifest: { expected_steps: 10, variables: { prec: { archived_files: 10 } } },
                },
              },
            }, {
              shortPath: value => String(value).split("/").pop(),
              objectiveLabel: value => `目标-${value}`,
              profileLabel: value => `尺度-${value}`,
              readableRunReferenceName: value => value,
            });
            const byLabel = Object.fromEntries(rows.map(row => [row[0], row]));
            if (byLabel["起报状态"][1] !== "可用") throw new Error("state row missing");
            if (byLabel["预报来源"][2] !== "source") throw new Error(`source path not shortened: ${byLabel["预报来源"][2]}`);
            if (byLabel["参数来源"][1] !== "源结果参数（2 项）") throw new Error(`parameter row wrong: ${byLabel["参数来源"][1]}`);
            if (!byLabel["参数来源"][2].includes("来源：源结果A")) throw new Error(`parameter detail wrong: ${byLabel["参数来源"][2]}`);
            if (byLabel["预报气象"][1] !== "已归档 10 个预报时步") throw new Error(`archive row wrong: ${byLabel["预报气象"][1]}`);
            if (byLabel["降水"][1] !== "10/10 个时步") throw new Error(`variable row wrong: ${byLabel["降水"][1]}`);
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

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_forecast_source_options_and_summary_rendering(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            for (const name of ["renderForecastSourceOptions", "renderForecastSourceSummary"]) {
              if (typeof view?.[name] !== "function") throw new Error(`missing forecast source export: ${name}`);
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
              forecastArchiveDetailText() { return "窗口：2026-01-11 至 2026-01-20"; },
              forecastArchiveSummaryText() { return "待本次预报生成"; },
              forecastFriendlyRunName(run) { return `友好名<${run.name}>`; },
              forecastParameterContextHtml() { return '<div class="forecast-parameter-context">参数上下文</div>'; },
              forecastParameterSourceSummary() { return { value: "源结果参数（15 项）", detail: "读取源结果保存参数" }; },
              forecastRunReady(run) { return Boolean(run.ready); },
              forecastRunReadinessText(run) { return run.ready ? "可起报" : "缺少起报状态"; },
              forecastSuggestedStart() { return "2026-01-11"; },
              objectiveLabel(value) { return `目标-${value}`; },
              profileLabel(value) { return value === "daily" ? "日尺度" : value; },
              runDisplayName(run) { return `结果<${run.name}>`; },
              runProfileValue(run) { return run.profile; },
              runTypeLabel(value) { return value === "calibration" ? "率定结果" : value; },
              runTypeValue(run) { return run.kind; },
              runWorkspaceName() { return "工作区<A>"; },
              samePath(a, b) { return String(a || "").toLowerCase() === String(b || "").toLowerCase(); },
            };

            const options = view.renderForecastSourceOptions([
              { path: "C:/runs/A", name: "A" },
              { path: "C:/runs/B", name: "B" },
            ], "c:/RUNS/b", helpers);
            if (options.disabled || !options.html.includes('value="C:/runs/B" selected')) {
              throw new Error(`selected forecast option missing: ${options.html}`);
            }
            if (!options.html.includes("友好名&lt;A&gt; · 缺少起报状态")) {
              throw new Error(`option label should be escaped: ${options.html}`);
            }
            const emptyOptions = view.renderForecastSourceOptions([], "", helpers);
            if (!emptyOptions.disabled || !emptyOptions.html.includes("暂无可选源结果")) {
              throw new Error(`empty options wrong: ${JSON.stringify(emptyOptions)}`);
            }

            const emptySummary = view.renderForecastSourceSummary(null, helpers);
            if (emptySummary.ready || emptySummary.hintClassName !== "hint-box status-warn" || !emptySummary.html.includes("当前没有可作为预报起点")) {
              throw new Error(`empty summary wrong: ${JSON.stringify(emptySummary)}`);
            }

            const summary = view.renderForecastSourceSummary({
              path: "C:/runs/A",
              name: "A",
              ready: true,
              kind: "calibration",
              profile: "daily",
              state_snapshot_time: "2026-01-10",
              source_state_snapshot_time: "2026-01-09",
              effective_objective_mode: "daily_unified_professional_v1",
              workspace_name: "",
            }, helpers);
            if (!summary.ready || summary.hintClassName !== "hint-box status-ok" || !summary.hintText.includes("建议从 2026-01-11 起报")) {
              throw new Error(`summary hint wrong: ${summary.hintClassName} ${summary.hintText}`);
            }
            for (const text of ["友好名&lt;A&gt;", "结果类型", "率定结果", "日尺度", "目标-daily_unified_professional_v1", "源结果参数（15 项）", "参数上下文", "工作区&lt;A&gt;"]) {
              if (!summary.html.includes(text)) throw new Error(`summary missing ${text}: ${summary.html}`);
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

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_forecast_task_list_filters_sorts_and_renders_cards(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            for (const name of ["forecastRestartTasks", "renderForecastTaskCard", "renderForecastTaskList"]) {
              if (typeof view?.[name] !== "function") {
                throw new Error(`missing forecast task export: ${name}`);
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
              focusStatusClass(status) {
                return status === "ok" ? "status-ok" : status === "fail" ? "status-fail" : "status-warn";
              },
              focusStatusLabel(status) {
                return status === "ok" ? "通过" : status === "fail" ? "未通过" : "需复核";
              },
              formatDateTime(value) { return `时间:${value || ""}`; },
              renderTaskActions(task) { return `<button data-task-open-result="${task.id}">查看结果</button>`; },
              renderTaskMilestones(task) { return `<div class="milestones">${task.id}</div>`; },
              shortPath(value) { return String(value || "").split(/[\\/]/).pop() || ""; },
              taskDebugDetails(task, options) { return `<pre data-lines="${options.lines}">${task.id}</pre>`; },
              taskPrimaryTitle(task) { return task.label || "预报任务"; },
              taskStatusClass(status) { return status === "failed" ? "status-fail" : status === "running" ? "status-warn" : "status-ok"; },
              taskStatusLabel(status) { return status === "failed" ? "失败" : status === "running" ? "运行中" : "已完成"; },
              taskSummaryLine(task) { return task.summary || "预报任务摘要"; },
              taskTypeLabel() { return "连续状态预报"; },
            };

            const tasks = [
              {
                id: "forecast-old",
                task_type: "forecast_restart",
                status: "running",
                label: "旧预报",
                summary: "正在预报",
                updated_at: 10,
              },
              {
                id: "calibration-task",
                task_type: "calibration",
                status: "running",
                label: "率定任务",
                updated_at: 999,
              },
              {
                id: "forecast-new",
                task_type: "forecast_restart",
                status: "failed",
                label: "预报<新>",
                summary: "缺少未来气象",
                updated_at: 30,
                forecast_end: "2026-02-03",
                forecast_input_check: {
                  status: "fail",
                  headline: "预报输入检查",
                  source: { state_available: true, source_state_time: "2026-02-01" },
                  window: { forecast_start: "2026-02-02", forecast_end: "2026-02-03", expected_steps: 2 },
                  output: { result_label: "预报结果 A" },
                  variables: [{ key: "prec", label: "降水", status: "fail", summary: "缺少 1 个时间步", path: "C:/meteo/prec" }],
                  errors: ["未来降水缺失"],
                },
              },
              {
                id: "forecast-last",
                task_type: "forecast_restart",
                status: "completed",
                label: "完成预报",
                summary: "已完成",
                updated_at: 20,
              },
            ];

            const picked = view.forecastRestartTasks(tasks, { limit: 2 });
            if (picked.map(task => task.id).join(",") !== "forecast-new,forecast-last") {
              throw new Error(`unexpected forecast order: ${picked.map(task => task.id).join(",")}`);
            }

            const html = view.renderForecastTaskList(tasks, helpers);
            if (html.includes("calibration-task")) throw new Error("non-forecast task should not render");
            if (html.indexOf("forecast-new") > html.indexOf("forecast-last")) {
              throw new Error("forecast tasks should render newest first");
            }
            if (!html.includes("预报&lt;新&gt;")) throw new Error("forecast title should be escaped");
            if (!html.includes("预报至 2026-02-03")) throw new Error("forecast end label missing");
            if (!html.includes("forecast-task-input-check") || !html.includes("源状态")) {
              throw new Error("forecast input check summary missing");
            }
            if (!html.includes('data-lines="40"') || !html.includes('data-lines="80"')) {
              throw new Error("forecast log line limits missing");
            }
            if (!view.renderForecastTaskList([], helpers).includes("暂无连续状态预报任务")) {
              throw new Error("empty forecast task hint missing");
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
