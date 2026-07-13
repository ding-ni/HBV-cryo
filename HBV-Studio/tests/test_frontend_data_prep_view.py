import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendDataPrepViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_data_prep_step_list_renders_status_actions_and_dependencies(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/dataPrepView.js", "utf8"), context);

            const view = context.window.HBVStudioDataPrepView;
            if (!view?.boundaryGuidanceState || !view?.bootstrapTaskRequestState || !view?.boundaryPreviewErrorState || !view?.boundaryPreviewQueryState || !view?.boundaryPreviewRequestState || !view?.boundaryPreviewState || !view?.cdsApiStatusQueryState || !view?.customMeteoImportCopyState || !view?.customMeteoImportDirectoryState || !view?.elevationSuggestionQueryState || !view?.emptyInputCheckCache || !view?.era5ApiPanelState || !view?.formatPrepDisplayTitle || !view?.formatPrepBlockedMessage || !view?.fromWizardInputTimeValue || !view?.gisImportErrorUiState || !view?.gisImportRequestState || !view?.gisModePanelState || !view?.gisImportStartingUiState || !view?.gisImportSuccessUiState || !view?.hasRecentInputCheckCache || !view?.inputCheckCacheEntry || !view?.inputCheckCompletionState || !view?.inputCheckQueryState || !view?.meteoImportCreatingUiState || !view?.meteoImportErrorUiState || !view?.meteoImportRequestState || !view?.meteoImportUiState || !view?.meteoModeHintState || !view?.meteoModePanelState || !view?.meteoSourceLabels || !view?.meteoSourceState || !view?.observationInfoQueryState || !view?.observationHintState || !view?.prepPanelSummary || !view?.prepStatusQueryState || !view?.prepStepRunningStatus || !view?.prepTaskRequestState || !view?.prepTaskErrorUiState || !view?.prepTaskUiState || !view?.projectFocusHintState || !view?.renderBootstrapStatus || !view?.renderInputCheckError || !view?.renderInputCheckImportBlock || !view?.renderInputCheckProgress || !view?.renderInputCheckResults || !view?.renderPrepStepList || !view?.toWizardInputTimeValue || !view?.visiblePrepSteps || !view?.workspaceReadinessQueryState || !view?.wizardConditionalFieldState || !view?.wizardSaveStepRequestState || !view?.wizardValidationFailureState) {
              throw new Error("data prep view exports are missing");
            }
            for (const name of ["currentMeteoImportTask", "currentPrepTask"]) {
              if (typeof view?.[name] !== "function") {
                throw new Error(`missing data prep task export: ${name}`);
              }
            }
            const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
              "&": "&amp;",
              "<": "&lt;",
              ">": "&gt;",
              "\"": "&quot;",
              "'": "&#39;",
            }[ch]));
            const helpers = {
              escapeHtml,
              isGisStepId: id => id === "gis_base",
              samePath(a, b) {
                return String(a || "").replace(/\\/g, "/") === String(b || "").replace(/\\/g, "/");
              },
              formatNumber(value, digits = 0) {
                const number = Number(value);
                return Number.isFinite(number) ? number.toFixed(digits) : "—";
              },
              renderEngineeringFocusChecks(checks, options) {
                return `<div class="focus-proxy" data-title="${escapeHtml(options.title)}">${checks.map(check => `${escapeHtml(check.status)}:${escapeHtml(check.summary)}:${check.items.length}`).join("|")}</div>`;
              },
            };

            if (view.formatPrepDisplayTitle(2, "01. 下载 ERA5") !== "2. 下载 ERA5") {
              throw new Error("display title should strip stale numbering");
            }
            const dataPrepTasks = [
              { id: "old-import", task_type: "meteo_import", config_path: "C:/ws/old.json", status: "running" },
              { id: "done-import", task_type: "meteo_import", config_path: "C:/ws/A.json", status: "completed" },
              { id: "running-import", task_type: "meteo_import", config_path: "C:/ws/A.json", status: "running" },
              { id: "prep-running", task_type: "data_prep", config_path: "C:/ws/A.json", status: "running" },
              { id: "calibration", task_type: "calibration", config_path: "C:/ws/A.json", status: "running" },
            ];
            const firstImport = view.currentMeteoImportTask(dataPrepTasks, "C:\\ws\\A.json", {}, helpers);
            if (firstImport?.id !== "done-import") {
              throw new Error(`current meteo import task should return first matching task: ${firstImport?.id}`);
            }
            const runningImport = view.currentMeteoImportTask(dataPrepTasks, "C:/ws/A.json", { runningOnly: true }, helpers);
            if (runningImport?.id !== "running-import") {
              throw new Error(`current meteo import task should honor runningOnly: ${runningImport?.id}`);
            }
            const runningPrep = view.currentPrepTask(dataPrepTasks, "C:\\ws\\A.json", { runningOnly: true }, helpers);
            if (runningPrep?.id !== "prep-running") {
              throw new Error(`current prep task should select data_prep only: ${runningPrep?.id}`);
            }
            if (view.currentPrepTask(dataPrepTasks, "", {}, helpers) !== null) {
              throw new Error("current prep task should require a workspace path");
            }

            if (view.toWizardInputTimeValue("2020-01-02 03:04", false) !== "2020-01-02") {
              throw new Error("daily wizard input value should keep date only");
            }
            if (view.toWizardInputTimeValue("2020-01-02", true) !== "2020-01-02T00:00") {
              throw new Error("hourly wizard input value should add midnight when time is missing");
            }
            if (view.toWizardInputTimeValue("2020-01-02T03:04", true) !== "2020-01-02T03:04") {
              throw new Error("hourly wizard input value should preserve explicit time");
            }
            if (view.toWizardInputTimeValue("not-a-date", true) !== "not-a-date") {
              throw new Error("invalid wizard input value should round-trip as text");
            }
            if (view.fromWizardInputTimeValue("2020-01-02T03:04", true) !== "2020-01-02 03:04") {
              throw new Error("hourly wizard stored value should use a space separator");
            }
            if (view.fromWizardInputTimeValue("2020-01-02T03:04", false) !== "2020-01-02") {
              throw new Error("daily wizard stored value should keep date only");
            }
            const missingWizardSave = view.wizardSaveStepRequestState({ workspacePath: " ", step: 2, data: { name: "A" } });
            if (missingWizardSave.ready || missingWizardSave.reason !== "missing-workspace" ||
                missingWizardSave.requestPath !== "/api/wizard/save-step" ||
                missingWizardSave.payload.workspace_path !== "" ||
                missingWizardSave.payload.step !== 2 ||
                missingWizardSave.payload.data.name !== "A") {
              throw new Error(`missing wizard save request state mismatch: ${JSON.stringify(missingWizardSave)}`);
            }
            const wizardSave = view.wizardSaveStepRequestState({
              workspacePath: " C:/ws/A.json ",
              step: 5,
              data: { dem_path: "D:/dem.tif", glacier_mode: "inline" },
            });
            if (!wizardSave.ready || wizardSave.reason ||
                wizardSave.requestPath !== "/api/wizard/save-step" ||
                wizardSave.workspacePath !== "C:/ws/A.json" ||
                wizardSave.payload.workspace_path !== "C:/ws/A.json" ||
                wizardSave.payload.step !== 5 ||
                wizardSave.payload.data.dem_path !== "D:/dem.tif" ||
                wizardSave.payload.data.glacier_mode !== "inline") {
              throw new Error(`wizard save request state mismatch: ${JSON.stringify(wizardSave)}`);
            }
            const blockedText = view.formatPrepBlockedMessage(
              { blocked_by: ["gis_base", "download_era5"] },
              [{ id: "download_era5", displayTitle: "1. 下载 ERA5" }],
              [],
              helpers,
            );
            if (blockedText !== "依赖未满足：请先完成 第 5 步地理数据、下载 ERA5。") {
              throw new Error(`blocked message mismatch: ${blockedText}`);
            }

            const html = view.renderPrepStepList({
              workspaceSelected: true,
              steps: [
                {
                  id: "download_era5",
                  displayTitle: "1. 下载 ERA5 <raw>",
                  displayDescription: "下载气象驱动 & 校验",
                  supports_overwrite: true,
                },
                {
                  id: "align_inputs",
                  displayTitle: "2. 写入工程目录",
                  displayDescription: "裁剪对齐到 DEM",
                },
                {
                  id: "manual_station",
                  displayTitle: "3. 补充站点资料",
                  displayDescription: "人工补充",
                  manual: true,
                },
              ],
              allSteps: [
                { id: "download_era5", title: "下载 ERA5" },
                { id: "gis_base", title: "基础地理数据" },
              ],
              prepStatus: {
                download_era5: { done: true, message: "已完成，可重跑" },
                align_inputs: { blocked_by: ["gis_base", "download_era5"] },
                manual_station: { manual: true, message: "请补充站点表" },
              },
            }, helpers);

            if (!html.includes("1. 下载 ERA5 &lt;raw&gt;") || html.includes("1. 下载 ERA5 <raw>")) {
              throw new Error(`step title should be escaped: ${html}`);
            }
            if (!html.includes("下载气象驱动 &amp; 校验")) throw new Error("description should be escaped");
            if (!html.includes("status-badge status-ok") || !html.includes(">已完成<")) throw new Error("done status missing");
            if (!html.includes('data-run-step="download_era5"') || !html.includes(">重新运行<")) throw new Error("rerun button missing");
            if (!html.includes('data-run-step-overwrite="download_era5"') || !html.includes(">覆盖重跑<")) throw new Error("overwrite button missing");
            if (!html.includes("status-badge status-fail") || !html.includes("依赖未满足：请先完成 第 5 步地理数据、下载 ERA5 &lt;raw&gt;。")) {
              throw new Error(`blocked step missing: ${html}`);
            }
            if (!html.includes('data-run-step="align_inputs" disabled')) throw new Error("blocked step should be disabled");
            if (html.includes('data-run-step="manual_station"')) throw new Error("manual step should not render run button");
            if (!html.includes(">需补充资料<")) throw new Error("manual status missing");

            const noWorkspace = view.renderPrepStepList({ workspaceSelected: false, emptyText: "请选择 <workspace>" }, helpers);
            if (!noWorkspace.includes("请选择 &lt;workspace&gt;")) throw new Error("empty workspace text should be escaped");
            const noSteps = view.renderPrepStepList({ workspaceSelected: true, steps: [], noStepsText: "无步骤 <ok>" }, helpers);
            if (!noSteps.includes("无步骤 &lt;ok&gt;")) throw new Error("no steps text should be escaped");

            const defaultConditionalFields = view.wizardConditionalFieldState({
              fullUpstream: true,
              precipMode: "grid_only",
              timescale: "daily",
              sources: { prec: "era5", temp: "era5", pet: "era5_fao56" },
            });
            if (!defaultConditionalFields.step3Skipped || defaultConditionalFields.stationFieldsVisible || defaultConditionalFields.hourlyPrecipVisible || defaultConditionalFields.customPrecVisible || defaultConditionalFields.customTempVisible || defaultConditionalFields.customPetVisible) {
              throw new Error(`default conditional fields mismatch: ${JSON.stringify(defaultConditionalFields)}`);
            }
            const customConditionalFields = view.wizardConditionalFieldState({
              fullUpstream: false,
              precipMode: "grid_plus_station_bias",
              timescale: "hourly",
              sources: { prec: "custom_tif", temp: "custom_tif", pet: "custom_tif" },
            });
            if (customConditionalFields.step3Skipped || !customConditionalFields.stationFieldsVisible || !customConditionalFields.hourlyPrecipVisible || !customConditionalFields.customPrecVisible || !customConditionalFields.customTempVisible || !customConditionalFields.customPetVisible) {
              throw new Error(`custom conditional fields mismatch: ${JSON.stringify(customConditionalFields)}`);
            }
            const dailyFullFocus = view.projectFocusHintState({ hourly: false, objectType: "full_upstream_basin" });
            if (dailyFullFocus.className !== "hint-box status-ok" || !dailyFullFocus.text.includes("日尺度 + 完整上游流域")) {
              throw new Error(`daily full-upstream focus mismatch: ${JSON.stringify(dailyFullFocus)}`);
            }
            const dailyBoundaryFocus = view.projectFocusHintState({ hourly: false, objectType: "interbasin_with_boundary" });
            if (dailyBoundaryFocus.className !== "hint-box status-warn" || !dailyBoundaryFocus.text.includes("上游边界入流文件")) {
              throw new Error(`daily boundary focus mismatch: ${JSON.stringify(dailyBoundaryFocus)}`);
            }
            const hourlyFullFocus = view.projectFocusHintState({ hourly: true, objectType: "full_upstream_basin" });
            if (hourlyFullFocus.className !== "hint-box status-warn" || !hourlyFullFocus.text.includes("小时尺度 + 完整上游流域")) {
              throw new Error(`hourly full-upstream focus mismatch: ${JSON.stringify(hourlyFullFocus)}`);
            }
            const hourlyBoundaryFocus = view.projectFocusHintState({ hourly: true, objectType: "interbasin_with_boundary" });
            if (hourlyBoundaryFocus.className !== "hint-box status-warn" || !hourlyBoundaryFocus.text.includes("小时尺度 + 区间流域")) {
              throw new Error(`hourly boundary focus mismatch: ${JSON.stringify(hourlyBoundaryFocus)}`);
            }
            const fullBoundaryGuidance = view.boundaryGuidanceState({ fullUpstream: true, hourly: false });
            if (fullBoundaryGuidance.className !== "hint-box" || !fullBoundaryGuidance.text.includes("不需要提供上游边界入流")) {
              throw new Error(`full-upstream boundary guidance mismatch: ${JSON.stringify(fullBoundaryGuidance)}`);
            }
            const dailyBoundaryGuidance = view.boundaryGuidanceState({ fullUpstream: false, hourly: false });
            if (dailyBoundaryGuidance.className !== "hint-box status-warn" || !dailyBoundaryGuidance.text.includes("水文日 08:00")) {
              throw new Error(`daily boundary guidance mismatch: ${JSON.stringify(dailyBoundaryGuidance)}`);
            }
            const hourlyBoundaryGuidance = view.boundaryGuidanceState({ fullUpstream: false, hourly: true });
            if (hourlyBoundaryGuidance.className !== "hint-box status-warn" || !hourlyBoundaryGuidance.text.includes("1 小时")) {
              throw new Error(`hourly boundary guidance mismatch: ${JSON.stringify(hourlyBoundaryGuidance)}`);
            }
            const rangeBoundaryQuery = view.boundaryPreviewQueryState({
              hourly: true,
              expectedStart: "2020-01-01 00:00",
              expectedEnd: "2020-01-10 00:00",
              workspacePath: "workspaces/demo.json",
            });
            if (rangeBoundaryQuery.source !== "expected_range" || rangeBoundaryQuery.stepHours !== "1" || JSON.stringify(rangeBoundaryQuery.entries) !== JSON.stringify([["expected_start", "2020-01-01 00:00"], ["expected_end", "2020-01-10 00:00"], ["expected_step_hours", "1"]])) {
              throw new Error(`boundary range query mismatch: ${JSON.stringify(rangeBoundaryQuery)}`);
            }
            const workspaceBoundaryQuery = view.boundaryPreviewQueryState({
              hourly: false,
              expectedStart: "",
              expectedEnd: "",
              workspacePath: " workspaces/demo.json ",
            });
            if (workspaceBoundaryQuery.source !== "workspace" || workspaceBoundaryQuery.stepHours !== "24" || JSON.stringify(workspaceBoundaryQuery.entries) !== JSON.stringify([["config_path", "workspaces/demo.json"]])) {
              throw new Error(`boundary workspace query mismatch: ${JSON.stringify(workspaceBoundaryQuery)}`);
            }
            const stepBoundaryQuery = view.boundaryPreviewQueryState({ hourly: false });
            if (stepBoundaryQuery.source !== "step_hours" || JSON.stringify(stepBoundaryQuery.entries) !== JSON.stringify([["expected_step_hours", "24"]])) {
              throw new Error(`boundary step query mismatch: ${JSON.stringify(stepBoundaryQuery)}`);
            }
            const boundaryRequest = view.boundaryPreviewRequestState({
              hourly: true,
              expectedStart: "2020-01-01 00:00",
              expectedEnd: "2020-01-10 00:00",
              csvPath: " C:/边界入流/入流 A&B.csv ",
              dateField: " 时间 字段 ",
              flowField: " 流量&m3s ",
            });
            if (!boundaryRequest.ready ||
                boundaryRequest.source !== "expected_range" ||
                boundaryRequest.csvPath !== "C:/边界入流/入流 A&B.csv" ||
                boundaryRequest.dateField !== "时间 字段" ||
                boundaryRequest.flowField !== "流量&m3s" ||
                boundaryRequest.previewPath !== "/api/boundary-preview?expected_start=2020-01-01%2000%3A00&expected_end=2020-01-10%2000%3A00&expected_step_hours=1&path=C%3A%2F%E8%BE%B9%E7%95%8C%E5%85%A5%E6%B5%81%2F%E5%85%A5%E6%B5%81%20A%26B.csv&date_field=%E6%97%B6%E9%97%B4%20%E5%AD%97%E6%AE%B5&flow_field=%E6%B5%81%E9%87%8F%26m3s") {
              throw new Error(`boundary preview request mismatch: ${JSON.stringify(boundaryRequest)}`);
            }
            const emptyBoundaryRequest = view.boundaryPreviewRequestState({
              hourly: false,
              workspacePath: " C:/工作区/A.json ",
            });
            if (emptyBoundaryRequest.ready ||
                emptyBoundaryRequest.message !== "请先选择边界入流文件。" ||
                emptyBoundaryRequest.source !== "workspace" ||
                emptyBoundaryRequest.previewPath !== "/api/boundary-preview?config_path=C%3A%2F%E5%B7%A5%E4%BD%9C%E5%8C%BA%2FA.json&path=&date_field=date&flow_field=flow") {
              throw new Error(`empty boundary request mismatch: ${JSON.stringify(emptyBoundaryRequest)}`);
            }
            const obsQuery = view.observationInfoQueryState({
              path: " C:/观测资料/流量 A&B.csv ",
              targetStepHours: 1,
            });
            if (!obsQuery.ready ||
                obsQuery.message !== "" ||
                obsQuery.path !== "C:/观测资料/流量 A&B.csv" ||
                obsQuery.targetStepHours !== "1" ||
                obsQuery.infoPath !== "/api/obs-info?path=C%3A%2F%E8%A7%82%E6%B5%8B%E8%B5%84%E6%96%99%2F%E6%B5%81%E9%87%8F%20A%26B.csv&target_step_hours=1") {
              throw new Error(`observation info query mismatch: ${JSON.stringify(obsQuery)}`);
            }
            const emptyObsQuery = view.observationInfoQueryState({ path: " ", hourly: false });
            if (emptyObsQuery.ready ||
                emptyObsQuery.message !== "请选择观测流量 CSV。" ||
                emptyObsQuery.targetStepHours !== "24" ||
                emptyObsQuery.infoPath !== "/api/obs-info?path=&target_step_hours=24") {
              throw new Error(`empty observation query mismatch: ${JSON.stringify(emptyObsQuery)}`);
            }
            const elevationQuery = view.elevationSuggestionQueryState({
              shpPath: " C:/边界/流域 A&B.shp ",
              demPath: " C:/DEM/海拔 30m.tif ",
            });
            if (!elevationQuery.ready ||
                elevationQuery.message !== "" ||
                elevationQuery.shpPath !== "C:/边界/流域 A&B.shp" ||
                elevationQuery.demPath !== "C:/DEM/海拔 30m.tif" ||
                elevationQuery.suggestionPath !== "/api/suggest/cfmax-threshold?shp_path=C%3A%2F%E8%BE%B9%E7%95%8C%2F%E6%B5%81%E5%9F%9F%20A%26B.shp&dem_path=C%3A%2FDEM%2F%E6%B5%B7%E6%8B%94%2030m.tif") {
              throw new Error(`elevation suggestion query mismatch: ${JSON.stringify(elevationQuery)}`);
            }
            const emptyElevationQuery = view.elevationSuggestionQueryState({ shpPath: " ", demPath: " C:/DEM/a.tif " });
            if (emptyElevationQuery.ready ||
                emptyElevationQuery.message !== "请选择流域边界。" ||
                emptyElevationQuery.suggestionPath !== "/api/suggest/cfmax-threshold?shp_path=&dem_path=C%3A%2FDEM%2Fa.tif") {
              throw new Error(`empty elevation query mismatch: ${JSON.stringify(emptyElevationQuery)}`);
            }
            const boundaryPreview = view.boundaryPreviewState({
              suggested_calibration_mode: "hourly",
              time_step_hours: 1,
              expected_time_step_hours: 24,
              coverage_ratio: 0.75,
              duplicate_count: 2,
              negative_count: 1,
              zero_count: 8,
              valid_rows: 10,
              total_rows: 12,
              date_range: { start: "2020-01-01 <bad>", end: "2020-01-02" },
              flow_stats: { min: -1.234, max: 4.567 },
            }, helpers);
            if (boundaryPreview.status !== "fail" || boundaryPreview.className !== "hint-box status-fail" || !boundaryPreview.html.includes("边界入流概览")) {
              throw new Error(`boundary preview state mismatch: ${JSON.stringify(boundaryPreview)}`);
            }
            if (!boundaryPreview.html.includes("2020-01-01 &lt;bad&gt;") || boundaryPreview.html.includes("2020-01-01 <bad>")) {
              throw new Error(`boundary preview date should be escaped: ${boundaryPreview.html}`);
            }
            if (!boundaryPreview.html.includes("流量范围 -1.23 ~ 4.57 m³/s") || !boundaryPreview.html.includes("建议模式 小时尺度")) {
              throw new Error(`boundary preview summary html mismatch: ${boundaryPreview.html}`);
            }
            if (!boundaryPreview.html.includes("focus-proxy") || !boundaryPreview.html.includes("fail:当前边界入流和项目时段相比仍有缺口") || !boundaryPreview.html.includes(":6")) {
              throw new Error(`boundary preview focus checks missing: ${boundaryPreview.html}`);
            }
            const stepCheck = boundaryPreview.checks.find(item => item.label === "识别时间步长");
            const zeroCheck = boundaryPreview.checks.find(item => item.label === "零值比例");
            if (stepCheck?.value !== "1 小时" || stepCheck?.status !== "fail" || zeroCheck?.value !== "80.0%" || zeroCheck?.status !== "warn") {
              throw new Error(`boundary preview checks mismatch: ${JSON.stringify(boundaryPreview.checks)}`);
            }
            const boundaryError = view.boundaryPreviewErrorState({ message: "CSV <bad>" }, helpers);
            if (boundaryError.className !== "hint-box status-fail" || !boundaryError.html.includes("CSV &lt;bad&gt;") || boundaryError.html.includes("CSV <bad>")) {
              throw new Error(`boundary preview error mismatch: ${JSON.stringify(boundaryError)}`);
            }
            const wizardStep2Failure = view.wizardValidationFailureState({
              missing: ["观测 <CSV>", "流域范围", "率定期", "验证期", "额外缺项"],
              warnings: ["警告 <一>", "警告二", "警告三"],
              event_windows: { count: 2 },
              event_observation_coverage: { ok: false },
            }, 2, helpers);
            if (wizardStep2Failure.hint?.targetId !== "wz-obs-hint" || wizardStep2Failure.hint.className !== "hint-box status-fail") {
              throw new Error(`step 2 validation hint target mismatch: ${JSON.stringify(wizardStep2Failure)}`);
            }
            if (!wizardStep2Failure.hint.html.includes("<strong>第 2 步未通过。</strong>") || !wizardStep2Failure.hint.html.includes("观测 &lt;CSV&gt;") || wizardStep2Failure.hint.html.includes("观测 <CSV>")) {
              throw new Error(`step 2 validation html mismatch: ${wizardStep2Failure.hint.html}`);
            }
            if ((wizardStep2Failure.hint.html.match(/<li>/g) || []).length !== 6 || wizardStep2Failure.hint.html.includes("额外缺项") || wizardStep2Failure.hint.html.includes("警告三")) {
              throw new Error(`step 2 validation list limits mismatch: ${wizardStep2Failure.hint.html}`);
            }
            if (wizardStep2Failure.toastText !== "第 2 步未完成：观测 <CSV>；流域范围；率定期") {
              throw new Error(`step 2 validation toast mismatch: ${wizardStep2Failure.toastText}`);
            }
            if (wizardStep2Failure.eventSummary?.eventWindows?.count !== 2 || wizardStep2Failure.eventSummary?.observationCoverage?.ok !== false) {
              throw new Error(`step 2 event summary mismatch: ${JSON.stringify(wizardStep2Failure.eventSummary)}`);
            }
            const wizardStep3Failure = view.wizardValidationFailureState({ missing: ["边界入流"], warnings: [] }, 3, helpers);
            if (wizardStep3Failure.hint?.targetId !== "wz-boundary-preview" || !wizardStep3Failure.hint.html.startsWith('<div class="hint-box status-fail"><strong>第 3 步未通过。</strong>')) {
              throw new Error(`step 3 validation hint mismatch: ${JSON.stringify(wizardStep3Failure)}`);
            }
            const wizardStep5Failure = view.wizardValidationFailureState({}, 5, helpers);
            if (wizardStep5Failure.hint !== null || wizardStep5Failure.eventSummary !== null || wizardStep5Failure.toastText !== "第 5 步未完成：请补全必填项") {
              throw new Error(`generic validation failure mismatch: ${JSON.stringify(wizardStep5Failure)}`);
            }
            const emptyObsHint = view.observationHintState(null, helpers);
            if (emptyObsHint.text !== "选择观测径流文件后将自动推断时间范围。" || emptyObsHint.className !== "hint-box" || emptyObsHint.html !== "") {
              throw new Error(`empty observation hint mismatch: ${JSON.stringify(emptyObsHint)}`);
            }
            const okObsHint = view.observationHintState({
              info: { date_field: "date <x>", start: "2020-01-01", end: "2020-12-31", suggested_calibration_mode: "daily" },
              selectedProfile: "daily",
              timeBasis: "continuous",
              periods: [
                { label: "率定期", start: "2020-01-01", end: "2020-06-30" },
                { label: "验证期", start: "2020-07-01", end: "2020-12-31" },
              ],
            }, helpers);
            if (okObsHint.className !== "hint-box status-ok" || okObsHint.html !== "" || !okObsHint.text.includes("date <x>") || !okObsHint.text.includes("当前率定期和验证期都落在观测覆盖范围内")) {
              throw new Error(`ok observation hint mismatch: ${JSON.stringify(okObsHint)}`);
            }
            const failObsHint = view.observationHintState({
              info: { date_field: "time", start: "2020-02-01", end: "2020-10-31", suggested_calibration_mode: "hourly", effective_calibration_mode: "hourly" },
              selectedProfile: "daily",
              timeBasis: "continuous",
              periods: [
                { label: "率定期", start: "2020-01-01", end: "2020-06-30" },
                { label: "验证期", start: "2020-07-01", end: "2020-12-31" },
              ],
            }, helpers);
            if (failObsHint.className !== "hint-box status-fail" || !failObsHint.html.includes("观测时段检查未通过") || !failObsHint.html.includes("观测序列更像小时尺度") || !failObsHint.html.includes("率定期开始早于观测起点") || !failObsHint.html.includes("验证期结束晚于观测终点")) {
              throw new Error(`failed observation hint mismatch: ${failObsHint.html}`);
            }
            const warnObsHint = view.observationHintState({
              info: { date_field: "date", start: "2020-01-01", end: "2020-12-31", suggested_calibration_mode: "daily", resampled_to_daily: true, daily_aggregation: { min_hours_per_day: 20 } },
              selectedProfile: "daily",
              timeBasis: "event_windows",
              periods: [{ label: "率定期", start: "2019-01-01", end: "2019-01-10" }],
            }, helpers);
            if (warnObsHint.className !== "hint-box status-warn" || !warnObsHint.html.includes("至少 20 小时/天") || !warnObsHint.html.includes("当前按洪水事件检查资料") || warnObsHint.html.includes("率定期开始早于观测起点")) {
              throw new Error(`warning observation hint mismatch: ${warnObsHint.html}`);
            }

            const sourceSteps = [
              "download_era5", "process_era5", "process_prec", "station_precip_strategy", "align_inputs", "apply_precip_strategy",
              "download_hourly_era5", "process_hourly_era5", "process_hourly_prec", "align_hourly_inputs",
              "clip_dem", "check_inputs",
            ].map(id => ({ id, title: `旧标题 ${id}`, description: `旧说明 ${id}` }));
            const dailySteps = view.visiblePrepSteps({
              steps: sourceSteps,
              sources: { prec: "era5", temp: "custom_tif", pet: "custom_tif" },
              precipMode: "thiessen",
              hourly: false,
              gisStepIds: ["clip_dem"],
              checkStepIds: ["check_inputs"],
            });
            if (dailySteps.map(step => step.id).join(",") !== "download_era5,process_prec,station_precip_strategy,align_inputs,apply_precip_strategy") {
              throw new Error(`daily visible prep ids mismatch: ${dailySteps.map(step => step.id).join(",")}`);
            }
            if (dailySteps[0].displayTitle !== "1. 下载 ERA5 降水" || dailySteps[1].displayTitle !== "2. 整理降水" || dailySteps[4].displayTitle !== "5. 执行降水方案") {
              throw new Error(`daily visible prep titles mismatch: ${JSON.stringify(dailySteps.map(step => step.displayTitle))}`);
            }
            if (dailySteps.some(step => step.id === "clip_dem" || step.id === "check_inputs")) {
              throw new Error("GIS/check steps should be excluded from visible prep steps");
            }
            const hourlySteps = view.visiblePrepSteps({
              steps: sourceSteps,
              sources: { prec: "custom_tif", temp: "era5", pet: "era5_fao56" },
              precipMode: "grid_only",
              hourly: true,
              excludedStepIds: new Set(["clip_dem", "check_inputs"]),
            });
            if (hourlySteps.map(step => step.id).join(",") !== "download_hourly_era5,process_hourly_era5,align_hourly_inputs") {
              throw new Error(`hourly visible prep ids mismatch: ${hourlySteps.map(step => step.id).join(",")}`);
            }
            if (hourlySteps[0].displayTitle !== "1. 下载小时 ERA5 变量" || hourlySteps[1].displayTitle !== "2. 生成小时气温和潜在蒸散发") {
              throw new Error(`hourly visible prep titles mismatch: ${JSON.stringify(hourlySteps.map(step => step.displayTitle))}`);
            }
            if (!hourlySteps[1].displayDescription.includes("小时结果")) {
              throw new Error(`hourly visible prep description mismatch: ${hourlySteps[1].displayDescription}`);
            }

            const bootstrapHtml = view.renderBootstrapStatus([
              { id: "dem", title: "裁剪 DEM <1>", done: true, message: "已完成 & 可复核" },
              { id: "flow_acc", title: "生成流向", done: false, message: "等待执行" },
              { id: "glacier", title: "冰川高程", done: false, optional: true, message: "当前未启用冰川边界" },
            ], helpers);
            if (!bootstrapHtml.includes("bootstrap-item done") || !bootstrapHtml.includes("status-badge status-ok") || !bootstrapHtml.includes(">已完成<")) {
              throw new Error(`bootstrap done item missing: ${bootstrapHtml}`);
            }
            if (!bootstrapHtml.includes("裁剪 DEM &lt;1&gt;") || bootstrapHtml.includes("裁剪 DEM <1>")) {
              throw new Error("bootstrap title should be escaped");
            }
            if (!bootstrapHtml.includes("已完成 &amp; 可复核")) throw new Error("bootstrap message should be escaped");
            if (!bootstrapHtml.includes("status-badge status-warn") || !bootstrapHtml.includes(">待执行<")) {
              throw new Error("bootstrap pending item missing");
            }
            if (!bootstrapHtml.includes("status-badge \">未启用<")) throw new Error("bootstrap optional disabled item missing");
            const emptyBootstrap = view.renderBootstrapStatus([], helpers);
            if (!emptyBootstrap.includes("暂无 GIS 步骤状态信息。")) throw new Error("empty bootstrap state missing");
            const bootstrapRequest = view.bootstrapTaskRequestState({ configPath: " C:/ws/A.json ", runtimePrecipSource: " cmfd " });
            if (!bootstrapRequest.ready || bootstrapRequest.message !== "" || bootstrapRequest.requestPath !== "/api/bootstrap/start" ||
                JSON.stringify(bootstrapRequest.request) !== JSON.stringify({ prec_source: "cmfd" }) ||
                JSON.stringify(bootstrapRequest.payload) !== JSON.stringify({ config_path: "C:/ws/A.json", prec_source: "cmfd" })) {
              throw new Error(`bootstrap request mismatch: ${JSON.stringify(bootstrapRequest)}`);
            }
            const missingBootstrapRequest = view.bootstrapTaskRequestState({ runtimePrecipSource: " " });
            if (missingBootstrapRequest.ready || missingBootstrapRequest.message !== "请选择降水来源。" || missingBootstrapRequest.request.prec_source !== "" || missingBootstrapRequest.payload.config_path !== "") {
              throw new Error(`missing bootstrap request mismatch: ${JSON.stringify(missingBootstrapRequest)}`);
            }
            const gisStarting = view.gisImportStartingUiState();
            if (gisStarting.hint.text !== "正在导入..." || Object.prototype.hasOwnProperty.call(gisStarting.hint, "className")) {
              throw new Error(`GIS import starting state mismatch: ${JSON.stringify(gisStarting)}`);
            }
            const gisSuccess = view.gisImportSuccessUiState({ message: "导入完成 <ok>" });
            if (gisSuccess.hint.text !== "导入完成 <ok>" || gisSuccess.hint.className !== "hint-box status-ok") {
              throw new Error(`GIS import success state mismatch: ${JSON.stringify(gisSuccess)}`);
            }
            const gisDefaultSuccess = view.gisImportSuccessUiState({});
            if (gisDefaultSuccess.hint.text !== "导入完成！" || gisDefaultSuccess.hint.className !== "hint-box status-ok") {
              throw new Error(`GIS import default success state mismatch: ${JSON.stringify(gisDefaultSuccess)}`);
            }
            const gisError = view.gisImportErrorUiState(new Error("缺少 DEM"));
            if (gisError.hint.text !== "缺少 DEM" || gisError.hint.className !== "hint-box status-fail") {
              throw new Error(`GIS import error state mismatch: ${JSON.stringify(gisError)}`);
            }
            const missingGisRequest = view.gisImportRequestState({ demPath: " ", flowaccPath: "" });
            if (missingGisRequest.ready || missingGisRequest.message !== "请至少选择裁剪后 DEM 和流量累积掩膜文件。" || missingGisRequest.missing.join(",") !== "dem_path,flowacc_masked_path") {
              throw new Error(`GIS import missing request mismatch: ${JSON.stringify(missingGisRequest)}`);
            }
            const missingFlowaccRequest = view.gisImportRequestState({ demPath: "C:/data/dem.tif", flowaccPath: " " });
            if (missingFlowaccRequest.ready || missingFlowaccRequest.missing.join(",") !== "flowacc_masked_path") {
              throw new Error(`GIS import flowacc validation mismatch: ${JSON.stringify(missingFlowaccRequest)}`);
            }
            const gisRequest = view.gisImportRequestState({
              configPath: " C:/ws/A.json ",
              demPath: "  C:/data/dem.tif  ",
              flowaccPath: "  C:/data/flowacc_masked.tif ",
              flowdirPath: " C:/data/flowdir.tif ",
              glacierMaskPath: "  C:/data/glacier.tif ",
            });
            const expectedGisRequest = {
              dem_path: "C:/data/dem.tif",
              flowacc_masked_path: "C:/data/flowacc_masked.tif",
              flowdir_path: "C:/data/flowdir.tif",
              glacier_mask_path: "C:/data/glacier.tif",
            };
            const expectedGisPayload = { config_path: "C:/ws/A.json", ...expectedGisRequest };
            if (!gisRequest.ready || gisRequest.message !== "" || gisRequest.requestPath !== "/api/gis/import" || gisRequest.missing.length ||
                JSON.stringify(gisRequest.request) !== JSON.stringify(expectedGisRequest) ||
                JSON.stringify(gisRequest.payload) !== JSON.stringify(expectedGisPayload)) {
              throw new Error(`GIS import request mismatch: ${JSON.stringify(gisRequest)}`);
            }
            const gisOptionalRequest = view.gisImportRequestState({ demPath: "dem.tif", flowaccPath: "flowacc.tif" });
            if (!gisOptionalRequest.ready || gisOptionalRequest.request.flowdir_path !== "" || gisOptionalRequest.request.glacier_mask_path !== "") {
              throw new Error(`GIS import optional request mismatch: ${JSON.stringify(gisOptionalRequest)}`);
            }
            const gisAutoPanel = view.gisModePanelState("auto");
            if (!gisAutoPanel.panels.autoVisible || gisAutoPanel.panels.importVisible) {
              throw new Error(`GIS auto panel mismatch: ${JSON.stringify(gisAutoPanel)}`);
            }
            const gisImportPanel = view.gisModePanelState("import");
            if (gisImportPanel.panels.autoVisible || !gisImportPanel.panels.importVisible) {
              throw new Error(`GIS import panel mismatch: ${JSON.stringify(gisImportPanel)}`);
            }
            const gisEmptyPanel = view.gisModePanelState("");
            if (gisEmptyPanel.panels.autoVisible || gisEmptyPanel.panels.importVisible) {
              throw new Error(`GIS empty panel mismatch: ${JSON.stringify(gisEmptyPanel)}`);
            }

            const hiddenEra5 = view.era5ApiPanelState({ mode: "manual", needsDownload: true });
            if (hiddenEra5.hint.visible || hiddenEra5.actions.visible || hiddenEra5.hint.className !== "hint-box") {
              throw new Error(`ERA5 panel should hide outside pipeline mode: ${JSON.stringify(hiddenEra5)}`);
            }
            const loadingEra5 = view.era5ApiPanelState({ mode: "pipeline", needsDownload: true, sources: { prec: "era5", temp: "custom_tif", pet: "custom_tif" }, status: { loading: true } });
            if (!loadingEra5.hint.visible || !loadingEra5.actions.visible || loadingEra5.hint.className !== "hint-box status-warn" || !loadingEra5.hint.text.includes("正在检查当前电脑")) {
              throw new Error(`ERA5 loading panel mismatch: ${JSON.stringify(loadingEra5)}`);
            }
            const cdsApiQuery = view.cdsApiStatusQueryState();
            if (cdsApiQuery.statusPath !== "/api/cdsapi/status") {
              throw new Error(`CDS API status query mismatch: ${JSON.stringify(cdsApiQuery)}`);
            }
            const errorEra5 = view.era5ApiPanelState({ mode: "pipeline", needsDownload: true, sources: { prec: "era5", temp: "custom_tif", pet: "custom_tif" }, status: { error: "key <bad>" } });
            if (errorEra5.hint.className !== "hint-box status-fail" || !errorEra5.hint.text.includes("key <bad>")) {
              throw new Error(`ERA5 error panel mismatch: ${JSON.stringify(errorEra5)}`);
            }
            const validEra5 = view.era5ApiPanelState({ mode: "pipeline", needsDownload: true, sources: { prec: "era5", temp: "custom_tif", pet: "custom_tif" }, status: { exists: true, looks_valid: true } });
            if (validEra5.hint.className !== "hint-box status-ok" || !validEra5.hint.text.includes("这一步会下载 ERA5 降水。 已检测到 CDS API 配置")) {
              throw new Error(`ERA5 valid panel mismatch: ${JSON.stringify(validEra5)}`);
            }
            const invalidPetEra5 = view.era5ApiPanelState({ mode: "pipeline", needsDownload: true, sources: { prec: "custom_tif", temp: "custom_tif", pet: "era5_fao56" }, status: { exists: true, looks_valid: false } });
            if (invalidPetEra5.hint.className !== "hint-box status-warn" || !invalidPetEra5.hint.text.includes("计算潜在蒸散发要用的 ERA5 变量") || !invalidPetEra5.hint.text.includes("内容看起来不完整")) {
              throw new Error(`ERA5 invalid PET panel mismatch: ${JSON.stringify(invalidPetEra5)}`);
            }
            const missingEra5 = view.era5ApiPanelState({ mode: "pipeline", needsDownload: true, sources: { prec: "mswep", temp: "era5", pet: "era5_fao56" }, status: { exists: false } });
            if (missingEra5.hint.className !== "hint-box status-warn" || !missingEra5.hint.text.includes("当前方案要用的 ERA5 变量") || !missingEra5.hint.text.includes("还没检测到 .cdsapirc")) {
              throw new Error(`ERA5 missing panel mismatch: ${JSON.stringify(missingEra5)}`);
            }

            const meteoRunning = view.meteoImportUiState({
              status: "running",
              ui_progress: { stage: "裁剪导入", current: 2, total: 5, label: "降水", item_current: 3, item_total: 7, timestamp: "2026-06-03T09:00" },
              output: Array.from({ length: 82 }, (_, index) => `导入日志 ${index}`),
            }, helpers);
            if (meteoRunning.hint.text !== "裁剪导入：总进度 2/5；降水 3/7 · 当前时间 2026-06-03T09:00" || meteoRunning.hint.className !== "hint-box status-warn") {
              throw new Error(`meteo import running state mismatch: ${JSON.stringify(meteoRunning)}`);
            }
            if (!meteoRunning.button.disabled || meteoRunning.button.text !== "正在导入..." || meteoRunning.log.lines.length !== 80 || meteoRunning.log.lines[0] !== "导入日志 2") {
              throw new Error(`meteo import running controls mismatch: ${JSON.stringify(meteoRunning)}`);
            }
            const meteoCompleted = view.meteoImportUiState({
              status: "completed",
              result: {
                preparation_mode_label: "本地导入 <A>",
                prec_count: 2,
                temp_count: 3,
                evap_count: 4,
                aligned: false,
                validation_ok: false,
                validation_warnings: ["文件名 <不规范>", "缺测 & 待补", "第三条不显示"],
                source_dirs: { prec: "C:/raw/precip <bad>", temp: "C:/raw/temp" },
                target_dirs: { prec: "D:/workspace/prec", evap: "D:/workspace/evap <bad>" },
              },
              output: ["完成日志"],
            }, { ...helpers, shortPath: value => String(value || "").split(/[\\/]/).pop() });
            if (meteoCompleted.hint.className !== "hint-box status-warn" || meteoCompleted.button.disabled || meteoCompleted.button.text !== "验证并导入") {
              throw new Error(`meteo import completed controls mismatch: ${JSON.stringify(meteoCompleted)}`);
            }
            if (!meteoCompleted.hint.html.includes("本地导入 &lt;A&gt;完成") || !meteoCompleted.hint.html.includes("已自动裁剪对齐到 DEM 网格。")) {
              throw new Error(`meteo import completed text mismatch: ${meteoCompleted.hint.html}`);
            }
            if (!meteoCompleted.hint.html.includes("文件名 &lt;不规范&gt;；缺测 &amp; 待补") || meteoCompleted.hint.html.includes("第三条不显示")) {
              throw new Error(`meteo import warning summary mismatch: ${meteoCompleted.hint.html}`);
            }
            if (!meteoCompleted.hint.html.includes("precip &lt;bad&gt;") || !meteoCompleted.hint.html.includes("evap &lt;bad&gt;")) {
              throw new Error(`meteo import paths should be escaped: ${meteoCompleted.hint.html}`);
            }
            const meteoFailed = view.meteoImportUiState({ status: "failed", output: [] }, helpers);
            if (meteoFailed.hint.text !== "导入失败，请检查目录与文件名格式。" || meteoFailed.hint.className !== "hint-box status-fail" || meteoFailed.log.visible) {
              throw new Error(`meteo import failed fallback mismatch: ${JSON.stringify(meteoFailed)}`);
            }
            const meteoCreating = view.meteoImportCreatingUiState();
            if (meteoCreating.hint.text !== "正在创建导入任务..." || meteoCreating.hint.className !== "hint-box status-warn" || !meteoCreating.log.visible || meteoCreating.log.lines.length !== 0 || meteoCreating.log.key !== "wizard:import-log") {
              throw new Error(`meteo import creating state mismatch: ${JSON.stringify(meteoCreating)}`);
            }
            const meteoPollError = view.meteoImportErrorUiState(new Error("网络中断"));
            if (meteoPollError.hint.text !== "网络中断" || meteoPollError.hint.className !== "hint-box status-fail" || meteoPollError.log !== null || meteoPollError.button.disabled || meteoPollError.button.text !== "验证并导入") {
              throw new Error(`meteo import polling error state mismatch: ${JSON.stringify(meteoPollError)}`);
            }
            const meteoStartError = view.meteoImportErrorUiState({ message: "目录错误" }, { hideLog: true });
            if (meteoStartError.hint.text !== "目录错误" || !meteoStartError.log || meteoStartError.log.visible || meteoStartError.log.key !== "wizard:import-log") {
              throw new Error(`meteo import start error state mismatch: ${JSON.stringify(meteoStartError)}`);
            }
            const meteoLocalLabels = view.meteoSourceLabels({ prec: "custom_tif", temp: "era5", pet: "custom_tif" }, "local");
            const meteoPipelineLabels = view.meteoSourceLabels({ prec: "custom_tif", temp: "era5", pet: "custom_tif" }, "pipeline");
            if (meteoLocalLabels.join(",") !== "降水,蒸散发" || meteoPipelineLabels.join(",") !== "气温") {
              throw new Error(`meteo source labels mismatch: ${meteoLocalLabels} / ${meteoPipelineLabels}`);
            }
            const mixedSourceState = view.meteoSourceState({ prec: "custom_tif", temp: "era5", pet: "era5_fao56" });
            if (mixedSourceState.localLabels.join(",") !== "降水" || mixedSourceState.pipelineLabels.join(",") !== "气温,蒸散发") {
              throw new Error(`mixed meteo source labels mismatch: ${JSON.stringify(mixedSourceState)}`);
            }
            if (!mixedSourceState.needsEra5Download || mixedSourceState.needSignature !== "custom_tif|era5|era5_fao56" || !mixedSourceState.hasLocalMeteoSourceConfigured || mixedSourceState.allMeteoSourcesUseLocalTif) {
              throw new Error(`mixed meteo source state mismatch: ${JSON.stringify(mixedSourceState)}`);
            }
            const allLocalSourceState = view.meteoSourceState({ prec: "custom_tif", temp: "custom_tif", pet: "custom_tif" });
            if (allLocalSourceState.needsEra5Download || allLocalSourceState.localLabels.length !== 3 || !allLocalSourceState.allMeteoSourcesUseLocalTif) {
              throw new Error(`all-local meteo source state mismatch: ${JSON.stringify(allLocalSourceState)}`);
            }
            const pipelineSourceState = view.meteoSourceState({ prec: "era5", temp: "era5", pet: "era5_fao56" });
            if (!pipelineSourceState.needsEra5Download || pipelineSourceState.localLabels.length !== 0 || pipelineSourceState.pipelineLabels.length !== 3 || pipelineSourceState.hasLocalMeteoSourceConfigured) {
              throw new Error(`pipeline meteo source state mismatch: ${JSON.stringify(pipelineSourceState)}`);
            }
            const copyPlan = view.customMeteoImportCopyState({
              sources: { prec: "custom_tif", temp: "custom_tif", pet: "era5_fao56" },
              registeredDirs: { prec: " D:/meteo/prec ", temp: "D:/meteo/temp", pet: "D:/meteo/pet" },
              importDirs: { prec: "", temp: "D:/manual/temp", pet: "" },
              force: false,
            });
            if (copyPlan.copiedCount !== 1 || copyPlan.copiedLabels.join(",") !== "降水" || JSON.stringify(copyPlan.updates) !== JSON.stringify([{ key: "prec", value: "D:/meteo/prec", label: "降水" }])) {
              throw new Error(`custom meteo copy plan mismatch: ${JSON.stringify(copyPlan)}`);
            }
            const forceCopyPlan = view.customMeteoImportCopyState({
              sources: { prec: "custom_tif", temp: "custom_tif", pet: "custom_tif" },
              registeredDirs: { prec: "", temp: "D:/meteo/temp", pet: "D:/meteo/pet" },
              importDirs: { prec: "", temp: "D:/manual/temp", pet: "" },
              force: true,
            });
            if (forceCopyPlan.copiedCount !== 2 || forceCopyPlan.copiedLabels.join(",") !== "气温,蒸散发" || forceCopyPlan.updates[0].value !== "D:/meteo/temp" || forceCopyPlan.updates[1].key !== "pet") {
              throw new Error(`force custom meteo copy plan mismatch: ${JSON.stringify(forceCopyPlan)}`);
            }
            const importDirState = view.customMeteoImportDirectoryState({
              sources: { prec: "custom_tif", temp: "era5", pet: "custom_tif" },
              registeredDirs: { prec: " D:/meteo/prec ", temp: "D:/meteo/temp", pet: "D:/meteo/pet" },
              importDirs: { prec: "", temp: "D:/manual/temp", pet: "" },
            });
            if (!importDirState.ready || importDirState.dirs.prec !== "D:/meteo/prec" || importDirState.dirs.temp !== "D:/manual/temp" || importDirState.dirs.pet !== "D:/meteo/pet") {
              throw new Error(`custom meteo import dir state mismatch: ${JSON.stringify(importDirState)}`);
            }
            if (JSON.stringify(importDirState.writeBackUpdates) !== JSON.stringify([{ key: "prec", value: "D:/meteo/prec" }, { key: "pet", value: "D:/meteo/pet" }])) {
              throw new Error(`custom meteo import dir writeback mismatch: ${JSON.stringify(importDirState.writeBackUpdates)}`);
            }
            const incompleteImportDirState = view.customMeteoImportDirectoryState({
              sources: { prec: "era5", temp: "custom_tif", pet: "custom_tif" },
              registeredDirs: { temp: "D:/meteo/temp", pet: "" },
              importDirs: { prec: "", temp: "", pet: "" },
            });
            if (incompleteImportDirState.ready || incompleteImportDirState.missing.join(",") !== "prec,pet" || incompleteImportDirState.writeBackUpdates.length) {
              throw new Error(`incomplete custom meteo import dir state mismatch: ${JSON.stringify(incompleteImportDirState)}`);
            }
            const meteoRequest = view.meteoImportRequestState({
              configPath: " C:/ws/A.json ",
              sources: { prec: "custom_tif", temp: "era5", pet: "custom_tif" },
              registeredDirs: { prec: " D:/meteo/prec ", temp: "D:/meteo/temp", pet: "D:/meteo/pet" },
              importDirs: { prec: "", temp: " D:/manual/temp ", pet: "" },
              runtimePrecipSource: " custom_tif ",
              isDaily: true,
              precipUnit: "mm/day",
              precipDayBasis: "product_calendar_day",
            });
            const expectedMeteoRequest = {
              prec_source: "custom_tif",
              prec_dir: "D:/meteo/prec",
              temp_dir: "D:/manual/temp",
              evap_dir: "D:/meteo/pet",
              precip_unit: "mm/day",
              precip_day_basis: "product_calendar_day",
            };
            const expectedMeteoPayload = { config_path: "C:/ws/A.json", ...expectedMeteoRequest };
            if (!meteoRequest.ready || meteoRequest.message !== "" || meteoRequest.requestPath !== "/api/meteo/import/start" || meteoRequest.missing.length ||
                JSON.stringify(meteoRequest.request) !== JSON.stringify(expectedMeteoRequest) ||
                JSON.stringify(meteoRequest.payload) !== JSON.stringify(expectedMeteoPayload)) {
              throw new Error(`meteo import request mismatch: ${JSON.stringify(meteoRequest)}`);
            }
            if (JSON.stringify(meteoRequest.writeBackUpdates) !== JSON.stringify([{ key: "prec", value: "D:/meteo/prec" }, { key: "pet", value: "D:/meteo/pet" }])) {
              throw new Error(`meteo import request writeback mismatch: ${JSON.stringify(meteoRequest.writeBackUpdates)}`);
            }
            const incompleteMeteoRequest = view.meteoImportRequestState({
              sources: { prec: "era5", temp: "custom_tif", pet: "custom_tif" },
              registeredDirs: { temp: "D:/meteo/temp", pet: "" },
              importDirs: { prec: "", temp: "", pet: "" },
              runtimePrecipSource: "era5",
            });
            if (incompleteMeteoRequest.ready || incompleteMeteoRequest.message !== "请选择降水、气温和蒸散发三个目录。" || incompleteMeteoRequest.missing.join(",") !== "prec,pet" || incompleteMeteoRequest.writeBackUpdates.length) {
              throw new Error(`incomplete meteo import request mismatch: ${JSON.stringify(incompleteMeteoRequest)}`);
            }
            const missingDailyMetadata = view.meteoImportRequestState({
              configPath: "C:/ws/A.json",
              sources: { prec: "custom_tif", temp: "custom_tif", pet: "custom_tif" },
              registeredDirs: { prec: "D:/p", temp: "D:/t", pet: "D:/e" },
              importDirs: {},
              runtimePrecipSource: "custom_tif",
              isDaily: true,
            });
            if (missingDailyMetadata.ready || missingDailyMetadata.missing.join(",") !== "precip_unit,precip_day_basis" || missingDailyMetadata.message !== "请显式确认日降水单位和日界。") {
              throw new Error(`daily import metadata gate mismatch: ${JSON.stringify(missingDailyMetadata)}`);
            }
            const allLocalHint = view.meteoModeHintState({
              sources: { prec: "custom_tif", temp: "custom_tif", pet: "custom_tif" },
              copiedLabels: ["降水", "气温"],
            });
            if (!allLocalHint.shouldApply || allLocalHint.hint.className !== "hint-box status-ok" || !allLocalHint.hint.text.includes("已自动带入第 4 步登记的本地栅格目录（降水、气温）") || !allLocalHint.hint.text.includes("直接导入本地栅格")) {
              throw new Error(`all-local meteo mode hint mismatch: ${JSON.stringify(allLocalHint)}`);
            }
            const mixedHint = view.meteoModeHintState({
              sources: { prec: "custom_tif", temp: "era5", pet: "era5_fao56" },
              copiedLabels: ["降水"],
            });
            if (!mixedHint.shouldApply || !mixedHint.hint.text.includes("当前为混合来源方案") || !mixedHint.hint.text.includes("仍需按步骤处理 气温、蒸散发")) {
              throw new Error(`mixed meteo mode hint mismatch: ${JSON.stringify(mixedHint)}`);
            }
            const noLocalPreserveFail = view.meteoModeHintState({
              sources: { prec: "era5", temp: "era5", pet: "era5_fao56" },
              currentText: "导入失败",
              currentClassName: "hint-box status-fail",
            });
            if (noLocalPreserveFail.shouldApply || noLocalPreserveFail.hint.text !== "") {
              throw new Error(`no-local meteo mode should preserve visible failure: ${JSON.stringify(noLocalPreserveFail)}`);
            }
            const pipelinePanel = view.meteoModePanelState({
              sources: { prec: "era5", temp: "custom_tif", pet: "custom_tif" },
              mode: "pipeline",
            });
            if (pipelinePanel.forceImport || pipelinePanel.pipelineRadio.disabled || pipelinePanel.importRadio.checked || !pipelinePanel.panels.pipelineVisible || pipelinePanel.panels.importVisible) {
              throw new Error(`pipeline meteo mode panel mismatch: ${JSON.stringify(pipelinePanel)}`);
            }
            const importPanel = view.meteoModePanelState({
              sources: { prec: "era5", temp: "custom_tif", pet: "custom_tif" },
              mode: "import",
            });
            if (importPanel.forceImport || importPanel.panels.pipelineVisible || !importPanel.panels.importVisible) {
              throw new Error(`import meteo mode panel mismatch: ${JSON.stringify(importPanel)}`);
            }
            const forcedImportPanel = view.meteoModePanelState({
              sources: { prec: "custom_tif", temp: "custom_tif", pet: "custom_tif" },
              mode: "pipeline",
            });
            if (!forcedImportPanel.forceImport || forcedImportPanel.mode !== "import" || !forcedImportPanel.pipelineRadio.disabled || !forcedImportPanel.importRadio.checked || forcedImportPanel.panels.pipelineVisible || !forcedImportPanel.panels.importVisible || forcedImportPanel.pipelineCard.opacity !== "0.55" || !forcedImportPanel.pipelineCard.title.includes("直接导入本地目录")) {
              throw new Error(`forced-import meteo mode panel mismatch: ${JSON.stringify(forcedImportPanel)}`);
            }

            const era5PrecipSummary = view.prepPanelSummary({ prec: "era5", temp: "custom_tif", pet: "custom_tif" });
            if (era5PrecipSummary.className !== "hint-box status-ok" || !era5PrecipSummary.text.includes("降水用ERA5 自动下载") || !era5PrecipSummary.text.includes("下面先下载 ERA5 降水")) {
              throw new Error(`ERA5 precip summary mismatch: ${JSON.stringify(era5PrecipSummary)}`);
            }
            const localSummary = view.prepPanelSummary({ prec: "custom_tif", temp: "custom_tif", pet: "custom_tif" });
            if (!localSummary.text.includes("降水用本地栅格") || !localSummary.text.includes("气温用本地栅格") || !localSummary.text.includes("下面按顺序整理本项目需要的气象数据")) {
              throw new Error(`local summary mismatch: ${JSON.stringify(localSummary)}`);
            }
            const petSummary = view.prepPanelSummary({ prec: "custom_tif", temp: "custom_tif", pet: "era5_fao56" });
            if (!petSummary.text.includes("潜在蒸散发用ERA5+FAO56") || !petSummary.text.includes("下载计算潜在蒸散发要用的 ERA5 变量")) {
              throw new Error(`PET summary mismatch: ${JSON.stringify(petSummary)}`);
            }
            const cmfdSummary = view.prepPanelSummary({ prec: "cmfd", temp: "era5", pet: "era5_fao56" });
            if (!cmfdSummary.text.includes("降水用CMFD 本地原始文件") || !cmfdSummary.text.includes("下面按顺序完成 ERA5 下载和结果生成")) {
              throw new Error(`CMFD summary mismatch: ${JSON.stringify(cmfdSummary)}`);
            }

            const prepTaskState = view.prepTaskUiState({
              status: "running",
              label: "默认标签",
              ui_progress: { stage: "裁剪栅格", label: "DEM <tile>", current: 3, total: 9 },
              output: Array.from({ length: 122 }, (_, index) => `日志 ${index}`),
            });
            if (prepTaskState.hint.text !== "裁剪栅格：DEM <tile>（3/9）" || prepTaskState.hint.className !== "hint-box status-warn") {
              throw new Error(`running prep task state mismatch: ${JSON.stringify(prepTaskState)}`);
            }
            if (!prepTaskState.log.visible || prepTaskState.log.lines.length !== 120 || prepTaskState.log.lines[0] !== "日志 2" || prepTaskState.log.key !== "wizard:pipeline-log") {
              throw new Error(`prep task logs should be capped: ${JSON.stringify(prepTaskState.log)}`);
            }
            const completedPrepState = view.prepTaskUiState({ status: "completed", step_title: "写入工程目录" });
            if (completedPrepState.hint.text !== "已完成：写入工程目录" || completedPrepState.hint.className !== "hint-box status-ok" || completedPrepState.log.visible) {
              throw new Error(`completed prep task state mismatch: ${JSON.stringify(completedPrepState)}`);
            }
            const failedPrepState = view.prepTaskUiState({ status: "failed" });
            if (failedPrepState.hint.text !== "执行失败：数据处理" || failedPrepState.hint.className !== "hint-box status-fail") {
              throw new Error(`failed prep task fallback mismatch: ${JSON.stringify(failedPrepState)}`);
            }
            const prepErrorState = view.prepTaskErrorUiState(new Error("轮询失败"));
            if (prepErrorState.hint.text !== "轮询失败" || prepErrorState.hint.className !== "hint-box status-fail" || prepErrorState.log !== null) {
              throw new Error(`prep task error state mismatch: ${JSON.stringify(prepErrorState)}`);
            }
            const prepRequest = view.prepTaskRequestState({
              configPath: " C:/ws/A.json ",
              stepId: " meteo_align ",
              runtimePrecipSource: " era5 ",
              overwrite: 1,
            });
            const expectedPrepRequest = {
              step_id: "meteo_align",
              prec_source: "era5",
              overwrite: true,
            };
            const expectedPrepPayload = { config_path: "C:/ws/A.json", ...expectedPrepRequest };
            if (!prepRequest.ready || prepRequest.message !== "" || prepRequest.requestPath !== "/api/data-prep/start" ||
                JSON.stringify(prepRequest.request) !== JSON.stringify(expectedPrepRequest) ||
                JSON.stringify(prepRequest.payload) !== JSON.stringify(expectedPrepPayload)) {
              throw new Error(`prep task request mismatch: ${JSON.stringify(prepRequest)}`);
            }
            const missingPrepRequest = view.prepTaskRequestState({ stepId: " ", runtimePrecipSource: "cmfd" });
            if (missingPrepRequest.ready || missingPrepRequest.message !== "请选择要执行的数据处理步骤。" ||
                missingPrepRequest.request.step_id !== "" ||
                missingPrepRequest.request.prec_source !== "cmfd" ||
                missingPrepRequest.request.overwrite ||
                missingPrepRequest.payload.config_path !== "") {
              throw new Error(`missing prep task request mismatch: ${JSON.stringify(missingPrepRequest)}`);
            }
            const prepStatusQuery = view.prepStatusQueryState({
              configPath: " C:/工作区/A & B ",
              precipSource: " cmfd ",
            });
            const encodedPrepConfig = encodeURIComponent("C:/工作区/A & B");
            if (!prepStatusQuery.ready || prepStatusQuery.message !== "" || prepStatusQuery.configPath !== "C:/工作区/A & B" || prepStatusQuery.precipSource !== "cmfd") {
              throw new Error(`prep status query state mismatch: ${JSON.stringify(prepStatusQuery)}`);
            }
            if (prepStatusQuery.stepsPath !== `/api/data-prep/steps?config_path=${encodedPrepConfig}` || prepStatusQuery.statusPath !== `/api/data-prep/status?config_path=${encodedPrepConfig}&prec_source=cmfd`) {
              throw new Error(`prep status query paths mismatch: ${JSON.stringify(prepStatusQuery)}`);
            }
            const missingPrepStatusQuery = view.prepStatusQueryState({ configPath: " ", precipSource: "era5" });
            if (missingPrepStatusQuery.ready || missingPrepStatusQuery.message !== "请先保存工作区。" || !missingPrepStatusQuery.stepsPath.includes("config_path=") || !missingPrepStatusQuery.statusPath.includes("prec_source=era5")) {
              throw new Error(`missing prep status query mismatch: ${JSON.stringify(missingPrepStatusQuery)}`);
            }
            const prepStepRunning = view.prepStepRunningStatus({ done: true, message: "旧消息" });
            if (!prepStepRunning.done || !prepStepRunning.running || prepStepRunning.message !== "正在执行，请看下方日志。") {
              throw new Error(`prep step running status mismatch: ${JSON.stringify(prepStepRunning)}`);
            }

            const importBlock = view.renderInputCheckImportBlock({
              ui_progress: {
                stage: "导入 ERA5 <daily>",
                current: 2,
                total: 5,
                label: "降水 & 气温",
                item_current: 3,
                item_total: 8,
                timestamp: "2026-06-03 <09:00>",
              },
              output: Array.from({ length: 22 }, (_, index) => `日志 ${index} <raw>`),
            }, helpers);
            if (!importBlock.includes("当前正在导入气象驱动") || !importBlock.includes("导入 ERA5 &lt;daily&gt;：总进度 2/5")) {
              throw new Error(`import block progress missing: ${importBlock}`);
            }
            if (!importBlock.includes("降水 &amp; 气温 3/8") || !importBlock.includes("2026-06-03 &lt;09:00&gt;")) {
              throw new Error("import block detail should be escaped");
            }
            if (!importBlock.includes("task-output-box") || !importBlock.includes("日志 21 &lt;raw&gt;") || importBlock.includes("日志 1 &lt;raw&gt;")) {
              throw new Error("import block should show only the latest escaped logs");
            }

            const progressHtml = view.renderInputCheckProgress({ stage: "基础配置检查 <A>", elapsed: 4 }, helpers);
            if (!progressHtml.includes("基础配置检查 &lt;A&gt;") || !progressHtml.includes("已用时 4 秒") || progressHtml.includes("status-warn")) {
              throw new Error(`short input check progress failed: ${progressHtml}`);
            }
            const longProgressHtml = view.renderInputCheckProgress({ stage: "详细输入检查", elapsed: 31 }, helpers);
            if (!longProgressHtml.includes("status-warn") || !longProgressHtml.includes("数据量较大时可能需要数分钟")) {
              throw new Error(`long input check progress failed: ${longProgressHtml}`);
            }
            const errorHtml = view.renderInputCheckError({ message: "缺少文件 <dem>", stage: "详细输入检查 <B>", elapsed: 9 }, helpers);
            if (!errorHtml.includes("检查失败：缺少文件 &lt;dem&gt;") || !errorHtml.includes("失败阶段：详细输入检查 &lt;B&gt;；已用时 9 秒")) {
              throw new Error(`input check error should be escaped: ${errorHtml}`);
            }
            const failedCompletion = view.inputCheckCompletionState({
              validation: { valid: false, missing: ["缺 DEM"], warnings: ["站点偏少"] },
              previousWorkflow: { total_steps: 8, completed_count: 8, completion_ratio: 1, steps_remaining: [2, 5] },
              detail: true,
              advice: { recommendations: [{ title: "补资料", detail: "回到第 5 步" }] },
              stage: "calibration",
            });
            if (failedCompletion.comp.ready || failedCompletion.comp.missing.length !== 1 || failedCompletion.comp.warnings.length !== 1 || !failedCompletion.shouldUpdateCalibrationUi) {
              throw new Error(`failed input check comp mismatch: ${JSON.stringify(failedCompletion)}`);
            }
            const failedWorkflow = failedCompletion.statePatch.currentWorkspaceWorkflow;
            if (failedWorkflow.ready_for_calibration || !failedWorkflow.pending_validation || failedWorkflow.next_step !== 7 || failedWorkflow.completed_count !== 7 || failedWorkflow.completion_ratio !== 7 / 8 || failedWorkflow.steps_remaining.join(",") !== "2,5,7" || failedWorkflow.missing_count !== 1 || failedWorkflow.warning_count !== 1) {
              throw new Error(`failed input check workflow mismatch: ${JSON.stringify(failedWorkflow)}`);
            }
            if (failedCompletion.statePatch.currentWorkspaceAdvice.recommendations.length !== 1) {
              throw new Error("detailed calibration check should carry advice into state patch");
            }
            const readyCompletion = view.inputCheckCompletionState({
              validation: { valid: true },
              previousWorkflow: { total_steps: 8, completed_count: 5, completion_ratio: 0.5, steps_remaining: [7] },
              stage: "calibration",
            });
            const readyWorkflow = readyCompletion.statePatch.currentWorkspaceWorkflow;
            if (!readyCompletion.comp.ready_for_calibration || !readyWorkflow.ready_for_calibration || readyWorkflow.pending_validation || readyWorkflow.next_step !== null || readyWorkflow.completed_count !== 8 || readyWorkflow.completion_ratio !== 1 || readyWorkflow.steps_remaining.length !== 0) {
              throw new Error(`ready input check workflow mismatch: ${JSON.stringify(readyCompletion)}`);
            }
            const quickCompletion = view.inputCheckCompletionState({
              validation: { valid: true, missing: ["ignored"], warnings: ["ignored"] },
              previousWorkflow: { total_steps: 8 },
              stage: "quick_test",
            });
            if (!quickCompletion.comp.ready || quickCompletion.shouldUpdateCalibrationUi || Object.keys(quickCompletion.statePatch).length !== 0) {
              throw new Error(`quick input check should not patch calibration workflow: ${JSON.stringify(quickCompletion)}`);
            }
            const detailCheckQuery = view.inputCheckQueryState({
              configPath: " C:/工作区/A & B ",
              precipSource: " era5 ",
              stage: "calibration",
              detail: true,
            });
            const encodedConfigPath = encodeURIComponent("C:/工作区/A & B");
            if (!detailCheckQuery.ready || !detailCheckQuery.wantsDetail || detailCheckQuery.stage !== "calibration" || detailCheckQuery.precipSource !== "era5") {
              throw new Error(`detailed input check query state mismatch: ${JSON.stringify(detailCheckQuery)}`);
            }
            if (detailCheckQuery.validationPath !== `/api/config/validate?config_path=${encodedConfigPath}&stage=calibration&prec_source=era5`) {
              throw new Error(`validation path mismatch: ${detailCheckQuery.validationPath}`);
            }
            if (detailCheckQuery.detailPath !== `/api/workspace/detailed-check?config_path=${encodedConfigPath}&prec_source=era5` || detailCheckQuery.advicePath !== `/api/workspace/advice?config_path=${encodedConfigPath}&prec_source=era5`) {
              throw new Error(`detail/advice path mismatch: ${JSON.stringify(detailCheckQuery)}`);
            }
            const quickCheckQuery = view.inputCheckQueryState({
              configPath: "C:/Workspace/A",
              precipSource: "cmfd",
              stage: "quick_test",
              detail: true,
            });
            if (!quickCheckQuery.ready || quickCheckQuery.wantsDetail || quickCheckQuery.detailPath !== "" || quickCheckQuery.advicePath !== "" || !quickCheckQuery.validationPath.includes("stage=quick_test")) {
              throw new Error(`quick input check query mismatch: ${JSON.stringify(quickCheckQuery)}`);
            }
            const missingCheckQuery = view.inputCheckQueryState({ configPath: " ", precipSource: "era5" });
            if (missingCheckQuery.ready || missingCheckQuery.message !== "请先保存工作区。" || !missingCheckQuery.validationPath.includes("config_path=")) {
              throw new Error(`missing input check query mismatch: ${JSON.stringify(missingCheckQuery)}`);
            }
            const readinessQuery = view.workspaceReadinessQueryState({
              configPath: " C:/工作区/A & B ",
              precipSource: " era5 ",
            });
            if (!readinessQuery.ready || readinessQuery.message !== "" || readinessQuery.configPath !== "C:/工作区/A & B" || readinessQuery.precipSource !== "era5") {
              throw new Error(`workspace readiness query mismatch: ${JSON.stringify(readinessQuery)}`);
            }
            if (readinessQuery.completenessPath !== `/api/workspace/completeness?config_path=${encodedConfigPath}&prec_source=era5` || readinessQuery.advicePath !== `/api/workspace/advice?config_path=${encodedConfigPath}&prec_source=era5`) {
              throw new Error(`workspace readiness paths mismatch: ${JSON.stringify(readinessQuery)}`);
            }
            const missingReadinessQuery = view.workspaceReadinessQueryState({ configPath: " ", precipSource: "cmfd" });
            if (missingReadinessQuery.ready || missingReadinessQuery.message !== "请先保存工作区。" || !missingReadinessQuery.completenessPath.includes("prec_source=cmfd")) {
              throw new Error(`missing workspace readiness query mismatch: ${JSON.stringify(missingReadinessQuery)}`);
            }
            const emptyCache = view.emptyInputCheckCache();
            if (emptyCache.configPath !== "" || emptyCache.stage !== "calibration" || emptyCache.result !== null || emptyCache.html !== "") {
              throw new Error(`empty input check cache mismatch: ${JSON.stringify(emptyCache)}`);
            }
            const cacheEntry = view.inputCheckCacheEntry({
              configPath: "C:/Workspace/A",
              precipSource: "ERA5",
              stage: "quick_test",
              checkedAt: 1000,
              result: { ready: false },
              html: "<div>ok</div>",
            });
            if (cacheEntry.configPath !== "C:/Workspace/A" || cacheEntry.precipSource !== "ERA5" || cacheEntry.stage !== "quick_test" || cacheEntry.checkedAt !== 1000 || cacheEntry.html !== "<div>ok</div>") {
              throw new Error(`input check cache entry mismatch: ${JSON.stringify(cacheEntry)}`);
            }
            const cacheHelpers = { samePath: (left, right) => String(left).toLowerCase() === String(right).toLowerCase() };
            const freshCacheModel = {
              workspacePath: "c:/workspace/a",
              precipSource: "era5",
              stage: "quick_test",
              nowMs: 1200,
              maxAgeMs: 45000,
            };
            if (!view.hasRecentInputCheckCache(cacheEntry, freshCacheModel, cacheHelpers)) {
              throw new Error("fresh input check cache should be accepted");
            }
            if (view.hasRecentInputCheckCache(cacheEntry, { ...freshCacheModel, requireReady: true }, cacheHelpers)) {
              throw new Error("requireReady should reject non-ready cache result");
            }
            if (view.hasRecentInputCheckCache(cacheEntry, { ...freshCacheModel, precipSource: "cmfd" }, cacheHelpers)) {
              throw new Error("precip source mismatch should reject cache");
            }
            if (view.hasRecentInputCheckCache(cacheEntry, { ...freshCacheModel, nowMs: 60000 }, cacheHelpers)) {
              throw new Error("expired cache should be rejected");
            }
            if (view.hasRecentInputCheckCache(cacheEntry, { ...freshCacheModel, hasRunningImport: true }, cacheHelpers)) {
              throw new Error("running meteo import should reject cache");
            }

            const checkHelpers = {
              ...helpers,
              inferIssueTarget(detail, targetStep) {
                return String(detail || "").includes("第 3 步")
                  ? { step: targetStep, selector: "#wz-boundary <bad>" }
                  : null;
              },
              renderEngineeringFocusChecks(checks, options) {
                return `<div class="focus-checks">${escapeHtml(options.title)}:${checks.length}</div>`;
              },
              renderIssueJumpButton(item, step) {
                return `<button data-jump="${escapeHtml(item)}" data-step="${escapeHtml(step)}">定位</button>`;
              },
              renderValidationEventSections(validation) {
                return `<section class="event-section">${escapeHtml(validation.eventName || "事件 <x>")}</section>`;
              },
            };
            const checkHtml = view.renderInputCheckResults({
              validation: { valid: false, eventName: "洪水 <A>", focus_checks: [{ id: "range" }] },
              comp: {
                ready: false,
                missing: ["缺少 DEM <tif>"],
                warnings: ["站点偏少 & 待确认"],
              },
              detail: true,
              stage: "calibration",
              detailData: {
                reasonableness_checks: [{ id: "flow" }],
                summary: [
                  { group: "水文 <组>", label: "流量 & 单位", value: "m3/s <bad>", ok: true },
                  { group: "水文 <组>", label: "缺项", value: "空", ok: false },
                ],
              },
              advice: {
                recommendations: [
                  { title: "补充资料 <A>", detail: "回到第 3 步 & 导入", target_step: 3 },
                  { title: "检查站点", detail: "核对雨量站" },
                  { title: "检查边界", detail: "核对边界" },
                  { title: "检查气象", detail: "核对气象" },
                  { title: "第五条不显示", detail: "不应渲染" },
                ],
              },
            }, checkHelpers);
            if (!checkHtml.includes("洪水 &lt;A&gt;") || checkHtml.includes("洪水 <A>")) {
              throw new Error(`event section should be escaped: ${checkHtml}`);
            }
            if (!checkHtml.includes("以下数据缺失或配置不完整") || !checkHtml.includes("缺少 DEM &lt;tif&gt;")) {
              throw new Error(`missing item section failed: ${checkHtml}`);
            }
            if (!checkHtml.includes("站点偏少 &amp; 待确认") || !checkHtml.includes('data-jump="站点偏少 &amp; 待确认"')) {
              throw new Error(`warning section failed: ${checkHtml}`);
            }
            if (!checkHtml.includes("专项工程检查") || !checkHtml.includes("专项工程检查:1")) {
              throw new Error("focus checks should be rendered");
            }
            if (!checkHtml.includes("数值合理性检查") || !checkHtml.includes("数值合理性检查:1")) {
              throw new Error("reasonableness checks should be rendered");
            }
            if (!checkHtml.includes("智能建议") || !checkHtml.includes("补充资料 &lt;A&gt;") || !checkHtml.includes('data-go-step="3"')) {
              throw new Error(`recommendations failed: ${checkHtml}`);
            }
            if (!checkHtml.includes('data-go-selector="#wz-boundary &lt;bad&gt;"')) {
              throw new Error("recommendation selector should be escaped");
            }
            if (checkHtml.includes("第五条不显示")) throw new Error("recommendations should be limited to four items");
            if (!checkHtml.includes("水文 &lt;组&gt;") || !checkHtml.includes("流量 &amp; 单位") || !checkHtml.includes("m3/s &lt;bad&gt;")) {
              throw new Error(`detail table should be escaped: ${checkHtml}`);
            }
            if (!checkHtml.includes("check-row status-ok") || !checkHtml.includes("check-row status-fail")) {
              throw new Error("detail table status classes missing");
            }

            const overviewHtml = view.renderInputCheckResults({
              validation: { valid: true },
              comp: { ready: true, missing: [], warnings: [] },
              detail: false,
              stage: "quick_test",
            }, checkHelpers);
            if (!overviewHtml.includes("输入预核算所需数据已就位") || !overviewHtml.includes("当前显示的是输入检查概览")) {
              throw new Error(`overview input check state failed: ${overviewHtml}`);
            }
            """
        )
        script_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".js", dir=STUDIO_DIR, delete=False, encoding="utf-8") as temp_js:
                temp_js.write(script)
                script_path = Path(temp_js.name)
            result = subprocess.run(
                ["node", str(script_path)],
                cwd=STUDIO_DIR,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=20,
            )
        finally:
            if script_path:
                script_path.unlink(missing_ok=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
