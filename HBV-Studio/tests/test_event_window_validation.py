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


def _touch_tifs(directory: Path, timestamps: pd.DatetimeIndex, prefix: str, fmt: str = "%Y.%m.%d") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for timestamp in timestamps:
        (directory / f"{prefix}_{pd.Timestamp(timestamp):{fmt}}.tif").write_bytes(b"")


def _hourly_event_config() -> dict:
    return {
        "任务时段模式": "event_windows",
        "时间步长_小时": 1,
        "时间": {
            "预热开始": "2025-01-01 00:00",
            "率定开始": "2025-01-01 00:00",
            "率定结束": "2025-12-31 23:00",
            "验证开始": "2025-01-01 00:00",
            "验证结束": "2025-12-31 23:00",
        },
        "洪水事件率定": {
            "启用": True,
            "事件窗口资料": True,
            "事件表": [
                {
                    "event_id": "H202505",
                    "purpose": "calibration",
                    "run_start": "2025-05-01 00:00",
                    "score_start": "2025-05-01 02:00",
                    "score_end": "2025-05-01 07:00",
                    "run_end": "2025-05-01 09:00",
                },
                {
                    "event_id": "H202508",
                    "purpose": "validation",
                    "run_start": "2025-08-02 00:00",
                    "score_start": "2025-08-02 02:00",
                    "score_end": "2025-08-02 07:00",
                    "run_end": "2025-08-02 09:00",
                },
            ],
        },
    }


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

    def test_hourly_event_windows_allow_between_event_gaps_but_not_internal_gaps(self) -> None:
        config = _hourly_event_config()
        event_info = svc.normalized_flood_events(config, step_hours=1)
        forcing_index = svc.build_expected_forcing_index(config)
        observation_index = svc.build_expected_observation_index(config)
        continuous_index = svc.build_expected_time_index(config)

        self.assertEqual(len(forcing_index), 20)
        self.assertEqual(len(observation_index), 12)
        self.assertGreater(len(continuous_index), len(forcing_index))
        self.assertIn(pd.Timestamp("2025-08-02 04:00"), set(forcing_index))
        self.assertNotIn(pd.Timestamp("2025-06-01 00:00"), set(forcing_index))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directories = {}
            for key, label in (("prec", "降水"), ("temp", "气温"), ("evap", "潜在蒸散发")):
                data_dir = root / key
                _touch_tifs(data_dir, forcing_index, key, fmt="%Y.%m.%d.%H")
                directories[key] = svc.validate_tif_time_series(label, data_dir, 1, forcing_index, "洪水事件窗口")

            forcing_coverage = svc.event_forcing_coverage_summary(event_info, directories, 1)
            self.assertEqual(forcing_coverage["status"], "ok")
            self.assertEqual(forcing_coverage["complete_event_count"], 2)

            observed = pd.Series(1.0, index=observation_index)
            observation_coverage = svc.event_observation_coverage_summary(event_info, observed, 1)
            self.assertEqual(observation_coverage["status"], "ok")
            self.assertEqual(observation_coverage["required_complete_event_count"], 2)

            missing_temp = root / "temp" / "temp_2025.08.02.04.tif"
            missing_temp.unlink()
            directories["temp"] = svc.validate_tif_time_series("气温", root / "temp", 1, forcing_index, "洪水事件窗口")
            forcing_coverage = svc.event_forcing_coverage_summary(event_info, directories, 1)
            self.assertEqual(forcing_coverage["status"], "fail")
            failed = [event for event in forcing_coverage["events"] if event["event_id"] == "H202508"][0]
            self.assertEqual(failed["variables"]["temp"]["missing_steps"], 1)


if __name__ == "__main__":
    unittest.main()
