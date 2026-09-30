from __future__ import annotations

import contextlib
import io
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

import precipitation_strategy_runner as runner  # noqa: E402


class PrecipitationStrategyRunnerTests(unittest.TestCase):
    @staticmethod
    def _write_records(root: Path, timestamps: list[pd.Timestamp], values: list[float]) -> list[tuple[pd.Timestamp, Path]]:
        records = []
        for timestamp, value in zip(timestamps, values):
            path = root / (pd.Timestamp(timestamp).strftime("%Y.%m.%d.%H.%M") + ".tif")
            with rasterio.open(
                path, "w", driver="GTiff", height=1, width=1, count=1,
                dtype="float32", crs="EPSG:3857", transform=from_origin(0.0, 1000.0, 1000.0, 1000.0),
                nodata=-9999.0,
            ) as dst:
                dst.write(np.asarray([[value]], dtype="float32"), 1)
            records.append((pd.Timestamp(timestamp), path))
        return records

    @staticmethod
    def _one_station() -> pd.DataFrame:
        return pd.DataFrame({"station_id": ["S1"], "x": [500.0], "y": [500.0], "weight": [1.0]})

    def test_station_series_integrity_blocks_distinct_ids_with_identical_nonzero_series(self) -> None:
        index = pd.date_range("2026-01-01", periods=30, freq="1D")
        series = pd.DataFrame(
            {
                "A": np.arange(30, dtype="float64"),
                "B": np.arange(30, dtype="float64"),
                "C": np.arange(30, dtype="float64") + 1.0,
            },
            index=index,
        )

        result = runner.station_series_integrity_diagnostics(series)

        self.assertTrue(result["qc_blocked"])
        self.assertEqual(result["duplicate_pair_count"], 1)
        self.assertEqual(result["duplicate_pairs"][0]["station_a"], "A")
        self.assertEqual(result["duplicate_pairs"][0]["station_b"], "B")

    def test_raster_series_fingerprint_changes_with_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "2026.01.01.tif"
            path.write_bytes(b"first")
            records = [(pd.Timestamp("2026-01-01"), path)]
            first = runner.raster_series_fingerprint(records)
            path.write_bytes(b"second")
            second = runner.raster_series_fingerprint(records)

        self.assertNotEqual(first["series_sha256"], second["series_sha256"])

    def test_station_elevation_support_reports_no_station_above_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            dem = root / "station_dem.tif"
            profile = {
                "driver": "GTiff",
                "height": 2,
                "width": 2,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:4326",
                "transform": from_origin(90.0, 30.0, 0.1, 0.1),
                "nodata": -9999.0,
            }
            with rasterio.open(dem, "w", **profile) as dst:
                dst.write(np.asarray([[3500.0, 3600.0], [3700.0, 3800.0]], dtype="float32"), 1)
            stations = pd.DataFrame(
                {
                    "station_id": ["A", "B"],
                    "x_raw": [90.05, 90.15],
                    "y_raw": [29.95, 29.85],
                }
            )

            result = runner.station_elevation_support_diagnostics(
                {
                    "气象策略": {"站点高程DEM_tif": str(dem)},
                    "CFMAX分区阈值_m": 4500.0,
                },
                stations,
            )

        self.assertTrue(result["available"])
        self.assertEqual(result["status"], "high_zone_unsupported")
        self.assertEqual(result["high_zone_station_count"], 0)

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
                runner.apply_grid_bias_correction(
                    [(pd.Timestamp("2026-01-01"), raster_path)],
                    output_dir, stations, station_series, overwrite=True,
                    algorithm=runner.STATION_CORRECTION_ALGORITHM_V2,
                )
                written = runner.apply_grid_bias_correction(
                    [(pd.Timestamp("2026-01-01"), raster_path)],
                    output_dir,
                    stations,
                    station_series,
                    overwrite=False,
                    algorithm=runner.STATION_CORRECTION_ALGORITHM_V2,
                )

        self.assertEqual(written, 1)
        log = stdout.getvalue()
        self.assertIn("已有输出复用 1 日", log)
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
                algorithm=runner.STATION_CORRECTION_ALGORITHM_V2,
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
                algorithm=runner.STATION_CORRECTION_ALGORITHM_V2,
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
                algorithm=runner.STATION_CORRECTION_ALGORITHM_V2,
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

    def test_monthly_transfer_uses_paired_totals_and_one_rule_for_all_years(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            training_times = list(pd.date_range("2025-10-01", periods=10, freq="D"))
            timestamps = [pd.Timestamp("2022-01-01"), pd.Timestamp("2022-10-01"), *training_times]
            base = [3.0, 50.0, 100.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 50.0, 0.0]
            records = self._write_records(root, timestamps, base)
            station_series = pd.DataFrame(
                {"S1": [5.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, np.nan, 2.0]}, index=training_times,
            )
            output_dir = root / "out"
            summary = runner.fit_monthly_transfer_rules(records, output_dir, self._one_station(), station_series)
            rules = runner.load_monthly_transfer_rules(output_dir)
            self.assertIsNotNone(rules)
            ratio = 8.0 / 107.0
            self.assertAlmostEqual(float(rules["arrays"]["month_10_ratio"][0, 0]), ratio, places=7)
            self.assertLess(ratio, 0.2)
            sample = summary["monthly"]["10"]["station_samples"][0]
            self.assertEqual(sample["paired_steps"], 9)
            self.assertEqual(sample["observed_total_mm"], 8.0)
            self.assertEqual(sample["grid_total_mm"], 107.0)
            self.assertEqual(summary["monthly"]["01"]["fallback"], "identity")
            self.assertEqual(summary["monthly"]["01"]["status"], "unverified_identity")
            stats = runner.apply_grid_bias_correction(
                records, output_dir, self._one_station(), station_series, False, rules,
                return_stats=True, algorithm=runner.STATION_CORRECTION_ALGORITHM_V3,
            )
            actual = []
            for _, path in records:
                with rasterio.open(output_dir / path.name) as src:
                    actual.append(float(src.read(1)[0, 0]))
            np.testing.assert_allclose(actual, [3.0, *[value * ratio for value in base[1:]]], rtol=1e-6)
            self.assertEqual(actual[-1], 0.0)  # no additive residual creates rain
            self.assertEqual(stats["direct_station_corrected_steps"], 0)
            self.assertEqual(stats["frozen_rule_applied_steps"], 11)
            self.assertEqual(stats["unsupported_month_identity_steps"], 1)
            self.assertEqual(stats["quality_checks"]["checked_steps"], 12)
            self.assertEqual(stats["quality_checks"]["status"], "passed")
            self.assertEqual(stats["occurrence_correction"], "not_performed")
            self.assertFalse(stats["qc_blocked"])

    def test_monthly_transfer_training_range_changes_the_frozen_rule_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = list(pd.date_range("2025-05-01", periods=14, freq="D"))
            records = self._write_records(root, timestamps, [1.0] * 14)
            stations = self._one_station()
            series = pd.DataFrame({"S1": [2.0] * 7 + [1.0] * 7}, index=timestamps)
            out = root / "out"
            all_data = runner.fit_monthly_transfer_rules(records, out, stations, series)
            selected = runner.fit_monthly_transfer_rules(
                records, out, stations, series, training_start="2025-05-08", training_end="2025-05-14",
            )
            self.assertNotEqual(all_data["identity_sha256"], selected["identity_sha256"])
            self.assertEqual(selected["training_days"], 7)
            self.assertEqual(selected["actual_training_start"], "2025-05-08T00:00:00")
            self.assertEqual(selected["monthly"]["05"]["ratio_mean"], 1.0)
            again = runner.fit_monthly_transfer_rules(
                records, out, stations, series, training_start="2025-05-08", training_end="2025-05-14",
            )
            self.assertTrue(again["loaded_existing"])

    def test_monthly_transfer_does_not_extrapolate_a_single_station_day_to_a_month(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = [*list(pd.date_range("2025-05-01", periods=7)), pd.Timestamp("2025-02-01")]
            records = self._write_records(root, timestamps, [2.0] * 7 + [1.0])
            series = pd.DataFrame({"S1": [1.0] * 7 + [8.0]}, index=timestamps)
            summary = runner.fit_monthly_transfer_rules(records, root / "out", self._one_station(), series)
            self.assertEqual(summary["supported_months"], ["05"])
            self.assertIn("02", summary["unverified_months"])
            self.assertEqual(summary["monthly"]["02"]["ratio_mean"], 1.0)
            self.assertEqual(summary["monthly"]["02"]["station_samples"][0]["status"], "insufficient_paired_days")
            self.assertEqual(summary["quality_checks"]["status"], "passed")

    def test_monthly_transfer_cache_rebuilds_after_source_observation_or_output_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = list(pd.date_range("2025-10-01", periods=7))
            records = self._write_records(root, timestamps, [2.0] * 7)
            stations = self._one_station()
            series = pd.DataFrame({"S1": [1.0] * 7}, index=timestamps)
            out = root / "out"
            first = runner.apply_grid_bias_correction(records, out, stations, series, False, return_stats=True)
            cached = runner.apply_grid_bias_correction(records, out, stations, series, False, return_stats=True)
            self.assertEqual(cached["processed_steps"], 0)
            self.assertEqual(cached["quality_checks"], first["quality_checks"])
            self.assertTrue(cached["quality_evidence_reused"])
            self._write_records(root, timestamps[:1], [4.0])
            changed_base = runner.apply_grid_bias_correction(records, out, stations, series, False, return_stats=True)
            self.assertNotEqual(first["input_identity_sha256"], changed_base["input_identity_sha256"])
            self.assertEqual(changed_base["processed_steps"], 7)
            with rasterio.open(out / records[0][1].name) as src:
                self.assertAlmostEqual(float(src.read(1)[0, 0]), 4.0 * 7.0 / 16.0)
            series.loc[timestamps[0], "S1"] = 2.0
            changed_observation = runner.apply_grid_bias_correction(records, out, stations, series, False, return_stats=True)
            self.assertNotEqual(changed_base["rules_identity_sha256"], changed_observation["rules_identity_sha256"])
            self._write_records(out, timestamps[:1], [999.0])
            repaired = runner.apply_grid_bias_correction(records, out, stations, series, False, return_stats=True)
            self.assertEqual(repaired["processed_steps"], 7)
            with rasterio.open(out / records[0][1].name) as src:
                self.assertAlmostEqual(float(src.read(1)[0, 0]), 2.0)
            cache_path = out / runner.CORRECTION_CACHE_JSON
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload["processing_stats"].pop("quality_checks")
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            rebuilt_qc = runner.apply_grid_bias_correction(records, out, stations, series, False, return_stats=True)
            self.assertEqual(rebuilt_qc["processed_steps"], 7)
            self.assertEqual(rebuilt_qc["quality_checks"]["checked_steps"], 7)

    def test_monthly_transfer_no_grid_rain_does_not_invent_rain_and_reports_missing_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = list(pd.date_range("2025-10-01", periods=7))
            records = self._write_records(root, timestamps, [0.0] * 7)
            series = pd.DataFrame({"S1": [1.0] * 7}, index=timestamps)
            stats = runner.apply_grid_bias_correction(records, root / "out", self._one_station(), series, False, return_stats=True)
            self.assertTrue(stats["qc_blocked"])
            self.assertEqual(stats["quality_checks"]["status"], "failed")
            self.assertIn("no_supported_months", stats["quality_checks"]["failures"])
            for _, path in records:
                with rasterio.open(root / "out" / path.name) as src:
                    self.assertEqual(float(src.read(1)[0, 0]), 0.0)

    def test_monthly_transfer_hourly_samples_require_seven_effective_days(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = list(pd.date_range("2025-10-01 12:00", periods=7, freq="D"))
            records = self._write_records(root, timestamps, [2.0] * 7)
            series = pd.DataFrame({"S1": [1.0] * 7}, index=timestamps)
            summary = runner.fit_monthly_transfer_rules(records, root / "out", self._one_station(), series, step_hours=1.0)
            self.assertEqual(summary["supported_months"], [])
            self.assertAlmostEqual(summary["monthly"]["10"]["station_samples"][0]["effective_days"], 7.0 / 24.0)
            self.assertTrue(summary["quality_checks"]["qc_blocked"])

    def test_monthly_transfer_upper_bound_clipping_remains_a_quality_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = list(pd.date_range("2025-10-01", periods=7))
            records = self._write_records(root, timestamps, [1.0] * 7)
            series = pd.DataFrame({"S1": [15.0] * 7}, index=timestamps)
            out = root / "out"
            summary = runner.fit_monthly_transfer_rules(records, out, self._one_station(), series)
            self.assertEqual(summary["monthly"]["10"]["raw_anchor_ratio_max"], 15.0)
            self.assertEqual(summary["monthly"]["10"]["ratio_max"], 10.0)
            self.assertTrue(summary["quality_checks"]["qc_blocked"])
            rules = runner.load_monthly_transfer_rules(out)
            stats = runner.apply_grid_bias_correction(
                records, out, self._one_station(), series, False, rules,
                return_stats=True, algorithm=runner.STATION_CORRECTION_ALGORITHM_V3,
            )
            self.assertTrue(stats["qc_blocked"])
            cached = runner.apply_grid_bias_correction(
                records, out, self._one_station(), series, False, rules,
                return_stats=True, algorithm=runner.STATION_CORRECTION_ALGORITHM_V3,
            )
            self.assertTrue(cached["qc_blocked"])

    def test_monthly_transfer_same_shape_different_grid_is_rejected_for_forecast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = list(pd.date_range("2025-10-01", periods=7))
            records = self._write_records(root, timestamps, [2.0] * 7)
            series = pd.DataFrame({"S1": [1.0] * 7}, index=timestamps)
            out = root / "out"
            runner.fit_monthly_transfer_rules(records, out, self._one_station(), series)
            rules = runner.load_monthly_transfer_rules(out)
            shifted = root / "shifted.tif"
            with rasterio.open(
                shifted, "w", driver="GTiff", height=1, width=1, count=1, dtype="float32",
                crs="EPSG:3857", transform=from_origin(1000.0, 1000.0, 1000.0, 1000.0), nodata=-9999.0,
            ) as dst:
                dst.write(np.ones((1, 1), dtype="float32"), 1)
            existing_output = out / "existing_forecast.tif"
            self._write_records(out, [pd.Timestamp("2026-10-01")], [2.0])
            (out / "2026.10.01.00.00.tif").rename(existing_output)
            with self.assertRaisesRegex(ValueError, "格网不一致"):
                runner.apply_transfer_rule_to_raster(
                    pd.Timestamp("2026-10-01"), shifted, existing_output, rules, overwrite=False,
                )

    def test_monthly_transfer_unknown_rule_quality_cannot_bypass_checks_via_output_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = list(pd.date_range("2025-10-01", periods=7))
            records = self._write_records(root, timestamps, [2.0] * 7)
            series = pd.DataFrame({"S1": [1.0] * 7}, index=timestamps)
            out = root / "out"
            runner.apply_grid_bias_correction(records, out, self._one_station(), series, False, return_stats=True)
            rules = runner.load_monthly_transfer_rules(out)
            rules["summary"].pop("quality_checks")
            with self.assertRaisesRegex(ValueError, "质量证据"):
                runner.apply_grid_bias_correction(
                    records, out, self._one_station(), series, False, rules,
                    return_stats=True, algorithm=runner.STATION_CORRECTION_ALGORITHM_V3,
                )

    def test_v2_reuse_keeps_failed_monthly_qc_and_never_multiplies_output_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = list(pd.date_range("2025-10-01", periods=3))
            records = self._write_records(root, timestamps, [1.0] * 3)
            stations = self._one_station()
            series = pd.DataFrame({"S1": [0.0, 0.0, 1.0]}, index=timestamps)
            out = root / "out"
            first = runner.apply_grid_bias_correction(
                records, out, stations, series, False, return_stats=True, algorithm=runner.STATION_CORRECTION_ALGORITHM_V2,
            )
            cached = runner.apply_grid_bias_correction(
                records, out, stations, series, False, return_stats=True, algorithm=runner.STATION_CORRECTION_ALGORITHM_V2,
            )
            overwritten = runner.apply_grid_bias_correction(
                records, out, stations, series, True, return_stats=True, algorithm=runner.STATION_CORRECTION_ALGORITHM_V2,
            )
            self.assertTrue(first["qc_blocked"])
            self.assertTrue(cached["qc_blocked"])
            self.assertTrue(overwritten["qc_blocked"])
            self.assertEqual(cached["processed_steps"], 0)
            self.assertEqual(cached["monthly_conservation"], first["monthly_conservation"])
            self.assertEqual(overwritten["monthly_conservation"], first["monthly_conservation"])
            with rasterio.open(out / records[-1][1].name) as src:
                self.assertEqual(float(src.read(1)[0, 0]), 3.0)

    def test_v2_monthly_redistribution_keeps_missing_station_day_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timestamps = list(pd.date_range("2025-10-01", periods=3))
            records = self._write_records(root, timestamps, [1.0, 5.0, 1.0])
            series = pd.DataFrame({"S1": [0.0, np.nan, 1.0]}, index=timestamps)
            out = root / "out"
            stats = runner.apply_grid_bias_correction(
                records, out, self._one_station(), series, False,
                return_stats=True, algorithm=runner.STATION_CORRECTION_ALGORITHM_V2,
            )
            actual = []
            for _, path in records:
                with rasterio.open(out / path.name) as src:
                    actual.append(float(src.read(1)[0, 0]))
            self.assertEqual(actual, [0.0, 5.0, 2.0])
            self.assertEqual(stats["monthly_conservation"]["frozen_missing_station_steps"], 1)
            self.assertEqual(stats["monthly_conservation"]["scope"], "observed_station_steps_only")
            self.assertTrue(stats["qc_blocked"])


if __name__ == "__main__":
    unittest.main()
