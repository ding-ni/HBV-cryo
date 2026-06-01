import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendForecastViewTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
