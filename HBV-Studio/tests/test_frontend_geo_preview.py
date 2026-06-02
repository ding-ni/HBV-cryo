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

            const context = { window: {}, console, URLSearchParams };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/mapLayerPlan.js", "utf8"), context);
            vm.runInContext(fs.readFileSync("web/js/geoPreview.js", "utf8"), context);

            const geo = context.window.HBVStudioGeoPreview;
            if (!geo) throw new Error("geo preview module was not exported");
            const css = fs.readFileSync("web/styles.css", "utf8");
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
                  message: "4 个站点",
                  metrics: { station_count: 4, station_type_counts: { rain: 1, hydrology: 1, outlet: 1, station: 1 } },
                  points: [
                    { id: "S1", label: "S<1", coord: [100.0, 31.0], station_type: "rain", station_type_label: "雨量站" },
                    { id: "S2", label: "S2", coord: [100.3, 31.2], station_type: "hydrology", station_type_label: "水文站" },
                    { id: "OUT", label: "出口", coord: [100.4, 31.25], station_type: "outlet", station_type_label: "出口站" },
                    { id: "REF", label: "参照站", coord: [100.1, 31.1] },
                  ],
                },
              ],
            });

            if (!html.includes("<path")) throw new Error(`typed station symbols were not rendered: ${html}`);
            if (!html.includes("<circle")) throw new Error(`station circles were not rendered: ${html}`);
            if (!html.includes("geo-layer-stations")) throw new Error("station CSS class missing");
            if (!html.includes("geo-layer-control geo-layer-stations")) throw new Error("station layer toggle missing");
            if (!html.includes('data-geo-layer-toggle="stations"')) throw new Error("station layer toggle key missing");
            if (!html.includes('data-geo-layer-opacity="stations:medium"')) throw new Error("station layer opacity control missing");
            if (!html.includes('class="geo-layer-opacity-radio geo-layer-opacity-stations-medium"')) {
              throw new Error("station medium opacity class missing");
            }
            if (!html.includes("geo-coordinate-frame")) throw new Error("coordinate frame missing");
            for (const coord of ["99.800°E", "100.500°E", "31.400°N", "30.800°N"]) {
              if (!html.includes(coord)) throw new Error(`coordinate label missing: ${coord}`);
            }
            if (!html.includes("geo-scale-bar")) throw new Error("scale bar missing");
            for (const cls of ["geo-station-type-rain", "geo-station-type-hydrology", "geo-station-type-outlet", "geo-station-type-station"]) {
              if (!html.includes(cls)) throw new Error(`station type class missing: ${cls}`);
            }
            if (!html.includes("S&lt;1 · 雨量站")) throw new Error("station typed title should be escaped");
            if (!html.includes("站点")) throw new Error("station metric label missing");
            if (!html.includes("4 个")) throw new Error("station count metric missing");
            for (const item of ["雨量站 1", "水文站 1", "出口站 1", "站点 1"]) {
              if (!html.includes(item)) throw new Error(`station type legend missing: ${item}`);
            }
            for (const key of ["dem", "basin", "elevation_zone", "glacier", "stations"]) {
              const selector = `.geo-preview-map:has(.geo-layer-toggle-${key}:not(:checked))`;
              if (!css.includes(selector)) throw new Error(`layer visibility selector missing: ${selector}`);
            }
            for (const key of ["dem", "basin", "elevation_zone", "glacier", "stations"]) {
              for (const level of ["low", "medium", "high"]) {
                const selector = `.geo-preview-map:has(.geo-layer-opacity-${key}-${level}:checked)`;
                if (!css.includes(selector)) throw new Error(`layer opacity selector missing: ${selector}`);
              }
            }
            for (const selector of [".geo-coordinate-label", ".geo-scale-bar line", ".geo-scale-bar text"]) {
              if (!css.includes(selector)) throw new Error(`coordinate style missing: ${selector}`);
            }
            if (!html.includes('data-geo-layer-count="1"')) throw new Error("layer count attribute mismatch");
            if (!html.includes("geo-map-plan")) throw new Error("offline map plan summary missing");
            if (!html.includes('data-map-plan-sources="1"')) throw new Error("offline map source count missing");
            if (!html.includes('data-map-plan-layers="1"')) throw new Error("offline map layer count missing");
            if (!html.includes("/api/geo/*")) throw new Error("offline map plan should mention local geo endpoints");
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
            const controlled = geo.buildMapLibreLayerPlan(overview, overview.config_path, {
              demStyle: "gray",
              layerControls: {
                dem: { opacity: 0.25 },
                glacier: { visible: false, opacity: 0.4 },
                stations: { opacity: 0.5 },
              },
            });

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
            const controlIds = plan.layerControls.map(item => item.id);
            for (const id of ["dem", "elevation_zone", "glacier", "basin", "stations"]) {
              if (!controlIds.includes(id)) throw new Error(`missing layer control ${id}: ${controlIds.join(",")}`);
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
            const controlledDem = controlled.layers.find(layer => layer.id === "dem");
            if (controlledDem.paint["raster-opacity"] !== 0.22) {
              throw new Error(`DEM opacity should apply layer control: ${JSON.stringify(controlledDem.paint)}`);
            }
            const controlledGlacierFill = controlled.layers.find(layer => layer.id === "glacier-fill");
            const controlledGlacierLine = controlled.layers.find(layer => layer.id === "glacier-line");
            if (controlledGlacierFill.layout.visibility !== "none" || controlledGlacierLine.layout.visibility !== "none") {
              throw new Error("glacier visibility control should hide both fill and line layers");
            }
            if (controlledGlacierFill.paint["fill-opacity"] !== 0.136 || controlledGlacierLine.paint["line-opacity"] !== 0.4) {
              throw new Error(`glacier opacity control mismatch: ${JSON.stringify([controlledGlacierFill.paint, controlledGlacierLine.paint])}`);
            }
            const controlledStations = controlled.layers.find(layer => layer.id === "stations");
            if (controlledStations.paint["circle-opacity"] !== 0.5 || controlledStations.paint["circle-stroke-opacity"] !== 0.5) {
              throw new Error(`station opacity should affect symbol and stroke: ${JSON.stringify(controlledStations.paint)}`);
            }
            const glacierControl = controlled.layerControls.find(item => item.id === "glacier");
            if (glacierControl.visible !== false || glacierControl.opacity !== 0.4) {
              throw new Error(`glacier control metadata mismatch: ${JSON.stringify(glacierControl)}`);
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
