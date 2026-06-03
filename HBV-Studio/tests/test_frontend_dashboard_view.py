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
            if (!dashboard?.dashboardDataState || !dashboard?.dashboardFallbackState || !dashboard?.dashboardLoadQueryState || !dashboard?.renderWorkspaceCards || !dashboard?.renderTemplates || !dashboard?.templateListDataState || !dashboard?.templateListQueryState || !dashboard?.templateListState || !dashboard?.workspaceCardsState || !dashboard?.workspaceListDataState || !dashboard?.workspaceListQueryState || !dashboard?.workspaceLoadQueryState) {
              throw new Error("dashboard view module exports are missing");
            }
            const loadQuery = dashboard.dashboardLoadQueryState();
            if (loadQuery.dashboardPath !== "/api/dashboard" ||
                loadQuery.fallbackOrder.join("|") !== "templates|workspaces|runs|tasks" ||
                loadQuery.fallbackPaths.templates !== "/api/templates" ||
                loadQuery.fallbackPaths.workspaces !== "/api/workspaces" ||
                loadQuery.fallbackPaths.runs !== "/api/runs" ||
                loadQuery.fallbackPaths.tasks !== "/api/tasks") {
              throw new Error(`dashboard load query mismatch: ${JSON.stringify(loadQuery)}`);
            }
            const aggregateState = dashboard.dashboardDataState({
              templates: [{ id: "tpl" }],
              workspaces: [{ id: "ws" }],
              runs: [{ id: "run" }],
              tasks: [{ id: "task" }],
            }).statePatch;
            if (aggregateState.templates[0].id !== "tpl" ||
                aggregateState.workspaces[0].id !== "ws" ||
                aggregateState.runs[0].id !== "run" ||
                aggregateState.tasks[0].id !== "task") {
              throw new Error(`dashboard aggregate state mismatch: ${JSON.stringify(aggregateState)}`);
            }
            const emptyAggregateState = dashboard.dashboardDataState({ templates: null }).statePatch;
            if (emptyAggregateState.templates.length || emptyAggregateState.workspaces.length || emptyAggregateState.runs.length || emptyAggregateState.tasks.length) {
              throw new Error(`empty aggregate state should use arrays: ${JSON.stringify(emptyAggregateState)}`);
            }
            const fallbackState = dashboard.dashboardFallbackState([
              { status: "fulfilled", value: { data: [{ id: "tpl" }] } },
              { status: "rejected", reason: new Error("workspaces failed") },
              { status: "fulfilled", value: { data: [{ id: "run" }] } },
              { status: "fulfilled", value: { data: "bad" } },
            ]);
            if (fallbackState.allFailed ||
                fallbackState.statePatch.templates[0].id !== "tpl" ||
                fallbackState.statePatch.workspaces.length !== 0 ||
                fallbackState.statePatch.runs[0].id !== "run" ||
                fallbackState.statePatch.tasks.length !== 0) {
              throw new Error(`dashboard fallback state mismatch: ${JSON.stringify(fallbackState)}`);
            }
            const failedFallbackState = dashboard.dashboardFallbackState([
              { status: "rejected" },
              { status: "rejected" },
              { status: "rejected" },
              { status: "rejected" },
            ]);
            if (!failedFallbackState.allFailed) {
              throw new Error(`failed fallback should be marked all failed: ${JSON.stringify(failedFallbackState)}`);
            }
            const templateQuery = dashboard.templateListQueryState();
            if (templateQuery.templatesPath !== "/api/templates") {
              throw new Error(`template query mismatch: ${JSON.stringify(templateQuery)}`);
            }
            const templateData = dashboard.templateListDataState([{ id: "tpl" }]);
            if (templateData.templates[0].id !== "tpl" || templateData.statePatch.templates !== templateData.templates) {
              throw new Error(`template data state mismatch: ${JSON.stringify(templateData)}`);
            }
            const emptyTemplateData = dashboard.templateListDataState({ bad: true });
            if (emptyTemplateData.templates.length !== 0 || emptyTemplateData.statePatch.templates.length !== 0) {
              throw new Error(`invalid template data should normalize to empty array: ${JSON.stringify(emptyTemplateData)}`);
            }
            const workspaceListQuery = dashboard.workspaceListQueryState();
            if (workspaceListQuery.workspacesPath !== "/api/workspaces") {
              throw new Error(`workspace list query mismatch: ${JSON.stringify(workspaceListQuery)}`);
            }
            const workspaceListData = dashboard.workspaceListDataState([{ path: "C:/ws/A.json" }]);
            if (workspaceListData.workspaces[0].path !== "C:/ws/A.json" || workspaceListData.statePatch.workspaces !== workspaceListData.workspaces) {
              throw new Error(`workspace list data state mismatch: ${JSON.stringify(workspaceListData)}`);
            }
            const emptyWorkspaceListData = dashboard.workspaceListDataState(null);
            if (emptyWorkspaceListData.workspaces.length !== 0 || emptyWorkspaceListData.statePatch.workspaces.length !== 0) {
              throw new Error(`invalid workspace data should normalize to empty array: ${JSON.stringify(emptyWorkspaceListData)}`);
            }
            const workspaceQuery = dashboard.workspaceLoadQueryState({ path: " F:/工作区/A & B " });
            const encodedPath = encodeURIComponent("F:/工作区/A & B");
            if (!workspaceQuery.ready || workspaceQuery.path !== "F:/工作区/A & B" || workspaceQuery.workspacePath !== `/api/workspace?path=${encodedPath}`) {
              throw new Error(`workspace load query mismatch: ${JSON.stringify(workspaceQuery)}`);
            }
            const missingWorkspaceQuery = dashboard.workspaceLoadQueryState({ path: " " });
            if (missingWorkspaceQuery.ready || missingWorkspaceQuery.message !== "请选择工作区。" || !missingWorkspaceQuery.workspacePath.includes("path=")) {
              throw new Error(`missing workspace load query mismatch: ${JSON.stringify(missingWorkspaceQuery)}`);
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
