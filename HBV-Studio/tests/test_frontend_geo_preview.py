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

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_maplibre_layer_plan_uses_offline_geo_endpoints(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console, URLSearchParams };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/mapLayerPlan.js", "utf8"), context);

            const geo = context.window.HBVStudioMapLayerPlan;
            if (!geo?.buildMapLibreLayerPlan || !geo?.buildMapLibreStyle) {
              throw new Error("geo map planning exports are missing");
            }
            const overview = {
              config_path: "F:/测试 工作区/workspace.json",
              focus_bounds: { west: 99.8, south: 30.8, east: 100.5, north: 31.4 },
              layers: [
                { id: "dem", kind: "raster", status: "ok", bounds: { west: 99.8, south: 30.8, east: 100.5, north: 31.4 } },
                { id: "basin", kind: "vector", status: "ok" },
                { id: "elevation_zone", kind: "raster", status: "ok" },
                { id: "glacier", kind: "raster", status: "ok" },
                { id: "stations", kind: "point", status: "ok" },
              ],
            };
            const plan = geo.buildMapLibreLayerPlan(overview, overview.config_path, { demStyle: "gray" });
            const style = geo.buildMapLibreStyle(overview, overview.config_path, { demStyle: "gray" });

            if (plan.version !== 8 || plan.offline !== true) throw new Error("plan metadata mismatch");
            if (plan.sources.dem.type !== "image") throw new Error("DEM should use image source");
            if (!plan.sources.dem.url.startsWith("/api/geo/dem?")) throw new Error(plan.sources.dem.url);
            if (!plan.sources.dem.url.includes("style=gray")) throw new Error(plan.sources.dem.url);
            if (!plan.sources.dem.url.includes("ws=F%3A%2F%E6%B5%8B%E8%AF%95+%E5%B7%A5%E4%BD%9C%E5%8C%BA%2Fworkspace.json")) {
              throw new Error(`workspace path was not encoded: ${plan.sources.dem.url}`);
            }
            if (JSON.stringify(plan.sources.dem.coordinates[0]) !== JSON.stringify([99.8, 31.4])) {
              throw new Error("DEM image coordinates must start at top-left");
            }
            for (const key of ["basin", "elevation_zones", "glacier", "stations"]) {
              const serialized = JSON.stringify(plan.sources[key]);
              if (!serialized.includes("/api/geo/")) throw new Error(`${key} source missing geo endpoint`);
              if (/https?:\/\//i.test(serialized)) throw new Error(`${key} source must stay offline`);
            }
            const ids = plan.layers.map(layer => layer.id);
            for (const id of ["dem", "elevation-zones-fill", "glacier-fill", "basin-line", "stations"]) {
              if (!ids.includes(id)) throw new Error(`missing layer ${id}: ${ids.join(",")}`);
            }
            const zonesPaint = plan.layers.find(layer => layer.id === "elevation-zones-fill").paint["fill-color"];
            if (!Array.isArray(zonesPaint) || zonesPaint[0] !== "match" || !zonesPaint.includes("low") || !zonesPaint.includes("high")) {
              throw new Error(`elevation zones should use banded fill colors: ${JSON.stringify(zonesPaint)}`);
            }
            const stationPaint = plan.layers.find(layer => layer.id === "stations").paint;
            const stationColor = stationPaint["circle-color"];
            const stationRadius = stationPaint["circle-radius"];
            if (!Array.isArray(stationColor) || stationColor[0] !== "match" || JSON.stringify(stationColor[1]) !== JSON.stringify(["get", "station_type"])) {
              throw new Error(`station colors should be keyed by station_type: ${JSON.stringify(stationColor)}`);
            }
            if (!stationColor.includes("rain") || !stationColor.includes("hydrology") || !stationColor.includes("outlet")) {
              throw new Error(`station color palette missing station types: ${JSON.stringify(stationColor)}`);
            }
            if (!Array.isArray(stationRadius) || !stationRadius.includes("outlet") || !stationRadius.includes(6.2)) {
              throw new Error(`station radius should highlight outlet stations: ${JSON.stringify(stationRadius)}`);
            }
            if (JSON.stringify(style.sources) !== JSON.stringify(plan.sources)) {
              throw new Error("style sources should reuse the layer plan");
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
