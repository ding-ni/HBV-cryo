from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import studio_service as svc  # noqa: E402


class P2RealWorkspaceMapPoCTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for MapLibre plan validation")
    def test_builtin_tuotuohe_workspace_builds_offline_map_plan_from_real_layers(self) -> None:
        config_path = STUDIO_DIR / "workspaces" / "tuotuohe_test.json"
        self.assertTrue(config_path.exists(), f"missing builtin workspace: {config_path}")

        overview = svc.workspace_geo_overview(str(config_path.resolve()))
        ok_layers = {layer.get("id"): layer for layer in overview.get("layers", []) if layer.get("status") == "ok"}

        self.assertGreaterEqual(overview.get("available_layer_count", 0), 3)
        for layer_id in ("basin", "dem", "elevation_zone", "glacier"):
            with self.subTest(layer_id=layer_id):
                self.assertIn(layer_id, ok_layers)
                bounds = ok_layers[layer_id].get("bounds") or {}
                self.assertLess(bounds.get("west"), bounds.get("east"))
                self.assertLess(bounds.get("south"), bounds.get("north"))

        dem = svc.workspace_dem_png(str(config_path.resolve()), style="gray")
        self.assertEqual(dem["content_type"], "image/png")
        self.assertTrue(dem["body"].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(dem["metrics"]["preview_width"], 10)
        self.assertGreater(dem["metrics"]["preview_height"], 10)

        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const overview = JSON.parse(fs.readFileSync(0, "utf8"));
            const context = { window: {}, console, URLSearchParams };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/mapLayerPlan.js", "utf8"), context);

            const geo = context.window.HBVStudioMapLayerPlan;
            if (!geo?.buildMapLibreLayerPlan) throw new Error("map layer plan module missing");
            const plan = geo.buildMapLibreLayerPlan(overview, overview.config_path, {
              demStyle: "gray",
              layerControls: { glacier: { visible: false, opacity: 0.4 } },
            });

            if (plan.offline !== true) throw new Error("real workspace map plan must be offline");
            const requiredSources = ["dem", "basin", "elevation_zones", "glacier"];
            for (const key of requiredSources) {
              const serialized = JSON.stringify(plan.sources[key]);
              if (!serialized.includes("/api/geo/")) throw new Error(`${key} source missing local geo endpoint`);
              if (/https?:\/\//i.test(serialized)) throw new Error(`${key} source must not use online tiles`);
            }
            const ids = plan.layers.map(layer => layer.id);
            for (const id of ["dem", "elevation-zones-fill", "glacier-fill", "glacier-line", "basin-line"]) {
              if (!ids.includes(id)) throw new Error(`missing real workspace map layer ${id}`);
            }
            const controls = plan.layerControls.map(item => item.id);
            for (const id of ["dem", "elevation_zone", "glacier", "basin"]) {
              if (!controls.includes(id)) throw new Error(`missing real workspace control ${id}`);
            }
            const glacierFill = plan.layers.find(layer => layer.id === "glacier-fill");
            const glacierLine = plan.layers.find(layer => layer.id === "glacier-line");
            if (glacierFill.layout.visibility !== "none" || glacierLine.layout.visibility !== "none") {
              throw new Error("glacier control should hide both real workspace glacier layers");
            }
            if (glacierFill.paint["fill-opacity"] !== 0.136 || glacierLine.paint["line-opacity"] !== 0.4) {
              throw new Error("glacier opacity control was not applied to real workspace layers");
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            input=json.dumps(overview, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
