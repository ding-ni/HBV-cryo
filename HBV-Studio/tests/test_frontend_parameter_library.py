import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendParameterLibraryTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_manual_preset_diff_summary_sorts_and_formats(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            if (!library) throw new Error("parameter library was not exported");
            if (typeof library.manualPresetDiffSummary !== "function") {
              throw new Error("manualPresetDiffSummary was not exported");
            }
            if (typeof library.manualPresetDiffView !== "function") {
              throw new Error("manualPresetDiffView was not exported");
            }
            if (typeof library.manualPresetDiffPanelState !== "function") {
              throw new Error("manualPresetDiffPanelState was not exported");
            }

            const summary = library.manualPresetDiffSummary(
              { params: { TT: 0.5, FC: 130, K0: 0.11, unchanged: 7 } },
              { TT: 0.1, FC: 120, K0: 0.1, unchanged: 7 },
              { formatNumber: (value, digits) => Number(value).toFixed(digits), limit: 2 },
            );

            if (!summary.visible) throw new Error("summary should be visible for a selected preset");
            if (summary.diffs.length !== 3) throw new Error(`expected 3 diffs, got ${summary.diffs.length}`);
            if (summary.diffs[0].name !== "FC") throw new Error("diffs should be sorted by absolute delta");
            if (!summary.preview.includes("FC: 120.0000 -> 130.0000 (+10.0000)")) {
              throw new Error(`unexpected preview: ${summary.preview}`);
            }
            if (summary.preview.includes("K0")) throw new Error("preview should respect limit");

            const empty = library.manualPresetDiffSummary(null, { TT: 0.1 });
            if (empty.visible || empty.diffs.length || empty.preview) {
              throw new Error("missing preset should produce a hidden empty summary");
            }

            const hiddenView = library.manualPresetDiffView(null, { TT: 0.1 });
            if (hiddenView.visible || hiddenView.text || hiddenView.className || hiddenView.diffCount !== 0) {
              throw new Error(`unexpected hidden view: ${JSON.stringify(hiddenView)}`);
            }
            const hiddenPanel = library.manualPresetDiffPanelState(null, { TT: 0.1 });
            if (hiddenPanel.visible || hiddenPanel.text !== "" || hiddenPanel.className !== "hint-box" || hiddenPanel.diffCount !== 0) {
              throw new Error(`unexpected hidden panel: ${JSON.stringify(hiddenPanel)}`);
            }
            const sameView = library.manualPresetDiffView(
              { name: "Base", params: { TT: 0.1 } },
              { TT: 0.1 },
              { contextWarning: "注意：降水驱动不同。" },
              { formatNumber: (value, digits) => Number(value).toFixed(digits) },
            );
            if (!sameView.visible || sameView.diffCount !== 0 || sameView.className !== "hint-box status-warn") {
              throw new Error(`unexpected same view state: ${JSON.stringify(sameView)}`);
            }
            if (sameView.text !== "参数集“Base”与当前率定参数一致。 注意：降水驱动不同。") {
              throw new Error(`unexpected same view text: ${sameView.text}`);
            }
            const changedView = library.manualPresetDiffView(
              { name: "Trial", params: { TT: 0.5, FC: 130 } },
              { TT: 0.1, FC: 120 },
              {},
              { formatNumber: (value, digits) => Number(value).toFixed(digits) },
            );
            if (!changedView.visible || changedView.diffCount !== 2 || changedView.className !== "hint-box") {
              throw new Error(`unexpected changed view state: ${JSON.stringify(changedView)}`);
            }
            if (!changedView.text.includes("参数集“Trial”与当前率定值相比有 2 个参数不同。")) {
              throw new Error(`changed view intro missing: ${changedView.text}`);
            }
            if (!changedView.text.includes("FC: 120.0000 → 130.0000 (+10.0000)")) {
              throw new Error(`changed view should format arrows and separators: ${changedView.text}`);
            }
            const changedPanel = library.manualPresetDiffPanelState(
              { name: "Trial", params: { TT: 0.5 } },
              { TT: 0.1 },
              {},
              { formatNumber: (value, digits) => Number(value).toFixed(digits) },
            );
            if (!changedPanel.visible || changedPanel.className !== "hint-box" || changedPanel.diffCount !== 1) {
              throw new Error(`unexpected changed panel: ${JSON.stringify(changedPanel)}`);
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
    def test_manual_preset_compare_summary_builds_status_and_lines(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            if (typeof library.manualPresetCompareSummary !== "function") {
              throw new Error("manualPresetCompareSummary was not exported");
            }
            if (typeof library.manualPresetCompareView !== "function") {
              throw new Error("manualPresetCompareView was not exported");
            }
            if (typeof library.manualPresetComparePanelState !== "function") {
              throw new Error("manualPresetComparePanelState was not exported");
            }
            if (typeof library.compareMetricSummary !== "function") {
              throw new Error("compareMetricSummary was not exported");
            }
            for (const name of ["manualPresetComparePendingView", "manualPresetCompareErrorView"]) {
              if (typeof library[name] !== "function") throw new Error(`${name} was not exported`);
            }

            const summary = library.manualPresetCompareSummary(
              {
                label: "Trial A",
                compareMetrics: { nse_cal: 0.81, nse_val: 0.72 },
                baseCalibration: { nse: 0.76 },
                baseValidation: { nse: 0.75 },
                adjusted: true,
              },
              {
                title: label => `comparing ${label}`,
                metricSummary: (label, current, baseline) => `${label}:${current}-${baseline}`,
                calibrationLabel: "cal",
                validationLabel: "val",
                adjustedNote: () => "adjusted",
              },
            );

            if (!summary.visible) throw new Error("summary should be visible");
            if (summary.statusClass !== "status-ok") throw new Error(`unexpected status: ${summary.statusClass}`);
            if (Math.abs(summary.deltaCalibration - 0.05) > 1e-12) throw new Error("wrong calibration delta");
            if (Math.abs(summary.deltaValidation + 0.03) > 1e-12) throw new Error("wrong validation delta");
            if (summary.lines.join("|") !== "comparing Trial A|cal:0.81-0.76|val:0.72-0.75|adjusted") {
              throw new Error(`unexpected lines: ${summary.lines.join("|")}`);
            }

            const hidden = library.manualPresetCompareSummary({ label: "", compareMetrics: { nse_cal: 0.8 } });
            if (hidden.visible || hidden.lines.length) throw new Error("missing label should hide summary");

            const compareTexts = [
              library.compareMetricSummary("率定纳什效率系数", 0.812345, 0.762345, 4),
              library.compareMetricSummary("验证纳什效率系数", 0.7123, 0.75, 4),
              library.compareMetricSummary("率定纳什效率系数", undefined, 0.76, 4),
              library.compareMetricSummary("验证纳什效率系数", 0.72, undefined, 4),
              library.compareMetricSummary("验证纳什效率系数", undefined, undefined, 4),
            ].join("|");
            const expectedCompareTexts = [
              "率定纳什效率系数：0.8123（较当前 +0.0500）",
              "验证纳什效率系数：0.7123（较当前 -0.0377）",
              "率定纳什效率系数：—（该参数集未产生该指标）",
              "验证纳什效率系数：0.7200（当前结果无可比指标）",
              "验证纳什效率系数：—（当前结果和对比参数集都没有该指标）",
            ].join("|");
            if (compareTexts !== expectedCompareTexts) {
              throw new Error(`unexpected compare metric summaries: ${compareTexts}`);
            }

            const view = library.manualPresetCompareView(
              {
                label: "Trial A",
                compareMetrics: { nse_cal: 0.81, nse_val: 0.72 },
                baseCalibration: { nse: 0.76 },
                baseValidation: { nse: 0.75 },
                adjusted: true,
              },
              {
                title: label => `comparing ${label}`,
                metricSummary: (label, current, baseline) => `${label}:${current}-${baseline}`,
                calibrationLabel: "cal",
                validationLabel: "val",
                adjustedNote: () => "adjusted",
              },
            );
            if (!view.visible || view.className !== "hint-box status-ok") {
              throw new Error(`unexpected compare view state: ${JSON.stringify(view)}`);
            }
            if (view.text !== "comparing Trial A cal:0.81-0.76 val:0.72-0.75 adjusted") {
              throw new Error(`unexpected compare view text: ${view.text}`);
            }
            const hiddenView = library.manualPresetCompareView({ label: "", compareMetrics: { nse_cal: 0.8 } });
            if (hiddenView.visible || hiddenView.className || hiddenView.text) {
              throw new Error(`unexpected hidden compare view: ${JSON.stringify(hiddenView)}`);
            }
            const panelView = library.manualPresetComparePanelState({
              runData: {
                metadata: {
                  metrics: {
                    calibration: { nse: 0.76 },
                    validation: { nse: 0.75 },
                  },
                },
              },
              compareMetrics: { nse_cal: 0.81, nse_val: 0.72 },
              compareLabel: "Trial A",
              adjusted: true,
            });
            const expectedPanelText = "当前正在对比参数集“Trial A”。 率定纳什效率系数：0.8100（较当前 +0.0500）。 验证纳什效率系数：0.7200（较当前 -0.0300）。 该参数集在运行前已按约束自动修正。";
            if (!panelView.visible || panelView.className !== "hint-box status-ok" || panelView.text !== expectedPanelText) {
              throw new Error(`unexpected compare panel view: ${JSON.stringify(panelView)}`);
            }
            const hiddenPanelView = library.manualPresetComparePanelState({
              runData: null,
              compareMetrics: { nse_cal: 0.8 },
              compareLabel: "Trial A",
            });
            if (hiddenPanelView.visible || hiddenPanelView.className !== "hint-box" || hiddenPanelView.text !== "") {
              throw new Error(`unexpected hidden compare panel view: ${JSON.stringify(hiddenPanelView)}`);
            }
            const pendingView = library.manualPresetComparePendingView({ name: "Trial A" });
            if (!pendingView.visible || pendingView.className !== "hint-box" || pendingView.text !== "正在计算参数集“Trial A”的对比结果...") {
              throw new Error(`unexpected pending compare view: ${JSON.stringify(pendingView)}`);
            }
            const fallbackPendingView = library.manualPresetComparePendingView({});
            if (!fallbackPendingView.text.includes("参数集")) {
              throw new Error(`pending view should have fallback name: ${JSON.stringify(fallbackPendingView)}`);
            }
            const errorView = library.manualPresetCompareErrorView(new Error("接口超时"));
            if (!errorView.visible || errorView.className !== "hint-box status-fail" || errorView.text !== "参数集对比失败：接口超时") {
              throw new Error(`unexpected error compare view: ${JSON.stringify(errorView)}`);
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
    def test_manual_preset_lookup_and_payload_builders(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            const presets = [
              { id: "local-1", name: "Local", scope: "workspace" },
              { parameter_set_id: "global-1", name: "Global", scope: "global" },
            ];
            if (library.findPresetById(presets, "global-1").name !== "Global") {
              throw new Error("parameter_set_id lookup failed");
            }
            if (library.findPresetById(presets, "missing") !== null) {
              throw new Error("missing preset should return null");
            }
            for (const name of [
              "manualPresetSavePreflight",
              "manualPresetLoadPreflight",
              "manualPresetDeletePreflight",
              "manualPresetSaveSuccessState",
              "manualPresetLoadSuccessState",
              "manualPresetDeleteViewState",
            ]) {
              if (typeof library[name] !== "function") throw new Error(`${name} was not exported`);
            }

            const unsupportedSave = library.manualPresetSavePreflight({
              configPath: "C:/workspaces/A/workspace.json",
              editable: false,
              name: "Trial set",
              params: { TT: 0.2 },
              runData: { run: { path: "C:/runs/source" } },
            });
            if (unsupportedSave.ok || unsupportedSave.reason !== "unsupported-run" || !unsupportedSave.message.includes("不支持")) {
              throw new Error(`unsupported save preflight wrong: ${JSON.stringify(unsupportedSave)}`);
            }
            const missingConfigSave = library.manualPresetSavePreflight({
              editable: true,
              name: "Trial set",
              params: { TT: 0.2 },
              runData: { run: { path: "C:/runs/source" } },
            });
            if (missingConfigSave.ok || missingConfigSave.reason !== "missing-config" || !missingConfigSave.message.includes("配置路径")) {
              throw new Error(`missing config save preflight wrong: ${JSON.stringify(missingConfigSave)}`);
            }
            const missingNameSave = library.manualPresetSavePreflight({
              configPath: "C:/workspaces/A/workspace.json",
              editable: true,
              name: " ",
              params: { TT: 0.2 },
              runData: { run: { path: "C:/runs/source" } },
            });
            if (missingNameSave.ok || missingNameSave.reason !== "missing-name" || !missingNameSave.message.includes("名称")) {
              throw new Error(`missing name save preflight wrong: ${JSON.stringify(missingNameSave)}`);
            }
            const readySave = library.manualPresetSavePreflight({
              configPath: " C:/workspaces/A/workspace.json ",
              editable: true,
              name: " Trial set ",
              params: { TT: 0.2 },
              runData: { run: { path: "C:/runs/source" } },
            });
            if (!readySave.ok || readySave.reason || readySave.message ||
                readySave.configPath !== "C:/workspaces/A/workspace.json" ||
                readySave.name !== "Trial set") {
              throw new Error(`ready save preflight wrong: ${JSON.stringify(readySave)}`);
            }
            const missingLoad = library.manualPresetLoadPreflight(null);
            if (missingLoad.ok || missingLoad.reason !== "missing-preset" || !missingLoad.message.includes("参数集") ||
                missingLoad.preset !== null || missingLoad.presetName !== "") {
              throw new Error(`missing load preflight wrong: ${JSON.stringify(missingLoad)}`);
            }
            const readyLoad = library.manualPresetLoadPreflight({ id: "p1", name: " Trial A ", params_adjusted: true });
            if (!readyLoad.ok || readyLoad.reason || readyLoad.message || readyLoad.preset.id !== "p1" || readyLoad.presetName !== "Trial A") {
              throw new Error(`ready load preflight wrong: ${JSON.stringify(readyLoad)}`);
            }
            const unnamedLoad = library.manualPresetLoadPreflight({ id: "p2", name: " " });
            if (!unnamedLoad.ok || unnamedLoad.presetName !== "参数集") {
              throw new Error(`unnamed load should use fallback name: ${JSON.stringify(unnamedLoad)}`);
            }
            const missingDeletePreset = library.manualPresetDeletePreflight("C:/workspaces/A/workspace.json", null);
            if (missingDeletePreset.ok || missingDeletePreset.reason !== "missing-preset" || !missingDeletePreset.message.includes("参数集")) {
              throw new Error(`missing delete preset preflight wrong: ${JSON.stringify(missingDeletePreset)}`);
            }
            const missingDeleteConfig = library.manualPresetDeletePreflight(" ", presets[0]);
            if (missingDeleteConfig.ok || missingDeleteConfig.reason !== "missing-config" ||
                missingDeleteConfig.configPath !== "" || missingDeleteConfig.presetId !== "") {
              throw new Error(`missing delete config preflight wrong: ${JSON.stringify(missingDeleteConfig)}`);
            }
            const readyDelete = library.manualPresetDeletePreflight(" C:/workspaces/A/workspace.json ", presets[1]);
            if (!readyDelete.ok || readyDelete.configPath !== "C:/workspaces/A/workspace.json" ||
                readyDelete.presetId !== "global-1" || readyDelete.presetName !== "Global" || readyDelete.preset !== presets[1]) {
              throw new Error(`ready delete preflight wrong: ${JSON.stringify(readyDelete)}`);
            }

            const savePayload = library.manualPresetSavePayload({
              configPath: " C:/workspaces/A/workspace.json ",
              scope: "global",
              runData: {
                run: { path: "C:/runs/source" },
                metadata: {
                  calibration_profile: "hourly",
                  parameter_profile: { bounds_profile: "hourly_step" },
                  data_sources: {
                    runtime_prec_source: "CUSTOM_TIF",
                    glacier_mode: "inline",
                  },
                },
              },
              objectiveMode: "daily_unified_professional_v1",
              name: "  Trial set  ",
              params: { TT: 0.2 },
            });
            if (savePayload.config_path !== "C:/workspaces/A/workspace.json") throw new Error("config path not trimmed");
            if (savePayload.scope !== "global") throw new Error("scope not carried");
            if (savePayload.run_path !== "C:/runs/source") throw new Error("run path not carried");
            if (savePayload.calibration_profile !== "hourly") throw new Error("calibration profile not carried");
            if (savePayload.param_bounds_profile !== "hourly_step") throw new Error("bounds profile not carried");
            if (savePayload.prec_source !== "custom_tif") throw new Error("precipitation source not normalized");
            if (savePayload.name !== "Trial set") throw new Error("name not trimmed");
            if (savePayload.params.TT !== 0.2) throw new Error("params not carried");

            const deletePayload = library.manualPresetDeletePayload("C:/workspace.json", presets[1]);
            if (deletePayload.preset_id !== "global-1" || deletePayload.scope !== "global") {
              throw new Error("delete payload did not use parameter_set_id and scope");
            }
            const saveSuccess = library.manualPresetSaveSuccessState({
              preset: { id: "p1", name: "Trial set", scope: "global", params_adjusted: true },
            }, "Fallback");
            if (saveSuccess.savedId !== "p1" || saveSuccess.scopeLabel !== "公共参数库" ||
                saveSuccess.presetName !== "Trial set" ||
                saveSuccess.toastText !== "已保存到公共参数库：Trial set（已按约束自动修正）") {
              throw new Error(`save success state wrong: ${JSON.stringify(saveSuccess)}`);
            }
            const saveFallback = library.manualPresetSaveSuccessState({}, " Fallback ");
            if (saveFallback.savedId !== "" || saveFallback.scopeLabel !== "当前工作区" ||
                saveFallback.presetName !== "Fallback" ||
                saveFallback.toastText !== "已保存到当前工作区：Fallback") {
              throw new Error(`save fallback state wrong: ${JSON.stringify(saveFallback)}`);
            }
            const loadSuccess = library.manualPresetLoadSuccessState({ name: "Trial A", params_adjusted: true }, "");
            if (loadSuccess.inputName !== "Trial A" || loadSuccess.toastText !== "已载入参数集：Trial A（已按约束自动修正）") {
              throw new Error(`load success state wrong: ${JSON.stringify(loadSuccess)}`);
            }
            const deleteView = library.manualPresetDeleteViewState(" Trial A ");
            if (deleteView.presetName !== "Trial A" ||
                deleteView.confirmText !== "确定删除参数集“Trial A”吗？" ||
                deleteView.toastText !== "已删除参数集：Trial A") {
              throw new Error(`delete view state wrong: ${JSON.stringify(deleteView)}`);
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
    def test_manual_preset_apply_state_merges_marks_changes_and_builds_hint(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            for (const name of ["manualPresetAppliedParams", "manualPresetApplyState", "manualParamUpdateState", "manualParamResetState", "manualParamResetViewState"]) {
              if (typeof library[name] !== "function") throw new Error(`${name} was not exported`);
            }
            const result = library.manualPresetAppliedParams(
              { TT: 0.1, FC: 110, K0: 0.3 },
              { TT: 0.1, FC: 120, K0: 0.3 },
              { params: { TT: 0.1, FC: 130 } },
            );

            if (result.params.TT !== 0.1 || result.params.FC !== 130 || result.params.K0 !== 0.3) {
              throw new Error("merged params are wrong");
            }
            const byName = Object.fromEntries(result.applied.map(item => [item.name, item]));
            if (byName.TT.changed) throw new Error("unchanged parameter should not be marked changed");
            if (!byName.FC.changed) throw new Error("changed parameter should be marked changed");
            if ("K0" in byName) throw new Error("unapplied existing params should not be listed as applied");

            const state = library.manualPresetApplyState(
              { TT: 0.1, FC: 110, K0: 0.3 },
              { TT: 0.1, FC: 120, K0: 0.3 },
              { name: " Trial A ", params_adjusted: true, params: { TT: 0.1, FC: 130 } },
              { contextWarning: "注意：降水驱动不同。" },
            );
            if (!state.applied || state.presetName !== "Trial A") {
              throw new Error(`apply state should carry fallback-safe preset name: ${JSON.stringify(state)}`);
            }
            if (state.params.FC !== 130 || state.params.K0 !== 0.3 || state.paramUpdates.length !== 2) {
              throw new Error(`apply state params or updates wrong: ${JSON.stringify(state)}`);
            }
            const stateUpdates = Object.fromEntries(state.paramUpdates.map(item => [item.name, item]));
            if (stateUpdates.TT.changed || !stateUpdates.FC.changed) {
              throw new Error(`apply state changed flags wrong: ${JSON.stringify(state.paramUpdates)}`);
            }
            if (!state.hint.visible || state.hint.className !== "hint-box status-warn" ||
                state.hint.text !== "已载入参数集：Trial A（已按约束自动修正）。注意：降水驱动不同。") {
              throw new Error(`apply state hint wrong: ${JSON.stringify(state.hint)}`);
            }
            const okHint = library.manualPresetApplyState(
              { TT: 0.1 },
              { TT: 0.1 },
              { name: " ", params: { TT: 0.2 } },
            );
            if (!okHint.applied || okHint.presetName !== "参数集" || okHint.hint.className !== "hint-box status-ok" ||
                okHint.hint.text !== "已载入参数集：参数集") {
              throw new Error(`apply state default hint wrong: ${JSON.stringify(okHint)}`);
            }
            const missing = library.manualPresetApplyState(null, { TT: 0.1 }, { name: "Trial", params: { TT: 0.2 } });
            if (missing.applied || missing.paramUpdates.length || missing.hint.visible || missing.presetName) {
              throw new Error(`missing context should not apply preset: ${JSON.stringify(missing)}`);
            }

            const currentParams = { TT: 0.1, FC: 110 };
            const update = library.manualParamUpdateState(currentParams, { TT: 0.1, FC: 120 }, " FC ", "130.5");
            if (!update.applied || update.name !== "FC" || update.value !== 130.5 || !update.changed ||
                update.params.FC !== 130.5 || update.params.TT !== 0.1) {
              throw new Error(`manual param update state wrong: ${JSON.stringify(update)}`);
            }
            if (currentParams.FC !== 110) {
              throw new Error("manual param update state should not mutate current params");
            }
            const unchangedUpdate = library.manualParamUpdateState({ TT: 0.1 }, { TT: 0.1 }, "TT", 0.1);
            if (!unchangedUpdate.applied || unchangedUpdate.changed) {
              throw new Error(`unchanged manual param update wrong: ${JSON.stringify(unchangedUpdate)}`);
            }
            for (const bad of [
              library.manualParamUpdateState({ TT: 0.1 }, { TT: 0.1 }, "", 0.2),
              library.manualParamUpdateState({ TT: 0.1 }, { TT: 0.1 }, "TT", "bad"),
              library.manualParamUpdateState(null, { TT: 0.1 }, "TT", 0.2),
            ]) {
              if (bad.applied || bad.changed || bad.value !== null) {
                throw new Error(`bad manual param update should not apply: ${JSON.stringify(bad)}`);
              }
            }

            const reset = library.manualParamResetState({ TT: 0.1, FC: 120 });
            if (!reset.reset || reset.params.TT !== 0.1 || reset.params.FC !== 120 ||
                reset.paramUpdates.length !== 2 || reset.paramUpdates.some(item => item.changed) ||
                reset.hint.visible || reset.hint.className !== "hint-box") {
              throw new Error(`manual param reset state wrong: ${JSON.stringify(reset)}`);
            }
            reset.params.TT = 9;
            if (reset.paramUpdates.find(item => item.name === "TT").value !== 0.1) {
              throw new Error("manual param reset updates should not track later params mutation");
            }
            const missingReset = library.manualParamResetState(null);
            if (missingReset.reset || missingReset.paramUpdates.length || missingReset.hint.visible) {
              throw new Error(`missing manual param reset should not reset: ${JSON.stringify(missingReset)}`);
            }
            const resetView = library.manualParamResetViewState(
              { TT: 0.1, FC: 120 },
              {
                run: { path: "C:/runs/A" },
                metadata: {
                  metrics: {
                    calibration: { nse: 0.82 },
                    validation: { nse: 0.71 },
                  },
                },
              },
            );
            if (!resetView.reset || !resetView.shouldRestoreRun || resetView.chartData.run.path !== "C:/runs/A" ||
                !resetView.shouldUpdateMetrics || resetView.calibrationMetrics.nse !== 0.82 ||
                resetView.validationMetrics.nse !== 0.71 || resetView.metricMetadata.metrics.calibration.nse !== 0.82) {
              throw new Error(`manual param reset view state wrong: ${JSON.stringify(resetView)}`);
            }
            const resetViewWithoutRun = library.manualParamResetViewState({ TT: 0.1 }, null);
            if (!resetViewWithoutRun.reset || resetViewWithoutRun.shouldRestoreRun ||
                resetViewWithoutRun.chartData !== null || !resetViewWithoutRun.shouldUpdateMetrics ||
                Object.keys(resetViewWithoutRun.calibrationMetrics).length ||
                Object.keys(resetViewWithoutRun.validationMetrics).length) {
              throw new Error(`manual param reset view without run wrong: ${JSON.stringify(resetViewWithoutRun)}`);
            }
            const missingResetView = library.manualParamResetViewState(null, { metadata: { metrics: { calibration: { nse: 1 } } } });
            if (missingResetView.reset || missingResetView.shouldRestoreRun || missingResetView.chartData !== null ||
                missingResetView.shouldUpdateMetrics) {
              throw new Error(`missing manual param reset view should not reset: ${JSON.stringify(missingResetView)}`);
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
    def test_manual_preset_list_path_and_stale_compare_guard(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console, encodeURIComponent };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            for (const name of ["taskManualPresetLoadStartState", "taskManualPresetLoadSuccessState", "taskManualPresetLoadErrorState", "manualPresetTaskSyncState", "manualPresetConfigPathFromRunData", "manualPresetProfileState"]) {
              if (typeof library[name] !== "function") throw new Error(`${name} was not exported`);
            }
            const path = library.manualPresetListPath(" C:/工作区/workspace.json ", "daily mode", "all");
            if (path !== "/api/manual-presets?config_path=C%3A%2F%E5%B7%A5%E4%BD%9C%E5%8C%BA%2Fworkspace.json&calibration_profile=daily%20mode&scope=all") {
              throw new Error(`unexpected list path: ${path}`);
            }
            const configFromMetadata = library.manualPresetConfigPathFromRunData({
              metadata: { workspace_config: " C:/ws/meta.json " },
              run: { workspace_config: "C:/ws/run.json" },
            });
            if (configFromMetadata !== "C:/ws/meta.json") {
              throw new Error(`metadata config path should win: ${configFromMetadata}`);
            }
            const configFromRun = library.manualPresetConfigPathFromRunData({
              run: { workspace_config: " C:/ws/run.json " },
            });
            if (configFromRun !== "C:/ws/run.json") {
              throw new Error(`run config path fallback wrong: ${configFromRun}`);
            }
            if (library.manualPresetConfigPathFromRunData(null) !== "") {
              throw new Error("missing run data should return empty config path");
            }
            const samePath = (a, b) => String(a || "").replace(/\\/g, "/") === String(b || "").replace(/\\/g, "/");
            const emptyLoad = library.taskManualPresetLoadStartState(" ", "C:/ws/A", { samePath });
            if (emptyLoad.path !== "" || emptyLoad.shouldRequest || !emptyLoad.shouldRender ||
                emptyLoad.statePatch.taskManualPresetConfigPath !== "" ||
                emptyLoad.statePatch.taskManualPresets.length !== 0) {
              throw new Error(`empty task preset load start wrong: ${JSON.stringify(emptyLoad)}`);
            }
            const sameLoad = library.taskManualPresetLoadStartState("C:/ws/A", "C:\\ws\\A", { samePath });
            if (sameLoad.changed || !sameLoad.shouldRequest || sameLoad.shouldRender ||
                sameLoad.statePatch.taskManualPresetConfigPath !== "C:/ws/A" ||
                Object.prototype.hasOwnProperty.call(sameLoad.statePatch, "taskManualPresets")) {
              throw new Error(`same task preset load start wrong: ${JSON.stringify(sameLoad)}`);
            }
            const changedLoad = library.taskManualPresetLoadStartState(" C:/ws/B ", "C:/ws/A", { samePath });
            if (!changedLoad.changed || !changedLoad.shouldRequest || !changedLoad.shouldRender ||
                changedLoad.path !== "C:/ws/B" ||
                changedLoad.statePatch.taskManualPresetConfigPath !== "C:/ws/B" ||
                changedLoad.statePatch.taskManualPresets.length !== 0) {
              throw new Error(`changed task preset load start wrong: ${JSON.stringify(changedLoad)}`);
            }
            const loadSuccess = library.taskManualPresetLoadSuccessState({ presets: [{ id: "A" }, { id: "B" }] });
            if (loadSuccess.presets.length !== 2 || loadSuccess.statePatch.taskManualPresets[1].id !== "B") {
              throw new Error(`task preset load success wrong: ${JSON.stringify(loadSuccess)}`);
            }
            const loadSuccessFallback = library.taskManualPresetLoadSuccessState({});
            if (loadSuccessFallback.presets.length !== 0 || loadSuccessFallback.statePatch.taskManualPresets.length !== 0) {
              throw new Error(`task preset load success fallback wrong: ${JSON.stringify(loadSuccessFallback)}`);
            }
            const loadError = library.taskManualPresetLoadErrorState();
            if (loadError.presets.length !== 0 || loadError.statePatch.taskManualPresets.length !== 0) {
              throw new Error(`task preset load error wrong: ${JSON.stringify(loadError)}`);
            }
            const syncState = library.manualPresetTaskSyncState(
              " C:/ws/A/workspace.json ",
              "C:\\ws\\A\\workspace.json",
              { workspaceProfile: "hourly", runCalibrationProfile: "daily" },
              { samePath },
            );
            if (!syncState.shouldSync || syncState.sourceConfigPath !== "C:/ws/A/workspace.json" ||
                syncState.targetConfigPath !== "C:\\ws\\A\\workspace.json" ||
                syncState.calibrationProfile !== "hourly") {
              throw new Error(`manual preset task sync state wrong: ${JSON.stringify(syncState)}`);
            }
            const runProfileSync = library.manualPresetTaskSyncState(
              "C:/ws/A/workspace.json",
              "C:/ws/A/workspace.json",
              { workspaceProfile: "", runCalibrationProfile: "daily" },
              { samePath },
            );
            if (!runProfileSync.shouldSync || runProfileSync.calibrationProfile !== "daily") {
              throw new Error(`manual preset task sync run profile wrong: ${JSON.stringify(runProfileSync)}`);
            }
            const mismatchSync = library.manualPresetTaskSyncState("C:/ws/A/workspace.json", "C:/ws/B/workspace.json", {}, { samePath });
            if (mismatchSync.shouldSync || mismatchSync.calibrationProfile !== "daily") {
              throw new Error(`manual preset task sync mismatch wrong: ${JSON.stringify(mismatchSync)}`);
            }
            const emptySync = library.manualPresetTaskSyncState("", "", { workspaceProfile: "hourly" }, { samePath });
            if (emptySync.shouldSync || emptySync.sourceConfigPath || emptySync.targetConfigPath || emptySync.calibrationProfile !== "hourly") {
              throw new Error(`manual preset task sync empty path wrong: ${JSON.stringify(emptySync)}`);
            }
            const explicitProfile = library.manualPresetProfileState("C:/ws/A/workspace.json", " Hourly ", {}, { samePath });
            if (explicitProfile.profile !== "hourly" || explicitProfile.source !== "explicit") {
              throw new Error(`explicit manual preset profile wrong: ${JSON.stringify(explicitProfile)}`);
            }
            const runProfile = library.manualPresetProfileState(
              "C:/ws/A/workspace.json",
              "",
              {
                runConfigPath: "C:\\ws\\A\\workspace.json",
                runCalibrationProfile: " Daily ",
                taskConfigPath: "C:/ws/B/workspace.json",
                workspaceProfile: "hourly",
              },
              { samePath },
            );
            if (runProfile.profile !== "daily" || runProfile.source !== "run") {
              throw new Error(`run manual preset profile wrong: ${JSON.stringify(runProfile)}`);
            }
            const workspaceProfile = library.manualPresetProfileState(
              "C:/ws/B/workspace.json",
              "",
              {
                runConfigPath: "C:/ws/A/workspace.json",
                runCalibrationProfile: "daily",
                taskConfigPath: "C:/ws/B/workspace.json",
                workspaceProfile: "hourly",
              },
              { samePath },
            );
            if (workspaceProfile.profile !== "hourly" || workspaceProfile.source !== "workspace") {
              throw new Error(`workspace manual preset profile wrong: ${JSON.stringify(workspaceProfile)}`);
            }
            const fallbackProfile = library.manualPresetProfileState("C:/ws/C/workspace.json", "", {}, { samePath });
            if (fallbackProfile.profile !== "daily" || fallbackProfile.source !== "fallback") {
              throw new Error(`fallback manual preset profile wrong: ${JSON.stringify(fallbackProfile)}`);
            }
            if (library.shouldClearManualPresetComparison({ id: "same" }, "same")) {
              throw new Error("same id should keep comparison");
            }
            if (library.shouldClearManualPresetComparison({ parameter_set_id: "same-global" }, "same-global")) {
              throw new Error("same parameter_set_id should keep comparison");
            }
            if (!library.shouldClearManualPresetComparison({ id: "current" }, "old")) {
              throw new Error("different id should clear comparison");
            }
            if (!library.shouldClearManualPresetComparison(null, "old")) {
              throw new Error("missing current preset should clear stale comparison");
            }
            if (library.shouldClearManualPresetComparison({ id: "current" }, "")) {
              throw new Error("empty compare id should not clear");
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
    def test_manual_preset_control_state(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console, encodeURIComponent };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            if (typeof library.manualPresetControlViewState !== "function") {
              throw new Error("manualPresetControlViewState was not exported");
            }
            const ready = library.manualPresetControlState({
              editable: true,
              configPath: "C:/workspace.json",
              preset: { id: "p1" },
              compareMetrics: { nse_cal: 0.8 },
            });
            if (!ready.baseEnabled || !ready.presetActionEnabled || !ready.clearCompareEnabled) {
              throw new Error(`unexpected ready state: ${JSON.stringify(ready)}`);
            }

            const noPreset = library.manualPresetControlState({
              editable: true,
              configPath: "C:/workspace.json",
              preset: null,
            });
            if (!noPreset.baseEnabled || noPreset.presetActionEnabled || noPreset.clearCompareEnabled) {
              throw new Error(`unexpected no-preset state: ${JSON.stringify(noPreset)}`);
            }

            const readonly = library.manualPresetControlState({
              editable: false,
              configPath: "C:/workspace.json",
              preset: { id: "p1" },
              compareSeries: { dates: [] },
            });
            if (readonly.baseEnabled || readonly.presetActionEnabled || !readonly.clearCompareEnabled) {
              throw new Error(`unexpected readonly state: ${JSON.stringify(readonly)}`);
            }

            const readyView = library.manualPresetControlViewState({
              editable: true,
              configPath: "C:/workspace.json",
              preset: { id: "p1" },
              compareMetrics: { nse_cal: 0.8 },
            });
            if (readyView.controls.length !== 8 || readyView.controls.some(item => item.disabled)) {
              throw new Error(`unexpected ready controls: ${JSON.stringify(readyView.controls)}`);
            }
            const readonlyView = library.manualPresetControlViewState({
              editable: false,
              configPath: "C:/workspace.json",
              preset: { id: "p1" },
              compareSeries: { dates: [] },
            });
            const readonlyDisabled = Object.fromEntries(readonlyView.controls.map(item => [item.selector, item.disabled]));
            if (!readonlyDisabled["#manual-preset-name"] ||
                !readonlyDisabled["#btn-load-manual-preset"] ||
                readonlyDisabled["#btn-clear-manual-compare"]) {
              throw new Error(`unexpected readonly controls: ${JSON.stringify(readonlyView.controls)}`);
            }
            const expectedSelectors = [
              "#manual-preset-name",
              "#manual-preset-scope",
              "#manual-preset-select",
              "#btn-save-manual-preset",
              "#btn-load-manual-preset",
              "#btn-delete-manual-preset",
              "#btn-compare-manual-preset",
              "#btn-clear-manual-compare",
            ].join("|");
            if (readyView.controls.map(item => item.selector).join("|") !== expectedSelectors) {
              throw new Error(`unexpected control selectors: ${JSON.stringify(readyView.controls)}`);
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
    def test_task_preset_context_merges_workspace_and_form_values(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            if (typeof library.taskPresetContext !== "function") {
              throw new Error("taskPresetContext was not exported");
            }

            const daily = library.taskPresetContext({
              workspace: {
                率定模式: "daily",
                时间步长_小时: 24,
                任务时段模式: "event_windows",
                气象策略: {
                  降水方案: "grid_plus_station_bias",
                },
              },
              profile: "daily",
              objectiveMode: "daily_unified_professional_v1",
              precSource: "era5",
              glacierMode: "inline",
              paramBoundsProfile: "qtp_alpine_default",
            });
            if (daily.profile !== "daily" || daily.time_step_hours !== 24) {
              throw new Error(`daily profile or step mismatch: ${JSON.stringify(daily)}`);
            }
            if (daily.precipitation_mode !== "grid_plus_station_bias") {
              throw new Error(`daily precipitation mode should come from workspace: ${JSON.stringify(daily)}`);
            }
            if (daily.task_time_basis !== "event_windows") {
              throw new Error(`daily time basis should come from workspace: ${JSON.stringify(daily)}`);
            }
            if (daily.param_bounds_profile !== "qtp_alpine_default") {
              throw new Error(`daily bounds profile mismatch: ${JSON.stringify(daily)}`);
            }

            const hourly = library.taskPresetContext({
              workspace: {
                率定模式: "daily",
                time_step_hours: "bad",
                time_basis: "continuous",
                气象策略: {
                  precipitation_mode: "thiessen_station_only",
                },
              },
              profile: "hourly",
              objectiveMode: "flood_event",
              precSource: "custom_tif",
              glacierMode: "off",
              paramBoundsProfile: "should_be_ignored",
              precipitationMode: "grid_only",
              taskTimeBasis: "forecast_window",
            });
            if (hourly.profile !== "hourly" || hourly.time_step_hours !== 1) {
              throw new Error(`hourly profile or default step mismatch: ${JSON.stringify(hourly)}`);
            }
            if (hourly.param_bounds_profile !== "hourly_step") {
              throw new Error(`hourly bounds profile should be forced: ${JSON.stringify(hourly)}`);
            }
            if (hourly.precipitation_mode !== "grid_only" || hourly.task_time_basis !== "forecast_window") {
              throw new Error(`explicit form values should win: ${JSON.stringify(hourly)}`);
            }
            if (hourly.objective_mode !== "flood_event" || hourly.prec_source !== "custom_tif" || hourly.glacier_mode !== "off") {
              throw new Error(`task context core fields mismatch: ${JSON.stringify(hourly)}`);
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
    def test_manual_context_from_run_data_extracts_comparison_fields(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            if (typeof library.manualContextFromRunData !== "function") {
              throw new Error("manualContextFromRunData was not exported");
            }
            if (typeof library.manualPresetContextWarningState !== "function") {
              throw new Error("manualPresetContextWarningState was not exported");
            }

            const fromRun = library.manualContextFromRunData({
              metadata: {
                effective_objective_mode: "Daily_Unified_Professional_V1",
                data_sources: {
                  runtime_prec_source: "ERA5_GRID",
                  glacier_mode: "INLINE",
                },
                parameter_profile: {
                  bounds_profile: "QTP_ALPINE_DEFAULT",
                },
              },
            });
            if (fromRun.objective_mode !== "daily_unified_professional_v1") {
              throw new Error(`objective mode not normalized: ${JSON.stringify(fromRun)}`);
            }
            if (fromRun.prec_source !== "era5_grid" || fromRun.glacier_mode !== "inline") {
              throw new Error(`data source fields not normalized: ${JSON.stringify(fromRun)}`);
            }
            if (fromRun.param_bounds_profile !== "qtp_alpine_default") {
              throw new Error(`bounds profile not normalized: ${JSON.stringify(fromRun)}`);
            }

            const fromMeta = library.manualContextFromRunData(
              {
                optimization: { objective_mode: "legacy_mode" },
                data_sources: { configured_precip_source: "Custom_TIF" },
                param_bounds_profile: "Hourly_Step",
              },
              {
                effectiveObjectiveMode(meta) {
                  return `custom:${meta.optimization.objective_mode}`;
                },
              },
            );
            if (fromMeta.objective_mode !== "custom:legacy_mode") {
              throw new Error(`custom objective resolver not used: ${JSON.stringify(fromMeta)}`);
            }
            if (fromMeta.prec_source !== "custom_tif" || fromMeta.param_bounds_profile !== "hourly_step") {
              throw new Error(`metadata fallback fields mismatch: ${JSON.stringify(fromMeta)}`);
            }
            const warningState = library.manualPresetContextWarningState(
              {
                objective_mode: "legacy_mode",
                prec_source: "custom_tif",
                param_bounds_profile: "wide_bounds",
              },
              {
                metadata: {
                  optimization: { objective_mode: "daily_unified_professional_v1" },
                  data_sources: { configured_precip_source: "ERA5" },
                  param_bounds_profile: "qtp_alpine_default",
                },
              },
              {
                objectiveLabel(value) { return `OBJ:${value}`; },
                precipSourceLabel(value) { return `P:${value}`; },
                boundsLabel(value) { return `B:${value}`; },
              },
            );
            const expectedWarning = "注意：目标函数模式不同（参数集 OBJ:legacy_mode，当前 OBJ:daily_unified_professional_v1）；降水驱动不同（参数集 P:custom_tif，当前 P:era5）；参数范围不同（参数集 B:wide_bounds，当前 B:qtp_alpine_default）。";
            if (warningState.text !== expectedWarning || warningState.current.objective_mode !== "daily_unified_professional_v1") {
              throw new Error(`manual preset context warning state wrong: ${JSON.stringify(warningState)}`);
            }
            const emptyWarning = library.manualPresetContextWarningState(null, { metadata: {} });
            if (emptyWarning.text !== "") {
              throw new Error(`missing preset should not warn: ${JSON.stringify(emptyWarning)}`);
            }
            const missingRunWarning = library.manualPresetContextWarningState({ objective_mode: "legacy" }, null);
            if (missingRunWarning.text !== "") {
              throw new Error(`missing run data should not warn: ${JSON.stringify(missingRunWarning)}`);
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
    def test_manual_group_helpers_and_param_slider_rendering(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            for (const name of ["manualGroupParamNames", "manualPhaseGuide", "manualChangeSummary", "manualChangeSummaryPanelState", "renderParamSliders"]) {
              if (typeof library[name] !== "function") throw new Error(`${name} was not exported`);
            }
            const groupParams = {
              all: [],
              snow: ["TT", "SFCF"],
              soil: ["FC"],
              glacier: ["ICE_FACTOR"],
            };
            const groupMeta = {
              all: { title: "全部参数", guide: "先看整体。" },
              snow: { title: "雪过程", guide: "再看融雪。" },
              glacier: { title: "冰川过程", guide: "最后看冰川。" },
            };
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
            };

            const snowNames = library.manualGroupParamNames("snow", ["TT", "FC", "SFCF"], groupParams);
            if (snowNames.join(",") !== "TT,SFCF") throw new Error(`unexpected snow names: ${snowNames}`);
            const allNames = library.manualGroupParamNames("all", ["TT", "FC"], groupParams);
            if (allNames.join(",") !== "TT,FC") throw new Error(`unexpected all names: ${allNames}`);

            const guide = library.manualPhaseGuide("snow", ["TT", "FC"], groupMeta, groupParams);
            if (guide.className !== "hint-box" || !guide.text.includes("雪过程：再看融雪。 当前显示 1 个参数。")) {
              throw new Error(`unexpected guide: ${JSON.stringify(guide)}`);
            }
            const emptyGuide = library.manualPhaseGuide("glacier", ["TT", "FC"], groupMeta, groupParams);
            if (emptyGuide.className !== "hint-box status-warn" || !emptyGuide.text.includes("当前结果中没有这一组参数")) {
              throw new Error(`unexpected empty guide: ${JSON.stringify(emptyGuide)}`);
            }

            const changed = library.manualChangeSummary({ TT: 0.2, FC: 100 }, { TT: 0.1, FC: 100 }, "snow", groupParams);
            if (!changed.visible || changed.text !== "已修改 1 个参数。当前分组中已改动：TT") {
              throw new Error(`unexpected changed summary: ${JSON.stringify(changed)}`);
            }
            const hidden = library.manualChangeSummary({ TT: 0.1 }, { TT: 0.1 }, "snow", groupParams);
            if (hidden.visible || hidden.text) throw new Error("unchanged params should hide summary");
            const hiddenPanel = library.manualChangeSummaryPanelState({ TT: 0.1 }, { TT: 0.1 }, "snow", groupParams);
            if (hiddenPanel.visible || hiddenPanel.text !== "" || hiddenPanel.className !== "hint-box") {
              throw new Error(`unexpected hidden change panel: ${JSON.stringify(hiddenPanel)}`);
            }
            const changedPanel = library.manualChangeSummaryPanelState({ TT: 0.2, FC: 100 }, { TT: 0.1, FC: 100 }, "snow", groupParams);
            if (!changedPanel.visible || changedPanel.className !== "hint-box status-warn" ||
                changedPanel.text !== "已修改 1 个参数。当前分组中已改动：TT") {
              throw new Error(`unexpected changed panel: ${JSON.stringify(changedPanel)}`);
            }

            const readonly = library.renderParamSliders({ editable: false }, helpers);
            if (readonly.status !== "readonly" || !readonly.html.includes("不能手动调参")) {
              throw new Error(`unexpected readonly sliders: ${JSON.stringify(readonly)}`);
            }
            const groupEmpty = library.renderParamSliders({
              editable: true,
              params: { TT: 0.5 },
              bounds: { TT: [0, 1] },
              group: "glacier",
              groupParams,
              labels: { TT: "温度阈值" },
            }, helpers);
            if (groupEmpty.status !== "group-empty" || !groupEmpty.html.includes("当前分组没有可调参数")) {
              throw new Error(`unexpected group-empty sliders: ${JSON.stringify(groupEmpty)}`);
            }
            const rendered = library.renderParamSliders({
              editable: true,
              params: { "TT<bad>": 0.5, FC: 130 },
              bounds: { "TT<bad>": [0, 1], FC: [100, 200] },
              group: "all",
              groupParams,
              labels: { "TT<bad>": "温度<阈值>", FC: "土壤蓄水" },
            }, helpers);
            if (rendered.status !== "ready" || rendered.paramNames.length !== 2 || rendered.shownParamNames.length !== 2) {
              throw new Error(`unexpected rendered status: ${JSON.stringify(rendered)}`);
            }
            if (!rendered.html.includes('data-param="TT&lt;bad&gt;"') || !rendered.html.includes("温度&lt;阈值&gt;")) {
              throw new Error(`slider html should escape names and labels: ${rendered.html}`);
            }
            if (!rendered.html.includes('step="0.001"') || !rendered.html.includes('min="100"') || !rendered.html.includes('max="200"')) {
              throw new Error(`slider bounds or step missing: ${rendered.html}`);
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
