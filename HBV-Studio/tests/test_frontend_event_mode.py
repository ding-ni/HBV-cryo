import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendEventModeTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_flood_event_summary_rows_and_labels(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/eventMode.js", "utf8"), context);

            const eventMode = context.window.HBVStudioEventMode;
            if (!eventMode) throw new Error("event mode module was not exported");

            const evaluation = {
              enabled: true,
              objective_enabled: true,
              valid_event_count: 2,
              event_count: 3,
              summary: { all: { mean_diagnostic_objective: 0.123456 } },
              events: Array.from({ length: 13 }, (_, index) => ({
                name: index === 0 ? "2020-07 洪水" : "",
                peak_error_percent: index + 0.125,
                peak_time_error_hours: index + 0.5,
                volume_error_percent: index + 0.75,
                nse: 0.8 + index / 100,
                kge: 0.7 + index / 100,
              })),
            };
            const meta = {
              diagnostics: { flood_event_evaluation: evaluation },
              event_mode: {
                enabled: true,
                runtime_mode: "independent_event_windows",
                event_count: 3,
                initial_state_policy: "source_state",
              },
            };

            if (eventMode.floodEventEvaluation(meta) !== evaluation) {
              throw new Error("evaluation fallback path mismatch");
            }
            if (eventMode.floodEventStatusText(evaluation) !== "事件目标函数：2/3 场有效") {
              throw new Error("status text mismatch");
            }
            if (eventMode.floodEventObjectiveText(evaluation) !== "0.1235") {
              throw new Error("objective text mismatch");
            }
            if (eventMode.initialStatePolicyLabel("source_state") !== "来源状态") {
              throw new Error("initial state policy label mismatch");
            }

            const rows = eventMode.floodEventRows(meta);
            if (rows.length !== 16) throw new Error(`unexpected row count: ${rows.length}`);
            if (rows[0][0] !== "事件评价" || rows[0][1] !== "事件目标函数：2/3 场有效") {
              throw new Error(`unexpected first row: ${JSON.stringify(rows[0])}`);
            }
            if (rows[1][0] !== "事件目标值" || rows[1][1] !== "0.1235") {
              throw new Error(`unexpected objective row: ${JSON.stringify(rows[1])}`);
            }
            if (rows[2][0] !== "事件资料模式" || rows[2][1] !== "事件窗口独立运行，3 场" || rows[2][2] !== "初始条件：来源状态") {
              throw new Error(`unexpected event runtime row: ${JSON.stringify(rows[2])}`);
            }
            if (rows[3][0] !== "2020-07 洪水" || rows[3][1] !== "洪峰 0.13% / 峰现 0.5 h / 洪量 0.75%") {
              throw new Error(`unexpected event metric row: ${JSON.stringify(rows[3])}`);
            }
            const more = rows[rows.length - 1];
            if (more[0] !== "更多事件" || more[1] !== "还有 1 场") {
              throw new Error(`unexpected overflow row: ${JSON.stringify(more)}`);
            }

            if (eventMode.floodEventStatusText({ enabled: false }) !== "未启用") {
              throw new Error("disabled status mismatch");
            }
            if (eventMode.floodEventRows({}).length !== 0) {
              throw new Error("disabled rows should be empty");
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
