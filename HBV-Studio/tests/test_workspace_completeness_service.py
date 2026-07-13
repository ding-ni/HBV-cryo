from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.workspace_completeness import (  # noqa: E402
    WorkspaceCompletenessContext,
    workspace_completeness,
)


class WorkspaceCompletenessServiceTests(unittest.TestCase):
    def test_quick_summary_defers_full_calibration_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "workspace.json"
            config_path.write_text("{}", encoding="utf-8")
            gis_dir = root / "gis"
            gis_dir.mkdir()
            for name in (
                "dem.tif",
                "flow_accumulation_masked.tif",
                "elevation_zone_low.tif",
                "elevation_zone_high.tif",
            ):
                (gis_dir / name).write_text("", encoding="utf-8")
            strict_calls = []

            def strict_validation(*args, **kwargs):
                strict_calls.append((args, kwargs))
                return {"valid": True, "missing": [], "warnings": []}

            context = WorkspaceCompletenessContext(
                resolve_any_path=lambda raw, **kwargs: Path(raw),
                read_runtime_config=lambda _path: {},
                resolve_precip_source=lambda _config, _source: "custom_tif",
                detect_object_type=lambda _config: "full_upstream_basin",
                wizard_validate_step=lambda *_args, **_kwargs: {"valid": True},
                current_profile=lambda _config: "daily",
                build_profile_paths=lambda _config, _profile: {
                    "gis_dir": str(gis_dir),
                    "aligned_temp_dir": str(root / "temp"),
                    "aligned_evap_dir": str(root / "evap"),
                },
                workspace_dem_path=lambda _gis, prefer=None: gis_dir / "dem.tif",
                configured_dem_kind=lambda _config: "1km",
                effective_precip_paths=lambda *_args, **_kwargs: ("custom_tif", str(root / "prec"), ""),
                has_matching=lambda _path: True,
                validate_workspace_fields=strict_validation,
                object_interbasin="interbasin_with_boundary",
            )

            quick = workspace_completeness(str(config_path), context, quick=True)

            self.assertEqual(strict_calls, [])
            self.assertTrue(quick["pending_validation"])
            self.assertFalse(quick["ready_for_calibration"])
            self.assertEqual(quick["next_step"], 7)
            self.assertIn(7, quick["steps_remaining"])

            full = workspace_completeness(str(config_path), context, quick=False)
            self.assertTrue(full["ready_for_calibration"])
            self.assertEqual(len(strict_calls), 1)


if __name__ == "__main__":
    unittest.main()
