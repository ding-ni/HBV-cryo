# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from services.project_license import (
    LICENSE_EXPIRES_ON,
    evaluate_license,
    license_blocks_post,
)


class ProjectLicenseTests(unittest.TestCase):
    def test_unlimited_local_variant_never_expires(self) -> None:
        with mock.patch("services.project_license.LICENSE_MODE", "unlimited"):
            status = evaluate_license(today=date(2099, 1, 1))
            blocked, message = license_blocks_post("/api/data-prep/start", today=date(2099, 1, 1))
        self.assertTrue(status.ok)
        self.assertFalse(status.expired)
        self.assertEqual(status.expires_on, "")
        self.assertFalse(blocked)
        self.assertEqual(message, "")

    def test_expires_on_is_project_end_of_2027(self) -> None:
        self.assertEqual(LICENSE_EXPIRES_ON, date(2027, 12, 31))

    def test_valid_before_expiry(self) -> None:
        status = evaluate_license(today=date(2027, 12, 31))
        self.assertFalse(status.expired)
        self.assertTrue(status.ok)
        self.assertEqual(status.days_remaining, 0)

    def test_expired_after_expiry(self) -> None:
        status = evaluate_license(today=date(2028, 1, 1))
        self.assertTrue(status.expired)
        self.assertFalse(status.ok)
        self.assertLess(status.days_remaining, 0)

    def test_warning_window(self) -> None:
        status = evaluate_license(today=date(2027, 12, 10))
        self.assertFalse(status.expired)
        self.assertTrue(status.warning)

    def test_blocks_modeling_posts_when_expired(self) -> None:
        blocked, message = license_blocks_post("/api/calibration/start", today=date(2028, 1, 1))
        self.assertTrue(blocked)
        self.assertIn("到期", message)

        blocked_export, _ = license_blocks_post("/api/run/export-excel", today=date(2028, 1, 1))
        self.assertFalse(blocked_export)

        blocked_active, _ = license_blocks_post("/api/calibration/start", today=date(2027, 6, 1))
        self.assertFalse(blocked_active)


if __name__ == "__main__":
    unittest.main()
