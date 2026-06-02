import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendDashboardViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_dashboard_view_renders_workspace_and_template_cards(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/dashboardView.js", "utf8"), context);

            const dashboard = context.window.HBVStudioDashboardView;
            if (!dashboard?.renderWorkspaceCards || !dashboard?.renderTemplates || !dashboard?.templateListState || !dashboard?.workspaceCardsState) {
              throw new Error("dashboard view module exports are missing");
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
              objectLabels: { full_upstream_basin: "完整上游流域" },
              profileBadge(mode) { return `<span class="badge">${mode}</span>`; },
              shortPath(value) { return String(value || "").split(/[\\/]/).pop() || "—"; },
              workspaceNextStepText(workflow) { return workflow?.next_step_label || "输入检查"; },
            };

            const workspaceHtml = dashboard.renderWorkspaceCards([
              {
                path: "C:/workspaces/A/config.json",
                flow_name: "测试<流域>",
                calibration_mode: "daily",
                object_type: "full_upstream_basin",
                workflow: { ready_for_calibration: true, completed_count: 6, total_steps: 7, next_step_label: "率定", missing_count: 0 },
                display_path: "C:/workspaces/A/config.json",
                runtime_display_path: "C:/workspaces/A/runtime",
              },
            ], { ...helpers, selectedPath: "C:/workspaces/A/config.json" });

            if (!workspaceHtml.includes("workspace-card selected")) throw new Error(workspaceHtml);
            if (!workspaceHtml.includes("测试&lt;流域&gt;")) throw new Error("workspace name should be escaped");
            if (!workspaceHtml.includes("可率定")) throw new Error("workflow status missing");
            if (!workspaceHtml.includes("步骤 6/7 · 下一步 率定")) throw new Error("workflow summary missing");
            for (const attr of ["data-preview-workspace", "data-view-workspace-runs", "data-open-workspace", "data-delete-path"]) {
              if (!workspaceHtml.includes(attr)) throw new Error(`workspace action missing: ${attr}`);
            }
            const workspaceState = dashboard.workspaceCardsState([
              {
                path: "C:/workspaces/A/config.json",
                flow_name: "测试<流域>",
                calibration_mode: "daily",
                object_type: "full_upstream_basin",
                workflow: { ready_for_calibration: true, completed_count: 6, total_steps: 7, next_step_label: "率定", missing_count: 0 },
                display_path: "C:/workspaces/A/config.json",
                runtime_display_path: "C:/workspaces/A/runtime",
              },
            ], { ...helpers, selectedPath: "C:/workspaces/A/config.json" });
            const workspaceDom = Object.fromEntries(workspaceState.domUpdates.map(update => [update.selector, update]));
            if (workspaceState.html !== workspaceHtml || workspaceDom["#workspace-card-list"].html !== workspaceHtml) {
              throw new Error(`unexpected workspace DOM updates: ${JSON.stringify(workspaceState)}`);
            }
            if (!dashboard.renderWorkspaceCards([], helpers).includes("还没有工作区")) {
              throw new Error("empty workspace hint missing");
            }

            const templateHtml = dashboard.renderTemplates([
              {
                id: "tuotuohe-daily-builtin",
                title: "沱沱河<模板>",
                description: "内置测试",
                calibration_mode: "daily",
                object_type: "full_upstream_basin",
              },
            ], helpers);
            if (!templateHtml.includes("沱沱河&lt;模板&gt;")) throw new Error("template title should be escaped");
            if (!templateHtml.includes('data-template-instantiate="tuotuohe-daily-builtin"')) {
              throw new Error("template instantiate action missing");
            }
            if (!templateHtml.includes('data-template-sync="tuotuohe"')) {
              throw new Error("built-in template sync action missing");
            }
            const templateState = dashboard.templateListState([
              {
                id: "tuotuohe-daily-builtin",
                title: "沱沱河<模板>",
                description: "内置测试",
                calibration_mode: "daily",
                object_type: "full_upstream_basin",
              },
            ], helpers);
            const templateDom = Object.fromEntries(templateState.domUpdates.map(update => [update.selector, update]));
            if (templateState.html !== templateHtml || templateDom["#template-list"].html !== templateHtml) {
              throw new Error(`unexpected template DOM updates: ${JSON.stringify(templateState)}`);
            }
            if (!dashboard.renderTemplates([], helpers).includes("未发现模板")) {
              throw new Error("empty template hint missing");
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
