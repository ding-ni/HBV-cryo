from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.forecast_input import ForecastInputCheckContext, ensure_forecast_input_ready, forecast_input_check  # noqa: E402


class ForecastInputServiceTests(unittest.TestCase):
    def _unused_context(self) -> ForecastInputCheckContext:
        def fail(*args, **kwargs):
            raise AssertionError("context should not be used")

        return ForecastInputCheckContext(
            resolve_path=fail,
            read_json_file=fail,
            parameter_check_context=fail,
            normalize_time_step_hours=fail,
            forecast_source_state_time=fail,
            format_time_for_check=fail,
            forecast_expected_index=fail,
            forecast_input_dir_summary=fail,
            forecast_output_preview=fail,
            forecast_parameter_detail_text=fail,
            forecast_station_precip_check=fail,
        )

    def test_forecast_input_check_rejects_missing_source_without_context_io(self) -> None:
        result = forecast_input_check({}, self._unused_context())

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["headline"], "请先选择预报源结果。")
        self.assertEqual(result["errors"], ["请先选择预报源结果。"])
        self.assertEqual(result["variables"], [])

    def test_ensure_forecast_input_ready_raises_for_failed_check(self) -> None:
        with self.assertRaisesRegex(ValueError, "连续状态预报输入检查未通过：请先选择预报源结果"):
            ensure_forecast_input_ready({}, self._unused_context())


if __name__ == "__main__":
    unittest.main()
