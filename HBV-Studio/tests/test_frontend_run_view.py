import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendRunViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_run_display_names_hide_generated_directory_names(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/runView.js", "utf8"), context);

            const runView = context.window.HBVStudioRunView;
            if (!runView) throw new Error("run view module was not exported");
            const generatedRun = {
              name: "hbv_manual_20260102_030405",
              run_type: "manual_result",
              workspace_config: "C:/workspace/a/config.json",
              run_time_label: "2026-01-02 03:04",
            };
            const displayName = runView.runDisplayName(generatedRun, {
              workspaceLabelByPath: () => "玛曲流域",
            });
            if (displayName !== "玛曲流域 · 手调结果 · 2026-01-02 03:04") {
              throw new Error(`unexpected display name: ${displayName}`);
            }

            const explicit = runView.runDisplayName({ result_title: "状态接续预报A" });
            if (explicit !== "连续状态预报A") throw new Error(`unexpected explicit name: ${explicit}`);

            const subtitle = runView.runDisplaySubtitle({ display_subtitle: "目录名：hbv_run_20260102_030405" });
            if (subtitle !== "") throw new Error(`generated subtitle should be hidden: ${subtitle}`);
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
    def test_run_time_ranges_and_objective_statuses(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/runView.js", "utf8"), context);

            const runView = context.window.HBVStudioRunView;
            const hourly = runView.timeRangeText("2026-01-01T03:00", "2026-01-02T04:00", 1);
            if (hourly !== "2026-01-01 03:00 ~ 2026-01-02 04:00") {
              throw new Error(`unexpected hourly range: ${hourly}`);
            }
            const daily = runView.timeRangeText("2026-01-01T03:00", "2026-01-02T04:00", 24);
            if (daily !== "2026-01-01 ~ 2026-01-02") {
              throw new Error(`unexpected daily range: ${daily}`);
            }

            const current = runView.objectiveVersionStatus({ recorded_objective_family: "daily_unified_professional_v1" });
            if (current.label !== "当前口径" || current.badgeClass !== "status-ok") {
              throw new Error(`unexpected current status: ${JSON.stringify(current)}`);
            }
            const currentHourly = runView.objectiveVersionStatus({ objective_family: "hourly_alpine_qtp_v1" });
            if (currentHourly.label !== "当前口径" ||
                currentHourly.value !== "当前小时尺度综合评价口径" ||
                currentHourly.badgeClass !== "status-ok") {
              throw new Error(`unexpected hourly status: ${JSON.stringify(currentHourly)}`);
            }
            const legacy = runView.objectiveVersionStatus({ objective_family: "weighted_daily_universal" });
            if (legacy.label !== "历史口径" || legacy.badgeClass !== "status-warn") {
              throw new Error(`unexpected legacy status: ${JSON.stringify(legacy)}`);
            }
            const badge = runView.runTypeBadge({ run_type: "forecast_restart" });
            if (!badge.includes("连续状态预报")) throw new Error(`unexpected badge: ${badge}`);
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
