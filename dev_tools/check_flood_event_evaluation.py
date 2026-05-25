# -*- coding: utf-8 -*-
"""Synthetic smoke check for flood-event diagnostics."""

import importlib.util
import math
import pathlib
import tempfile

import numpy as np
import pandas as pd


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = REPO_ROOT / "HBV-Cryo" / "\u7387\u5b9a\u6838\u5fc3.py"


def load_core():
    spec = importlib.util.spec_from_file_location("hbv_core_flood_event_check", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    core = load_core()
    core.TIME_STEP_HOURS = 24.0

    dates = pd.date_range("2020-07-01", periods=12, freq="D")
    obs = np.array([20, 30, 55, 120, 260, 420, 300, 180, 100, 60, 40, 30], dtype=float)
    sim = np.array([18, 28, 50, 100, 220, 360, 430, 260, 150, 80, 48, 33], dtype=float)
    config = {
        "\u542f\u7528": True,
        "\u4e8b\u4ef6\u8868": [
            {
                "\u540d\u79f0": "flood_2020_07",
                "\u7c7b\u578b": "calibration",
                "\u9884\u70ed\u5f00\u59cb": "2020-06-01",
                "\u4e8b\u4ef6\u5f00\u59cb": "2020-07-01",
                "\u4e8b\u4ef6\u7ed3\u675f": "2020-07-12",
            }
        ],
        "\u76ee\u6807\u6743\u91cd": {
            "\u6d2a\u5cf0\u6d41\u91cf\u8bef\u5dee": 0.30,
            "\u5cf0\u73b0\u65f6\u95f4\u8bef\u5dee": 0.25,
            "\u6d2a\u91cf\u8bef\u5dee": 0.25,
            "\u9000\u6c34\u8fc7\u7a0b\u8bef\u5dee": 0.10,
            "\u9ad8\u6d41\u91cf\u52a0\u6743NSE": 0.10,
        },
    }

    summary = core.compute_flood_event_evaluation(dates, obs, sim, config, evaluation_basis="q_total")
    assert summary["enabled"] is True
    assert summary["status"] == "ok", summary
    assert summary["event_count"] == 1, summary
    assert summary["valid_event_count"] == 1, summary

    event = summary["events"][0]
    assert event["status"] == "ok", event
    assert abs(event["obs_peak_m3s"] - 420.0) < 1e-9
    assert abs(event["sim_peak_m3s"] - 430.0) < 1e-9
    assert abs(event["peak_time_error_hours"] - 24.0) < 1e-9
    assert math.isfinite(event["volume_error_percent"])
    assert math.isfinite(event["high_flow_weighted_nse"])
    assert math.isfinite(event["diagnostic_objective"]["score"])

    with tempfile.TemporaryDirectory() as tmp:
        output_name = core.write_flood_event_outputs(tmp, summary)
        assert output_name == "flood_events.csv"
        csv_text = (pathlib.Path(tmp) / output_name).read_text(encoding="utf-8-sig")
        assert "peak_time_error_hours" in csv_text
        assert "flood_2020_07" in csv_text

    print("flood_event_evaluation_check=ok")


if __name__ == "__main__":
    main()
