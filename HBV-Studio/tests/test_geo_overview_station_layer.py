from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
from rasterio.transform import from_origin


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services import geo_overview as geo_service  # noqa: E402
from services.geo_overview import (  # noqa: E402
    GeoOverviewContext,
    workspace_basin_geojson,
    workspace_dem_png,
    workspace_elevation_zones_geojson,
    workspace_geo_overview,
    workspace_glacier_geojson,
    workspace_station_geojson,
)


class GeoOverviewStationLayerTests(unittest.TestCase):
    def test_station_metadata_csv_becomes_point_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "workspace.json"
            gis_dir = root / "gis"
            gis_dir.mkdir()
            station_csv = root / "stations.csv"
            station_csv.write_text(
                "station_id,lon,lat\nS1,100.0,31.0\nS2,100.3,31.2\nBAD,,31.5\n",
                encoding="utf-8",
            )
            config = {
                "流域名称": "测试流域",
                "气象策略": {"站点信息_csv": "stations.csv"},
            }

            def resolve_related(_: dict, raw: object):
                text = str(raw or "").strip()
                return root / text if text else None

            context = GeoOverviewContext(
                load_workspace_config=lambda raw: (cfg_path, config),
                read_json_file=lambda path: config,
                current_profile=lambda cfg: "daily",
                build_profile_paths=lambda cfg, profile: {"gis_dir": str(gis_dir)},
                resolve_config_related_path=resolve_related,
                workspace_dem_path=lambda path, prefer=None: Path(path) / "missing_dem.tif",
                configured_dem_kind=lambda cfg: "",
                to_display_path=lambda path: Path(path).name,
                profile_labels={"daily": "日尺度"},
            )

            overview = workspace_geo_overview(str(cfg_path), context)
            station_layer = next(layer for layer in overview["layers"] if layer["id"] == "stations")

            self.assertEqual(station_layer["status"], "ok")
            self.assertEqual(station_layer["kind"], "point")
            self.assertEqual(station_layer["message"], "2 个站点")
            self.assertEqual(station_layer["metrics"]["station_count"], 2)
            self.assertEqual([item["id"] for item in station_layer["points"]], ["S1", "S2"])
            self.assertEqual(station_layer["points"][0]["coord"], [100.0, 31.0])
            self.assertEqual(overview["available_layer_count"], 1)
            self.assertEqual(overview["bounds"], station_layer["bounds"])
            self.assertEqual(overview["focus_bounds"], station_layer["bounds"])

            geojson = workspace_station_geojson(str(cfg_path), context)
            self.assertEqual(geojson["type"], "FeatureCollection")
            self.assertEqual(geojson["properties"]["id"], "stations")
            self.assertEqual(geojson["properties"]["status"], "ok")
            self.assertEqual(geojson["properties"]["metrics"]["station_count"], 2)
            self.assertEqual(len(geojson["features"]), 2)
        self.assertEqual(geojson["features"][0]["geometry"], {"type": "Point", "coordinates": [100.0, 31.0]})
        self.assertEqual(geojson["features"][0]["properties"]["label"], "S1")

    def test_dem_raster_can_be_rendered_as_offline_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "workspace.json"
            gis_dir = root / "gis"
            gis_dir.mkdir()
            dem_path = root / "dem.tif"
            values = np.arange(96, dtype="float32").reshape(8, 12)
            with rasterio.open(
                dem_path,
                "w",
                driver="GTiff",
                height=values.shape[0],
                width=values.shape[1],
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(100.0, 32.0, 0.01, 0.01),
            ) as dst:
                dst.write(values, 1)

            config = {"流域名称": "测试流域", "DEM_tif": "dem.tif"}

            def resolve_related(_: dict, raw: object):
                text = str(raw or "").strip()
                return root / text if text else None

            context = GeoOverviewContext(
                load_workspace_config=lambda raw: (cfg_path, config),
                read_json_file=lambda path: config,
                current_profile=lambda cfg: "daily",
                build_profile_paths=lambda cfg, profile: {"gis_dir": str(gis_dir)},
                resolve_config_related_path=resolve_related,
                workspace_dem_path=lambda path, prefer=None: Path(path) / "missing_dem.tif",
                configured_dem_kind=lambda cfg: "",
                to_display_path=lambda path: Path(path).name,
                profile_labels={"daily": "日尺度"},
            )

            image = workspace_dem_png(str(cfg_path), context)

        self.assertEqual(image["content_type"], "image/png")
        self.assertTrue(image["body"].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(image["body"]), 80)
        self.assertEqual(image["metrics"]["style"], "hillshade")
        self.assertEqual(image["metrics"]["preview_width"], 12)
        self.assertEqual(image["metrics"]["preview_height"], 8)
        self.assertAlmostEqual(image["bounds"]["west"], 100.0)
        self.assertAlmostEqual(image["bounds"]["east"], 100.12)
        self.assertAlmostEqual(image["bounds"]["north"], 32.0)
        self.assertAlmostEqual(image["bounds"]["south"], 31.92)

    def test_basin_layer_rings_become_geojson_polygon(self) -> None:
        context = mock.Mock()
        basin_layer = {
            "id": "basin",
            "label": "流域边界",
            "status": "ok",
            "message": "1 个要素",
            "bounds": {"west": 100.0, "south": 31.0, "east": 100.2, "north": 31.2},
            "metrics": {"feature_count": 1},
            "rings": [
                {"points": [[100.0, 31.0], [100.2, 31.0], [100.2, 31.2], [100.0, 31.2]]},
            ],
        }
        with mock.patch.object(geo_service, "workspace_geo_overview", return_value={"layers": [basin_layer]}):
            geojson = workspace_basin_geojson("workspace.json", context)

        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertEqual(geojson["properties"]["id"], "basin")
        self.assertEqual(geojson["properties"]["metrics"]["feature_count"], 1)
        self.assertEqual(len(geojson["features"]), 1)
        geometry = geojson["features"][0]["geometry"]
        self.assertEqual(geometry["type"], "Polygon")
        self.assertEqual(geometry["coordinates"][0][0], [100.0, 31.0])
        self.assertEqual(geometry["coordinates"][0][-1], [100.0, 31.0])

    def test_glacier_layer_rings_become_geojson_polygon(self) -> None:
        context = mock.Mock()
        glacier_layer = {
            "id": "glacier",
            "label": "冰川",
            "kind": "raster",
            "status": "ok",
            "message": "25 x 25",
            "bounds": {"west": 100.0, "south": 31.0, "east": 100.1, "north": 31.1},
            "metrics": {"width": 25, "height": 25},
            "rings": [
                {"points": [[100.0, 31.0], [100.1, 31.0], [100.1, 31.1], [100.0, 31.1]]},
            ],
        }
        with mock.patch.object(geo_service, "workspace_geo_overview", return_value={"layers": [glacier_layer]}):
            geojson = workspace_glacier_geojson("workspace.json", context)

        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertEqual(geojson["properties"]["id"], "glacier")
        self.assertEqual(geojson["properties"]["kind"], "raster")
        self.assertEqual(geojson["properties"]["status"], "ok")
        self.assertEqual(len(geojson["features"]), 1)
        self.assertEqual(geojson["features"][0]["properties"]["source_kind"], "raster")
        self.assertEqual(geojson["features"][0]["geometry"]["type"], "Polygon")

    def test_elevation_zone_rasters_are_combined_as_geojson_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "workspace.json"
            gis_dir = root / "gis"
            gis_dir.mkdir()
            (gis_dir / "elevation_zone_low.tif").write_bytes(b"low")
            (gis_dir / "elevation_zone_high.tif").write_bytes(b"high")

            context = GeoOverviewContext(
                load_workspace_config=lambda raw: (cfg_path, {"流域名称": "测试流域", "CFMAX分区阈值_m": 4900}),
                read_json_file=lambda path: {},
                current_profile=lambda cfg: "daily",
                build_profile_paths=lambda cfg, profile: {"gis_dir": str(gis_dir)},
                resolve_config_related_path=lambda cfg, raw: None,
                workspace_dem_path=lambda path, prefer=None: Path(path) / "missing_dem.tif",
                configured_dem_kind=lambda cfg: "",
                to_display_path=lambda path: Path(path).name,
                profile_labels={"daily": "日尺度"},
            )

            def fake_raster_layer(layer_id: str, label: str, path: Path | None, _: GeoOverviewContext) -> dict:
                west = 100.0 if "low" in layer_id else 100.2
                return {
                    "id": layer_id,
                    "label": label,
                    "kind": "raster",
                    "status": "ok",
                    "message": "10 x 10",
                    "path": str(path or ""),
                    "display_path": Path(path or "").name,
                    "bounds": {"west": west, "south": 31.0, "east": west + 0.1, "north": 31.1},
                    "rings": [
                        {"points": [[west, 31.0], [west + 0.1, 31.0], [west + 0.1, 31.1], [west, 31.1]]},
                    ],
                    "points": [],
                    "metrics": {"width": 10, "height": 10},
                }

            with mock.patch.object(geo_service, "_raster_geo_layer", side_effect=fake_raster_layer):
                geojson = workspace_elevation_zones_geojson(str(cfg_path), context)

        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertEqual(geojson["properties"]["id"], "elevation_zones")
        self.assertEqual(geojson["properties"]["status"], "ok")
        self.assertEqual(geojson["properties"]["metrics"]["layer_count"], 2)
        self.assertEqual(len(geojson["features"]), 2)
        zones = [feature["properties"]["zone"] for feature in geojson["features"]]
        self.assertEqual(zones, ["low", "high"])
        low_props = geojson["features"][0]["properties"]
        high_props = geojson["features"][1]["properties"]
        self.assertEqual(low_props["elev"], 4900.0)
        self.assertEqual(low_props["cfmax_threshold_m"], 4900.0)
        self.assertEqual(low_props["elev_max_m"], 4900.0)
        self.assertEqual(low_props["elev_label"], "<= 4900 m")
        self.assertEqual(high_props["elev"], 4900.0)
        self.assertEqual(high_props["elev_min_m"], 4900.0)
        self.assertEqual(high_props["elev_label"], "> 4900 m")
        self.assertEqual(geojson["properties"]["layers"][0]["elev"], 4900.0)
        self.assertEqual(geojson["properties"]["bounds"]["west"], 100.0)
        self.assertEqual(geojson["properties"]["bounds"]["east"], 100.3)


if __name__ == "__main__":
    unittest.main()
