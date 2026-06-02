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
            for (const name of [
              "forecastInputCheckDelay",
              "forecastInputCheckTimerState",
              "forecastInputType",
              "forecastSuggestedStart",
              "forecastTimeComparable",
              "formatForecastInputTime",
              "parseForecastTime",
            ]) {
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
            if (view.forecastInputCheckDelay(0) !== 0) throw new Error("zero delay should stay immediate");
            if (view.forecastInputCheckDelay(undefined) !== 350) throw new Error("missing delay should use default");
            if (view.forecastInputCheckDelay("bad") !== 350) throw new Error("invalid delay should use default");
            if (view.forecastInputCheckDelay(-1) !== 350) throw new Error("negative delay should use default");
            const timer = { id: 12 };
            const timerState = view.forecastInputCheckTimerState(timer);
            if (timerState.statePatch.forecastInputCheckTimer !== timer) {
              throw new Error(`timer state should keep timer reference: ${JSON.stringify(timerState)}`);
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
    def test_forecast_source_candidate_and_readiness_helpers(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            for (const name of [
              "forecastCandidateRuns",
              "forecastRunReady",
              "forecastRunReadinessText",
              "pickForecastSourceRun",
              "forecastSelectedSourceRun",
              "forecastSourceOptionsState",
              "forecastSourceButtonState",
              "forecastSourceSelectionState",
            ]) {
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

            const samePath = (a, b) => String(a || "").toLowerCase() === String(b || "").toLowerCase();
            const selected = view.forecastSelectedSourceRun(candidates, "c:/RUNS/manual", { samePath });
            if (selected?.id !== "manual-ready") throw new Error(`selected source mismatch: ${selected?.id}`);
            if (view.forecastSelectedSourceRun(candidates, "C:/runs/missing", { samePath }) !== null) {
              throw new Error("missing source path should not fallback");
            }
            if (view.forecastSelectedSourceRun(candidates, "", { samePath }) !== null) {
              throw new Error("empty source path should not fallback");
            }
            const selectionState = view.forecastSourceSelectionState(" C:/runs/manual ");
            if (selectionState.statePatch.forecastSourceRunPath !== "C:/runs/manual") {
              throw new Error(`source selection state wrong: ${JSON.stringify(selectionState)}`);
            }
            const emptySelectionState = view.forecastSourceSelectionState(null);
            if (emptySelectionState.statePatch.forecastSourceRunPath !== "") {
              throw new Error(`empty source selection state wrong: ${JSON.stringify(emptySelectionState)}`);
            }
            const sourceOptions = view.forecastSourceOptionsState(candidates, "c:/RUNS/manual", { samePath, forecastRunReady: view.forecastRunReady });
            if (sourceOptions.selected?.id !== "manual-ready" || sourceOptions.selectedPath !== "C:/runs/manual" ||
                sourceOptions.statePatch.forecastSourceRunPath !== "C:/runs/manual") {
              throw new Error(`source options preferred state wrong: ${JSON.stringify(sourceOptions)}`);
            }
            const fallbackOptions = view.forecastSourceOptionsState(candidates, "C:/runs/missing", { samePath, forecastRunReady: view.forecastRunReady });
            if (fallbackOptions.selected?.id !== "cal-ready" || fallbackOptions.selectedPath !== "C:/runs/cal") {
              throw new Error(`source options ready fallback wrong: ${JSON.stringify(fallbackOptions)}`);
            }
            const emptyButtons = view.forecastSourceButtonState(null);
            if (!emptyButtons.openSourceDisabled || !emptyButtons.startDisabled) {
              throw new Error(`empty source buttons wrong: ${JSON.stringify(emptyButtons)}`);
            }
            const emptyButtonDom = Object.fromEntries(emptyButtons.domUpdates.map(update => [update.selector, update]));
            if (emptyButtonDom["#forecast-open-source"].disabled !== true ||
                emptyButtonDom["#forecast-start-button"].disabled !== true) {
              throw new Error(`empty source button DOM updates wrong: ${JSON.stringify(emptyButtonDom)}`);
            }
            const readyButtons = view.forecastSourceButtonState(runs[1]);
            if (readyButtons.openSourceDisabled || readyButtons.startDisabled) {
              throw new Error(`ready source buttons wrong: ${JSON.stringify(readyButtons)}`);
            }
            const readyButtonDom = Object.fromEntries(readyButtons.domUpdates.map(update => [update.selector, update]));
            if (readyButtonDom["#forecast-open-source"].disabled !== false ||
                readyButtonDom["#forecast-start-button"].disabled !== false) {
              throw new Error(`ready source button DOM updates wrong: ${JSON.stringify(readyButtonDom)}`);
            }
            const blockedButtons = view.forecastSourceButtonState(runs[3]);
            if (blockedButtons.openSourceDisabled || !blockedButtons.startDisabled) {
              throw new Error(`blocked source buttons wrong: ${JSON.stringify(blockedButtons)}`);
            }
            const blockedButtonDom = Object.fromEntries(blockedButtons.domUpdates.map(update => [update.selector, update]));
            if (blockedButtonDom["#forecast-open-source"].disabled !== false ||
                blockedButtonDom["#forecast-start-button"].disabled !== true) {
              throw new Error(`blocked source button DOM updates wrong: ${JSON.stringify(blockedButtonDom)}`);
            }
            const preferred = view.pickForecastSourceRun(candidates, "c:/RUNS/manual", { samePath });
            if (preferred?.id !== "manual-ready") throw new Error(`preferred source mismatch: ${preferred?.id}`);
            const fallbackReady = view.pickForecastSourceRun(candidates, "", { samePath });
            if (fallbackReady?.id !== "cal-ready") throw new Error(`ready fallback mismatch: ${fallbackReady?.id}`);
            const fallbackFirst = view.pickForecastSourceRun([
              { id: "blocked-first", path: "C:/runs/blocked", forecast_source_ready: false },
              { id: "blocked-second", path: "C:/runs/blocked2", forecast_source_ready: false },
            ], "", { samePath });
            if (fallbackFirst?.id !== "blocked-first") throw new Error(`first fallback mismatch: ${fallbackFirst?.id}`);
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
    def test_forecast_result_selection_helpers_filter_sort_and_fallback(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            for (const name of [
              "forecastResultRuns",
              "forecastSelectedResultRun",
              "forecastCompletedResultState",
              "forecastResultDetailState",
              "forecastResultLoadErrorState",
              "forecastResultLoadStartState",
              "forecastResultLoadSuccessState",
              "forecastResultPanelState",
              "forecastResultSelectionState",
              "renderForecastResultOptions",
            ]) {
              if (typeof view?.[name] !== "function") throw new Error(`missing forecast result export: ${name}`);
            }

            const runs = [
              { id: "cal", path: "C:/runs/cal", kind: "calibration", updated_at: 999 },
              { id: "forecast-old", path: "C:/runs/forecast-old", kind: "forecast_restart", updated_at: 10 },
              { id: "forecast-empty", path: "", kind: "forecast_restart", updated_at: 200 },
              { id: "forecast-new", path: "C:/runs/forecast-new", kind: "forecast_restart", updated_at: 30 },
              { id: "forecast-mid", path: "C:/runs/forecast-mid", kind: "forecast_restart", updated_at: 20 },
            ];
            const forecastRuns = view.forecastResultRuns(runs, { runTypeValue: run => run.kind });
            const ids = forecastRuns.map(run => run.id).join(",");
            if (ids !== "forecast-new,forecast-mid,forecast-old") {
              throw new Error(`unexpected forecast result order: ${ids}`);
            }

            const samePath = (a, b) => String(a || "").toLowerCase() === String(b || "").toLowerCase();
            const selected = view.forecastSelectedResultRun(forecastRuns, "c:/RUNS/forecast-mid", { samePath });
            if (selected?.id !== "forecast-mid") throw new Error(`selected result mismatch: ${selected?.id}`);
            const fallback = view.forecastSelectedResultRun(forecastRuns, "C:/runs/missing", { samePath });
            if (fallback?.id !== "forecast-new") throw new Error(`fallback result mismatch: ${fallback?.id}`);
            if (view.forecastSelectedResultRun([], "", { samePath }) !== null) throw new Error("empty result list should return null");

            const emptyPanel = view.forecastResultPanelState([], "C:/runs/forecast-mid", {
              currentData: { run: { path: "C:/runs/forecast-mid" } },
              loadingPath: "C:/runs/forecast-mid",
            }, { samePath });
            if (emptyPanel.hasRuns || emptyPanel.renderMode !== "empty" || emptyPanel.selectedPath !== "" || !emptyPanel.selectDisabled) {
              throw new Error(`empty panel state wrong: ${JSON.stringify(emptyPanel)}`);
            }
            if (emptyPanel.statePatch.forecastResultRunPath !== "" ||
                emptyPanel.statePatch.forecastResultData !== null ||
                emptyPanel.statePatch.forecastResultLoadingPath !== "" ||
                emptyPanel.statePatch.lastForecastExportPath !== "") {
              throw new Error(`empty panel patch should clear result state: ${JSON.stringify(emptyPanel.statePatch)}`);
            }

            const detailPanel = view.forecastResultPanelState(forecastRuns, "c:/RUNS/forecast-mid", {
              currentData: { run: { path: "C:/runs/forecast-mid" } },
              loadingPath: "",
            }, { samePath });
            if (detailPanel.selected?.id !== "forecast-mid" || detailPanel.renderMode !== "detail" || detailPanel.loadPath !== "") {
              throw new Error(`detail panel state wrong: ${JSON.stringify(detailPanel)}`);
            }
            if (detailPanel.statePatch.forecastResultRunPath !== "C:/runs/forecast-mid" ||
                Object.prototype.hasOwnProperty.call(detailPanel.statePatch, "forecastResultData") ||
                Object.prototype.hasOwnProperty.call(detailPanel.statePatch, "forecastResultLoadingPath") ||
                Object.prototype.hasOwnProperty.call(detailPanel.statePatch, "lastForecastExportPath")) {
              throw new Error(`detail panel patch should only select path: ${JSON.stringify(detailPanel.statePatch)}`);
            }

            const loadingPanel = view.forecastResultPanelState(forecastRuns, "C:/runs/forecast-old", {
              currentData: null,
              loadingPath: "c:/RUNS/forecast-old",
            }, { samePath });
            if (loadingPanel.selected?.id !== "forecast-old" || loadingPanel.renderMode !== "loading" || loadingPanel.loadPath !== "") {
              throw new Error(`loading panel state wrong: ${JSON.stringify(loadingPanel)}`);
            }
            if (loadingPanel.statePatch.forecastResultRunPath !== "C:/runs/forecast-old" ||
                Object.prototype.hasOwnProperty.call(loadingPanel.statePatch, "forecastResultLoadingPath")) {
              throw new Error(`loading panel patch should not clear loading state: ${JSON.stringify(loadingPanel.statePatch)}`);
            }

            const loadPanel = view.forecastResultPanelState(forecastRuns, "C:/runs/missing", {
              currentData: { run: { path: "C:/runs/forecast-old" } },
              loadingPath: "",
            }, { samePath });
            if (loadPanel.selected?.id !== "forecast-new" || loadPanel.renderMode !== "load" || loadPanel.loadPath !== "C:/runs/forecast-new") {
              throw new Error(`load panel state wrong: ${JSON.stringify(loadPanel)}`);
            }
            if (loadPanel.statePatch.forecastResultRunPath !== "C:/runs/forecast-new" ||
                Object.prototype.hasOwnProperty.call(loadPanel.statePatch, "forecastResultData")) {
              throw new Error(`load panel patch should only select path: ${JSON.stringify(loadPanel.statePatch)}`);
            }

            const detailState = view.forecastResultDetailState({
              run: { id: "detail-run", path: "C:/runs/detail" },
              series: { dates: ["2026-06-01"] },
            }, { id: "selected-run", path: "C:/runs/selected" });
            if (detailState.renderMode !== "detail" || detailState.buttonRun?.id !== "detail-run" || !detailState.detailData?.series?.dates?.length) {
              throw new Error(`detail state wrong: ${JSON.stringify(detailState)}`);
            }

            const emptyDetailState = view.forecastResultDetailState({}, { id: "selected-run", path: "C:/runs/selected" });
            if (emptyDetailState.renderMode !== "empty" || emptyDetailState.buttonRun?.id !== "selected-run" || emptyDetailState.detailData !== null) {
              throw new Error(`empty detail state should keep selected run buttons: ${JSON.stringify(emptyDetailState)}`);
            }

            const emptyNoRunState = view.forecastResultDetailState(null, null);
            if (emptyNoRunState.renderMode !== "empty" || emptyNoRunState.buttonRun !== null || emptyNoRunState.detailData !== null) {
              throw new Error(`empty no-run detail state wrong: ${JSON.stringify(emptyNoRunState)}`);
            }

            const emptyLoadStart = view.forecastResultLoadStartState(" ");
            if (emptyLoadStart.ok || emptyLoadStart.targetPath !== "" || emptyLoadStart.statePatch !== null) {
              throw new Error(`empty load start state wrong: ${JSON.stringify(emptyLoadStart)}`);
            }

            const loadStart = view.forecastResultLoadStartState(" C:/runs/forecast-new ");
            if (!loadStart.ok || loadStart.targetPath !== "C:/runs/forecast-new" || loadStart.buttonRun?.path !== "C:/runs/forecast-new") {
              throw new Error(`load start state wrong: ${JSON.stringify(loadStart)}`);
            }
            if (loadStart.statePatch.forecastResultRunPath !== "C:/runs/forecast-new" ||
                loadStart.statePatch.forecastResultLoadingPath !== "C:/runs/forecast-new" ||
                loadStart.statePatch.lastForecastExportPath !== "") {
              throw new Error(`load start patch wrong: ${JSON.stringify(loadStart.statePatch)}`);
            }

            const loadSuccess = view.forecastResultLoadSuccessState({ run: { path: "C:/runs/forecast-new" } });
            if (loadSuccess.statePatch.forecastResultData?.run?.path !== "C:/runs/forecast-new" ||
                loadSuccess.statePatch.forecastResultLoadingPath !== "" ||
                loadSuccess.detailData?.run?.path !== "C:/runs/forecast-new") {
              throw new Error(`load success state wrong: ${JSON.stringify(loadSuccess)}`);
            }

            const loadError = view.forecastResultLoadErrorState(new Error("failed"));
            if (loadError.statePatch.forecastResultData !== null ||
                loadError.statePatch.forecastResultLoadingPath !== "" ||
                loadError.buttonRun !== null) {
              throw new Error(`load error state wrong: ${JSON.stringify(loadError)}`);
            }

            const selectionState = view.forecastResultSelectionState(" C:/runs/forecast-mid ");
            if (selectionState.statePatch.forecastResultRunPath !== "C:/runs/forecast-mid" ||
                selectionState.statePatch.forecastResultData !== null ||
                selectionState.statePatch.forecastResultLoadingPath !== "" ||
                selectionState.statePatch.lastForecastExportPath !== "") {
              throw new Error(`selection state wrong: ${JSON.stringify(selectionState)}`);
            }

            const emptySelectionState = view.forecastResultSelectionState(null);
            if (emptySelectionState.statePatch.forecastResultRunPath !== "" ||
                emptySelectionState.statePatch.forecastResultData !== null ||
                emptySelectionState.statePatch.forecastResultLoadingPath !== "" ||
                emptySelectionState.statePatch.lastForecastExportPath !== "") {
              throw new Error(`empty selection state wrong: ${JSON.stringify(emptySelectionState)}`);
            }

            const completedFromResult = view.forecastCompletedResultState({
              result: { run_path: " C:/runs/from-result " },
              run_path: "C:/runs/from-task",
              detected_runs: ["C:/runs/from-detected"],
            });
            if (!completedFromResult.ok || completedFromResult.runPath !== "C:/runs/from-result" ||
                completedFromResult.statePatch.forecastResultRunPath !== "C:/runs/from-result" ||
                completedFromResult.statePatch.forecastResultData !== null ||
                completedFromResult.statePatch.forecastResultLoadingPath !== "" ||
                completedFromResult.statePatch.lastForecastExportPath !== "") {
              throw new Error(`completed result path state wrong: ${JSON.stringify(completedFromResult)}`);
            }

            const completedFromRun = view.forecastCompletedResultState({
              run_path: " C:/runs/from-task ",
              detected_runs: ["C:/runs/from-detected"],
            });
            if (!completedFromRun.ok || completedFromRun.runPath !== "C:/runs/from-task") {
              throw new Error(`completed task run_path fallback wrong: ${JSON.stringify(completedFromRun)}`);
            }

            const completedFromDetected = view.forecastCompletedResultState({
              detected_runs: [" C:/runs/from-detected "],
            });
            if (!completedFromDetected.ok || completedFromDetected.runPath !== "C:/runs/from-detected") {
              throw new Error(`completed detected run fallback wrong: ${JSON.stringify(completedFromDetected)}`);
            }

            const completedMissing = view.forecastCompletedResultState({ detected_runs: [] });
            if (completedMissing.ok || completedMissing.runPath !== "" || completedMissing.statePatch !== null) {
              throw new Error(`completed missing state wrong: ${JSON.stringify(completedMissing)}`);
            }

            const rendered = view.renderForecastResultOptions([
              {
                path: "C:/runs/forecast<A>",
                display_name: "预报<A>",
                time_config: { forecast_start: "2026-06-01", forecast_end: "2026-06-03", time_step_hours: 24 },
              },
              {
                path: "C:/runs/forecast-b",
                display_name: "预报B · 2026-06-04 至 2026-06-05",
                time_config: { forecast_start: "2026-06-04", forecast_end: "2026-06-05", time_step_hours: 24 },
              },
            ], "c:/RUNS/forecast<a>", {
              escapeHtml(value) {
                return String(value ?? "").replace(/[&<>"']/g, ch => ({
                  "&": "&amp;",
                  "<": "&lt;",
                  ">": "&gt;",
                  "\"": "&quot;",
                  "'": "&#39;",
                }[ch]));
              },
              forecastFriendlyRunName(run) { return run.display_name || "结果"; },
              samePath,
              timeRangeText(start, end) { return start && end ? `${start} 至 ${end}` : "—"; },
            });
            if (rendered.selected?.path !== "C:/runs/forecast<A>") throw new Error(`rendered selected mismatch: ${rendered.selected?.path}`);
            if (!rendered.html.includes('value="C:/runs/forecast&lt;A&gt;" selected')) {
              throw new Error(`selected escaped option missing: ${rendered.html}`);
            }
            if (!rendered.html.includes("预报&lt;A&gt; · 2026-06-01 至 2026-06-03")) {
              throw new Error(`range label missing or not escaped: ${rendered.html}`);
            }
            if ((rendered.html.match(/2026-06-04 至 2026-06-05/g) || []).length !== 1) {
              throw new Error(`range should not be duplicated when friendly name already contains it: ${rendered.html}`);
            }
            const renderedDom = Object.fromEntries(rendered.domUpdates.map(update => [update.selector, update]));
            if (renderedDom["#forecast-result-run"].disabled !== false ||
                renderedDom["#forecast-result-run"].html !== rendered.html) {
              throw new Error(`result options DOM updates wrong: ${JSON.stringify(renderedDom)}`);
            }
            const emptyRendered = view.renderForecastResultOptions([], "", { samePath });
            if (emptyRendered.selected !== null || !emptyRendered.disabled || !emptyRendered.html.includes("暂无连续状态预报结果")) {
              throw new Error(`empty result options wrong: ${JSON.stringify(emptyRendered)}`);
            }
            const emptyRenderedDom = Object.fromEntries(emptyRendered.domUpdates.map(update => [update.selector, update]));
            if (emptyRenderedDom["#forecast-result-run"].disabled !== true ||
                emptyRenderedDom["#forecast-result-run"].html !== emptyRendered.html) {
              throw new Error(`empty result options DOM updates wrong: ${JSON.stringify(emptyRenderedDom)}`);
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
    def test_forecast_input_payload_normalizes_form_fields(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            if (typeof view?.forecastInputPayload !== "function") {
              throw new Error("missing forecast input payload export");
            }

            const payload = view.forecastInputPayload({
              path: " C:/runs/source ",
              workspace_config: " C:/workspaces/source.json ",
              time_config: { time_step_hours: 1 },
            }, {
              forecast_start: " 2026-02-01T00:00 ",
              forecast_end: " 2026-02-02T00:00 ",
              forecast_prec_dir: " C:/meteo/prec ",
              forecast_temp_dir: " C:/meteo/temp ",
              forecast_evap_dir: " C:/meteo/evap ",
            }, { fallbackConfigPath: "C:/workspaces/fallback.json" });

            const expected = {
              source_run: "C:/runs/source",
              config_path: "C:/workspaces/source.json",
              forecast_start: "2026-02-01T00:00",
              forecast_end: "2026-02-02T00:00",
              forecast_prec_dir: "C:/meteo/prec",
              forecast_temp_dir: "C:/meteo/temp",
              forecast_evap_dir: "C:/meteo/evap",
              time_step_hours: 1,
            };
            for (const [key, value] of Object.entries(expected)) {
              if (payload[key] !== value) throw new Error(`${key} mismatch: ${payload[key]} !== ${value}`);
            }

            const fallback = view.forecastInputPayload({
              path: "C:/runs/no-workspace",
            }, {}, { fallbackConfigPath: " C:/workspaces/fallback.json " });
            if (fallback.config_path !== "C:/workspaces/fallback.json") throw new Error(`fallback config wrong: ${fallback.config_path}`);
            if (fallback.time_step_hours !== 24) throw new Error(`default step hours wrong: ${fallback.time_step_hours}`);
            if (fallback.forecast_prec_dir !== "" || fallback.forecast_temp_dir !== "" || fallback.forecast_evap_dir !== "") {
              throw new Error("missing directory fields should normalize to empty strings");
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
    def test_forecast_input_check_error_summary_is_stable(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            if (typeof view?.forecastInputCheckError !== "function") {
              throw new Error("missing forecast input check error helper");
            }

            const check = view.forecastInputCheckError(new Error("目录无法读取"));
            if (check.status !== "fail") throw new Error(`status mismatch: ${check.status}`);
            if (check.headline !== "预报气象输入检查失败。") throw new Error(`headline mismatch: ${check.headline}`);
            if (check.errors.length !== 1 || check.errors[0] !== "目录无法读取") throw new Error(`error message mismatch: ${check.errors}`);
            if (check.warnings.length || check.items.length || check.variables.length) {
              throw new Error(`detail arrays should be empty: ${JSON.stringify(check)}`);
            }

            const fallback = view.forecastInputCheckError({});
            if (fallback.errors[0] !== "预报气象输入检查失败。") throw new Error(`fallback message wrong: ${fallback.errors[0]}`);
            const textError = view.forecastInputCheckError("手动错误");
            if (textError.errors[0] !== "手动错误") throw new Error(`text message wrong: ${textError.errors[0]}`);
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
    def test_forecast_input_check_decision_blocks_failures_and_surfaces_warnings(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            if (typeof view?.forecastInputCheckDecision !== "function") {
              throw new Error("missing forecast input check decision helper");
            }

            const missing = view.forecastInputCheckDecision(null);
            if (!missing.blocked || !missing.isError || missing.message !== "预报气象输入检查未通过。") {
              throw new Error(`missing check decision wrong: ${JSON.stringify(missing)}`);
            }

            const failed = view.forecastInputCheckDecision({ status: "fail", errors: ["未来降水缺失"] });
            if (!failed.blocked || !failed.isError || failed.message !== "未来降水缺失") {
              throw new Error(`failed check decision wrong: ${JSON.stringify(failed)}`);
            }

            const warning = view.forecastInputCheckDecision({ status: "warn", warnings: ["窗口外文件会被忽略"] });
            if (warning.blocked || warning.isError || warning.message !== "窗口外文件会被忽略") {
              throw new Error(`warning check decision wrong: ${JSON.stringify(warning)}`);
            }

            const defaultWarning = view.forecastInputCheckDecision({ status: "warn", warnings: [] });
            if (defaultWarning.blocked || defaultWarning.isError || !defaultWarning.message.includes("按预报窗口筛选归档")) {
              throw new Error(`default warning wrong: ${JSON.stringify(defaultWarning)}`);
            }

            const ok = view.forecastInputCheckDecision({ status: "ok" });
            if (ok.blocked || ok.isError || ok.message !== "") {
              throw new Error(`ok decision wrong: ${JSON.stringify(ok)}`);
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
    def test_forecast_restart_payload_uses_run_and_context_metadata(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            if (typeof view?.forecastRestartPayload !== "function") {
              throw new Error("missing forecast restart payload export");
            }

            const payload = view.forecastRestartPayload({
              path: " C:/runs/source ",
              workspace_config: "",
              objective_family: "daily_unified_professional_v1",
            }, {
              forecast_start: " 2026-03-01 ",
              forecast_end: " 2026-03-10 ",
              forecast_prec_dir: " C:/forecast/prec ",
              forecast_temp_dir: " C:/forecast/temp ",
              forecast_evap_dir: " C:/forecast/evap ",
              glacier_mode: " external ",
            }, {
              fallbackConfigPath: " C:/workspaces/current.json ",
              profile: " daily ",
              defaultObjectiveMode: "fallback_objective",
            });

            const expected = {
              source_run: "C:/runs/source",
              config_path: "C:/workspaces/current.json",
              forecast_start: "2026-03-01",
              forecast_end: "2026-03-10",
              forecast_prec_dir: "C:/forecast/prec",
              forecast_temp_dir: "C:/forecast/temp",
              forecast_evap_dir: "C:/forecast/evap",
              profile: "daily",
              objective_mode: "daily_unified_professional_v1",
              prec_source: "custom_tif",
              glacier_mode: "external",
            };
            for (const [key, value] of Object.entries(expected)) {
              if (payload[key] !== value) throw new Error(`${key} mismatch: ${payload[key]} !== ${value}`);
            }
            if ("time_step_hours" in payload) throw new Error("restart payload should not include input-check-only time_step_hours");

            const fallback = view.forecastRestartPayload({
              path: "C:/runs/source2",
            }, {
              glacier_mode: "",
            }, {
              profile: "",
              defaultObjectiveMode: "daily_unified_professional_v1",
            });
            if (fallback.objective_mode !== "daily_unified_professional_v1") throw new Error(`fallback objective wrong: ${fallback.objective_mode}`);
            if (fallback.glacier_mode !== "inline") throw new Error(`fallback glacier mode wrong: ${fallback.glacier_mode}`);
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
    def test_forecast_restart_preflight_reports_blocking_inputs(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            if (typeof view?.forecastRestartPreflight !== "function") {
              throw new Error("missing forecast restart preflight export");
            }

            const readyRun = {
              path: "C:/runs/source",
              studio_compatible: true,
              time_step_hours: 24,
              state_snapshot_time: "2026-01-10",
            };
            const validFields = {
              forecast_start: "2026-01-11",
              forecast_end: "2026-01-20",
              forecast_prec_dir: "C:/forecast/prec",
              forecast_temp_dir: "C:/forecast/temp",
              forecast_evap_dir: "C:/forecast/evap",
            };

            const cases = [
              [null, validFields, "请先选择源结果。"],
              [{ path: "C:/runs/source", forecast_source_ready: false }, validFields, "源结果缺少率定参数或起报状态"],
              [readyRun, { ...validFields, forecast_end: "" }, "请填写预报结束时间。"],
              [readyRun, { ...validFields, forecast_start: "2026-01-12" }, "当前应从 2026-01-11 起报"],
              [readyRun, { ...validFields, forecast_temp_dir: " " }, "请完整选择预报降水"],
            ];
            for (const [run, fields, message] of cases) {
              const result = view.forecastRestartPreflight(run, fields);
              if (result.ok || !result.message.includes(message)) {
                throw new Error(`unexpected preflight result for ${message}: ${JSON.stringify(result)}`);
              }
            }

            const ok = view.forecastRestartPreflight(readyRun, validFields);
            if (!ok.ok || ok.message !== "" || ok.expectedStart !== "2026-01-11") {
              throw new Error(`valid preflight wrong: ${JSON.stringify(ok)}`);
            }
            const autoStartOk = view.forecastRestartPreflight(readyRun, { ...validFields, forecast_start: "" });
            if (!autoStartOk.ok) throw new Error(`empty start should be allowed: ${JSON.stringify(autoStartOk)}`);
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
    def test_forecast_result_export_payload_uses_metadata_and_boundary_fields(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            if (typeof view?.forecastResultExportPayload !== "function") {
              throw new Error("missing forecast result export payload helper");
            }

            const payload = view.forecastResultExportPayload({
              run: { path: " C:/runs/forecast-result " },
              metadata: {
                time_config: { forecast_start: "2026-04-01", forecast_end: "2026-04-10" },
                boundary: { enabled: true },
              },
              series: { dates: ["2026-04-02", "2026-04-09"] },
            }, null, {
              boundaryEnabledFromMeta(meta) { return Boolean(meta.boundary?.enabled); },
            });
            if (payload.path !== "C:/runs/forecast-result") throw new Error(`path mismatch: ${payload.path}`);
            if (payload.start_date !== "2026-04-01" || payload.end_date !== "2026-04-10") {
              throw new Error(`metadata date range mismatch: ${payload.start_date} ${payload.end_date}`);
            }
            if (payload.fields.join(",") !== "q_sim,q_rain,q_snow,q_ice,q_boundary_inflow") {
              throw new Error(`boundary field missing: ${payload.fields.join(",")}`);
            }

            const fallback = view.forecastResultExportPayload({
              metadata: { forecast_result: { forecast_start: "2026-05-01" } },
              series: { dates: ["2026-05-02", "2026-05-03"] },
            }, { path: "C:/runs/selected-result" });
            if (fallback.path !== "C:/runs/selected-result") throw new Error(`selected run path fallback wrong: ${fallback.path}`);
            if (fallback.start_date !== "2026-05-01" || fallback.end_date !== "2026-05-03") {
              throw new Error(`fallback date range wrong: ${fallback.start_date} ${fallback.end_date}`);
            }
            if (fallback.fields.join(",") !== "q_sim,q_rain,q_snow,q_ice") {
              throw new Error(`default fields wrong: ${fallback.fields.join(",")}`);
            }

            if (view.forecastResultExportPayload({ series: { dates: ["2026-01-01"] } }, null) !== null) {
              throw new Error("missing run path should return null");
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
    def test_forecast_result_export_success_text_uses_display_path_or_short_path(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            if (typeof view?.forecastResultExportSuccess !== "function") {
              throw new Error("missing forecast result export success helper");
            }
            if (typeof view?.forecastResultExportState !== "function") {
              throw new Error("missing forecast result export state helper");
            }

            const exportState = view.forecastResultExportState({ path: "C:/exports/forecast.xlsx" });
            if (exportState.exportPath !== "C:/exports/forecast.xlsx" ||
                exportState.statePatch.lastForecastExportPath !== "C:/exports/forecast.xlsx") {
              throw new Error(`export state wrong: ${JSON.stringify(exportState)}`);
            }

            const emptyExportState = view.forecastResultExportState({});
            if (emptyExportState.exportPath !== "" || emptyExportState.statePatch.lastForecastExportPath !== "") {
              throw new Error(`empty export state wrong: ${JSON.stringify(emptyExportState)}`);
            }

            const explicit = view.forecastResultExportSuccess({
              row_count: 12,
              display_path: "预报导出.xlsx",
            }, "C:/exports/fallback.xlsx", {
              shortPath(value) { return String(value).split(/[\\/]/).pop(); },
            });
            if (explicit.rowCount !== 12 || explicit.displayPath !== "预报导出.xlsx") {
              throw new Error(`explicit export text wrong: ${JSON.stringify(explicit)}`);
            }
            if (explicit.hintText !== "已导出 12 行到 预报导出.xlsx。") throw new Error(`hint wrong: ${explicit.hintText}`);
            if (explicit.hintClassName !== "hint-box status-ok") throw new Error(`hint class wrong: ${explicit.hintClassName}`);
            if (explicit.toastText !== "预报结果 Excel 已导出：12 行") throw new Error(`toast wrong: ${explicit.toastText}`);
            const explicitDom = Object.fromEntries(explicit.domUpdates.map(update => [update.selector, update]));
            if (explicitDom["#forecast-result-hint"].text !== "已导出 12 行到 预报导出.xlsx。" ||
                explicitDom["#forecast-result-hint"].className !== "hint-box status-ok") {
              throw new Error(`explicit export DOM updates wrong: ${JSON.stringify(explicitDom)}`);
            }

            const fallback = view.forecastResultExportSuccess({}, "C:/exports/fallback.xlsx", {
              shortPath(value) { return String(value).split(/[\\/]/).pop(); },
            });
            if (fallback.rowCount !== 0 || fallback.displayPath !== "fallback.xlsx") {
              throw new Error(`fallback export text wrong: ${JSON.stringify(fallback)}`);
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
    def test_forecast_result_button_state_tracks_run_and_export_availability(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/forecastView.js", "utf8"), context);

            const view = context.window.HBVStudioForecastView;
            if (typeof view?.forecastResultButtonState !== "function") {
              throw new Error("missing forecast result button state helper");
            }

            const empty = view.forecastResultButtonState(null, "");
            if (!empty.openResultDisabled || !empty.openResultDirDisabled || !empty.exportExcelDisabled || !empty.openExportFileDisabled) {
              throw new Error(`empty state should disable every button: ${JSON.stringify(empty)}`);
            }
            const emptyDom = Object.fromEntries(empty.domUpdates.map(update => [update.selector, update]));
            if (emptyDom["#forecast-open-result"].disabled !== true ||
                emptyDom["#forecast-open-result-dir"].disabled !== true ||
                emptyDom["#forecast-export-excel"].disabled !== true ||
                emptyDom["#forecast-open-export-file"].disabled !== true) {
              throw new Error(`empty button DOM updates wrong: ${JSON.stringify(emptyDom)}`);
            }

            const withRun = view.forecastResultButtonState({ path: "C:/runs/forecast" }, "");
            if (withRun.openResultDisabled || withRun.openResultDirDisabled || withRun.exportExcelDisabled || !withRun.openExportFileDisabled) {
              throw new Error(`run state should enable result buttons only: ${JSON.stringify(withRun)}`);
            }

            const withExport = view.forecastResultButtonState({ path: "C:/runs/forecast" }, "C:/exports/forecast.xlsx");
            if (withExport.openResultDisabled || withExport.openResultDirDisabled || withExport.exportExcelDisabled || withExport.openExportFileDisabled) {
              throw new Error(`export state should enable every button: ${JSON.stringify(withExport)}`);
            }
            const withExportDom = Object.fromEntries(withExport.domUpdates.map(update => [update.selector, update]));
            if (withExportDom["#forecast-open-result"].disabled !== false ||
                withExportDom["#forecast-open-result-dir"].disabled !== false ||
                withExportDom["#forecast-export-excel"].disabled !== false ||
                withExportDom["#forecast-open-export-file"].disabled !== false) {
              throw new Error(`export button DOM updates wrong: ${JSON.stringify(withExportDom)}`);
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
            const optionsDom = Object.fromEntries(options.domUpdates.map(update => [update.selector, update]));
            if (optionsDom["#forecast-source-run"].disabled !== false ||
                optionsDom["#forecast-source-run"].html !== options.html) {
              throw new Error(`source option DOM updates wrong: ${JSON.stringify(optionsDom)}`);
            }
            const emptyOptions = view.renderForecastSourceOptions([], "", helpers);
            if (!emptyOptions.disabled || !emptyOptions.html.includes("暂无可选源结果")) {
              throw new Error(`empty options wrong: ${JSON.stringify(emptyOptions)}`);
            }
            const emptyOptionsDom = Object.fromEntries(emptyOptions.domUpdates.map(update => [update.selector, update]));
            if (emptyOptionsDom["#forecast-source-run"].disabled !== true ||
                emptyOptionsDom["#forecast-source-run"].html !== emptyOptions.html) {
              throw new Error(`empty source option DOM updates wrong: ${JSON.stringify(emptyOptionsDom)}`);
            }

            const emptySummary = view.renderForecastSourceSummary(null, helpers);
            if (emptySummary.ready || emptySummary.hintClassName !== "hint-box status-warn" || !emptySummary.html.includes("当前没有可作为预报起点")) {
              throw new Error(`empty summary wrong: ${JSON.stringify(emptySummary)}`);
            }
            const emptySummaryDom = Object.fromEntries(emptySummary.domUpdates.map(update => [update.selector, update]));
            if (emptySummaryDom["#forecast-source-summary"].html !== emptySummary.html ||
                emptySummaryDom["#forecast-hint"].text !== "完成一次新版率定或手调重算后，可在这里直接接入未来气象驱动。" ||
                emptySummaryDom["#forecast-hint"].className !== "hint-box status-warn") {
              throw new Error(`empty summary DOM updates wrong: ${JSON.stringify(emptySummaryDom)}`);
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
            const summaryDom = Object.fromEntries(summary.domUpdates.map(update => [update.selector, update]));
            if (summaryDom["#forecast-source-summary"].html !== summary.html ||
                !summaryDom["#forecast-hint"].text.includes("建议从 2026-01-11 起报") ||
                summaryDom["#forecast-hint"].className !== "hint-box status-ok") {
              throw new Error(`summary DOM updates wrong: ${JSON.stringify(summaryDom)}`);
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
