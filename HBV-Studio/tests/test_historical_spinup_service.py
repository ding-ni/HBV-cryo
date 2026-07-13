from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.historical_spinup import (  # noqa: E402
    apply_monthly_transition,
    build_monthly_transition_factors,
    calculate_fao56_daily_pet,
    daily_values_from_next_midnight_accumulation,
)


class HistoricalSpinupServiceTests(unittest.TestCase):
    def test_daily_accumulation_requires_and_uses_next_midnight(self) -> None:
        times = pd.date_range("2024-12-30", "2025-01-01", freq="6h")
        values = np.arange(len(times), dtype="float64")[:, None]

        daily, dates = daily_values_from_next_midnight_accumulation(
            values,
            times,
            start="2024-12-30",
            end="2024-12-31",
        )

        self.assertEqual(dates.tolist(), [pd.Timestamp("2024-12-30"), pd.Timestamp("2024-12-31")])
        np.testing.assert_allclose(daily[:, 0], [4.0, 8.0])

        with self.assertRaisesRegex(ValueError, "next-day 00:00 boundary"):
            daily_values_from_next_midnight_accumulation(
                values[:-1],
                times[:-1],
                start="2024-12-30",
                end="2024-12-31",
            )

    def test_monthly_transition_conserves_basin_month_total(self) -> None:
        dates = pd.date_range("2025-01-01", "2025-12-31", freq="1D")
        era5 = np.vstack(
            [
                np.full(len(dates), 1.0, dtype="float64"),
                np.full(len(dates), 2.0, dtype="float64"),
            ]
        )
        v2 = era5.copy()
        v2[0, :] *= 0.5
        v2[1, :] *= 1.5
        weights = np.asarray([0.25, 0.75], dtype="float64")

        factors, report = build_monthly_transition_factors(era5, v2, dates, weights)
        corrected = apply_monthly_transition(era5, dates, factors)

        for month in range(1, 13):
            mask = dates.month == month
            actual = float(np.sum(np.sum(corrected[:, mask], axis=1) * weights))
            expected = float(np.sum(np.sum(v2[:, mask], axis=1) * weights))
            self.assertAlmostEqual(actual, expected, delta=5e-5)
        self.assertLess(report["maximum_abs_reconstructed_basin_pbias_percent"], 1e-4)
        self.assertTrue(report["uses_single_reference_year"])

    def test_monthly_transition_allows_basin_ratio_below_station_factor_floor(self) -> None:
        dates = pd.date_range("2025-01-01", "2025-12-31", freq="1D")
        era5 = np.full((2, len(dates)), 10.0, dtype="float64")
        v2 = np.full((2, len(dates)), 0.1, dtype="float64")
        weights = np.asarray([0.5, 0.5], dtype="float64")

        factors, report = build_monthly_transition_factors(era5, v2, dates, weights)
        corrected = apply_monthly_transition(era5, dates, factors)

        self.assertLess(float(np.max(factors)), 0.2)
        self.assertAlmostEqual(float(np.mean(corrected)), 0.1, delta=1e-6)
        self.assertLess(report["maximum_abs_reconstructed_basin_pbias_percent"], 1e-4)

    def test_fao56_pet_is_nonnegative_and_cell_specific(self) -> None:
        dates = pd.date_range("2024-07-01", periods=3, freq="1D")
        shape = (2, 3)
        t_mean = np.full(shape, 10.0)
        t_min = np.full(shape, 5.0)
        t_max = np.full(shape, 15.0)
        dewpoint = np.full(shape, 2.0)
        u10 = np.full(shape, 3.0)
        v10 = np.full(shape, 1.0)
        solar = np.full(shape, 20.0)

        pet = calculate_fao56_daily_pet(
            t_mean,
            t_min,
            t_max,
            dewpoint,
            u10,
            v10,
            solar,
            np.asarray([29.0, 29.0]),
            np.asarray([3000.0, 5000.0]),
            dates,
        )

        self.assertEqual(pet.shape, shape)
        self.assertTrue(np.all(np.isfinite(pet)))
        self.assertTrue(np.all(pet >= 0.0))
        self.assertFalse(np.allclose(pet[0], pet[1]))


if __name__ == "__main__":
    unittest.main()
