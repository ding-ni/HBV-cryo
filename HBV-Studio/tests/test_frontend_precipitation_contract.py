import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendPrecipitationContractTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_wizard_roundtrips_algorithm_and_training_dates_and_preserves_boundary_policy(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");
            const source = fs.readFileSync("web/app.js", "utf8");
            const elements = new Map();
            const radios = {};
            const getElement = selector => {
              if (!elements.has(selector)) {
                const classes = new Set();
                elements.set(selector, {
                  value: "", textContent: "", innerHTML: "", className: "", style: {},
                  classList: {
                    add: name => classes.add(name),
                    remove: name => classes.delete(name),
                    toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
                    contains: name => classes.has(name),
                  },
                });
              }
              return elements.get(selector);
            };
            const context = {
              window: {}, console, state: {}, $: getElement, $all: () => [],
              getSelectedRadio: name => radios[name] || "",
              setRadioAndCard: (name, value) => { radios[name] = value; },
              setRadioValue: (name, value) => { radios[name] = value; },
              workspaceConfiguredPrecipSource: cfg => cfg.气象策略?.降水来源 || "era5",
              taskManualPresetRequestGuard: { cancel() {} },
              clearInterval() {},
            };
            for (const name of [
              "clearInputCheckCache", "updateEventModeHint", "applyStep6MeteoDefaults",
              "updateConditionalFields", "updateGisMode", "updateSidebar", "refreshCalibrationControls",
              "refreshWizardWorkspacePreview", "syncObjectiveModeCards", "stopPrepTaskPolling",
              "stopForwardSimPolling", "renderManualPresetOptions", "updateManualGroupToolbar",
            ]) context[name] = () => {};
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/dataPrepView.js", "utf8"), context);
            for (const name of ["WIZARD_TIME_FIELDS", "STATION_RULE_TIME_FIELDS"]) {
              const match = source.match(new RegExp("const " + name + " = \\[[\\s\\S]*?\\];"));
              if (!match) throw new Error("missing time field list " + name);
              vm.runInContext(match[0], context);
            }
            for (const name of [
              "isHourlyTimescaleSelected", "toWizardInputTimeValue", "fromWizardInputTimeValue",
              "setWizardTimeValue", "getWizardTimeValue", "syncWizardTimeInputMode",
              "getWizardStationCorrectionAlgorithm", "populateStationCorrectionFields",
              "updateStationCorrectionFields", "collectStepData", "populateWizardFromConfig", "resetWizard",
            ]) {
              const match = source.match(new RegExp("^function " + name + "\\([\\s\\S]*?^\\}", "m"));
              if (!match) throw new Error("missing wizard function " + name);
              vm.runInContext(match[0], context);
            }

            for (const profile of ["daily", "hourly"]) {
              for (const algorithm of ["monthly_transfer_v3", "occurrence_amount_v2", "legacy_ratio_v1"]) {
                const trainingStart = profile === "hourly" ? "2025-05-01 08:00" : "2025-05-01";
                const trainingEnd = profile === "hourly" ? "2025-09-10 08:00" : "2025-09-10";
                const cfg = {
                  率定模式: profile,
                  气象策略: {
                    降水方案: "grid_plus_station_bias", station_correction_algorithm: algorithm,
                    station_rule_training_start: trainingStart, station_rule_training_end: trainingEnd,
                  },
                  边界条件: { 缺失填补: "zero" },
                };
                context.populateWizardFromConfig(cfg, "workspaces/project.json");
                const payload = context.collectStepData(4).气象策略;
                if (payload.station_correction_algorithm !== algorithm ||
                    payload.station_rule_training_start !== trainingStart ||
                    payload.station_rule_training_end !== trainingEnd) {
                  throw new Error("wizard changed recorded correction contract: " + JSON.stringify(payload));
                }
                if (context.collectStepData(3).gap_fill !== "zero") {
                  throw new Error("loading an existing explicit zero policy must preserve it");
                }
                const trainingHidden = getElement("#wz-station-rule-training-fields").classList.contains("hidden");
                if (trainingHidden !== (algorithm !== "monthly_transfer_v3")) {
                  throw new Error("training fields visibility is inconsistent with selected method");
                }
                if (profile === "hourly" && getElement("#wz-station-rule-training-start").type !== "datetime-local") {
                  throw new Error("hourly training dates must preserve hours");
                }
              }
            }

            context.populateWizardFromConfig({ 气象策略: { 降水方案: "grid_plus_station_bias" } }, "old.json");
            if (context.collectStepData(4).气象策略.station_correction_algorithm !== "legacy_ratio_v1") {
              throw new Error("unversioned existing projects must remain legacy on load/save");
            }
            context.resetWizard();
            if (context.collectStepData(3).gap_fill !== "preserve_missing") {
              throw new Error("new wizard reset must not silently select zero filling");
            }
            const resetMeteo = context.collectStepData(4).气象策略;
            if (resetMeteo.station_correction_algorithm !== "monthly_transfer_v3" ||
                resetMeteo.station_rule_training_start !== "" || resetMeteo.station_rule_training_end !== "") {
              throw new Error("new wizard should default to transfer with automatic overlap training");
            }
            """
        )
        proc = subprocess.run(["node", "-e", script], cwd=STUDIO_DIR, capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_wizard_exposes_methods_and_distinguishes_unobserved_boundary_from_zero(self) -> None:
        html = (STUDIO_DIR / "web" / "index.html").read_text(encoding="utf-8")
        for algorithm in ("monthly_transfer_v3", "occurrence_amount_v2", "legacy_ratio_v1"):
            self.assertIn(f'value="{algorithm}"', html)
        self.assertIn('id="wz-station-rule-training-start"', html)
        self.assertIn('id="wz-station-rule-training-end"', html)
        self.assertIn("统计订正：学习规则后应用全时段", html)
        self.assertIn("缺少该月观测支持时保留原格点并标注未验证", html)
        self.assertIn("实测零流量保留为 0，未观测的时段保留缺测", html)


if __name__ == "__main__":
    unittest.main()
