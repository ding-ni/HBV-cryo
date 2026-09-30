from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from dataclasses import replace

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import profile_runner  # noqa: E402
import precipitation_strategy_runner as runner  # noqa: E402
import studio_service  # noqa: E402
from services.forcing_validation import ForcingValidationContext, validate_forcing_bundle  # noqa: E402
from services.precip_strategy_status import (  # noqa: E402
    PrecipStrategyStatusContext,
    check_precip_strategy_outputs,
    versioned_precip_summary_error,
)
from services.workspace_completeness import WorkspaceCompletenessContext, workspace_completeness  # noqa: E402


class PrecipQualityWorkflowGateTests(unittest.TestCase):
    @staticmethod
    def _valid_summary(algorithm: str = "monthly_transfer_v3", paths: dict[str, Path] | None = None) -> dict:
        monthly = {
            "method": "same_cell_same_month_amount_conservation",
            "qc_blocked": False,
            "months": [{"month": "2025-05", "high_factor_cell_count": 0, "high_removed_fraction_cell_count": 0, "unresolved_cell_count": 0}],
            "high_factor_cell_count": 0,
            "high_removed_fraction_cell_count": 0,
            "unresolved_cell_count": 0,
        }
        summary = {
            "selected_steps": 1,
            "written_files": 1,
            "time_step_hours": 24,
            "missing_expected_steps": 0,
            "processing_stats": {
                "algorithm": algorithm,
                "qc_blocked": False,
                "monthly_conservation": monthly if algorithm == "occurrence_amount_v2" else None,
                "quality_checks": {"status": "passed", "qc_blocked": False, "checked_steps": 1, "failures": []},
                "rules_identity_sha256": "rule-fingerprint",
            },
            "transfer_rules": {
                "schema": "station_bias_monthly_transfer_rules_v3",
                "available": True,
                "identity_sha256": "rule-fingerprint",
                "quality_checks": {"status": "passed", "qc_blocked": False},
            },
        }
        if paths is not None:
            records = runner.list_rasters(paths["prec_base"])
            inputs = {
                "station_precipitation_input": runner.sha256_file_identity(paths["prec_base"].parent / "station_precip.csv"),
                "station_metadata_input": runner.sha256_file_identity(paths["prec_base"].parent / "stations.csv"),
                "source_daily_forcing_manifest": runner.sha256_file_identity(paths["prec_base"].parent / "daily_forcing_manifest.json"),
            }
            summary["provenance"] = {**inputs, "base_precipitation_series": runner.raster_series_fingerprint(records)}
            summary["transfer_rules"]["identity"] = {
                "requested_training_start": "", "requested_training_end": "",
                "algorithm": runner._algorithm_identity(algorithm, 24.0),
                "base_series": runner.raster_series_fingerprint(records), "input_files": inputs,
            }
        return summary

    @staticmethod
    def _artifacts(root: Path) -> dict[str, Path]:
        paths = {key: root / key for key in ("gis_dir", "prec_base", "prec_corrected", "aligned_temp_dir", "aligned_evap_dir")}
        for directory in paths.values():
            directory.mkdir(parents=True)
        for name in ("dem.tif", "flow_accumulation_masked.tif", "elevation_zone_low.tif", "elevation_zone_high.tif"):
            (paths["gis_dir"] / name).write_bytes(b"test")
        for key in ("prec_base", "prec_corrected", "aligned_temp_dir", "aligned_evap_dir"):
            (paths[key] / "P_2025.05.01.tif").write_bytes(b"test")
        (root / "station_precip.csv").write_text("date,S1\n2025-05-01,1\n", encoding="utf-8")
        (root / "stations.csv").write_text("station_id,lon,lat\nS1,0.5,1.5\n", encoding="utf-8")
        return paths

    @staticmethod
    def _config(algorithm: str = "monthly_transfer_v3", paths: dict[str, Path] | None = None) -> dict:
        meteo = {"降水方案": "grid_plus_station_bias", "station_correction_algorithm": algorithm}
        if paths is not None:
            meteo.update({"站点降水_csv": str(paths["prec_base"].parent / "station_precip.csv"), "站点信息_csv": str(paths["prec_base"].parent / "stations.csv")})
        config = {"气象策略": meteo, "时间步长_小时": 24}
        if paths is not None:
            config["_config_path"] = str(paths["prec_base"].parent / "workspace.json")
        return config

    @staticmethod
    def _status_context(paths: dict[str, Path]) -> PrecipStrategyStatusContext:
        return PrecipStrategyStatusContext(
            meteo_key="气象策略",
            meteo_precip_mode_key="降水方案",
            current_profile=lambda config: "daily",
            effective_precip_paths=lambda config, profile, **kwargs: (paths["prec_base"], paths["prec_corrected"], "era5"),
            count_matching=lambda directory: len(list(Path(directory).glob("*.tif"))),
            read_json_file=lambda path: json.loads(path.read_text(encoding="utf-8")),
        )

    def _workflow_context(self, root: Path, paths: dict[str, Path], config: dict, quality_check) -> WorkspaceCompletenessContext:
        return WorkspaceCompletenessContext(
            resolve_any_path=lambda raw, **kwargs: Path(raw),
            read_runtime_config=lambda path: config,
            resolve_precip_source=lambda config, source: "era5",
            detect_object_type=lambda config: "interbasin_with_boundary",
            wizard_validate_step=lambda path, step, **kwargs: {"valid": quality_check(config)[0] if step == 6 else True},
            current_profile=lambda config: "daily",
            build_profile_paths=lambda config, profile: paths,
            workspace_dem_path=lambda directory, **kwargs: paths["gis_dir"] / "dem.tif",
            configured_dem_kind=lambda config: "1km",
            effective_precip_paths=lambda config, profile, **kwargs: (paths["prec_base"], paths["prec_corrected"], "era5"),
            has_matching=lambda directory: any(Path(directory).glob("*.tif")),
            # Deliberately reproduce the old inconsistency: calibration validation claims ready.
            validate_workspace_fields=lambda path, **kwargs: {"valid": True, "missing": [], "warnings": []},
            object_interbasin="interbasin_with_boundary",
            check_precip_strategy_outputs=quality_check,
        )

    @staticmethod
    def _forcing_context(paths: dict[str, Path], quality_check) -> ForcingValidationContext:
        return ForcingValidationContext(
            current_profile=lambda config: "daily",
            build_profile_paths=lambda config, profile: paths,
            normalize_time_step_hours=lambda value: 24,
            task_time_basis=lambda config, **kwargs: "continuous",
            time_basis_labels={"continuous": "连续时段"},
            time_basis_event_windows="event_windows",
            build_expected_forcing_index=lambda config, **kwargs: pd.date_range("2025-05-01", periods=1, freq="D"),
            normalized_flood_events=lambda config, **kwargs: {},
            effective_precip_paths=lambda config, profile, **kwargs: (paths["prec_base"], paths["prec_corrected"], "era5"),
            validate_tif_time_series=lambda label, directory, *args: {"label": label, "ok": True, "errors": [], "warnings": [], "valid_time_steps": 1},
            workspace_dem_path=lambda directory, **kwargs: paths["gis_dir"] / "dem.tif",
            configured_dem_kind=lambda config: "1km",
            validate_tif_grid_alignment=lambda *args: {"ok": True, "error": None},
            event_windows_ui_summary=lambda *args: None,
            event_forcing_coverage_summary=lambda *args: None,
            check_precip_strategy_outputs=quality_check,
        )

    def test_versioned_products_require_readable_matching_passed_quality_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._artifacts(Path(temp_dir))
            context = self._status_context(paths)
            summary_path = paths["prec_corrected"] / "precipitation_strategy_summary.json"
            for algorithm in ("monthly_transfer_v3", "occurrence_amount_v2"):
                config = self._config(algorithm, paths)
                invalid = [None, "{invalid", {}]
                failed = self._valid_summary(algorithm)
                failed["processing_stats"]["qc_blocked"] = True
                invalid.append(failed)
                mismatch = self._valid_summary(algorithm)
                mismatch["processing_stats"]["algorithm"] = "legacy_ratio_v1"
                invalid.append(mismatch)
                missing = self._valid_summary(algorithm)
                if algorithm == "monthly_transfer_v3":
                    missing["processing_stats"].pop("quality_checks")
                else:
                    missing["processing_stats"]["monthly_conservation"] = None
                invalid.append(missing)
                for summary in invalid:
                    with self.subTest(algorithm=algorithm, summary=summary):
                        if summary is None:
                            # A missing file is modelled by an isolated directory, without deleting artifacts.
                            isolated = paths["prec_corrected"] / "missing_summary"
                            isolated.mkdir(exist_ok=True)
                            (isolated / "P_2025.05.01.tif").write_bytes(b"test")
                            missing_context = replace(context, effective_precip_paths=lambda config, profile, **kwargs: (paths["prec_base"], isolated, "era5"))
                            ok, message, count = check_precip_strategy_outputs(config, missing_context)
                        else:
                            summary_path.write_text(summary if isinstance(summary, str) else json.dumps(summary), encoding="utf-8")
                            ok, message, count = check_precip_strategy_outputs(config, context)
                        self.assertFalse(ok, message)
                        self.assertEqual(count, 1)
                summary_path.write_text(json.dumps(self._valid_summary(algorithm, paths)), encoding="utf-8")
                self.assertTrue(check_precip_strategy_outputs(config, context)[0])

    def test_known_v2_monthly_failures_cannot_pass_without_complete_monthly_quality_fields(self) -> None:
        invalid = self._valid_summary("occurrence_amount_v2")
        monthly = invalid["processing_stats"]["monthly_conservation"]
        monthly.pop("qc_blocked")
        monthly["high_factor_cell_count"] = 5
        monthly["high_removed_fraction_cell_count"] = 34
        self.assertTrue(versioned_precip_summary_error(invalid, "occurrence_amount_v2", 1))
        invalid = self._valid_summary("occurrence_amount_v2")
        invalid["processing_stats"]["monthly_conservation"].pop("months")
        self.assertTrue(versioned_precip_summary_error(invalid, "occurrence_amount_v2", 1))

    def test_v3_passed_label_without_explicit_qc_result_is_incomplete_evidence(self) -> None:
        invalid = self._valid_summary()
        invalid["processing_stats"]["quality_checks"].pop("qc_blocked")
        self.assertTrue(versioned_precip_summary_error(invalid, "monthly_transfer_v3", 1))

    def test_v3_count_and_frozen_rule_identity_must_match_checked_product(self) -> None:
        self.assertTrue(versioned_precip_summary_error(self._valid_summary(), "monthly_transfer_v3", 2))
        invalid = self._valid_summary()
        invalid["processing_stats"]["quality_checks"]["checked_steps"] = 0
        self.assertTrue(versioned_precip_summary_error(invalid, "monthly_transfer_v3", 1))
        invalid = self._valid_summary()
        invalid["processing_stats"]["rules_identity_sha256"] = "other-rules"
        self.assertTrue(versioned_precip_summary_error(invalid, "monthly_transfer_v3", 1))
        invalid = self._valid_summary()
        invalid["transfer_rules"]["quality_checks"]["status"] = "failed"
        self.assertTrue(versioned_precip_summary_error(invalid, "monthly_transfer_v3", 1))
        invalid = self._valid_summary()
        invalid["missing_expected_steps"] = 1
        self.assertTrue(versioned_precip_summary_error(invalid, "monthly_transfer_v3", 1))

    def test_failed_step6_never_reports_ready_even_with_all_rasters_and_calibration_validation_true(self) -> None:
        for algorithm in ("monthly_transfer_v3", "occurrence_amount_v2"):
            with self.subTest(algorithm=algorithm), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                paths = self._artifacts(root)
                config = self._config(algorithm, paths)
                summary = self._valid_summary(algorithm)
                summary["processing_stats"]["qc_blocked"] = True
                (paths["prec_corrected"] / "precipitation_strategy_summary.json").write_text(json.dumps(summary), encoding="utf-8")
                quality_check = lambda config, **kwargs: check_precip_strategy_outputs(config, self._status_context(paths))
                workflow = self._workflow_context(root, paths, config, quality_check)
                for quick in (True, False):
                    result = workspace_completeness(str(root / "workspace.json"), workflow, quick=quick)
                    self.assertFalse(result["ready_for_calibration"])
                    self.assertIn(6, result["steps_remaining"])
                    self.assertNotIn(6, result["steps_completed"])
                    self.assertLess(result["completed_count"], 7)
                    self.assertEqual(result["next_step"], 6)
                forcing = validate_forcing_bundle(config, self._forcing_context(paths, quality_check))
                self.assertFalse(forcing["ok"])
                self.assertTrue(forcing["errors"])
                with mock.patch.object(profile_runner, "build_profile_paths", return_value={"aligned_prec_effective_dir": paths["prec_corrected"]}), \
                     mock.patch.object(profile_runner, "daily_forcing_manifest_error", return_value=""), \
                     mock.patch.object(profile_runner, "required_boundary_coverage_error", return_value=""):
                    with self.assertRaisesRegex(ValueError, "正式运行输入契约未通过"):
                        profile_runner.validate_profile_input_contracts(config, "daily")

    def test_missing_qc_blocks_forcing_and_formal_runner_although_rasters_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._artifacts(Path(temp_dir))
            for algorithm in ("monthly_transfer_v3", "occurrence_amount_v2"):
                with self.subTest(algorithm=algorithm):
                    config = self._config(algorithm, paths)
                    quality_check = lambda config, **kwargs: check_precip_strategy_outputs(config, self._status_context(paths))
                    self.assertFalse(validate_forcing_bundle(config, self._forcing_context(paths, quality_check))["ok"])
                    with mock.patch.object(profile_runner, "build_profile_paths", return_value={"aligned_prec_effective_dir": paths["prec_corrected"]}), \
                         mock.patch.object(profile_runner, "daily_forcing_manifest_error", return_value=""), \
                         mock.patch.object(profile_runner, "required_boundary_coverage_error", return_value=""):
                        with self.assertRaisesRegex(ValueError, "缺少质量摘要"):
                            profile_runner.validate_profile_input_contracts(config, "daily")

    def test_passed_v3_can_finish_full_validation_but_quick_summary_keeps_step7_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._artifacts(root)
            config = self._config(paths=paths)
            (paths["prec_corrected"] / "precipitation_strategy_summary.json").write_text(json.dumps(self._valid_summary(paths=paths)), encoding="utf-8")
            quality_check = lambda config, **kwargs: check_precip_strategy_outputs(config, self._status_context(paths))
            workflow = self._workflow_context(root, paths, config, quality_check)
            quick = workspace_completeness(str(root / "workspace.json"), workflow, quick=True)
            self.assertFalse(quick["ready_for_calibration"])
            self.assertTrue(quick["pending_validation"])
            self.assertEqual(quick["steps_remaining"], [7])
            self.assertEqual(quick["next_step"], 7)
            full = workspace_completeness(str(root / "workspace.json"), workflow)
            self.assertTrue(full["ready_for_calibration"])
            self.assertEqual(full["steps_remaining"], [])
            self.assertTrue(validate_forcing_bundle(config, self._forcing_context(paths, quality_check))["ok"])

    def test_live_service_context_constructors_are_complete_and_quality_callback_is_bound(self) -> None:
        names = [
            "_forcing_validation_context", "_forcing_aligned_status_context", "_forcing_inputs_ready_context",
            "_forcing_preprocess_status_context", "_forcing_download_status_context", "_hourly_forcing_ready_context",
            "_workspace_completeness_context", "_workspace_validation_context", "_wizard_validation_context",
            "_data_prep_step_catalog_context",
        ]
        for name in names:
            with self.subTest(constructor=name):
                self.assertIsNotNone(getattr(studio_service, name)())
        self.assertIs(studio_service._forcing_validation_context().check_precip_strategy_outputs, studio_service.check_precip_strategy_outputs)
        self.assertIs(studio_service._workspace_completeness_context().check_precip_strategy_outputs, studio_service.check_precip_strategy_outputs)


if __name__ == "__main__":
    unittest.main()
