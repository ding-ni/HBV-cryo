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
    def test_manual_preset_applied_params_merges_and_marks_changes(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/parameterLibrary.js", "utf8"), context);

            const library = context.window.HBVStudioParameterLibrary;
            if (typeof library.manualPresetAppliedParams !== "function") {
              throw new Error("manualPresetAppliedParams was not exported");
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
            const path = library.manualPresetListPath(" C:/工作区/workspace.json ", "daily mode", "all");
            if (path !== "/api/manual-presets?config_path=C%3A%2F%E5%B7%A5%E4%BD%9C%E5%8C%BA%2Fworkspace.json&calibration_profile=daily%20mode&scope=all") {
              throw new Error(`unexpected list path: ${path}`);
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
            for (const name of ["manualGroupParamNames", "manualPhaseGuide", "manualChangeSummary", "renderParamSliders"]) {
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
