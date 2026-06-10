from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import forecast_run  # noqa: E402
import precipitation_strategy_runner as runner  # noqa: E402


class DummyForecastModule:
    @staticmethod
    def format_time_value(value) -> str:
        return pd.Timestamp(value).strftime("%Y-%m-%d")

    @staticmethod
    def build_time_index(start: str, end: str) -> pd.DatetimeIndex:
        return pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")

    @staticmethod
    def parse_time_from_name(name: str) -> pd.Timestamp | None:
        try:
            return pd.Timestamp(Path(name).stem)
        except Exception:
            return None


def write_tif(path: Path, value: float) -> None:
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 2,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(0.0, 2.0, 1.0, 1.0),
        "nodata": -9999.0,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full((2, 2), value, dtype="float32"), 1)


class ForecastRunTests(unittest.TestCase):
    def test_forecast_precip_uses_saved_station_bias_transfer_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rule_dir = root / "rules"
            train_path = root / "training" / "2026-07-01.tif"
            raw_prec_dir = root / "forecast_inputs" / "prec"
            raw_prec_path = raw_prec_dir / "2026-07-02.tif"
            manifest_path = root / "forecast_inputs" / "input_manifest.json"
            write_tif(train_path, 1.0)
            write_tif(raw_prec_path, 1.0)
            stations = pd.DataFrame({"station_id": ["S1"], "x": [0.5], "y": [1.5], "weight": [1.0]})
            station_series = pd.DataFrame({"S1": [2.0]}, index=[pd.Timestamp("2026-07-01")])
            runner.fit_grid_bias_transfer_rules(
                [(pd.Timestamp("2026-07-01"), train_path)],
                rule_dir,
                stations,
                station_series,
                overwrite=True,
            )

            manifest = {
                "schema": "forecast_input_manifest_v1",
                "variables": {"prec": {"archive_dir": str(raw_prec_dir)}},
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            input_archive = {
                "archived_dirs": {"prec": str(raw_prec_dir)},
                "manifest": manifest,
                "manifest_path": str(manifest_path),
            }

            result = forecast_run.apply_forecast_precip_transfer_rules(
                DummyForecastModule,
                {"data_sources": {"prec_dir": str(rule_dir)}},
                {"气象策略": {"降水方案": "grid_plus_station_bias"}},
                "daily",
                {},
                input_archive,
                "2026-07-02",
                "2026-07-02",
            )

            self.assertTrue(result["enabled"])
            self.assertEqual(result["applied_files"], 1)
            corrected_dir = Path(input_archive["archived_dirs"]["prec"])
            self.assertNotEqual(corrected_dir, raw_prec_dir)
            self.assertEqual(input_archive["archived_dirs"]["prec_raw_before_station_bias"], str(raw_prec_dir))
            with rasterio.open(corrected_dir / raw_prec_path.name) as src:
                data = src.read(1)
            self.assertAlmostEqual(float(np.nanmean(data)), 2.0, places=4)
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(saved_manifest["variables"]["prec"]["station_bias_transfer_applied"])

    def test_forecast_precip_does_not_apply_station_rules_for_grid_only_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_prec_dir = root / "forecast_inputs" / "prec"
            write_tif(raw_prec_dir / "2026-07-02.tif", 1.0)
            input_archive = {"archived_dirs": {"prec": str(raw_prec_dir)}, "manifest": {}, "manifest_path": ""}

            result = forecast_run.apply_forecast_precip_transfer_rules(
                DummyForecastModule,
                {"data_sources": {"station_precip_mode": "grid_only"}},
                {"气象策略": {"降水方案": "grid_plus_station_bias"}},
                "daily",
                {},
                input_archive,
                "2026-07-02",
                "2026-07-02",
            )

            self.assertFalse(result["enabled"])
            self.assertEqual(result["status"], "station_bias_not_selected")
            self.assertEqual(input_archive["archived_dirs"]["prec"], str(raw_prec_dir))


if __name__ == "__main__":
    unittest.main()
