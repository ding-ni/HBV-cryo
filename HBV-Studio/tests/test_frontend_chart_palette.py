import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = STUDIO_DIR / "web"


class FrontendChartPaletteTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_chart_palette_exports_scientific_dashboard_colors(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/chartPalette.js", "utf8"), context);

            const palette = context.window.HBVStudioChartPalette;
            if (!palette) throw new Error("chart palette module was not exported");
            if (typeof palette.chartColors !== "function") throw new Error("chartColors was not exported");

            const colors = palette.chartColors();
            const expected = {
              qObs: "#1e293b",
              qSim: "#0e7490",
              qRain: "#2563eb",
              qSnow: "#38bdf8",
              qIce: "#06b6d4",
              boundary: "#64748b",
              residual: "#b91c1c",
              precip: "#2563eb",
              temp: "#ef4444",
            };
            for (const [key, value] of Object.entries(expected)) {
              if (colors[key] !== value) {
                throw new Error(`unexpected ${key}: ${colors[key]}`);
              }
            }
            if (!Object.isFrozen(colors)) throw new Error("chart colors should be immutable");
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

    def test_legacy_chart_colors_are_not_hard_coded_in_frontend(self) -> None:
        legacy_colors = [
            "#1d6d74",
            "#b36a28",
            "#317f95",
            "#b7ced8",
            "#8aa9b7",
            "#2d7c52",
            "#b54538",
            "#7c5c99",
        ]
        paths = [
            WEB_DIR / "app.js",
            WEB_DIR / "js" / "eventMode.js",
            WEB_DIR / "js" / "forecastView.js",
        ]
        for path in paths:
            source = path.read_text(encoding="utf-8")
            for color in legacy_colors:
                self.assertNotIn(color, source, f"{path.name} still hard-codes {color}")


if __name__ == "__main__":
    unittest.main()
