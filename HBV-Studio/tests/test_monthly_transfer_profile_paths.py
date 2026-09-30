from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from profile_runner import build_profile_paths


class MonthlyTransferProfilePathsTests(unittest.TestCase):
    def test_new_rules_use_separate_outputs_for_daily_and_hourly_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for profile in ("daily", "hourly"):
                config = {
                    "_config_path": str(Path(temp_dir) / "workspace.json"),
                    "运行目录": str(Path(temp_dir) / profile),
                    "气象策略": {"降水方案": "grid_plus_station_bias", "station_correction_algorithm": "occurrence_amount_v2"},
                }
                old = build_profile_paths(config, profile)
                for key in ("era5", "", "cmfd", "custom"):
                    middle = "_" + key if key else ""
                    old[f"aligned_prec{middle}_corrected_dir"].mkdir(parents=True, exist_ok=True)
                config["气象策略"]["station_correction_algorithm"] = "monthly_transfer_v3"
                new = build_profile_paths(config, profile)
                for key in ("era5", "", "cmfd", "custom"):
                    middle = "_" + key if key else ""
                    self.assertEqual(new[f"aligned_prec{middle}_base_dir"], old[f"aligned_prec{middle}_base_dir"])
                    self.assertNotEqual(new[f"aligned_prec{middle}_corrected_dir"], old[f"aligned_prec{middle}_corrected_dir"])
                    self.assertIn("v3", new[f"aligned_prec{middle}_corrected_dir"].name)
                    self.assertTrue(old[f"aligned_prec{middle}_corrected_dir"].exists())

    def test_thiessen_is_not_relocated_by_unused_algorithm_setting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {"_config_path": str(Path(temp_dir) / "workspace.json"), "运行目录": temp_dir, "气象策略": {"降水方案": "thiessen_station_only"}}
            before = build_profile_paths(config, "daily")
            config["气象策略"]["station_correction_algorithm"] = "monthly_transfer_v3"
            after = build_profile_paths(config, "daily")
            self.assertEqual(before["aligned_prec_era5_corrected_dir"], after["aligned_prec_era5_corrected_dir"])


if __name__ == "__main__":
    unittest.main()
