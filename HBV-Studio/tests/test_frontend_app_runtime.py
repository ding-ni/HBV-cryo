import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendAppRuntimeTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_app_runtime_builds_lifecycle_request_states(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/appRuntime.js", "utf8"), context);

            const runtime = context.window.HBVStudioAppRuntime;
            if (!runtime?.healthQueryState || !runtime?.pollingScheduleState || !runtime?.quitRequestState || !runtime?.servicePillState || !runtime?.sidebarContextState || !runtime?.sidebarCountsState || !runtime?.viewNavigationState || !runtime?.viewSelectionState || !runtime?.windowUnloadRequestState) {
              throw new Error("app runtime module exports are missing");
            }

            const unload = runtime.windowUnloadRequestState();
            if (!unload.ready ||
                unload.method !== "POST" ||
                unload.requestPath !== "/api/app/window-unload" ||
                unload.body !== "{}" ||
                unload.contentType !== "application/json" ||
                unload.headers["Content-Type"] !== "application/json" ||
                unload.keepalive !== true ||
                Object.keys(unload.payload).length !== 0) {
              throw new Error(`window unload request state mismatch: ${JSON.stringify(unload)}`);
            }

            const unloadWithPayload = runtime.windowUnloadRequestState({ reason: "pagehide" });
            if (unloadWithPayload.body !== '{"reason":"pagehide"}' ||
                unloadWithPayload.payload.reason !== "pagehide") {
              throw new Error(`window unload payload should serialize JSON: ${JSON.stringify(unloadWithPayload)}`);
            }

            const unloadFallback = runtime.windowUnloadRequestState("bad-payload");
            if (unloadFallback.body !== "{}" || Object.keys(unloadFallback.payload).length !== 0) {
              throw new Error(`invalid unload payload should fall back to empty object: ${JSON.stringify(unloadFallback)}`);
            }

            const quit = runtime.quitRequestState();
            if (!quit.ready || quit.requestPath !== "/api/app/quit" || Object.keys(quit.payload).length !== 0) {
              throw new Error(`quit request state mismatch: ${JSON.stringify(quit)}`);
            }

            const health = runtime.healthQueryState();
            if (!health.ready || health.healthPath !== "/api/health") {
              throw new Error(`health query state mismatch: ${JSON.stringify(health)}`);
            }

            const idleWizardSchedule = runtime.pollingScheduleState({ currentView: "wizard", hasRunningTasks: false });
            if (idleWizardSchedule.hasRunningTasks ||
                idleWizardSchedule.currentView !== "wizard" ||
                idleWizardSchedule.immediateTaskRefreshDelayMs !== 0 ||
                idleWizardSchedule.nextTaskPollDelayMs !== 8000 ||
                idleWizardSchedule.shouldRefreshRuns ||
                idleWizardSchedule.nextRunPollDelayMs !== 20000) {
              throw new Error(`idle wizard polling schedule mismatch: ${JSON.stringify(idleWizardSchedule)}`);
            }

            const runningResultsSchedule = runtime.pollingScheduleState({ currentView: "results", hasRunningTasks: true });
            if (!runningResultsSchedule.hasRunningTasks ||
                runningResultsSchedule.currentView !== "results" ||
                runningResultsSchedule.immediateTaskRefreshDelayMs !== 1500 ||
                runningResultsSchedule.nextTaskPollDelayMs !== 3000 ||
                !runningResultsSchedule.shouldRefreshRuns ||
                runningResultsSchedule.nextRunPollDelayMs !== 12000) {
              throw new Error(`running polling schedule mismatch: ${JSON.stringify(runningResultsSchedule)}`);
            }

            for (const currentView of ["dashboard", "forecast", "results"]) {
              const schedule = runtime.pollingScheduleState({ currentView, hasRunningTasks: false });
              if (!schedule.shouldRefreshRuns ||
                  schedule.nextRunPollDelayMs !== 20000 ||
                  schedule.nextTaskPollDelayMs !== 8000 ||
                  schedule.immediateTaskRefreshDelayMs !== 0) {
                throw new Error(`idle refresh view schedule mismatch: ${JSON.stringify(schedule)}`);
              }
            }

            const legacyAliasSchedule = runtime.pollingScheduleState({ currentView: "calibration", hasRunning: true });
            if (!legacyAliasSchedule.hasRunningTasks ||
                !legacyAliasSchedule.shouldRefreshRuns ||
                legacyAliasSchedule.nextTaskPollDelayMs !== 3000 ||
                legacyAliasSchedule.nextRunPollDelayMs !== 12000) {
              throw new Error(`legacy hasRunning alias schedule mismatch: ${JSON.stringify(legacyAliasSchedule)}`);
            }

            const connectedPill = runtime.servicePillState(true, "本地服务已连接");
            if (!connectedPill.connected ||
                connectedPill.text !== "本地服务已连接" ||
                connectedPill.className !== "service-pill connected" ||
                connectedPill.domUpdates[0].selector !== "#service-pill" ||
                connectedPill.domUpdates[0].text !== "本地服务已连接" ||
                connectedPill.domUpdates[0].className !== "service-pill connected") {
              throw new Error(`connected service pill state mismatch: ${JSON.stringify(connectedPill)}`);
            }

            const errorPill = runtime.servicePillState(false, "连接失败");
            if (errorPill.connected ||
                errorPill.text !== "连接失败" ||
                errorPill.className !== "service-pill error" ||
                errorPill.domUpdates[0].className !== "service-pill error") {
              throw new Error(`error service pill state mismatch: ${JSON.stringify(errorPill)}`);
            }

            const counts = runtime.sidebarCountsState({
              templates: [{ id: "tpl-1" }, { id: "tpl-2" }],
              workspaces: [{ path: "ws" }],
              runs: [{ path: "run-1" }, { path: "run-2" }, { path: "run-3" }],
              tasks: [],
            });
            const countUpdates = Object.fromEntries(counts.domUpdates.map(update => [update.selector, update.text]));
            if (counts.counts.templates !== 2 ||
                counts.counts.workspaces !== 1 ||
                counts.counts.runs !== 3 ||
                counts.counts.tasks !== 0 ||
                countUpdates["#count-templates"] !== "2" ||
                countUpdates["#count-workspaces"] !== "1" ||
                countUpdates["#count-runs"] !== "3" ||
                countUpdates["#count-tasks"] !== "0") {
              throw new Error(`sidebar counts state mismatch: ${JSON.stringify(counts)}`);
            }

            const emptyCounts = runtime.sidebarCountsState({ templates: null, workspaces: {}, runs: "", tasks: undefined });
            if (emptyCounts.counts.templates !== 0 ||
                emptyCounts.counts.workspaces !== 0 ||
                emptyCounts.counts.runs !== 0 ||
                emptyCounts.counts.tasks !== 0) {
              throw new Error(`invalid sidebar counts should fall back to zero: ${JSON.stringify(emptyCounts)}`);
            }

            const emptyContext = runtime.sidebarContextState({}, {
              workspaceNextStepText() { return "—"; },
            });
            const emptyContextUpdates = Object.fromEntries(emptyContext.domUpdates.map(update => [update.selector, update.text]));
            if (emptyContext.context.workspaceText !== "未选择" ||
                emptyContext.context.profileText !== "未选择" ||
                emptyContext.context.objectText !== "未选择" ||
                emptyContext.context.workflowText !== "未检查" ||
                emptyContext.context.nextStepText !== "—" ||
                emptyContextUpdates["#sidebar-current-workspace"] !== "未选择" ||
                emptyContextUpdates["#sidebar-current-workflow"] !== "未检查") {
              throw new Error(`empty sidebar context mismatch: ${JSON.stringify(emptyContext)}`);
            }

            const sidebarContext = runtime.sidebarContextState({
              currentWorkspace: {
                "流域名称": "",
                "率定模式": "daily",
                "项目对象": "full_upstream_basin",
              },
              workspacePath: "C:/workspaces/A/config.json",
              workflow: {
                ready_for_calibration: false,
                pending_validation: true,
                completed_count: 4,
                total_steps: 7,
              },
            }, {
              objectLabels: { full_upstream_basin: "完整上游流域" },
              profileLabel(value) { return value === "daily" ? "日尺度" : "未选择"; },
              shortPath(value) { return String(value || "").split("/").pop(); },
              workspaceLabelByPath() { return ""; },
              workspaceNextStepText() { return "输入检查"; },
            });
            const contextUpdates = Object.fromEntries(sidebarContext.domUpdates.map(update => [update.selector, update.text]));
            if (sidebarContext.context.workspaceText !== "config.json" ||
                sidebarContext.context.profileText !== "日尺度" ||
                sidebarContext.context.objectText !== "完整上游流域" ||
                sidebarContext.context.workflowText !== "待检查 · 4/7" ||
                sidebarContext.context.nextStepText !== "输入检查" ||
                contextUpdates["#sidebar-current-profile"] !== "日尺度" ||
                contextUpdates["#sidebar-next-step"] !== "输入检查") {
              throw new Error(`sidebar context mismatch: ${JSON.stringify(sidebarContext)}`);
            }

            const readyContext = runtime.sidebarContextState({
              currentWorkspace: { "流域名称": "沱沱河", "率定模式": "hourly", "项目对象": "unknown" },
              workspacePath: "C:/workspaces/A/config.json",
              workflow: { ready_for_calibration: true, completed_count: 7, total_steps: 7 },
            }, {
              objectLabels: {},
              workspaceNextStepText() { return "可直接率定"; },
            });
            if (readyContext.context.workspaceText !== "沱沱河" ||
                readyContext.context.profileText !== "小时尺度" ||
                readyContext.context.objectText !== "未选择" ||
                readyContext.context.workflowText !== "可率定 · 7/7" ||
                readyContext.context.nextStepText !== "可直接率定") {
              throw new Error(`ready sidebar context mismatch: ${JSON.stringify(readyContext)}`);
            }

            const calibrationNavigation = runtime.viewNavigationState({
              currentView: "wizard",
              targetView: "calibration",
              workspacePath: " C:/ws/config.json ",
            });
            if (calibrationNavigation.currentView !== "wizard" ||
                calibrationNavigation.targetView !== "calibration" ||
                calibrationNavigation.workspacePath !== "C:/ws/config.json" ||
                !calibrationNavigation.shouldSaveWizardStep ||
                !calibrationNavigation.requiresCalibrationReadiness) {
              throw new Error(`calibration navigation state mismatch: ${JSON.stringify(calibrationNavigation)}`);
            }

            const resultsNavigation = runtime.viewNavigationState({
              currentView: "wizard",
              targetView: "results",
              workspacePath: "C:/ws/config.json",
            });
            if (!resultsNavigation.shouldSaveWizardStep || resultsNavigation.requiresCalibrationReadiness) {
              throw new Error(`results navigation state mismatch: ${JSON.stringify(resultsNavigation)}`);
            }

            const dashboardNavigation = runtime.viewNavigationState({
              currentView: "dashboard",
              targetView: "calibration",
              workspacePath: "C:/ws/config.json",
            });
            if (dashboardNavigation.shouldSaveWizardStep || dashboardNavigation.requiresCalibrationReadiness) {
              throw new Error(`dashboard navigation should not save wizard step: ${JSON.stringify(dashboardNavigation)}`);
            }

            const missingWorkspaceNavigation = runtime.viewNavigationState({
              currentView: "wizard",
              targetView: "calibration",
              workspacePath: " ",
            });
            if (missingWorkspaceNavigation.shouldSaveWizardStep || missingWorkspaceNavigation.requiresCalibrationReadiness) {
              throw new Error(`missing workspace navigation should not save wizard step: ${JSON.stringify(missingWorkspaceNavigation)}`);
            }

            const viewMeta = {
              dashboard: { title: "项目管理", subtitle: "管理工作区与内置模板" },
              results: { title: "结果分析", subtitle: "查看率定结果与诊断图表" },
            };
            const resultsView = runtime.viewSelectionState("results", viewMeta);
            const resultUpdates = Object.fromEntries(resultsView.domUpdates.map(update => [update.selector, update.text]));
            if (resultsView.requestedView !== "results" ||
                resultsView.selectedView !== "results" ||
                resultsView.title !== "结果分析" ||
                resultsView.subtitle !== "查看率定结果与诊断图表" ||
                resultUpdates["#page-title"] !== "结果分析" ||
                resultUpdates["#page-subtitle"] !== "查看率定结果与诊断图表") {
              throw new Error(`view selection state mismatch: ${JSON.stringify(resultsView)}`);
            }

            const fallbackView = runtime.viewSelectionState("missing", viewMeta);
            if (fallbackView.requestedView !== "missing" ||
                fallbackView.selectedView !== "dashboard" ||
                fallbackView.title !== "项目管理" ||
                fallbackView.subtitle !== "管理工作区与内置模板") {
              throw new Error(`view selection fallback mismatch: ${JSON.stringify(fallbackView)}`);
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
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
