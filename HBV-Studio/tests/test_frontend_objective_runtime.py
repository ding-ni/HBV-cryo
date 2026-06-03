import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendObjectiveRuntimeTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_objective_runtime_helpers(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/objectiveRuntime.js", "utf8"), context);

            const runtime = context.window.HBVStudioObjectiveRuntime;
            for (const name of ["effectiveObjectiveMode", "objectiveDetail", "objectiveLabel", "objectiveSummary", "requestedObjectiveMode"]) {
              if (typeof runtime?.[name] !== "function") {
                throw new Error(`missing objective runtime export: ${name}`);
              }
            }

            if (runtime.objectiveLabel("daily_unified_professional_v1") !== "统一日尺度专业目标函数" ||
                runtime.objectiveLabel("SINGLE_OBJECTIVE_NSE") !== "单指标纳什效率系数" ||
                runtime.objectiveLabel("") !== "未设置" ||
                runtime.objectiveLabel("custom_objective") !== "custom_objective") {
              throw new Error("objective label mismatch");
            }

            const objectiveMeta = {
              objective_profile: { type: "daily_unified_professional_v1" },
              optimization: { requested_objective_mode: "auto" },
            };
            if (runtime.effectiveObjectiveMode(objectiveMeta) !== "daily_unified_professional_v1" ||
                runtime.requestedObjectiveMode(objectiveMeta) !== "auto" ||
                !runtime.objectiveDetail(objectiveMeta).includes("流量拟合优先") ||
                !runtime.objectiveSummary(objectiveMeta).includes("统一日尺度专业目标函数")) {
              throw new Error("daily objective summary mismatch");
            }

            const legacyMeta = { objective_family: "weighted_daily_universal" };
            if (!runtime.objectiveDetail(legacyMeta).includes("历史结果")) {
              throw new Error("legacy objective detail mismatch");
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
