from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.event_config import (  # noqa: E402
    EVENT_PURPOSE_ALIASES,
    TIME_BASIS_CONTINUOUS,
    TIME_BASIS_EVENT_WINDOWS,
    TIME_BASIS_FORECAST_WINDOW,
    TIME_BASIS_LABELS,
    event_initial_state_policy_summary,
    flood_event_raw_config,
    normalize_event_initial_state_policy,
    task_time_basis,
    truthy_config,
)


class EventConfigServiceTests(unittest.TestCase):
    def test_truthy_config_accepts_english_and_chinese_flags(self) -> None:
        self.assertTrue(truthy_config(True))
        self.assertTrue(truthy_config("yes"))
        self.assertTrue(truthy_config("\u542f\u7528"))
        self.assertFalse(truthy_config("off", default=True))
        self.assertFalse(truthy_config("\u5426", default=True))
        self.assertTrue(truthy_config("unknown", default=True))

    def test_flood_event_raw_config_merges_legacy_event_mode_and_top_level_events(self) -> None:
        events = [{"event_id": "E1"}]
        config = {
            "\u4e8b\u4ef6\u8d44\u6599\u6a21\u5f0f": {"\u4e8b\u4ef6\u7a97\u53e3\u8d44\u6599": True},
            "events": events,
        }

        raw = flood_event_raw_config(config)

        self.assertTrue(raw["\u4e8b\u4ef6\u7a97\u53e3\u8d44\u6599"])
        self.assertEqual(raw["events"], events)
        self.assertEqual(
            flood_event_raw_config({"\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": events}),
            {"\u542f\u7528": True, "\u4e8b\u4ef6\u8868": events},
        )

    def test_event_initial_state_policy_aliases_and_unknown_summary(self) -> None:
        self.assertEqual(normalize_event_initial_state_policy("\u4e8b\u4ef6\u95f4\u8fde\u7eed"), "continuous_state")
        self.assertEqual(normalize_event_initial_state_policy(""), "event_warmup")
        self.assertEqual(normalize_event_initial_state_policy("custom_policy"), "custom_policy")

        fixed = event_initial_state_policy_summary("\u56fa\u5b9a\u521d\u503c")
        unknown = event_initial_state_policy_summary("custom_policy")

        self.assertEqual(fixed["policy"], "fixed_initial")
        self.assertEqual(fixed["label"], "\u56fa\u5b9a\u521d\u503c")
        self.assertTrue(fixed["warning"])
        self.assertEqual(unknown["policy"], "custom_policy")
        self.assertEqual(unknown["label"], "custom_policy")

    def test_task_time_basis_prefers_context_and_explicit_aliases(self) -> None:
        self.assertEqual(task_time_basis({}, context="forecast"), TIME_BASIS_FORECAST_WINDOW)
        self.assertEqual(task_time_basis({"\u4efb\u52a1\u65f6\u6bb5\u6a21\u5f0f": "\u4e8b\u4ef6\u7a97\u53e3"}), TIME_BASIS_EVENT_WINDOWS)
        self.assertEqual(task_time_basis({"time_basis": "\u9884\u62a5"}), TIME_BASIS_FORECAST_WINDOW)
        self.assertEqual(task_time_basis({"\u8d44\u6599\u65f6\u6bb5\u6a21\u5f0f": "\u8fde\u7eed\u65f6\u6bb5"}), TIME_BASIS_CONTINUOUS)

    def test_task_time_basis_uses_enabled_event_window_data_when_no_explicit_mode(self) -> None:
        config = {
            "\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a": {
                "\u542f\u7528": True,
                "\u4e8b\u4ef6\u7a97\u53e3\u8d44\u6599": True,
                "\u4e8b\u4ef6\u8868": [{"event_id": "E1"}],
            }
        }

        self.assertEqual(task_time_basis(config), TIME_BASIS_EVENT_WINDOWS)
        self.assertEqual(task_time_basis({}), TIME_BASIS_CONTINUOUS)

    def test_public_labels_and_purpose_aliases_preserve_existing_contract(self) -> None:
        self.assertEqual(TIME_BASIS_LABELS[TIME_BASIS_EVENT_WINDOWS], "\u6d2a\u6c34\u4e8b\u4ef6\u7a97\u53e3")
        self.assertEqual(EVENT_PURPOSE_ALIASES["\u7387\u5b9a"], "calibration")
        self.assertEqual(EVENT_PURPOSE_ALIASES["\u590d\u6838"], "diagnostic")


if __name__ == "__main__":
    unittest.main()
