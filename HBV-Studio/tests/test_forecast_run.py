from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
    TIME_STEP_HOURS = 24.0
    args = SimpleNamespace(glacier_mode="off")

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
    @staticmethod
    def monthly_source(root: Path, observed: float = 1.0) -> tuple[dict, dict, Path]:
        records = []
        dates = pd.date_range("2025-10-01", periods=7)
        for day in dates:
            path = root / "train" / f"{day:%Y-%m-%d}.tif"
            write_tif(path, 2.0)
            records.append((day, path))
        stations = pd.DataFrame({"station_id": ["S1"], "x": [0.5], "y": [1.5], "weight": [1.0]})
        rule_dir = root / "rules"
        summary = runner.fit_monthly_transfer_rules(records, rule_dir, stations, pd.DataFrame({"S1": [observed] * 7}, index=dates), overwrite=True)
        metadata = {"data_sources": {
            "prec_dir": str(rule_dir), "station_precip_mode": "grid_plus_station_bias",
            "station_correction_algorithm": "monthly_transfer_v3", "station_rule_identity_sha256": summary["identity_sha256"],
        }}
        return metadata, summary, rule_dir

    def test_monthly_forecast_uses_frozen_rule_and_keeps_unsupported_month(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            records = []
            dates = pd.date_range("2025-10-01", periods=7)
            for day in dates:
                path = root / "train" / f"{day:%Y-%m-%d}.tif"
                write_tif(path, 2.0)
                records.append((day, path))
            stations = pd.DataFrame({"station_id": ["S1"], "x": [0.5], "y": [1.5], "weight": [1.0]})
            rule_dir = root / "rules"
            summary = runner.fit_monthly_transfer_rules(records, rule_dir, stations, pd.DataFrame({"S1": [1.0] * 7}, index=dates))
            raw_dir = root / "forecast" / "prec"
            for name in ("2025-10-31.tif", "2025-11-01.tif"):
                write_tif(raw_dir / name, 4.0)
            archive = {"archived_dirs": {"prec": str(raw_dir)}, "manifest": {}, "manifest_path": ""}
            result = forecast_run.apply_forecast_precip_transfer_rules(
                DummyForecastModule,
                {"data_sources": {"prec_dir": str(rule_dir), "station_correction_algorithm": "monthly_transfer_v3", "station_rule_identity_sha256": summary["identity_sha256"]}},
                {"气象策略": {"降水方案": "grid_plus_station_bias", "station_correction_algorithm": "monthly_transfer_v3"}},
                "daily", {}, archive, "2025-10-31", "2025-11-01",
            )
            self.assertTrue(result["enabled"])
            self.assertEqual(result["unverified_identity_files"], 1)
            corrected = Path(archive["archived_dirs"]["prec"])
            with rasterio.open(corrected / "2025-10-31.tif") as src:
                self.assertAlmostEqual(float(src.read(1)[0, 0]), 2.0)
            with rasterio.open(corrected / "2025-11-01.tif") as src:
                self.assertAlmostEqual(float(src.read(1)[0, 0]), 4.0)

    def test_monthly_forecast_refuses_missing_frozen_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_dir = Path(tmpdir) / "prec"
            write_tif(raw_dir / "2025-10-01.tif", 2.0)
            with self.assertRaisesRegex(ValueError, "冻结月规则"):
                forecast_run.apply_forecast_precip_transfer_rules(
                    DummyForecastModule, {},
                    {"气象策略": {"降水方案": "grid_plus_station_bias", "station_correction_algorithm": "monthly_transfer_v3"}},
                    "daily", {}, {"archived_dirs": {"prec": str(raw_dir)}}, "2025-10-01", "2025-10-01",
                )

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

    def test_monthly_forecast_requires_historical_identity_even_when_current_rules_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata, _, rule_dir = self.monthly_source(root)
            metadata["data_sources"].pop("station_rule_identity_sha256")
            raw_dir = root / "forecast_inputs" / "prec"
            write_tif(raw_dir / "2025-10-31.tif", 4.0)
            with mock.patch.object(runner, "load_monthly_transfer_rules", wraps=runner.load_monthly_transfer_rules) as loader:
                with self.assertRaisesRegex(ValueError, "冻结月规则身份"):
                    forecast_run.apply_forecast_precip_transfer_rules(
                        DummyForecastModule, metadata, {}, "daily", {"aligned_prec_effective_dir": rule_dir},
                        {"archived_dirs": {"prec": str(raw_dir)}}, "2025-10-31", "2025-10-31",
                    )
                loader.assert_not_called()

    def test_monthly_forecast_refuses_known_failed_rule_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata, summary, rule_dir = self.monthly_source(root, observed=40.0)
            self.assertEqual(summary["quality_checks"]["status"], "failed")
            self.assertIsNotNone(runner.load_monthly_transfer_rules(rule_dir, expected_fingerprint=summary["identity_sha256"]))
            raw_dir = root / "forecast_inputs" / "prec"
            write_tif(raw_dir / "2025-10-31.tif", 4.0)
            with self.assertRaisesRegex(ValueError, "未通过质量检查"):
                forecast_run.apply_forecast_precip_transfer_rules(
                    DummyForecastModule, metadata, {}, "daily", {}, {"archived_dirs": {"prec": str(raw_dir)}},
                    "2025-10-31", "2025-10-31",
                )

    def test_forecast_chain_keeps_saved_rule_when_current_project_is_retrained(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata, original_summary, rule_dir = self.monthly_source(root)
            first_raw = root / "first" / "forecast_inputs" / "prec"
            write_tif(first_raw / "2025-10-31.tif", 4.0)
            first_archive = {"archived_dirs": {"prec": str(first_raw)}}
            first = forecast_run.apply_forecast_precip_transfer_rules(
                DummyForecastModule, metadata, {}, "daily", {}, first_archive, "2025-10-31", "2025-10-31",
            )
            self.assertTrue(Path(first["rule_snapshot_json"]).is_file())
            self.assertTrue(Path(first["rule_snapshot_npz"]).is_file())
            self.assertNotEqual(Path(first["rule_snapshot_dir"]), rule_dir)
            _, new_summary, _ = self.monthly_source(root, observed=4.0)
            self.assertNotEqual(original_summary["identity_sha256"], new_summary["identity_sha256"])
            chained_metadata = {"data_sources": {
                "station_precip_mode": first["station_precip_mode"],
                "station_correction_algorithm": first["station_correction_algorithm"],
                "station_rule_identity_sha256": first["station_rule_identity_sha256"],
                "station_rule_snapshot_dir": first["rule_snapshot_dir"],
            }}
            second_raw = root / "second" / "forecast_inputs" / "prec"
            write_tif(second_raw / "2026-10-01.tif", 4.0)
            second_archive = {"archived_dirs": {"prec": str(second_raw)}}
            second = forecast_run.apply_forecast_precip_transfer_rules(
                DummyForecastModule, chained_metadata,
                {"气象策略": {"降水方案": "grid_only", "station_correction_algorithm": "occurrence_amount_v2"}},
                "daily", {"aligned_prec_effective_dir": rule_dir}, second_archive, "2026-10-01", "2026-10-01",
            )
            self.assertEqual(second["station_rule_identity_sha256"], original_summary["identity_sha256"])
            with rasterio.open(Path(second_archive["archived_dirs"]["prec"]) / "2026-10-01.tif") as src:
                self.assertAlmostEqual(float(src.read(1)[0, 0]), 2.0)

    def test_old_nested_forecast_evidence_restores_exact_binding_without_current_config_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _, summary, rule_dir = self.monthly_source(root)
            metadata = {"forecast_result": {"precipitation_transfer": {
                "enabled": True, "status": "ok", "station_correction_algorithm": "monthly_transfer_v3",
                "source_rule_dir": str(rule_dir), "rule_summary": summary,
            }}}
            raw_dir = root / "forecast_inputs" / "prec"
            write_tif(raw_dir / "2025-10-31.tif", 4.0)
            archive = {"archived_dirs": {"prec": str(raw_dir)}}
            result = forecast_run.apply_forecast_precip_transfer_rules(
                DummyForecastModule, metadata, {"气象策略": {"降水方案": "grid_only"}}, "daily", {}, archive,
                "2025-10-31", "2025-10-31",
            )
            self.assertTrue(result["enabled"])
            self.assertEqual(result["station_rule_identity_sha256"], summary["identity_sha256"])

    def test_monthly_forecast_cannot_substitute_new_current_rule_for_missing_historical_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata, _, rule_dir = self.monthly_source(root)
            metadata["data_sources"]["station_rule_identity_sha256"] = "unavailable-historical-rule"
            raw_dir = root / "forecast_inputs" / "prec"
            write_tif(raw_dir / "2025-10-31.tif", 4.0)
            with self.assertRaisesRegex(ValueError, "与历史运行一致"):
                forecast_run.apply_forecast_precip_transfer_rules(
                    DummyForecastModule, metadata, {}, "daily", {"aligned_prec_effective_dir": rule_dir},
                    {"archived_dirs": {"prec": str(raw_dir)}}, "2025-10-31", "2025-10-31",
                )

    def test_forecast_metadata_exports_top_level_binding_and_snapshot_for_next_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata, summary, _ = self.monthly_source(root)
            source_run = root / "source_run"
            source_run.mkdir()
            metadata["initial_state"] = {"state_snapshot_time": "2025-10-30"}
            (source_run / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            output_dir = root / "forecast_result"
            raw_dir = output_dir / "forecast_inputs" / "prec"
            write_tif(raw_dir / "2025-10-31.tif", 4.0)
            archive = {"archived_dirs": {"prec": str(raw_dir)}}
            transfer = forecast_run.apply_forecast_precip_transfer_rules(
                DummyForecastModule, metadata, {}, "daily", {}, archive, "2025-10-31", "2025-10-31",
            )
            result = forecast_run.write_forecast_outputs(
                DummyForecastModule, output_dir,
                {"date": pd.date_range("2025-10-31", periods=1), "q_total": [1.0], "forecast_state_snapshot_arrays": {"SP": np.zeros((1, 1))}},
                source_run=source_run, snapshot_path=source_run / "state_snapshot.npz", params={"CFMAX": 2.0},
                config_path=root / "workspace.json", profile="daily", objective_mode="kge",
                forecast_dirs=archive["archived_dirs"], input_archive=archive, forecast_precip_transfer=transfer,
            )
            exported = result["metadata"]["data_sources"]
            self.assertEqual(exported["station_precip_mode"], "grid_plus_station_bias")
            self.assertEqual(exported["station_correction_algorithm"], "monthly_transfer_v3")
            self.assertEqual(exported["station_rule_identity_sha256"], summary["identity_sha256"])
            self.assertEqual(exported["station_rule_snapshot_dir"], transfer["rule_snapshot_dir"])
            self.assertTrue(Path(exported["station_rule_snapshot_dir"]).is_relative_to(output_dir))

    def test_incomplete_rule_application_raises_instead_of_returning_raw_precip_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata, _, _ = self.monthly_source(root)
            raw_dir = root / "forecast_inputs" / "prec"
            write_tif(raw_dir / "2025-10-30.tif", 4.0)
            archive = {"archived_dirs": {"prec": str(raw_dir)}}
            with self.assertRaisesRegex(ValueError, "未完整应用"):
                forecast_run.apply_forecast_precip_transfer_rules(
                    DummyForecastModule, metadata, {}, "daily", {}, archive, "2025-10-30", "2025-10-31",
                )
            self.assertEqual(archive["archived_dirs"]["prec"], str(raw_dir))

    def test_forecast_boundary_default_preserves_missing_and_explicit_zero_is_retained(self) -> None:
        self.assertEqual(forecast_run.forecast_boundary_fields(SimpleNamespace(), {})["gap_fill"], "preserve_missing")
        for args, metadata in (
            (SimpleNamespace(forecast_boundary_gap_fill="zero"), {}),
            (SimpleNamespace(), {"boundary_condition": {"gap_fill": "zero"}}),
        ):
            with self.subTest(args=args, metadata=metadata):
                self.assertEqual(forecast_run.forecast_boundary_fields(args, metadata)["gap_fill"], "zero")

    def test_archive_missing_forcing_reports_model_time_scale(self) -> None:
        class HourlyForecastModule(DummyForecastModule):
            TIME_STEP_HOURS = 1.0

            @staticmethod
            def format_time_value(value) -> str:
                return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")

            @staticmethod
            def build_time_index(start: str, end: str) -> pd.DatetimeIndex:
                return pd.date_range(start, end, freq="h")

        for module, start, end, filename, unit in (
            (DummyForecastModule, "2025-10-30", "2025-10-31", "2025-10-30.tif", "日"),
            (HourlyForecastModule, "2025-10-30 00:00", "2025-10-30 01:00", "2025-10-30T00.tif", "小时"),
        ):
            with self.subTest(scale=unit), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                raw_dir = root / "prec"
                write_tif(raw_dir / filename, 2.0)
                with self.assertRaisesRegex(ValueError, f"缺少.*{unit}"):
                    forecast_run.archive_forecast_inputs(
                        module, root / "forecast_result", {"prec": str(raw_dir)}, start, end,
                    )


if __name__ == "__main__":
    unittest.main()
