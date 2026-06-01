import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendStationPrecipTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_mode_labels_descriptions_and_validation_lookup(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/stationPrecip.js", "utf8"), context);

            const station = context.window.HBVStudioStationPrecip;
            if (!station) throw new Error("station precipitation module was not exported");

            if (station.stationPrecipModeLabel("grid_only") !== "格点直接使用") {
              throw new Error("grid-only label mismatch");
            }
            if (station.stationPrecipModeLabel("grid_plus_station_bias") !== "格点 + 站点偏差订正") {
              throw new Error("station-bias label mismatch");
            }
            if (station.stationPrecipModeLabel("thiessen_station_only") !== "纯泰森多边形插值") {
              throw new Error("thiessen label mismatch");
            }
            if (station.stationPrecipModeLabel("unknown_mode") !== "格点直接使用") {
              throw new Error("unknown mode should fall back to grid-only label");
            }

            const biasDescription = station.stationPrecipModeDescription("grid_plus_station_bias");
            if (!biasDescription.includes("修正格点降水")) throw new Error(`unexpected bias description: ${biasDescription}`);
            const thiessenDescription = station.stationPrecipModeDescription("thiessen_station_only");
            if (!thiessenDescription.includes("站点降水直接生成面降水")) throw new Error(`unexpected thiessen description: ${thiessenDescription}`);
            const gridDescription = station.stationPrecipModeDescription("grid_only");
            if (!gridDescription.includes("当前格点数据源")) throw new Error(`unexpected grid description: ${gridDescription}`);

            const byId = { id: "station_precip", title: "其他标题" };
            const byTitle = { id: "other", title: "站点降水专项检查" };
            const validation = { focus_checks: [{ id: "glacier" }, byId, byTitle] };
            if (station.stationPrecipCheckFromValidation(validation) !== byId) {
              throw new Error("station check should prefer canonical id");
            }
            const titleOnly = { focus_checks: [{ id: "glacier" }, byTitle] };
            if (station.stationPrecipCheckFromValidation(titleOnly) !== byTitle) {
              throw new Error("station check should fall back to title match");
            }
            if (station.stationPrecipCheckFromValidation({ focus_checks: [{ id: "glacier" }] }) !== null) {
              throw new Error("missing station check should return null");
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
