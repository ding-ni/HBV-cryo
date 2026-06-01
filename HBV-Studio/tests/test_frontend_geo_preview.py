import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendGeoPreviewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_station_point_layer_is_rendered_in_svg_preview(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/geoPreview.js", "utf8"), context);

            const geo = context.window.HBVStudioGeoPreview;
            if (!geo) throw new Error("geo preview module was not exported");
            const html = geo.renderOverview({
              flow_name: "测试流域",
              available_layer_count: 1,
              focus_bounds: { west: 99.8, south: 30.8, east: 100.5, north: 31.4 },
              layers: [
                {
                  id: "stations",
                  label: "站点",
                  kind: "point",
                  status: "ok",
                  message: "2 个站点",
                  metrics: { station_count: 2 },
                  points: [
                    { id: "S1", label: "S<1", coord: [100.0, 31.0] },
                    { id: "S2", label: "S2", coord: [100.3, 31.2] },
                  ],
                },
              ],
            });

            if (!html.includes("<circle")) throw new Error(`station circles were not rendered: ${html}`);
            if (!html.includes("geo-layer-stations")) throw new Error("station CSS class missing");
            if (!html.includes("S&lt;1")) throw new Error("station label should be escaped");
            if (!html.includes("站点")) throw new Error("station metric label missing");
            if (!html.includes("2 个")) throw new Error("station count metric missing");
            if (!html.includes('data-geo-layer-count="1"')) throw new Error("layer count attribute mismatch");
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
