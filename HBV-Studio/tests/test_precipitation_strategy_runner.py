from __future__ import annotations

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
