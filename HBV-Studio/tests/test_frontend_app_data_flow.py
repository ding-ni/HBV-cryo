import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendAppDataFlowTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_task_completion_state_selects_finished_run_targets(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/taskView.js", "utf8"), context);
            vm.runInContext(fs.readFileSync("web/js/appDataFlow.js", "utf8"), context);

            const dataFlow = context.window.HBVStudioAppDataFlow;
            if (typeof dataFlow?.taskCompletionState !== "function") {
              throw new Error("missing app data flow export");
            }

            const tasks = [
              { id: "manual", task_type: "manual_start", status: "completed", config_path: "C:/ws/A.json", result: { run_path: "C:/runs/manual" } },
              { id: "calibration", task_type: "calibration", status: "completed", config_path: "C:/ws/A.json", result: { workspace_config: "C:/ws/B.json" }, detected_runs: ["C:/runs/calib-detected"] },
              { id: "forecast", task_type: "forecast_restart", status: "completed", result: { run_path: "C:/runs/forecast" } },
              { id: "still-running", task_type: "calibration", status: "running" },
              { id: "new-complete", task_type: "manual_start", status: "completed", result: { run_path: "C:/runs/new" } },
            ];
            const previous = new Map([
              ["manual", { id: "manual", status: "running" }],
              ["calibration", { id: "calibration", status: "running" }],
              ["forecast", { id: "forecast", status: "running" }],
              ["still-running", { id: "still-running", status: "running" }],
            ]);

            const state = dataFlow.taskCompletionState(tasks, previous, {
              taskView: context.window.HBVStudioTaskView,
              latestEditableRunPath: () => "C:/runs/latest",
            });

            if (state.finishedTaskIds.join("|") !== "manual|calibration|forecast") {
              throw new Error(`finished ids mismatch: ${state.finishedTaskIds.join("|")}`);
            }
            if (!state.hasFinishedTasks) throw new Error("finished flag should be true");
            if (state.manualStartRunPath !== "C:/runs/manual") {
              throw new Error(`manual run path mismatch: ${state.manualStartRunPath}`);
            }
            if (state.manualStartWorkspacePath !== "C:/ws/A.json") {
              throw new Error(`manual workspace mismatch: ${state.manualStartWorkspacePath}`);
            }
            if (state.calibrationRunPath !== "C:/runs/calib-detected") {
              throw new Error(`calibration run path mismatch: ${state.calibrationRunPath}`);
            }
            if (state.calibrationWorkspacePath !== "C:/ws/B.json") {
              throw new Error(`calibration workspace mismatch: ${state.calibrationWorkspacePath}`);
            }
            if (state.forecastTask?.id !== "forecast") {
              throw new Error(`forecast task mismatch: ${state.forecastTask?.id}`);
            }

            const fallbackState = dataFlow.taskCompletionState(
              [{ id: "calib", task_type: "calibration", status: "completed" }],
              new Map([["calib", { id: "calib", status: "running" }]]),
              {
                taskView: context.window.HBVStudioTaskView,
                latestEditableRunPath: () => "C:/runs/latest",
              },
            );
            if (fallbackState.calibrationRunPath !== "C:/runs/latest") {
              throw new Error(`latest editable fallback mismatch: ${fallbackState.calibrationRunPath}`);
            }
            """
        )
        proc = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == "__main__":
    unittest.main()
