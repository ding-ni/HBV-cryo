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


if __name__ == "__main__":
    unittest.main()
