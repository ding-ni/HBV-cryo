import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendCalibrationViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_calibration_view_builds_request_states(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/calibrationView.js", "utf8"), context);

            const calibration = context.window.HBVStudioCalibrationView;
            if (!calibration?.calibrationLoadState ||
                !calibration?.calibrationStartRequestState ||
                !calibration?.selfCheckStartRequestState) {
              throw new Error("calibration view module exports are missing");
            }

            const selfCheck = calibration.selfCheckStartRequestState();
            if (!selfCheck.ready || selfCheck.requestPath !== "/api/self-check/start" ||
                Object.keys(selfCheck.payload).length !== 0) {
              throw new Error(`self-check request state mismatch: ${JSON.stringify(selfCheck)}`);
            }

            const mcOnlyLoad = calibration.calibrationLoadState({
              method: "mc_only",
              mcSamples: "250",
              workers: "5",
              paramCount: 20,
            });
            if (mcOnlyLoad.estimated !== 250 ||
                mcOnlyLoad.perWorker !== 50 ||
                mcOnlyLoad.label !== "\u5feb\u901f\u7b5b\u9009" ||
                mcOnlyLoad.level !== "light") {
              throw new Error(`mc-only load mismatch: ${JSON.stringify(mcOnlyLoad)}`);
            }

            const deLoad = calibration.calibrationLoadState({
              method: "de",
              maxiter: "10",
              popsize: "5",
              workers: "2",
              paramCount: 20,
            });
            if (deLoad.population !== 100 ||
                deLoad.estimated !== 1100 ||
                deLoad.perWorker !== 550 ||
                deLoad.label !== "\u7cbe\u7ec6\u641c\u7d22" ||
                deLoad.level !== "light") {
              throw new Error(`de load mismatch: ${JSON.stringify(deLoad)}`);
            }

            const combinedLoad = calibration.calibrationLoadState({
              method: "mc_screen_de",
              maxiter: "24",
              popsize: "10",
              mcSamples: "1000",
              workers: "4",
              paramCount: 50,
            });
            if (combinedLoad.population !== 500 ||
                combinedLoad.estimated !== 13500 ||
                combinedLoad.perWorker !== 3375 ||
                combinedLoad.label !== "\u5feb\u901f\u7b5b\u9009 + \u7cbe\u7ec6\u641c\u7d22" ||
                combinedLoad.level !== "heavy") {
              throw new Error(`combined load mismatch: ${JSON.stringify(combinedLoad)}`);
            }

            const missing = calibration.calibrationStartRequestState({ configPath: " ", method: "" });
            if (missing.ready || missing.reason !== "missing-workspace" ||
                missing.requestPath !== "/api/calibration/start" ||
                missing.payload.config_path !== "" ||
                missing.payload.calibration_mode !== "daily" ||
                missing.payload.objective_mode !== "daily_unified_professional_v1" ||
                missing.payload.prec_source !== "era5" ||
                missing.payload.glacier_mode !== "inline" ||
                missing.payload.workers !== 4 ||
                missing.payload.maxiter !== 24 ||
                missing.payload.popsize !== 6 ||
                missing.payload.seed !== 42 ||
                missing.payload.method !== "de" ||
                missing.payload.mc_samples !== 300 ||
                missing.payload.param_bounds_profile !== "qtp_alpine_default" ||
                missing.payload.init_preset_id !== "" ||
                missing.payload.init_bound_shrink !== 0 ||
                missing.payload.debug_days !== 0 ||
                missing.payload.quick_test !== false ||
                missing.payload.quick_days !== 30 ||
                missing.payload.refine_enabled !== false ||
                missing.payload.refine_maxiter !== 0) {
              throw new Error(`missing calibration request state mismatch: ${JSON.stringify(missing)}`);
            }

            const request = calibration.calibrationStartRequestState({
              configPath: " C:/ws/A.json ",
              calibrationMode: "hourly",
              objectiveMode: "flood_event_calibration_v1",
              precipSource: "custom_tif",
              glacierMode: "off",
              workers: "8",
              maxiter: "40",
              popsize: "7",
              seed: "123",
              method: "mc_screen_de",
              mcSamples: "500",
              paramBoundsProfile: "generic_wide",
              initPresetId: "preset-A",
              initBoundShrink: "0.35",
              debugDays: "10",
              quickTest: true,
              quickDays: "20",
              refineEnabled: true,
              refineMaxiter: "-3",
            });
            if (!request.ready || request.reason ||
                request.configPath !== "C:/ws/A.json" ||
                request.requestPath !== "/api/calibration/start") {
              throw new Error(`calibration request state should be ready: ${JSON.stringify(request)}`);
            }
            const payload = request.payload;
            if (payload.config_path !== "C:/ws/A.json" ||
                payload.calibration_mode !== "hourly" ||
                payload.objective_mode !== "flood_event_calibration_v1" ||
                payload.prec_source !== "custom_tif" ||
                payload.glacier_mode !== "off" ||
                payload.workers !== 8 ||
                payload.maxiter !== 40 ||
                payload.popsize !== 7 ||
                payload.seed !== 123 ||
                payload.method !== "mc_screen_de" ||
                payload.mc_samples !== 500 ||
                payload.param_bounds_profile !== "generic_wide" ||
                payload.init_preset_id !== "preset-A" ||
                payload.init_bound_shrink !== 0.35 ||
                payload.debug_days !== 10 ||
                payload.quick_test !== true ||
                payload.quick_days !== 20 ||
                payload.refine_enabled !== true ||
                payload.refine_maxiter !== 0) {
              throw new Error(`calibration payload mismatch: ${JSON.stringify(payload)}`);
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
