from __future__ import annotations

import contextlib
import io
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

import precipitation_strategy_runner as runner  # noqa: E402


class PrecipitationStrategyRunnerTests(unittest.TestCase):
    def test_aggregate_hourly_station_precip_for_daily_runner(self) -> None:
        hourly_index = pd.date_range("2026-05-01 08:00", periods=48, freq="1h")
        station_series = pd.DataFrame(
            {
                "S1": np.ones(48, dtype="float64"),
                "S2": np.full(48, 2.0, dtype="float64"),
            },
            index=hourly_index,
        )

        daily, meta = runner.aggregate_station_precip_for_model_step(station_series, 24)

        self.assertTrue(meta["enabled"])
        self.assertEqual(list(daily.index), [pd.Timestamp("2026-05-01"), pd.Timestamp("2026-05-02")])
        self.assertEqual(float(daily.loc[pd.Timestamp("2026-05-01"), "S1"]), 24.0)
        self.assertEqual(float(daily.loc[pd.Timestamp("2026-05-02"), "S2"]), 48.0)

    def test_no_available_station_steps_detects_nan_and_negative_only_steps(self) -> None:
        timestamps = pd.date_range("2026-01-01", periods=3, freq="1D")
        records = [(pd.Timestamp(ts), Path(f"{idx}.tif")) for idx, ts in enumerate(timestamps)]
        stations = pd.DataFrame({"station_id": ["S1", "S2"]})
        station_series = pd.DataFrame(
            {
                "S1": [1.0, np.nan, -1.0],
                "S2": [np.nan, np.nan, np.nan],
            },
            index=timestamps,
        )

        missing = runner.no_available_station_steps(records, stations, station_series)

        self.assertEqual(missing, [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03")])

    def test_grid_bias_reports_existing_outputs_skipped_without_recomputing_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raster_path = root / "2026.01.01.tif"
            output_dir = root / "out"
            output_dir.mkdir()
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
            with rasterio.open(raster_path, "w", **profile) as dst:
                dst.write(np.ones((2, 2), dtype="float32"), 1)
            with rasterio.open(output_dir / raster_path.name, "w", **profile) as dst:
                dst.write(np.full((2, 2), 2.0, dtype="float32"), 1)
            stations = pd.DataFrame({"station_id": ["S1"], "x": [0.5], "y": [1.5], "weight": [1.0]})
            station_series = pd.DataFrame({"S1": [10.0]}, index=[pd.Timestamp("2026-01-01")])

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                written = runner.apply_grid_bias_correction(
                    [(pd.Timestamp("2026-01-01"), raster_path)],
                    output_dir,
                    stations,
                    station_series,
                    overwrite=False,
                )

        self.assertEqual(written, 1)
        log = stdout.getvalue()
        self.assertIn("\u5df2\u6709\u8f93\u51fa\u8df3\u8fc7 1", log)
        self.assertIn("\u672c\u6b21\u6ca1\u6709\u91cd\u65b0\u8ba1\u7b97", log)

    def test_hydro_diagnostics_quantifies_station_error_and_basin_precip_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raster_path = root / "2026.01.01.tif"
            output_dir = root / "out"
            output_dir.mkdir()
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
            with rasterio.open(raster_path, "w", **profile) as dst:
                dst.write(np.ones((2, 2), dtype="float32"), 1)
            with rasterio.open(output_dir / raster_path.name, "w", **profile) as dst:
                dst.write(np.full((2, 2), 2.0, dtype="float32"), 1)
            stations = pd.DataFrame({"station_id": ["S1"], "x": [0.5], "y": [1.5], "weight": [1.0]})
            station_series = pd.DataFrame({"S1": [2.0]}, index=[pd.Timestamp("2026-01-01")])

            diagnostics = runner.summarize_precipitation_hydro_diagnostics(
                [(pd.Timestamp("2026-01-01"), raster_path)],
                output_dir,
                stations,
                station_series,
                "grid_plus_station_bias",
            )

        self.assertEqual(diagnostics["station_day_samples_available"], 1)
        self.assertAlmostEqual(diagnostics["basin_precip_total_before_mm"], 1.0)
        self.assertAlmostEqual(diagnostics["basin_precip_total_after_mm"], 2.0)
        self.assertAlmostEqual(diagnostics["basin_precip_total_change_percent"], 100.0)
        self.assertAlmostEqual(diagnostics["station_point_before"]["mae_mm"], 1.0)
        self.assertAlmostEqual(diagnostics["station_point_after"]["mae_mm"], 0.0)

    def test_apply_thiessen_raises_instead_of_writing_zero_when_no_station_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raster_path = root / "2026.01.01.tif"
            output_dir = root / "out"
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
            with rasterio.open(raster_path, "w", **profile) as dst:
                dst.write(np.ones((2, 2), dtype="float32"), 1)
            stations = pd.DataFrame({"station_id": ["S1"], "x": [0.5], "y": [1.5]})
            station_series = pd.DataFrame({"S1": [np.nan]}, index=[pd.Timestamp("2026-01-01")])

            with self.assertRaisesRegex(ValueError, "没有任何可用站点"):
                runner.apply_thiessen(
                    [(pd.Timestamp("2026-01-01"), raster_path)],
                    output_dir,
                    stations,
                    station_series,
                    overwrite=True,
                )

            self.assertFalse((output_dir / raster_path.name).exists())


if __name__ == "__main__":
    unittest.main()
