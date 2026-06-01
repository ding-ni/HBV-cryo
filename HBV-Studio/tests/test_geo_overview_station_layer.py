import sys
import tempfile
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.geo_overview import GeoOverviewContext, workspace_geo_overview  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
