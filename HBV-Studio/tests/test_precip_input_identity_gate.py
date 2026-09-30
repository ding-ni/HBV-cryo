from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import precipitation_strategy_runner as runner
from services import precip_strategy_status as status


class PrecipInputIdentityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        with status._IDENTITY_CACHE_LOCK:
            status._FILE_IDENTITY_CACHE.clear()
            status._SERIES_IDENTITY_CACHE.clear()

    @staticmethod
    def make_product(root: Path) -> tuple[dict, dict, Path, Path]:
        base = root / "base"
        corrected = root / "corrected"
        base.mkdir()
        corrected.mkdir()
        for timestamp in [*pd.date_range("2024-05-01", periods=8), *pd.date_range("2025-05-01", periods=2)]:
            (base / f"P_{timestamp:%Y.%m.%d}.tif").write_bytes(b"baseline")
        for timestamp in pd.date_range("2025-05-01", periods=2):
            (corrected / f"P_{timestamp:%Y.%m.%d}.tif").write_bytes(b"corrected")
        station_prec = root / "station_precip.csv"
        station_meta = root / "stations.csv"
        station_prec.write_text("date,S1\n2024-05-01,1\n", encoding="utf-8")
        station_meta.write_text("station_id,lon,lat\nS1,0.5,1.5\n", encoding="utf-8")
        config = {
            "_config_path": str(root / "workspace.json"), "时间步长_小时": 24,
            "时间": {"预热开始": "2025-05-01", "率定结束": "2025-05-02"},
            "气象策略": {
                "降水方案": "grid_plus_station_bias", "station_correction_algorithm": "monthly_transfer_v3",
                "站点降水_csv": str(station_prec), "站点信息_csv": str(station_meta),
                "station_rule_training_start": "2024-05-01", "station_rule_training_end": "2024-05-08",
            },
        }
        all_records = runner.list_rasters(base)
        application, _, _ = runner.filter_records_to_expected(all_records, runner.build_expected_forcing_index(config))
        training = runner._filter_rule_training_records(all_records, training_start="2024-05-01", training_end="2024-05-08")
        inputs = {
            "station_precipitation_input": runner.sha256_file_identity(station_prec),
            "station_metadata_input": runner.sha256_file_identity(station_meta),
            "source_daily_forcing_manifest": runner.sha256_file_identity(root / "daily_forcing_manifest.json"),
        }
        identity = {
            "algorithm": runner._algorithm_identity("monthly_transfer_v3", 24),
            "requested_training_start": "2024-05-01", "requested_training_end": "2024-05-08",
            "base_series": runner.raster_series_fingerprint(training), "input_files": inputs,
        }
        rule_identity = runner._json_digest(identity)
        summary = {
            "selected_steps": 2, "written_files": 2, "missing_expected_steps": 0, "time_step_hours": 24,
            "base_dir": str(base), "target_dir": str(corrected),
            "provenance": {**inputs, "base_precipitation_series": runner.raster_series_fingerprint(application)},
            "processing_stats": {
                "algorithm": "monthly_transfer_v3", "qc_blocked": False, "rules_identity_sha256": rule_identity,
                "quality_checks": {"status": "passed", "qc_blocked": False, "checked_steps": 2},
            },
            "transfer_rules": {
                "schema": "station_bias_monthly_transfer_rules_v3", "available": True,
                "identity_sha256": rule_identity, "identity": identity,
                "quality_checks": {"status": "passed", "qc_blocked": False},
            },
        }
        (corrected / "precipitation_strategy_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return config, summary, base, corrected

    @staticmethod
    def check(config: dict, summary: dict, base: Path) -> str:
        return status.versioned_precip_summary_error(summary, "monthly_transfer_v3", 2, config=config, base_dir=base)

    def test_training_outside_application_period_is_checked_without_confusing_the_two(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config, summary, base, _ = self.make_product(Path(td))
            self.assertNotEqual(summary["provenance"]["base_precipitation_series"]["series_sha256"], summary["transfer_rules"]["identity"]["base_series"]["series_sha256"])
            self.assertEqual(self.check(config, summary, base), "")

    def test_changed_training_window_blocks_same_count_products(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config, summary, base, _ = self.make_product(Path(td))
            config["气象策略"]["station_rule_training_end"] = "2024-05-07"
            self.assertIn("训练时段", self.check(config, summary, base))

    def test_replaced_station_content_of_same_size_blocks_old_product_after_cached_check(self) -> None:
        for field, message in (("站点降水_csv", "站点降水资料"), ("站点信息_csv", "站点信息")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                config, summary, base, _ = self.make_product(Path(td))
                self.assertEqual(self.check(config, summary, base), "")
                path = Path(config["气象策略"][field])
                before = path.stat()
                content = path.read_bytes().replace(b",1", b",2") if field == "站点降水_csv" else path.read_bytes().replace(b"0.5", b"0.6")
                self.assertEqual(len(content), before.st_size)
                path.write_bytes(content)
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
                self.assertIn(message, self.check(config, summary, base))

    def test_changed_application_baseline_blocks_same_file_count(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config, summary, base, _ = self.make_product(Path(td))
            self.assertEqual(self.check(config, summary, base), "")
            (base / "P_2025.05.01.tif").write_bytes(b"new base")
            self.assertIn("当前运行时段或基础降水", self.check(config, summary, base))

    def test_changed_training_baseline_outside_application_period_also_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config, summary, base, _ = self.make_product(Path(td))
            self.assertEqual(self.check(config, summary, base), "")
            (base / "P_2024.05.01.tif").write_bytes(b"new base")
            self.assertIn("训练时段的基础降水", self.check(config, summary, base))

    def test_changed_application_dates_of_same_length_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config, summary, base, _ = self.make_product(Path(td))
            config["时间"] = {"预热开始": "2024-05-01", "率定结束": "2024-05-02"}
            self.assertIn("当前运行时段", self.check(config, summary, base))

    def test_old_provenance_missing_or_mismatched_rule_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config, summary, base, _ = self.make_product(Path(td))
            old = copy.deepcopy(summary)
            old.pop("provenance")
            self.assertIn("缺少输入资料身份", self.check(config, old, base))
            inconsistent = copy.deepcopy(summary)
            original_input = inconsistent["transfer_rules"]["identity"]["input_files"]["station_precipitation_input"]
            inconsistent["transfer_rules"]["identity"]["input_files"]["station_precipitation_input"] = {**original_input, "sha256": "other-file"}
            self.assertIn("不同的输入资料", self.check(config, inconsistent, base))

    def test_ui_status_receives_current_config_and_rejects_stale_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config, summary, base, corrected = self.make_product(Path(td))
            context = status.PrecipStrategyStatusContext(
                meteo_key="气象策略", meteo_precip_mode_key="降水方案", current_profile=lambda _: "daily",
                effective_precip_paths=lambda *_args, **_kwargs: (base, corrected, "era5"),
                count_matching=lambda directory: len(list(Path(directory).glob("*.tif"))),
                read_json_file=lambda path: json.loads(path.read_text(encoding="utf-8")),
            )
            self.assertTrue(status.check_precip_strategy_outputs(config, context)[0])
            config["气象策略"]["station_rule_training_start"] = "2024-05-02"
            ok, message, count = status.check_precip_strategy_outputs(config, context)
            self.assertFalse(ok)
            self.assertEqual(count, 2)
            self.assertIn("训练时段", message)

    def test_repeated_ui_checks_do_not_reread_unchanged_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config, summary, base, _ = self.make_product(Path(td))
            with mock.patch.object(Path, "open", autospec=True, side_effect=Path.open) as opened:
                self.assertEqual(self.check(config, summary, base), "")
                first_reads = opened.call_count
                self.assertGreater(first_reads, 10)
                self.assertEqual(self.check(config, summary, base), "")
                self.assertEqual(opened.call_count, first_reads)


if __name__ == "__main__":
    unittest.main()
