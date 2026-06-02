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
            if (!results?.renderFilterToolbar || !results?.resultsFilterHint) {
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
            const fields = results.renderRunExportFields([{ key: "q<sim>", label: "模拟流量", checked: true }], helpers);
            if (!fields.includes('data-run-export-field="q&lt;sim&gt;"') || !fields.includes("checked")) {
              throw new Error("export fields should keep keys and checked state");
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
