from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import py_compile
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
import rasterio

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import app_bootstrap as bootstrap
import precipitation_strategy_runner as runner
import profile_runner
from services import precip_strategy_status as status
import test_precipitation_strategy_runner as runner_tests


class PrecipPortableIdentityTests(unittest.TestCase):
    @contextlib.contextmanager
    def installed_roots(self, root: Path):
        app = root / "HBVStudio"
        gui = app / "HBV-Studio"
        runtime = app / "用户数据" / "运行目录"
        gui.mkdir(parents=True)
        runtime.mkdir(parents=True)
        original_cwd = Path.cwd()
        with (
            mock.patch.object(profile_runner, "APP_ROOT", app),
            mock.patch.object(profile_runner, "PROJECT_ROOT", app),
            mock.patch.object(profile_runner, "GUI_ROOT", gui),
            mock.patch.object(bootstrap, "APP_ROOT", app),
            mock.patch.object(bootstrap, "GUI_ROOT", gui),
            mock.patch.object(bootstrap, "runtime_root_for_mode", return_value=runtime),
            mock.patch.dict(os.environ, {"HBV_STUDIO_RUNTIME_ROOT": str(runtime)}),
        ):
            os.chdir(app)
            try:
                yield app, runtime
            finally:
                os.chdir(original_cwd)

    @staticmethod
    def raw_inputs(prec: Path, meta: Path, manifest: Path) -> dict:
        result = {}
        for key, path in (
            ("station_precipitation_input", prec), ("station_metadata_input", meta),
            ("source_daily_forcing_manifest", manifest),
        ):
            result[key] = {**runner.sha256_file_identity(path), "path": str(path.resolve())}
        result["nested"] = {"paths": [str(prec), str(meta), str(manifest)]}
        return result

    def product(self, root: Path, runtime: Path):
        workspace = runtime / "YC-ML"
        base = workspace / "数据" / "模型输入" / "降水"
        corrected = base.with_name("降水_月规则_v3")
        base.mkdir(parents=True)
        dates = pd.date_range("2025-05-01", periods=7)
        records = runner_tests.PrecipitationStrategyRunnerTests._write_records(base, list(dates), [2.0] * 7)
        station_prec = workspace / "站点降水.csv"
        station_prec.write_text("date,S1\n" + "".join(f"{date:%Y-%m-%d},1\n" for date in dates), encoding="utf-8")
        station_meta = root / "外部资料" / "站点信息.csv"
        station_meta.parent.mkdir()
        station_meta.write_text("station_id,x,y\nS1,500,500\n", encoding="utf-8")
        manifest = base.parent / "daily_forcing_manifest.json"
        manifest.write_text(json.dumps(runner.portable_identity_value({"schema": "daily_forcing_v1", "prec_dir": str(base)})), encoding="utf-8")
        inputs = self.raw_inputs(station_prec, station_meta, manifest)
        stations = runner_tests.PrecipitationStrategyRunnerTests._one_station()
        series = pd.DataFrame({"S1": [1.0] * 7}, index=dates)
        rules_summary = runner.fit_monthly_transfer_rules(
            records, corrected, stations, series, input_identity=inputs,
            training_start="2025-05-01", training_end="2025-05-07",
        )
        rules = runner.load_monthly_transfer_rules(corrected, expected_fingerprint=rules_summary["identity_sha256"])
        self.assertIsNotNone(rules)
        stats = runner.apply_grid_bias_correction(
            records, corrected, stations, series, False, rules, return_stats=True,
            algorithm="monthly_transfer_v3", input_identity=inputs,
        )
        summary = {
            "selected_steps": 7, "written_files": 7, "missing_expected_steps": 0, "time_step_hours": 24,
            "processing_stats": stats, "transfer_rules": rules_summary,
            "base_dir": str(base), "target_dir": str(corrected),
            "provenance": {**{key: inputs[key] for key in ("station_precipitation_input", "station_metadata_input", "source_daily_forcing_manifest")},
                           "base_precipitation_series": runner.raster_series_fingerprint(records)},
        }
        summary_path = runner.write_strategy_summary(corrected, summary)
        config = {
            "_config_path": str(workspace / "workspace.json"), "时间步长_小时": 24,
            "时间": {"预热开始": "2025-05-01", "率定结束": "2025-05-07"},
            "气象策略": {"降水方案": "grid_plus_station_bias", "station_correction_algorithm": "monthly_transfer_v3",
                       "站点降水_csv": str(station_prec), "站点信息_csv": str(station_meta),
                       "station_rule_training_start": "2025-05-01", "station_rule_training_end": "2025-05-07"},
        }
        return records, corrected, stations, series, inputs, summary_path, config

    def test_real_startup_repair_twice_preserves_rule_cache_summary_and_quality(self) -> None:
        with tempfile.TemporaryDirectory() as td, self.installed_roots(Path(td)) as (_app, runtime):
            records, corrected, stations, series, inputs, summary_path, config = self.product(Path(td), runtime)
            rules_path = corrected / runner.MONTHLY_TRANSFER_RULES_JSON
            rules_before = json.loads(rules_path.read_text(encoding="utf-8"))
            self.assertTrue(rules_before["identity"]["input_files"]["station_precipitation_input"]["path"].startswith("__PROJECT_ROOT__/"))
            self.assertEqual(rules_before["identity"]["input_files"]["station_metadata_input"]["path"], inputs["station_metadata_input"]["path"])
            self.assertTrue(rules_before["json_path"].startswith("__PROJECT_ROOT__/"))
            before = {path: path.read_bytes() for path in runtime.rglob("*.json")}
            for _ in range(2):
                bootstrap.repair_runtime_jsons()
                self.assertEqual({path: path.read_bytes() for path in before}, before)
                rules = runner.load_monthly_transfer_rules(corrected, expected_fingerprint=rules_before["identity_sha256"])
                self.assertIsNotNone(rules)
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                self.assertEqual(status.versioned_precip_summary_error(summary, "monthly_transfer_v3", 7, config=config, base_dir=records[0][1].parent), "")
                reused = runner.apply_grid_bias_correction(
                    records, corrected, stations, series, False, rules, return_stats=True,
                    algorithm="monthly_transfer_v3", input_identity=inputs,
                )
                self.assertTrue(reused["quality_evidence_reused"])
                self.assertEqual(reused["processed_steps"], 0)
                with rasterio.open(corrected / records[0][1].name) as src:
                    self.assertAlmostEqual(float(src.read(1)[0, 0]), 1.0)

    def test_old_absolute_self_hashed_rule_is_rejected_after_actual_startup_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as td, self.installed_roots(Path(td)) as (_app, runtime):
            _records, corrected, _stations, _series, inputs, _summary_path, _config = self.product(Path(td), runtime)
            rules_path = corrected / runner.MONTHLY_TRANSFER_RULES_JSON
            legacy = json.loads(rules_path.read_text(encoding="utf-8"))
            legacy["identity"]["input_files"] = copy.deepcopy(inputs)
            legacy["json_path"] = str(rules_path)
            legacy["npz_path"] = str(corrected / runner.MONTHLY_TRANSFER_RULES_NPZ)
            legacy["identity_sha256"] = runner._json_digest(legacy["identity"])
            legacy.pop("summary_content_sha256")
            legacy["summary_content_sha256"] = runner._json_digest(legacy)
            rules_path.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertIsNotNone(runner.load_monthly_transfer_rules(corrected, expected_fingerprint=legacy["identity_sha256"]))
            bootstrap.repair_runtime_jsons()
            self.assertIsNone(runner.load_monthly_transfer_rules(corrected, expected_fingerprint=legacy["identity_sha256"]))

    def test_portable_paths_do_not_hide_changed_station_or_corrected_raster_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td, self.installed_roots(Path(td)) as (_app, runtime):
            records, corrected, stations, series, inputs, summary_path, config = self.product(Path(td), runtime)
            bootstrap.repair_runtime_jsons()
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(status.versioned_precip_summary_error(summary, "monthly_transfer_v3", 7, config=config, base_dir=records[0][1].parent), "")
            output = corrected / records[0][1].name
            with rasterio.open(output, "r+") as dst:
                dst.write(dst.read(1) * 3, 1)
            rules = runner.load_monthly_transfer_rules(corrected, expected_fingerprint=summary["transfer_rules"]["identity_sha256"])
            result = runner.apply_grid_bias_correction(records, corrected, stations, series, False, rules, return_stats=True, algorithm="monthly_transfer_v3", input_identity=inputs)
            self.assertFalse(result["quality_evidence_reused"])
            with rasterio.open(output) as src:
                self.assertAlmostEqual(float(src.read(1)[0, 0]), 1.0)
            station_prec = Path(config["气象策略"]["站点降水_csv"])
            old_stat = station_prec.stat()
            station_prec.write_bytes(station_prec.read_bytes().replace(b",1", b",9"))
            os.utime(station_prec, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000))
            self.assertIn("站点降水资料", status.versioned_precip_summary_error(summary, "monthly_transfer_v3", 7, config=config, base_dir=records[0][1].parent))

    def test_implementation_identity_keeps_source_and_compiled_bytes_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as td, self.installed_roots(Path(td)) as (app, runtime):
            source = app / "HBV-Studio" / "precipitation_strategy_runner.py"
            compiled = source.with_suffix(".pyc")
            source.write_bytes(Path(runner.__file__).read_bytes())
            py_compile.compile(str(source), cfile=str(compiled), doraise=True)
            self.assertNotEqual(hashlib.sha256(source.read_bytes()).hexdigest(), hashlib.sha256(compiled.read_bytes()).hexdigest())
            with mock.patch.object(runner, "__file__", str(compiled)):
                records, _corrected, _stations, _series, _inputs, summary_path, config = self.product(Path(td), runtime)
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                self.assertEqual(summary["transfer_rules"]["identity"]["algorithm"]["implementation_sha256"], hashlib.sha256(compiled.read_bytes()).hexdigest())
                self.assertEqual(status.versioned_precip_summary_error(summary, "monthly_transfer_v3", 7, config=config, base_dir=records[0][1].parent), "")
            with mock.patch.object(runner, "__file__", str(source)):
                self.assertIn("算法已更新", status.versioned_precip_summary_error(summary, "monthly_transfer_v3", 7, config=config, base_dir=records[0][1].parent))


if __name__ == "__main__":
    unittest.main()
