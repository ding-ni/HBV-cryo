import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendEngineeringFocusViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_engineering_focus_view_renders_checks_and_dom_state(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/engineeringFocusView.js", "utf8"), context);

            const view = context.window.HBVStudioEngineeringFocusView;
            for (const name of ["engineeringFocusChecksState", "renderEngineeringFocusChecks"]) {
              if (typeof view?.[name] !== "function") throw new Error(`missing focus view export: ${name}`);
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
              renderStationEventCoverage(check) {
                return check.event_coverage ? `<div class="event-coverage">${check.event_coverage}</div>` : "";
              },
            };
            const checks = [
              {
                title: "站点<降水>",
                status: "fail",
                summary: "缺少&站点信息",
                items: [
                  { label: "覆盖", value: "1/2", status: "warn" },
                  { label: "质量", value: "通过", status: "ok" },
                ],
                event_coverage: "事件覆盖",
              },
            ];
            const html = view.renderEngineeringFocusChecks(checks, { title: "专项检查" }, helpers);
            if (!html.includes("站点&lt;降水&gt;") || html.includes("站点<降水>")) {
              throw new Error(`check title should be escaped: ${html}`);
            }
            if (!html.includes("缺少&amp;站点信息") || !html.includes("status-badge status-fail")) {
              throw new Error(`summary or status missing: ${html}`);
            }
            if (!html.includes("event-coverage")) {
              throw new Error(`station event coverage extension missing: ${html}`);
            }
            const emptyHtml = view.renderEngineeringFocusChecks([], { emptyText: "暂无<A>" }, helpers);
            if (!emptyHtml.includes("暂无&lt;A&gt;")) {
              throw new Error(`empty hint should be escaped: ${emptyHtml}`);
            }
            const state = view.engineeringFocusChecksState("#focus-host", checks, { title: "专项检查" }, helpers);
            const dom = Object.fromEntries(state.domUpdates.map(update => [update.selector, update]));
            if (state.html !== html || dom["#focus-host"].html !== html) {
              throw new Error(`unexpected focus check DOM updates: ${JSON.stringify(state)}`);
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
