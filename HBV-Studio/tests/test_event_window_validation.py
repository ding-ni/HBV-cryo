import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import studio_service as svc  # noqa: E402


def _event_config() -> dict:
    return {
        "任务时段模式": "event_windows",
        "时间步长_小时": 24,
        "时间": {
            "预热开始": "2020-01-01",
            "率定开始": "2020-01-01",
            "率定结束": "2022-12-31",
            "验证开始": "2020-01-01",
            "验证结束": "2022-12-31",
        },
        "洪水事件率定": {
            "启用": True,
            "事件窗口资料": True,
            "事件表": [
                {
                    "event_id": "E202007",
                    "purpose": "calibration",
                    "run_start": "2020-07-01",
                    "score_start": "2020-07-03",
                    "score_end": "2020-07-05",
                    "run_end": "2020-07-06",
                },
                {
                    "event_id": "E202108",
                    "purpose": "validation",
                    "run_start": "2021-08-01",
                    "score_start": "2021-08-03",
                    "score_end": "2021-08-05",
                    "run_end": "2021-08-06",
                },
                {
                    "event_id": "E202206",
                    "purpose": "diagnostic",
                    "run_start": "2022-06-01",
                    "score_start": "2022-06-03",
                    "score_end": "2022-06-05",
                    "run_end": "2022-06-06",
                },
            ],
        },
    }


def _touch_tifs(directory: Path, timestamps: pd.DatetimeIndex, prefix: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for timestamp in timestamps:
        (directory / f"{prefix}_{pd.Timestamp(timestamp):%Y.%m.%d}.tif").write_bytes(b"")


class EventWindowValidationTests(unittest.TestCase):
    def test_expected_indexes_use_event_windows_not_full_period(self) -> None:
        config = _event_config()
        forcing_index = svc.build_expected_forcing_index(config)
        observation_index = svc.build_expected_observation_index(config)
        continuous_index = svc.build_expected_time_index(config)

        self.assertEqual(len(forcing_index), 18)
        self.assertEqual(len(observation_index), 9)
        self.assertGreater(len(continuous_index), len(forcing_index))
        self.assertIn(pd.Timestamp("2021-08-04"), set(forcing_index))
        self.assertNotIn(pd.Timestamp("2021-01-15"), set(forcing_index))

    def test_forcing_check_allows_between_event_gaps_and_fails_inside_event_gaps(self) -> None:
        config = _event_config()
        event_info = svc.normalized_flood_events(config, step_hours=24)
        expected_index = svc.build_expected_forcing_index(config)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directories = {}
            for key, label in (("prec", "降水"), ("temp", "气温"), ("evap", "潜在蒸散发")):
                data_dir = root / key
                _touch_tifs(data_dir, expected_index, key)
                if key == "prec":
                    (data_dir / "outside_2021.01.15.tif").write_bytes(b"")
                directories[key] = svc.validate_tif_time_series(label, data_dir, 24, expected_index, "洪水事件窗口")

            self.assertTrue(directories["prec"]["ok"])
            self.assertEqual(len(directories["prec"]["out_of_range_steps"]), 1)
            coverage = svc.event_forcing_coverage_summary(event_info, directories, 24)
            self.assertEqual(coverage["status"], "ok")
            self.assertEqual(coverage["complete_event_count"], 3)

            missing_temp = root / "temp" / "temp_2021.08.04.tif"
            missing_temp.unlink()
            directories["temp"] = svc.validate_tif_time_series("气温", root / "temp", 24, expected_index, "洪水事件窗口")
            coverage = svc.event_forcing_coverage_summary(event_info, directories, 24)
            self.assertEqual(coverage["status"], "fail")
            failed = [event for event in coverage["events"] if event["event_id"] == "E202108"][0]
            self.assertEqual(failed["variables"]["temp"]["missing_steps"], 1)

    def test_observation_check_requires_calibration_and_validation_events(self) -> None:
        config = _event_config()
        event_info = svc.normalized_flood_events(config, step_hours=24)
        observation_index = svc.build_expected_observation_index(config)

        required_index = pd.DatetimeIndex([ts for ts in observation_index if ts.year in {2020, 2021}])
        observed = pd.Series(1.0, index=required_index)
        coverage = svc.event_observation_coverage_summary(event_info, observed, 24)

        self.assertEqual(coverage["status"], "warn")
        diagnostic = [event for event in coverage["events"] if event["event_id"] == "E202206"][0]
        self.assertEqual(diagnostic["status"], "warn")
        self.assertEqual(coverage["required_complete_event_count"], 2)

        observed_missing_required = observed.drop(pd.Timestamp("2021-08-04"))
        coverage = svc.event_observation_coverage_summary(event_info, observed_missing_required, 24)
        self.assertEqual(coverage["status"], "fail")
        failed = [event for event in coverage["events"] if event["event_id"] == "E202108"][0]
        self.assertEqual(failed["missing_steps"], 1)


if __name__ == "__main__":
    unittest.main()
