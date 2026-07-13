from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import profile_runner as runner  # noqa: E402


class ProfileInputContractTests(unittest.TestCase):
    def test_metadata_pending_blocks_formal_calibration(self) -> None:
        error = runner.precipitation_product_metadata_error(
            {"降水产品元数据": {"metadata_status": "pending", "formal_run_allowed": False}}
        )

        self.assertIn("仅允许质检", error)

    def test_empirical_metadata_allows_only_explicit_internal_diagnostic(self) -> None:
        metadata = {
            "metadata_status": "empirically_inferred",
            "formal_run_allowed": False,
            "empirical_diagnostic_allowed": True,
        }
        self.assertEqual(
            runner.precipitation_product_metadata_error(
                {"运行用途": "internal_diagnostic", "降水产品元数据": metadata}
            ),
            "",
        )
        self.assertIn(
            "禁止正式率定",
            runner.precipitation_product_metadata_error(
                {"运行用途": "formal_calibration", "降水产品元数据": metadata}
            ),
        )

    def test_monthly_precipitation_qc_blocks_formal_calibration(self) -> None:
        error = runner.precipitation_strategy_qc_error(
            {
                "processing_stats": {
                    "qc_blocked": True,
                    "monthly_conservation": {
                        "high_factor_cell_count": 4,
                        "high_removed_fraction_cell_count": 2,
                        "unresolved_cell_count": 1,
                    },
                }
            }
        )

        self.assertIn("高倍率像元-月份 4", error)
        self.assertIn("移除比例超过 30% 的像元-月份 2", error)
        self.assertIn("未分配像元-月份 1", error)

    def test_v2_daily_workspace_requires_confirmed_daily_forcing_manifest(self) -> None:
        config = {"气象策略": {"station_correction_algorithm": "occurrence_amount_v2"}}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.object(runner, "build_profile_paths", return_value={"aligned_dir": root}):
                missing = runner.daily_forcing_manifest_error(config, runner.PROFILE_DAILY)
                self.assertIn("缺少日强迫契约清单", missing)
                (root / "daily_forcing_manifest.json").write_text(
                    json.dumps(
                        {
                            "schema": "hbv_cryo_daily_forcing_manifest_v1",
                            "precipitation": {
                                "output_unit": "mm/day",
                                "unit_confirmed": True,
                                "day_basis": "product_calendar_day",
                                "day_basis_confirmed": True,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                self.assertEqual(runner.daily_forcing_manifest_error(config, runner.PROFILE_DAILY), "")

    def test_required_boundary_index_covers_last_fourteen_warmup_days_and_evaluation(self) -> None:
        config = {
            "时间步长_小时": 24.0,
            "时间": {
                "预热开始": "2025-01-01",
                "预热结束": "2025-05-31",
                "率定开始": "2025-06-01",
                "率定结束": "2025-09-10",
                "验证结束": "2025-10-30",
            },
        }

        index, step_hours = runner.required_boundary_index(config)

        self.assertEqual(step_hours, 24.0)
        self.assertEqual(index[0], pd.Timestamp("2025-05-18"))
        self.assertEqual(index[-1], pd.Timestamp("2025-10-30"))
        self.assertEqual(len(index), 166)


if __name__ == "__main__":
    unittest.main()
