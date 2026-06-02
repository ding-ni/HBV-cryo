from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.runtime_params import (  # noqa: E402
    DEFAULT_MANUAL_START_VECTOR,
    build_runtime_param_vector,
    safe_float,
    sanitize_param_values,
)


class RuntimeParamsServiceTests(unittest.TestCase):
    def test_safe_float_rejects_blank_nan_and_non_numeric_values(self) -> None:
        self.assertIsNone(safe_float(None))
        self.assertIsNone(safe_float(""))
        self.assertIsNone(safe_float("nan"))
        self.assertIsNone(safe_float(float("nan")))
        self.assertIsNone(safe_float("bad"))
        self.assertEqual(safe_float("1.25"), 1.25)

    def test_sanitize_param_values_keeps_known_hbv_parameters_only(self) -> None:
        clean = sanitize_param_values({"TT": "-1.5", "FC": 1200, "unknown": 9})

        self.assertEqual(clean, {"TT": -1.5, "FC": 1200.0})

    def test_sanitize_param_values_rejects_invalid_or_unrecognized_sets(self) -> None:
        with self.assertRaisesRegex(ValueError, "参数 TT 不是有效数字"):
            sanitize_param_values({"TT": "bad"})
        with self.assertRaisesRegex(ValueError, "没有可识别"):
            sanitize_param_values({"unknown": 1})

    def test_build_runtime_param_vector_merges_base_params_and_overrides_with_runtime_params(self) -> None:
        calls: list[str] = []

        class Module:
            param_names = ["TT", "FC", "BETA"]

            def configure_time_step(self) -> None:
                calls.append("configure")

            def default_test_vector(self) -> list[float]:
                return [1.0, 2.0, 3.0]

        vector, clean, adjusted = build_runtime_param_vector(
            Module(),
            {"FC": "500.125"},
            base_params={"TT": "-2.0"},
        )

        self.assertEqual(calls, ["configure"])
        self.assertEqual(vector, [-2.0, 500.125, 3.0])
        self.assertEqual(clean, {"TT": -2.0, "FC": 500.125, "BETA": 3.0})
        self.assertFalse(adjusted)

    def test_build_runtime_param_vector_uses_manual_defaults_when_runtime_default_is_missing(self) -> None:
        class Module:
            param_names = ["TT", "FC"]

        vector, clean, adjusted = build_runtime_param_vector(Module(), None)

        self.assertEqual(vector, DEFAULT_MANUAL_START_VECTOR[:2])
        self.assertEqual(clean, {"TT": DEFAULT_MANUAL_START_VECTOR[0], "FC": DEFAULT_MANUAL_START_VECTOR[1]})
        self.assertFalse(adjusted)

    def test_build_runtime_param_vector_reports_sanitizer_or_validator_adjustments(self) -> None:
        class Module:
            param_names = ["TT", "FC"]

            def default_test_vector(self) -> list[float]:
                return [1.0, 2.0]

            def sanitize_initial_param_vector(self, vector: list[float]) -> list[float]:
                return [vector[0], 3.0]

            def validate_parameter_vector(self, vector: list[float]) -> list[float]:
                return [round(vector[0], 1), vector[1]]

        vector, clean, adjusted = build_runtime_param_vector(Module(), {"TT": "1.234"})

        self.assertEqual(vector, [1.2, 3.0])
        self.assertEqual(clean, {"TT": 1.2, "FC": 3.0})
        self.assertTrue(adjusted)


if __name__ == "__main__":
    unittest.main()
