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
