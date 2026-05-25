# -*- coding: utf-8 -*-
"""Synthetic smoke check for flood-event diagnostics."""

import importlib.util
import math
import pathlib
import sys
import tempfile

import numpy as np
import pandas as pd


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = REPO_ROOT / "HBV-Cryo" / "\u7387\u5b9a\u6838\u5fc3.py"
STUDIO_PATH = REPO_ROOT / "HBV-Studio"
if str(STUDIO_PATH) not in sys.path:
    sys.path.insert(0, str(STUDIO_PATH))


def load_core():
    spec = importlib.util.spec_from_file_location("hbv_core_flood_event_check", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    core = load_core()
    import profile_runner

    core.TIME_STEP_HOURS = 24.0

    dates = pd.date_range("2020-07-01", periods=12, freq="D")
    obs = np.array([20, 30, 55, 120, 260, 420, 300, 180, 100, 60, 40, 30], dtype=float)
    sim = np.array([18, 28, 50, 100, 220, 360, 430, 260, 150, 80, 48, 33], dtype=float)
    config = {
        "\u542f\u7528": True,
        "\u4f5c\u4e3a\u76ee\u6807\u51fd\u6570": True,
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
    assert profile_runner.resolve_objective_mode(
        {"\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": config},
        None,
        profile_runner.PROFILE_DAILY,
    ) == profile_runner.OBJECTIVE_MODE_FLOOD_EVENT
    diagnostic_config = dict(config)
    diagnostic_config.pop("\u4f5c\u4e3a\u76ee\u6807\u51fd\u6570")
    assert profile_runner.resolve_objective_mode(
        {"\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": diagnostic_config},
        None,
        profile_runner.PROFILE_DAILY,
    ) == profile_runner.OBJECTIVE_MODE_MULTI

    diagnostic_summary = core.compute_flood_event_evaluation(
        dates,
        obs,
        sim,
        diagnostic_config,
        evaluation_basis="q_total",
    )
    assert diagnostic_summary["objective_enabled"] is False
    assert diagnostic_summary["diagnostic_only"] is True
    assert diagnostic_summary["events"][0]["used_in_objective"] is False
    original_objective_mode = core.OBJECTIVE_MODE_SELECTED
    try:
        core.OBJECTIVE_MODE_SELECTED = core.FLOOD_EVENT_OBJECTIVE_FAMILY
        explicit_mode_summary = core.compute_flood_event_evaluation(
            dates,
            obs,
            sim,
            diagnostic_config,
            evaluation_basis="q_total",
        )
        assert explicit_mode_summary["objective_enabled"] is True
        assert explicit_mode_summary["events"][0]["used_in_objective"] is True
    finally:
        core.OBJECTIVE_MODE_SELECTED = original_objective_mode

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
    assert math.isfinite(event["high_flow_kge"])
    assert math.isfinite(event["diagnostic_objective"]["score"])
    assert event["used_in_objective"] is True

    metrics = {
        "nse_cal": 0.5,
        "nse_val": 0.4,
        "log_nse_cal": 0.45,
        "log_nse_val": 0.35,
        "pbias_cal": 5.0,
        "pbias_val": 6.0,
    }
    core.SIM_DATES = dates
    core.Q_OBS_FULL = obs
    core.FLOOD_EVENT_CONFIG = config
    obj, terms = core.compute_flood_event_objective_terms(metrics, {"q_total": sim})
    assert math.isfinite(obj), terms
    assert terms["objective_family"] == core.FLOOD_EVENT_OBJECTIVE_FAMILY
    assert terms["valid_objective_event_count"] == 1

    with tempfile.TemporaryDirectory() as tmp:
        output_name = core.write_flood_event_outputs(tmp, summary)
        assert output_name == "flood_events.csv"
        csv_text = (pathlib.Path(tmp) / output_name).read_text(encoding="utf-8-sig")
        assert "peak_time_error_hours" in csv_text
        assert "flood_2020_07" in csv_text

    print("flood_event_evaluation_check=ok")


if __name__ == "__main__":
    main()
