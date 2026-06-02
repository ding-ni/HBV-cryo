import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


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
            if (!results?.renderFilterToolbar || !results?.renderRunDetailMetadata || !results?.resultsFilterHint || !results?.resultMetricItems || !results?.runExportPanelState || !results?.runStepHours) {
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
