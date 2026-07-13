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
    def test_missing_algorithm_version_replays_legacy_but_explicit_v2_is_preserved(self) -> None:
        self.assertEqual(
            runner.configured_station_correction_algorithm({}),
            runner.STATION_CORRECTION_ALGORITHM_LEGACY,
        )
        self.assertEqual(
            runner.configured_station_correction_algorithm(
                {"station_correction_algorithm": runner.STATION_CORRECTION_ALGORITHM_V2}
            ),
            runner.STATION_CORRECTION_ALGORITHM_V2,
        )

    def test_occurrence_amount_v2_separates_dry_decision_from_amount_ratio(self) -> None:
        dry = runner.apply_station_observation_correction(
            np.asarray([1.0]),
            ratio_values=np.asarray([runner.RATIO_CLIP[0]]),
            station_prec_values=np.asarray([0.0]),
            station_occurrence_values=np.asarray([0.0]),
            confidence_values=np.asarray([1.0]),
        )
        weak_dry = runner.apply_station_observation_correction(
            np.asarray([1.0]),
            ratio_values=np.asarray([1.0]),
            station_prec_values=np.asarray([0.0]),
            station_occurrence_values=np.asarray([0.0]),
            confidence_values=np.asarray([0.2]),
        )
        missed_wet = runner.apply_station_observation_correction(
            np.asarray([0.0]),
            ratio_values=np.asarray([1.0]),
            station_prec_values=np.asarray([5.0]),
            station_occurrence_values=np.asarray([1.0]),
            confidence_values=np.asarray([1.0]),
        )
        amount = runner.apply_station_observation_correction(
            np.asarray([2.0]),
            ratio_values=np.asarray([4.0]),
            station_prec_values=np.asarray([4.0]),
            station_occurrence_values=np.asarray([1.0]),
            confidence_values=np.asarray([0.5]),
        )
        partial_network_dry = runner.apply_station_observation_correction(
            np.asarray([1.0]),
            ratio_values=np.asarray([1.0]),
            station_prec_values=np.asarray([0.0]),
            station_occurrence_values=np.asarray([0.0]),
            confidence_values=np.asarray([1.0]),
            allow_exact_dry=False,
        )

        self.assertEqual(float(dry["corrected"][0]), 0.0)
        self.assertTrue(bool(dry["high_confidence_dry"][0]))
        self.assertAlmostEqual(float(weak_dry["corrected"][0]), 1.0)
        self.assertAlmostEqual(float(missed_wet["corrected"][0]), 5.0)
        self.assertAlmostEqual(float(amount["corrected"][0]), 4.0)
        self.assertAlmostEqual(float(partial_network_dry["corrected"][0]), 1.0)

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

    def test_expected_forcing_index_starts_from_warmup_not_calibration(self) -> None:
        config = {
            "时间步长_小时": 24,
            "时间": {
                "预热开始": "2026-01-01",
                "率定开始": "2026-05-01",
                "率定结束": "2026-10-31",
                "验证结束": "2026-11-01",
            },
        }

        index = runner.build_expected_forcing_index(config)

        self.assertIsNotNone(index)
        self.assertEqual(index[0], pd.Timestamp("2026-01-01"))
        self.assertIn(pd.Timestamp("2026-04-30"), set(index))
        self.assertEqual(index[-1], pd.Timestamp("2026-11-01"))

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
        self.assertEqual(diagnostics["basin_monthly_total_before_mm"], {"2026-01": 1.0})
        self.assertEqual(diagnostics["basin_occurrence_before"]["longest_wet_spell_steps"], 1)
        self.assertEqual(diagnostics["station_occurrence_before"]["hits"], 1)
        self.assertAlmostEqual(diagnostics["station_occurrence_after"]["csi"], 1.0)

    def test_leave_one_station_out_diagnostics_excludes_held_station(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            records = []
            profile = {
                "driver": "GTiff",
                "height": 1,
                "width": 3,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:3857",
                "transform": from_origin(0.0, 1.0, 1.0, 1.0),
                "nodata": -9999.0,
            }
            for day in (1, 2):
                path = root / f"2026.01.{day:02d}.tif"
                with rasterio.open(path, "w", **profile) as dst:
                    dst.write(np.ones((1, 3), dtype="float32"), 1)
                records.append((pd.Timestamp(2026, 1, day), path))
            stations = pd.DataFrame(
                {
                    "station_id": ["S1", "S2", "S3"],
                    "x": [0.5, 1.5, 2.5],
                    "y": [0.5, 0.5, 0.5],
                    "weight": [1.0, 1.0, 1.0],
                }
            )
            station_series = pd.DataFrame(
                {"S1": [1.0, 0.0], "S2": [2.0, 0.0], "S3": [3.0, 0.0]},
                index=pd.date_range("2026-01-01", periods=2, freq="1D"),
            )

            diagnostics = runner.leave_one_station_out_diagnostics(records, stations, station_series)

        self.assertEqual(diagnostics["sample_count"], 6)
        self.assertEqual(len(diagnostics["per_station"]), 3)
        self.assertEqual(diagnostics["occurrence_after"]["false_alarms"], 0)
        self.assertIn("correlation", diagnostics["after"])

    def test_occurrence_metrics_report_hits_misses_false_alarms_and_dry_spells(self) -> None:
        metrics = runner.precipitation_occurrence_metrics(
            [1.0, 1.0, 0.0, 0.0],
            [1.0, 0.0, 1.0, 0.0],
        )

        self.assertEqual(metrics["hits"], 1)
        self.assertEqual(metrics["misses"], 1)
        self.assertEqual(metrics["false_alarms"], 1)
        self.assertEqual(metrics["correct_negatives"], 1)
        self.assertAlmostEqual(metrics["pod"], 0.5)
        self.assertAlmostEqual(metrics["far"], 0.5)
        self.assertAlmostEqual(metrics["csi"], 1.0 / 3.0)

        sequence = runner.precipitation_sequence_metrics([0.0, 0.05, 0.2, 0.3, 0.0])
        self.assertEqual(sequence["trace_day_count"], 1)
        self.assertEqual(sequence["longest_dry_spell_steps"], 2)
        self.assertEqual(sequence["longest_wet_spell_steps"], 2)

    def test_remove_stale_strategy_rasters_keeps_only_current_record_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            current = root / "P_2025.01.01.tif"
            stale = root / "P_2025.01.02.tif"
            current.write_bytes(b"current")
            stale.write_bytes(b"stale")

            removed = runner.remove_stale_strategy_rasters(
                root,
                [(pd.Timestamp("2025-01-01"), current)],
            )

            self.assertEqual(removed, 1)
            self.assertTrue(current.exists())
            self.assertFalse(stale.exists())

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

    def test_grid_bias_uses_transfer_rule_when_station_day_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            train_path = root / "2026.01.01.tif"
            missing_path = root / "2026.01.02.tif"
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
            for path in (train_path, missing_path):
                with rasterio.open(path, "w", **profile) as dst:
                    dst.write(np.ones((2, 2), dtype="float32"), 1)
            stations = pd.DataFrame({"station_id": ["S1"], "x": [0.5], "y": [1.5], "weight": [1.0]})
            station_series = pd.DataFrame(
                {"S1": [2.0, np.nan]},
                index=[pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")],
            )

            summary = runner.fit_grid_bias_transfer_rules(
                [(pd.Timestamp("2026-01-01"), train_path), (pd.Timestamp("2026-01-02"), missing_path)],
                output_dir,
                stations,
                station_series,
                overwrite=True,
            )
            rules = runner.load_grid_bias_transfer_rules(output_dir)
            written = runner.apply_grid_bias_correction(
                [(pd.Timestamp("2026-01-02"), missing_path)],
                output_dir,
                stations,
                station_series,
                overwrite=True,
                transfer_rules=rules,
                algorithm=runner.STATION_CORRECTION_ALGORITHM_LEGACY,
            )

            self.assertTrue(summary["available"])
            self.assertEqual(written, 1)
            with rasterio.open(output_dir / missing_path.name) as src:
                data = src.read(1)
            self.assertAlmostEqual(float(np.nanmean(data)), 2.0, places=4)

    def test_occurrence_amount_v2_passes_through_when_station_day_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raster_path = root / "2026.01.02.tif"
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
                dst.write(np.full((2, 2), 1.5, dtype="float32"), 1)
            stations = pd.DataFrame({"station_id": ["S1"], "x": [0.5], "y": [1.5], "weight": [1.0]})
            station_series = pd.DataFrame({"S1": [np.nan]}, index=[pd.Timestamp("2026-01-02")])

            stats = runner.apply_grid_bias_correction(
                [(pd.Timestamp("2026-01-02"), raster_path)],
                output_dir,
                stations,
                station_series,
                overwrite=True,
                transfer_rules={"arrays": {"global_ratio": np.full((2, 2), 3.0)}},
                return_stats=True,
            )

            with rasterio.open(output_dir / raster_path.name) as src:
                data = src.read(1)
            np.testing.assert_allclose(data, 1.5)
            self.assertEqual(stats["pass_through_steps"], 1)
            self.assertEqual(stats["algorithm"], runner.STATION_CORRECTION_ALGORITHM_V2)

    def test_occurrence_amount_v2_keeps_exact_dry_day_and_conserves_monthly_amount(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "out"
            records = []
            profile = {
                "driver": "GTiff",
                "height": 1,
                "width": 1,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:3857",
                "transform": from_origin(0.0, 1000.0, 1000.0, 1000.0),
                "nodata": -9999.0,
            }
            for day in (1, 2, 3, 4):
                path = root / f"2026.01.{day:02d}.tif"
                with rasterio.open(path, "w", **profile) as dst:
                    dst.write(np.ones((1, 1), dtype="float32"), 1)
                records.append((pd.Timestamp(2026, 1, day), path))
            stations = pd.DataFrame({"station_id": ["S1"], "x": [500.0], "y": [500.0], "weight": [1.0]})
            station_series = pd.DataFrame(
                {"S1": [0.0, 1.0, 1.0, 1.0]},
                index=pd.date_range("2026-01-01", periods=4, freq="1D"),
            )

            stats = runner.apply_grid_bias_correction(
                records,
                output_dir,
                stations,
                station_series,
                overwrite=True,
                return_stats=True,
            )

            with rasterio.open(output_dir / records[0][1].name) as src:
                dry_value = float(src.read(1)[0, 0])
            wet_values = []
            for _, path in records[1:]:
                with rasterio.open(output_dir / path.name) as src:
                    wet_values.append(float(src.read(1)[0, 0]))
            self.assertEqual(dry_value, 0.0)
            self.assertAlmostEqual(dry_value + sum(wet_values), 4.0, places=5)
            self.assertAlmostEqual(stats["monthly_conservation"]["max_redistribution_factor"], 4.0 / 3.0)
            self.assertAlmostEqual(stats["monthly_conservation"]["removed_volume_percent"], 25.0)
            self.assertFalse(stats["qc_blocked"])

    def test_occurrence_amount_v2_keeps_all_dry_month_and_reports_unallocated_volume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "out"
            records = []
            profile = {
                "driver": "GTiff",
                "height": 1,
                "width": 1,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:3857",
                "transform": from_origin(0.0, 1000.0, 1000.0, 1000.0),
                "nodata": -9999.0,
            }
            for day in (1, 2):
                path = root / f"2026.01.{day:02d}.tif"
                with rasterio.open(path, "w", **profile) as dst:
                    dst.write(np.ones((1, 1), dtype="float32"), 1)
                records.append((pd.Timestamp(2026, 1, day), path))
            stations = pd.DataFrame({"station_id": ["S1"], "x": [500.0], "y": [500.0], "weight": [1.0]})
            station_series = pd.DataFrame(
                {"S1": [0.0, 0.0]},
                index=[pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")],
            )

            stats = runner.apply_grid_bias_correction(
                records,
                output_dir,
                stations,
                station_series,
                overwrite=True,
                return_stats=True,
            )

            values = []
            for _, path in records:
                with rasterio.open(output_dir / path.name) as src:
                    values.append(float(src.read(1)[0, 0]))
            self.assertAlmostEqual(sum(values), 0.0, places=5)
            monthly = stats["monthly_conservation"]
            self.assertEqual(monthly["unresolved_cell_count"], 1)
            self.assertAlmostEqual(monthly["unresolved_volume_mm"], 2.0)
            self.assertAlmostEqual(monthly["removed_volume_percent"], 100.0)
            self.assertTrue(monthly["qc_blocked"])

    def test_fit_transfer_rules_writes_monthly_and_global_rule_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raster_path = root / "2026.06.01.tif"
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
            stations = pd.DataFrame({"station_id": ["S1"], "x": [0.5], "y": [1.5], "weight": [1.0]})
            station_series = pd.DataFrame({"S1": [3.0]}, index=[pd.Timestamp("2026-06-01")])

            summary = runner.fit_grid_bias_transfer_rules(
                [(pd.Timestamp("2026-06-01"), raster_path)],
                output_dir,
                stations,
                station_series,
                overwrite=True,
            )

            self.assertTrue((output_dir / runner.TRANSFER_RULES_JSON).exists())
            self.assertTrue((output_dir / runner.TRANSFER_RULES_NPZ).exists())
            self.assertEqual(summary["training_days"], 1)
            self.assertEqual(summary["monthly"]["06"]["training_days"], 1)
            self.assertEqual(summary["monthly"]["01"]["fallback"], "global")


if __name__ == "__main__":
    unittest.main()
