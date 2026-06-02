import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


def run_node_script(script: str) -> subprocess.CompletedProcess[str]:
    script_path = STUDIO_DIR / ".tmp_frontend_results_view_test.js"
    try:
        script_path.write_text(script, encoding="utf-8")
        return subprocess.run(
            ["node", str(script_path)],
            cwd=STUDIO_DIR,
            text=True,
            capture_output=True,
            timeout=20,
        )
    finally:
        script_path.unlink(missing_ok=True)


class FrontendResultsViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_results_view_renders_filters_hints_and_compact_widgets(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/resultsView.js", "utf8"), context);

            const results = context.window.HBVStudioResultsView;
            if (!results?.alignedRunFiltersForSelection || !results?.clearRunComparisonState || !results?.clearRunDetailState || !results?.filterRuns || !results?.latestEditableRunPath || !results?.manualStarterControlState || !results?.renderFilterToolbar || !results?.renderRunDetailMetadata || !results?.resultsFilterBreakdown || !results?.resultsFilterHint || !results?.resultMetricItems || !results?.runComparisonSuccessState || !results?.runDetailState || !results?.runExportFields || !results?.runExportPanelState || !results?.runExportPayload || !results?.runExportSuccess || !results?.runListState || !results?.runProfileValue || !results?.runsForWorkspace || !results?.selectedRunExportFields || !results?.selectedRunPath || !results?.runStepHours || !results?.workspaceHasEditableRun) {
              throw new Error("results view module exports are missing");
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
              samePath(a, b) {
                return String(a || "").replace(/\\/g, "/") === String(b || "").replace(/\\/g, "/");
              },
            };

            const toolbar = results.renderFilterToolbar({
              workspaceOptions: [
                { label: "全部结果", path: "" },
                { label: "当前工作区：A<1>", path: "C:/ws/A" },
              ],
              profileOptions: [{ label: "全部尺度", value: "" }, { label: "小时尺度", value: "hourly" }],
              stageOptions: [{ label: "全部阶段", value: "" }, { label: "手调结果", value: "manual_result" }],
              editabilityOptions: [{ label: "全部结果", value: "all" }, { label: "可继续手调", value: "editable" }],
              selectedWorkspacePath: "C:\\ws\\A",
              selectedProfile: "hourly",
              selectedType: "manual_result",
              selectedEditability: "editable",
            }, helpers);

            for (const attr of ["data-run-filter-path", "data-run-filter-profile", "data-run-filter-type", "data-run-filter-editability"]) {
              if (!toolbar.includes(attr)) throw new Error(`missing filter action ${attr}`);
            }
            if (!toolbar.includes("当前工作区：A&lt;1&gt;")) throw new Error("workspace label should be escaped");
            if ((toolbar.match(/class="phase-chip active"/g) || []).length !== 4) {
              throw new Error(`expected four active filter chips: ${toolbar}`);
            }

            const allHint = results.resultsFilterHint({ filtersActive: false, totalRuns: 3, breakdown: "正式率定 2" });
            if (allHint.text !== "当前显示全部结果，共 3 组。 其中 正式率定 2。" || allHint.className !== "hint-box") {
              throw new Error(`unexpected all-results hint: ${JSON.stringify(allHint)}`);
            }
            const emptyHint = results.resultsFilterHint({ filtersActive: true, shownCount: 0, workspaceText: "工作区A" });
            if (!emptyHint.text.includes("当前筛选：工作区A") || emptyHint.className !== "hint-box status-warn") {
              throw new Error(`unexpected filtered hint: ${JSON.stringify(emptyHint)}`);
            }

            const runItems = [
              { path: "r1", workspace_config: "C:/ws/A", calibration_profile: "daily", run_type: "calibration", studio_compatible: true },
              { path: "r2", workspace_config: "C:/ws/A", time_step_hours: 1, run_type: "manual_result", studio_compatible: true },
              { path: "r3", workspace_config: "C:/ws/B", calibration_profile: "daily", run_type: "forecast_restart", studio_compatible: false },
              { path: "r4", workspace_config: "C:/ws/A", calibration_profile: "daily", run_type: "legacy", studio_compatible: false },
            ];
            const filteredRuns = results.filterRuns(runItems, {
              workspacePath: "C:\\ws\\A",
              profile: "daily",
              type: "calibration",
              editability: "editable",
            }, {
              ...helpers,
              runTypeValue(run) { return run.run_type; },
            });
            if (filteredRuns.map(run => run.path).join("|") !== "r1") {
              throw new Error(`unexpected filtered runs: ${filteredRuns.map(run => run.path).join("|")}`);
            }
            if (results.runProfileValue(runItems[1]) !== "hourly" || results.runProfileValue({}) !== "daily") {
              throw new Error("run profile value should infer hourly from 1-hour step and default to daily");
            }
            const readonlyRuns = results.filterRuns(runItems, { editability: "readonly" }, { runTypeValue(run) { return run.run_type; } });
            if (readonlyRuns.map(run => run.path).join("|") !== "r3|r4") {
              throw new Error(`unexpected readonly filtered runs: ${readonlyRuns.map(run => run.path).join("|")}`);
            }
            const breakdown = results.resultsFilterBreakdown([
              runItems[2],
              runItems[1],
              runItems[3],
              runItems[0],
              { path: "r5", run_type: "manual_starter" },
            ], {
              runTypeValue(run) { return run.run_type; },
            });
            if (breakdown.text !== "正式率定 1 / 手调起点 1 / 手调结果 1 / 连续状态预报 1 / 历史结果 1") {
              throw new Error(`unexpected results filter breakdown: ${JSON.stringify(breakdown)}`);
            }
            const alignedNoChange = results.alignedRunFiltersForSelection(runItems[0], {
              workspacePath: "C:/ws/A",
              profile: "daily",
              type: "calibration",
              editability: "editable",
            }, [runItems[0]], {
              ...helpers,
              runTypeValue(run) { return run.run_type; },
            });
            if (alignedNoChange.changed || JSON.stringify(alignedNoChange.filters) !== JSON.stringify({
              workspacePath: "C:/ws/A",
              profile: "daily",
              type: "calibration",
              editability: "editable",
            })) {
              throw new Error(`aligned filters should stay unchanged: ${JSON.stringify(alignedNoChange)}`);
            }
            const alignedMismatch = results.alignedRunFiltersForSelection(runItems[2], {
              workspacePath: "C:/ws/A",
              profile: "hourly",
              type: "manual_result",
              editability: "editable",
            }, [runItems[1]], {
              ...helpers,
              runTypeValue(run) { return run.run_type; },
            });
            if (!alignedMismatch.changed || JSON.stringify(alignedMismatch.filters) !== JSON.stringify({
              workspacePath: "C:/ws/B",
              profile: "",
              type: "",
              editability: "all",
            })) {
              throw new Error(`aligned filters should clear incompatible selection: ${JSON.stringify(alignedMismatch)}`);
            }
            const alignedHiddenSelection = results.alignedRunFiltersForSelection(runItems[3], {
              workspacePath: "",
              profile: "",
              type: "calibration",
              editability: "all",
            }, [runItems[0]], {
              ...helpers,
              runTypeValue(run) { return run.run_type; },
            });
            if (!alignedHiddenSelection.changed || alignedHiddenSelection.filters.workspacePath !== "C:/ws/A" || alignedHiddenSelection.filters.type !== "") {
              throw new Error(`hidden selected run should activate its workspace and clear stage: ${JSON.stringify(alignedHiddenSelection)}`);
            }
            if (results.runsForWorkspace(runItems, "C:\\ws\\A", helpers).map(run => run.path).join("|") !== "r1|r2|r4") {
              throw new Error("runsForWorkspace should match normalized workspace paths");
            }
            if (!results.workspaceHasEditableRun(runItems, "C:/ws/A", helpers) || results.workspaceHasEditableRun(runItems, "C:/ws/B", helpers)) {
              throw new Error("workspaceHasEditableRun should only be true when the workspace has editable runs");
            }
            if (results.selectedRunPath({ selectedRunPath: " explicit ", currentRun: { run: { path: "nested" } } }) !== "explicit") {
              throw new Error("selectedRunPath should prefer explicit selection");
            }
            if (results.selectedRunPath({ currentRun: { run: { path: "nested-run" }, path: "fallback-run" } }) !== "nested-run") {
              throw new Error("selectedRunPath should use current run detail path before fallback path");
            }
            const clearedDetail = results.clearRunDetailState().statePatch;
            for (const key of ["currentRun", "selectedRunPath", "_runData", "_runParams", "_runOrigParams", "compareSeries", "compareMetrics", "compareLabel", "comparePresetId", "compareAdjusted", "lastRunExportPath", "runManualPresets", "runManualPresetConfigPath"]) {
              if (!Object.prototype.hasOwnProperty.call(clearedDetail, key)) {
                throw new Error(`clear run detail state missing ${key}`);
              }
            }
            if (clearedDetail.currentRun !== null || clearedDetail.selectedRunPath !== "" ||
                clearedDetail._runData !== null || clearedDetail._runParams !== null ||
                clearedDetail.compareAdjusted !== false || clearedDetail.runManualPresets.length !== 0 ||
                clearedDetail.runManualPresetConfigPath !== "") {
              throw new Error(`clear run detail state wrong: ${JSON.stringify(clearedDetail)}`);
            }
            const editableDetail = results.runDetailState({
              run: { path: "C:/runs/detail" },
              metadata: {
                optimized_params: { TT: 0.2, FC: 120 },
                metrics: {
                  calibration: { nse: 0.8 },
                  validation: { nse: 0.7 },
                },
              },
            }, {
              selectedRunPath: "C:/runs/previous",
            }, {
              isStudioEditableRun() { return true; },
            });
            if (!editableDetail.editable || editableDetail.selectedRunPath !== "C:/runs/detail" ||
                editableDetail.calibrationMetrics.nse !== 0.8 || editableDetail.validationMetrics.nse !== 0.7 ||
                editableDetail.statePatch.currentRun?.run?.path !== "C:/runs/detail" ||
                editableDetail.statePatch.lastRunExportPath !== "" ||
                editableDetail.statePatch.compareLabel !== "" ||
                editableDetail.statePatch._runParams.TT !== 0.2 ||
                editableDetail.statePatch._runOrigParams.FC !== 120) {
              throw new Error(`editable run detail state wrong: ${JSON.stringify(editableDetail)}`);
            }
            editableDetail.statePatch._runParams.TT = 9;
            if (editableDetail.statePatch._runOrigParams.TT !== 0.2) {
              throw new Error("run detail params and original params should be independent copies");
            }
            const readonlyDetail = results.runDetailState({
              path: "C:/runs/readonly",
              metadata: { optimized_params: { TT: 0.2 } },
            }, {
              editable: false,
              selectedRunPath: "C:/runs/previous",
            });
            if (readonlyDetail.editable || readonlyDetail.selectedRunPath !== "C:/runs/readonly" ||
                readonlyDetail.statePatch._runParams !== null || readonlyDetail.statePatch._runOrigParams !== null ||
                readonlyDetail.statePatch.currentRun?.path !== "C:/runs/readonly") {
              throw new Error(`readonly run detail state wrong: ${JSON.stringify(readonlyDetail)}`);
            }
            const clearedComparison = results.clearRunComparisonState().statePatch;
            if (clearedComparison.compareSeries !== null || clearedComparison.compareMetrics !== null ||
                clearedComparison.compareLabel !== "" || clearedComparison.comparePresetId !== "" ||
                clearedComparison.compareAdjusted !== false) {
              throw new Error(`clear comparison state wrong: ${JSON.stringify(clearedComparison)}`);
            }
            const comparisonSuccess = results.runComparisonSuccessState({
              id: "preset-A",
              name: "参数集A",
            }, {
              dates: ["2020-01-01", "2020-01-02", "2020-01-03"],
              q_sim: [10, 12, null],
              q_obs: [9, null, 13],
              metrics: { calibration: { nse: 0.86 } },
              runtime: { params_adjusted: true },
            }).statePatch;
            if (comparisonSuccess.compareLabel !== "参数集A" ||
                comparisonSuccess.comparePresetId !== "preset-A" ||
                comparisonSuccess.compareAdjusted !== true ||
                comparisonSuccess.compareMetrics.calibration.nse !== 0.86 ||
                comparisonSuccess.compareSeries.dates.length !== 3 ||
                comparisonSuccess.compareSeries.q_sim[1] !== 12 ||
                comparisonSuccess.compareSeries.residuals.join("|") !== "1||") {
              throw new Error(`comparison success state wrong: ${JSON.stringify(comparisonSuccess)}`);
            }
            const fallbackComparison = results.runComparisonSuccessState({}, {
              q_sim: [1, 2],
            }).statePatch;
            if (fallbackComparison.compareLabel !== "参数集" ||
                fallbackComparison.comparePresetId !== "" ||
                fallbackComparison.compareSeries.residuals.join("|") !== "|") {
              throw new Error(`fallback comparison state wrong: ${JSON.stringify(fallbackComparison)}`);
            }
            if (results.latestEditableRunPath([runItems[3], runItems[0]]) !== "r1" || results.latestEditableRunPath([runItems[3], runItems[2]]) !== "r4" || results.latestEditableRunPath([]) !== "") {
              throw new Error("latestEditableRunPath should prefer editable runs and otherwise fall back to first run");
            }
            const emptyAllState = results.runListState({
              totalRuns: 0,
              visibleCount: 0,
              manualStarterWorkspaceLabel: "工作区<A>",
            }, helpers);
            if (emptyAllState.status !== "empty-all" || !emptyAllState.listHtml.includes("暂无结果") || !emptyAllState.hintText.includes("工作区<A>") || emptyAllState.hintClassName !== "hint-box status-warn") {
              throw new Error(`unexpected no-results list state: ${JSON.stringify(emptyAllState)}`);
            }
            const workspaceEmptyState = results.runListState({
              totalRuns: 2,
              visibleCount: 0,
              workspaceFilterPath: "C:/ws/A",
              workspaceRunCount: 0,
              workspaceFilterLabel: "工作区<A>",
            }, helpers);
            if (workspaceEmptyState.status !== "empty-workspace" || !workspaceEmptyState.listHtml.includes("工作区&lt;A&gt;") || !workspaceEmptyState.hintText.includes("生成“手调起点”继续")) {
              throw new Error(`unexpected workspace-empty list state: ${JSON.stringify(workspaceEmptyState)}`);
            }
            const filterEmptyState = results.runListState({
              totalRuns: 2,
              visibleCount: 0,
              workspaceFilterPath: "C:/ws/A",
              workspaceRunCount: 2,
              workspaceFilterLabel: "工作区A",
            }, helpers);
            if (filterEmptyState.status !== "empty-filter" || !filterEmptyState.hintText.includes("当前筛选条件下没有匹配项")) {
              throw new Error(`unexpected filter-empty list state: ${JSON.stringify(filterEmptyState)}`);
            }
            const readyState = results.runListState({
              totalRuns: 2,
              visibleCount: 2,
              workspaceFilterPath: "C:/ws/A",
              workspaceFilterLabel: "工作区A",
              hasCurrentRun: false,
            }, helpers);
            if (readyState.status !== "ready" || !readyState.updateHint || readyState.hintClassName !== "hint-box" || !readyState.hintText.includes("先从左侧选择“工作区A”")) {
              throw new Error(`unexpected ready list state: ${JSON.stringify(readyState)}`);
            }
            const selectedReadyState = results.runListState({ totalRuns: 2, visibleCount: 1, hasCurrentRun: true }, helpers);
            if (selectedReadyState.status !== "ready" || selectedReadyState.updateHint) {
              throw new Error(`selected run should not overwrite entry hint: ${JSON.stringify(selectedReadyState)}`);
            }
            const starterNoWorkspace = results.manualStarterControlState({});
            if (!starterNoWorkspace.calibration.disabled || starterNoWorkspace.results.visible || !starterNoWorkspace.results.disabled) {
              throw new Error(`manual starter controls should be disabled without workspace: ${JSON.stringify(starterNoWorkspace)}`);
            }
            const starterEmptyWorkspace = results.manualStarterControlState({
              calibrationWorkspacePath: "C:/ws/A",
              resultsWorkspacePath: "C:/ws/A",
              totalRuns: 0,
            });
            if (starterEmptyWorkspace.calibration.disabled || !starterEmptyWorkspace.results.visible || starterEmptyWorkspace.results.disabled || starterEmptyWorkspace.results.text !== "生成手调起点") {
              throw new Error(`manual starter controls should allow empty workspace starter: ${JSON.stringify(starterEmptyWorkspace)}`);
            }
            const starterRunning = results.manualStarterControlState({
              calibrationWorkspacePath: "C:/ws/A",
              resultsWorkspacePath: "C:/ws/A",
              runningCalibrationTask: { id: "task-cal" },
              runningResultsTask: { id: "task-run" },
              totalRuns: 0,
            });
            if (!starterRunning.calibration.disabled || starterRunning.calibration.text !== "正在生成手调起点..." || !starterRunning.results.disabled || starterRunning.results.text !== "正在生成手调起点...") {
              throw new Error(`manual starter running state mismatch: ${JSON.stringify(starterRunning)}`);
            }
            const starterHidden = results.manualStarterControlState({
              calibrationWorkspacePath: "C:/ws/A",
              resultsWorkspacePath: "C:/ws/A",
              totalRuns: 3,
              workspaceFilterActive: true,
              resultsWorkspaceRunCount: 2,
            });
            if (starterHidden.results.visible) {
              throw new Error(`results starter should hide when filtered workspace already has runs: ${JSON.stringify(starterHidden)}`);
            }
            const starterFilteredEmpty = results.manualStarterControlState({
              calibrationWorkspacePath: "C:/ws/A",
              resultsWorkspacePath: "C:/ws/B",
              totalRuns: 3,
              workspaceFilterActive: true,
              resultsWorkspaceRunCount: 0,
            });
            if (!starterFilteredEmpty.results.visible || starterFilteredEmpty.results.disabled) {
              throw new Error(`results starter should show for empty filtered workspace: ${JSON.stringify(starterFilteredEmpty)}`);
            }

            const metrics = results.renderMetricStrip([{ l: "NSE<率定>", v: "0.91&" }], helpers);
            if (!metrics.includes("NSE&lt;率定&gt;") || !metrics.includes("0.91&amp;")) {
              throw new Error("metric strip should escape label and value");
            }
            const metricItems = results.resultMetricItems(
              { nse: 0.81234, kge: 0.73456, pbias: -1.234 },
              { nse: 0.70123 },
              { calibration_profile: "daily", time_config: { time_step_hours: 24 } },
              {
                profileLabel(value) { return value === "daily" ? "日尺度" : String(value || ""); },
                formatNumber(value, digits = 4) {
                  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
                },
                eventMetricItems() {
                  return [{ l: "洪水事件", v: "事件目标函数：2/3 场有效" }];
                },
              },
            );
            const metricText = metricItems.map(item => `${item.l}:${item.v}`).join("|");
            if (metricText !== "模式:日尺度|步长:24 小时|率定纳什效率系数:0.8123|验证纳什效率系数:0.7012|率定 KGE 综合效率:0.7346|率定水量偏差:-1.23%|洪水事件:事件目标函数：2/3 场有效") {
              throw new Error(`unexpected result metric items: ${metricText}`);
            }
            const fields = results.renderRunExportFields([{ key: "q<sim>", label: "模拟流量", checked: true }], helpers);
            if (!fields.includes('data-run-export-field="q&lt;sim&gt;"') || !fields.includes("checked")) {
              throw new Error("export fields should keep keys and checked state");
            }
            const defaultExportFields = results.runExportFields();
            if (defaultExportFields.map(field => field.key).join("|") !== "q_sim|q_obs|q_rain|q_snow|q_ice" || defaultExportFields.some(field => !field.checked)) {
              throw new Error(`unexpected default export fields: ${JSON.stringify(defaultExportFields)}`);
            }
            const boundaryExportFields = results.runExportFields({ boundaryEnabled: true });
            if (boundaryExportFields.map(field => `${field.key}:${field.checked ? "Y" : "N"}`).join("|") !== "q_sim:Y|q_obs:Y|q_rain:Y|q_snow:Y|q_ice:Y|q_boundary_inflow:N") {
              throw new Error(`unexpected boundary export fields: ${JSON.stringify(boundaryExportFields)}`);
            }

            const dailyExport = results.runExportPanelState({
              run: { path: "C:/runs/daily" },
              metadata: {
                time_config: {
                  time_step_hours: 24,
                  warmup_start: "2019-10-01",
                  calib_start: "2020-01-01",
                  valid_end: "2021-12-31",
                },
              },
              series: { dates: ["2020-01-02", "2021-12-30"] },
            }, {
              lastExportPath: "",
            }, {
              formatInputTime(value, hourly) {
                return `${hourly ? "H" : "D"}:${value}`;
              },
            });
            if (dailyExport.stepHours !== 24 || dailyExport.hourly) {
              throw new Error(`unexpected daily export timescale: ${JSON.stringify(dailyExport)}`);
            }
            if (dailyExport.start.type !== "date" || dailyExport.start.step !== "" || dailyExport.start.value !== "D:2019-10-01") {
              throw new Error(`unexpected daily export start: ${JSON.stringify(dailyExport.start)}`);
            }
            if (dailyExport.end.type !== "date" || dailyExport.end.step !== "" || dailyExport.end.value !== "D:2021-12-31") {
              throw new Error(`unexpected daily export end: ${JSON.stringify(dailyExport.end)}`);
            }
            if (dailyExport.exportDisabled || !dailyExport.openDisabled || dailyExport.hintClassName !== "hint-box" || !dailyExport.hintText.includes("日尺度结果")) {
              throw new Error(`unexpected daily export panel state: ${JSON.stringify(dailyExport)}`);
            }

            const hourlyExport = results.runExportPanelState({
              run: { path: "C:/runs/hourly" },
              metadata: {
                time_config: {
                  time_step_hours: 1,
                  calib_start: "2020-01-01 00:00",
                },
              },
              series: { dates: ["2020-01-01 01:00", "2020-01-03 23:00"] },
            }, {
              lastExportPath: "C:/runs/hourly/导出/result.xlsx",
            }, {
              formatInputTime(value, hourly) {
                return `${hourly ? "H" : "D"}:${value}`;
              },
            });
            if (hourlyExport.stepHours !== 1 || !hourlyExport.hourly) {
              throw new Error(`unexpected hourly export timescale: ${JSON.stringify(hourlyExport)}`);
            }
            if (hourlyExport.start.type !== "datetime-local" || hourlyExport.start.step !== "60" || hourlyExport.start.value !== "H:2020-01-01 00:00") {
              throw new Error(`unexpected hourly export start: ${JSON.stringify(hourlyExport.start)}`);
            }
            if (hourlyExport.end.type !== "datetime-local" || hourlyExport.end.step !== "60" || hourlyExport.end.value !== "H:2020-01-03 23:00") {
              throw new Error(`unexpected hourly export end: ${JSON.stringify(hourlyExport.end)}`);
            }
            if (hourlyExport.exportDisabled || hourlyExport.openDisabled || !hourlyExport.hintText.includes("小时结果") || !hourlyExport.hintText.includes("分钟精度")) {
              throw new Error(`unexpected hourly export panel state: ${JSON.stringify(hourlyExport)}`);
            }

            const emptyExport = results.runExportPanelState(null);
            if (!emptyExport.exportDisabled || !emptyExport.openDisabled || emptyExport.start.value !== "" || emptyExport.hintText !== "选择一个结果后，可按时间范围导出 Excel。") {
              throw new Error(`unexpected empty export panel state: ${JSON.stringify(emptyExport)}`);
            }

            const selectedFields = results.selectedRunExportFields([
              { checked: true, dataset: { runExportField: "q_sim" } },
              { checked: false, dataset: { runExportField: "q_obs" } },
              { checked: true, dataset: { runExportField: " q_ice " } },
              { checked: true, dataset: { runExportField: "" } },
            ]);
            if (selectedFields.join("|") !== "q_sim|q_ice") {
              throw new Error(`unexpected selected export fields: ${JSON.stringify(selectedFields)}`);
            }

            const missingRunPayload = results.runExportPayload(null, ["q_sim"]);
            if (missingRunPayload.ok || missingRunPayload.reason !== "missing-run" || missingRunPayload.payload !== null) {
              throw new Error(`missing run export payload should be blocked: ${JSON.stringify(missingRunPayload)}`);
            }
            const missingFieldsPayload = results.runExportPayload({ run: { path: "C:/runs/daily" } }, []);
            if (missingFieldsPayload.ok || missingFieldsPayload.reason !== "missing-fields" || missingFieldsPayload.payload !== null) {
              throw new Error(`missing field export payload should be blocked: ${JSON.stringify(missingFieldsPayload)}`);
            }
            const exportPayload = results.runExportPayload({
              run: { path: "C:/runs/hourly" },
              metadata: { time_config: { time_step_hours: 1 } },
            }, [" q_sim ", "q_ice"], {
              start: "2020-01-01T00:00",
              end: "2020-01-02T00:00",
            }, {
              fromInputTime(value, hourly) {
                return `${hourly ? "H" : "D"}:${value}`;
              },
            });
            if (!exportPayload.ok || !exportPayload.hourly || exportPayload.payload.path !== "C:/runs/hourly" ||
                exportPayload.payload.start_date !== "H:2020-01-01T00:00" ||
                exportPayload.payload.end_date !== "H:2020-01-02T00:00" ||
                exportPayload.payload.fields.join("|") !== "q_sim|q_ice") {
              throw new Error(`unexpected export payload: ${JSON.stringify(exportPayload)}`);
            }

            const exportSuccess = results.runExportSuccess({
              path: "C:/exports/result.xlsx",
              row_count: 42,
            }, {
              shortPath(value) { return String(value).split("/").pop(); },
            });
            if (exportSuccess.exportPath !== "C:/exports/result.xlsx" ||
                exportSuccess.statePatch.lastRunExportPath !== "C:/exports/result.xlsx" ||
                exportSuccess.openExportDisabled ||
                exportSuccess.rowCount !== 42 ||
                exportSuccess.displayPath !== "result.xlsx" ||
                !exportSuccess.hintText.includes("42") ||
                !exportSuccess.hintText.includes("result.xlsx") ||
                !exportSuccess.toastText.includes("42") ||
                exportSuccess.hintClassName !== "hint-box status-ok") {
              throw new Error(`unexpected export success state: ${JSON.stringify(exportSuccess)}`);
            }
            const emptyExportSuccess = results.runExportSuccess({});
            if (!emptyExportSuccess.openExportDisabled || emptyExportSuccess.statePatch.lastRunExportPath !== "") {
              throw new Error(`empty export success should disable open file: ${JSON.stringify(emptyExportSuccess)}`);
            }

            const chartPayloads = results.resultChartPayloads({
              metadata: { boundary: { enabled: true } },
              series: {
                dates: ["2020-01-01", "2020-01-02"],
                q_obs: [10, 11],
                q_sim: [9, 12],
                q_rain: [4, 5],
                q_snow: [3, 4],
                q_ice: [2, 3],
                q_boundary_inflow: [1, 1.5],
                residuals: [-1, 1],
              },
            }, {
              boundaryEnabled: true,
              compareLabel: "参数集<A>",
              compareSeries: {
                dates: ["2020-01-01", "2020-01-02"],
                q_sim: [8, 10],
                residuals: [-2, -1],
              },
            }, {
              colors: {
                qObs: "#obs",
                qSim: "#sim",
                qRain: "#rain",
                qSnow: "#snow",
                qIce: "#ice",
                boundary: "#boundary",
                residual: "#residual",
              },
            });
            const hydroNames = chartPayloads.hydrograph.traces.map(trace => trace.name).join("|");
            if (hydroNames !== "实测流量|模拟流量|对比：参数集<A>|边界入流") {
              throw new Error(`unexpected hydrograph traces: ${hydroNames}`);
            }
            if (chartPayloads.hydrograph.traces[0].line.color !== "#obs" || chartPayloads.hydrograph.traces[1].line.width !== 1.8) {
              throw new Error(`unexpected hydrograph trace styles: ${JSON.stringify(chartPayloads.hydrograph.traces)}`);
            }
            const componentNames = chartPayloads.component.traces.map(trace => trace.name).join("|");
            if (componentNames !== "降雨产流|融雪流量|裸冰融化流量") {
              throw new Error(`unexpected component traces: ${componentNames}`);
            }
            if (chartPayloads.component.traces[2].line.color !== "#ice" || chartPayloads.component.layout.yaxis.title !== "流量 m³/s") {
              throw new Error(`unexpected component chart payload: ${JSON.stringify(chartPayloads.component)}`);
            }
            const residualNames = chartPayloads.residual.traces.map(trace => trace.name).join("|");
            if (residualNames !== "当前残差|对比残差" || chartPayloads.residual.layout.yaxis.title !== "残差 m³/s") {
              throw new Error(`unexpected residual chart payload: ${JSON.stringify(chartPayloads.residual)}`);
            }
            const noBoundaryPayloads = results.resultChartPayloads({ series: { dates: ["2020-01-01"] } }, { boundaryEnabled: false });
            if (noBoundaryPayloads.hydrograph.traces.some(trace => trace.name === "边界入流")) {
              throw new Error("boundary trace should not render when disabled");
            }

            const cards = results.renderRunCards([
              {
                path: "C:/runs/A",
                workspace_config: "C:/ws/A",
                display_name: "结果<一>",
                display_subtitle: "目录名：run_A",
                nse_cal: 0.81234,
                nse_val: 0.71234,
                pbias_cal: -1.23,
                pbias_val: 2.34,
                studio_compatible: true,
                has_custom_title: false,
                hydrology_summary: {
                  workflow_label_zh: "单流程参数率定",
                  objective_label_zh: "统一专业目标",
                  flow_status_zh: "径流拟合达标",
                },
              },
              {
                path: "C:/runs/B",
                workspace_config: "C:/ws/active",
                display_name: "只读结果",
                nse_cal: null,
                nse_val: null,
                studio_compatible: false,
                has_custom_title: true,
                hydrology_summary: {},
              },
            ], {
              ...helpers,
              formatMetricValue(value, digits = 2, suffix = "") {
                return Number.isFinite(Number(value)) ? `${Number(value).toFixed(digits)}${suffix}` : "—";
              },
              formatNumber(value, digits = 4) {
                return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
              },
              hydrologySummaryValue(summary, key, fallback) {
                return summary?.[key] || fallback || "—";
              },
              objectiveVersionBadge() { return '<span class="status-badge">当前口径</span>'; },
              runDisplayName(run) { return run.display_name; },
              runDisplaySubtitle(run) { return run.display_subtitle || ""; },
              runTypeBadge() { return '<span class="status-badge status-type">正式率定</span>'; },
              runWorkspaceFilterPath: "C:/ws/active",
              runWorkspaceName() { return "流域A"; },
              selectedRunPath: "C:/runs/A",
            });
            if (!cards.includes("run-card selected")) throw new Error("selected run should be highlighted");
            if (!cards.includes("结果&lt;一&gt;")) throw new Error("run name should be escaped");
            if (!cards.includes("NSE 率定 / 验证") || !cards.includes("0.8123 / 0.7123")) {
              throw new Error("run score missing");
            }
            if (!cards.includes("PBIAS -1.23% / 2.34%")) throw new Error("pbias summary missing");
            for (const attr of ["data-run-path", "data-rename-run", "data-open-run-dir", "data-delete-run"]) {
              if (!cards.includes(attr)) throw new Error(`missing run card action ${attr}`);
            }
            if (!cards.includes("data-filter-run-workspace=\"C:/ws/A\"")) {
              throw new Error("workspace quick filter should be shown for other workspace");
            }
            if (cards.includes("data-filter-run-workspace=\"C:/ws/active\"")) {
              throw new Error("workspace quick filter should hide for active workspace");
            }
            if (!cards.includes("仅查看") || !cards.includes("修改标题")) {
              throw new Error("readonly/custom title labels missing");
            }

            const engineering = results.renderRunEngineeringSummary({
              run: {
                path: "C:/runs/A",
                run_type: "calibration",
                workspace_config: "C:/ws/A",
                has_custom_title: false,
              },
              metadata: {
                workspace_config: "C:/ws/A",
                hydrology_summary: {
                  workflow_label_zh: "正式率定",
                  objective_label_zh: "统一专业目标",
                  flow_status_zh: "径流拟合达标",
                  diagnostics_detail_path: "C:/runs/A/水文模拟结果说明.md",
                },
                manual_result: { enabled: false },
                starter_result: { enabled: false },
                reliability_flag: "degraded",
                reliability_notes: ["缺少完整观测回放"],
                project_object_type: "regression_validation",
              },
            }, {
              ...helpers,
              componentFractionBasisText() { return "率定期径流口径"; },
              componentFractionReport() { return { ok: true }; },
              componentFractionText() { return "雨水 50% / 融雪 30% / 冰川 20%"; },
              floodEventEvaluation() { return { enabled: true, objective_enabled: false }; },
              floodEventStatusText() { return "事件目标函数：2/3 场有效"; },
              hydrologySummaryValue(summary, key, fallback = "—") { return summary?.[key] || fallback; },
              isStudioEditableRun() { return true; },
              replayCompatibilityInfo() { return { obsReplay: true, boundaryReplay: true }; },
              runTypeLabel(value, fallback) { return fallback || value; },
              runWorkspaceFilterPath: "C:/ws/active",
              shortPath(value) { return String(value || "").split(/[\\/]/).pop() || ""; },
            });
            if (!engineering.summaryHtml.includes("正式率定") || !engineering.summaryHtml.includes("事件目标函数：2/3 场有效")) {
              throw new Error("engineering summary cards missing");
            }
            if (!engineering.summaryHtml.includes("水文模拟结果说明.md") || !engineering.summaryHtml.includes("雨水 50%")) {
              throw new Error("engineering report or component summary missing");
            }
            for (const attr of ["data-rename-run", "data-run-summary-open-dir", "data-run-summary-open-report", "data-run-summary-filter-workspace", "data-run-summary-open-workspace", "data-delete-run"]) {
              if (!engineering.actionsHtml.includes(attr)) throw new Error(`missing engineering action ${attr}`);
            }
            if (engineering.noteClassName !== "hint-box status-warn") {
              throw new Error(`unexpected engineering note class: ${engineering.noteClassName}`);
            }
            if (!engineering.noteText.includes("观测序列已从源结果回放恢复") || !engineering.noteText.includes("当前结果可靠性降级：缺少完整观测回放")) {
              throw new Error(`engineering note text missing replay/degraded context: ${engineering.noteText}`);
            }

            const detail = results.renderRunDetailMetadata({
              run: {
                path: "C:/runs/A",
                run_type: "manual_result",
                run_origin: "studio",
                workspace_config: "C:/ws/A",
              },
              metadata: {
                workspace_config: "C:/ws/A",
                run_time: "2026-06-02 19:30",
                param_bounds_profile: "daily",
                time_config: {
                  time_step_hours: 24,
                  calib_start: "2020-01-01",
                  calib_end: "2020-12-31",
                  valid_start: "2021-01-01",
                  valid_end: "2021-12-31",
                },
                manual_result: { enabled: true },
                hydrology_summary: {
                  workflow_label_zh: "正式率定<A>",
                  objective_label_zh: "统一目标&口径",
                  flow_status_zh: "径流拟合达标",
                  diagnostics_detail_path: "C:/runs/A/report&detail.md",
                },
              },
              series_range: {
                warmup_start: "2019-01-01",
                actual_start: "2020-01-02",
                warmup_covered: false,
              },
            }, {
              ...helpers,
              compactTimeText(value) { return `${value} 00:00`; },
              componentFractionBasisText() { return "率定期径流口径"; },
              componentFractionReport() { return { ok: true }; },
              componentFractionText() { return "雨水<50%> / 融雪 30% / 冰川 20%"; },
              currentRunStepHours() { return 24; },
              floodEventRows() { return [["事件<1>", "2/3&", "诊断<有效>"]]; },
              hydrologySummaryValue(summary, key, fallback = "—") { return summary?.[key] || fallback; },
              isStudioEditableRun() { return true; },
              paramBoundsProfileLabels: { daily: "日尺度参数范围" },
              restartStateRows() { return [["起报状态", "可用<稳定>", "来自上一场结果"]]; },
              runMetricsText() { return "率定期<2020>&验证期"; },
              runTypeLabel(value, fallback) { return fallback || value; },
              shortPath(value) { return String(value || "").split(/[\\/]/).pop() || ""; },
              timeRangeText(start, end, stepHours) { return `${start} 至 ${end}，${stepHours}小时`; },
              workspaceLabelByPath() { return "工作区<一>"; },
            });
            if (!detail.metadataHtml.includes("正式率定&lt;A&gt;") || detail.metadataHtml.includes("正式率定<A>")) {
              throw new Error("detail metadata should escape hydrology summary values");
            }
            if (!detail.metadataHtml.includes("雨水&lt;50%&gt;") || !detail.metadataHtml.includes("起报状态与预报") || !detail.metadataHtml.includes("洪水事件评价")) {
              throw new Error("detail metadata sections missing");
            }
            if (!detail.metadataHtml.includes('data-run-detail-open-dir="C:/runs/A"') || !detail.metadataHtml.includes('data-run-detail-open-report="C:/runs/A/report&amp;detail.md"')) {
              throw new Error("detail metadata action buttons missing");
            }
            if (detail.hintClassName !== "hint-box status-warn" || !detail.hintText.includes("未包含预热段") || !detail.hintText.includes("率定期<2020>&验证期")) {
              throw new Error(`unexpected detail hint: ${detail.hintClassName} ${detail.hintText}`);
            }
            """
        )
        result = run_node_script(script)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
