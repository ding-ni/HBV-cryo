from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.wizard_validation import wizard_step4_meteo_validation  # noqa: E402


class WizardValidationServiceTests(unittest.TestCase):
    def _context(self, root: Path) -> SimpleNamespace:
        def resolve_config_related_path(config: dict[str, object], value: object) -> Path | None:
            raw = str(value or "").strip()
            if not raw:
                return None
            path = Path(raw)
            return path if path.is_absolute() else root / path

        return SimpleNamespace(
            configured_precip_source=lambda config: str(config.get("precip_source", "era5")),
            resolve_config_related_path=resolve_config_related_path,
            meteo_key="meteo",
            meteo_precip_mode_key="precip_mode",
            meteo_temp_source_key="temp_source",
            meteo_pet_source_key="pet_source",
            meteo_station_prec_key="station_prec",
            meteo_station_meta_key="station_meta",
            meteo_custom_prec_dir_key="custom_prec_dir",
            meteo_custom_temp_dir_key="custom_temp_dir",
            meteo_custom_pet_dir_key="custom_pet_dir",
        )

    def test_step4_meteo_validation_reports_missing_station_and_custom_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "precip_source": "custom_tif",
                "meteo": {
                    "precip_mode": "grid_plus_station_bias",
                    "temp_source": "custom_tif",
                    "pet_source": "custom_tif",
                },
            }

            missing, warnings = wizard_step4_meteo_validation(config, self._context(Path(temp_dir)))

        self.assertEqual(warnings, [])
        self.assertIn("站点降水 csv", missing)
        self.assertIn("站点信息 csv", missing)
        self.assertIn("本地降水栅格目录", missing)
        self.assertIn("本地气温栅格目录", missing)
        self.assertIn("本地蒸散发栅格目录", missing)

    def test_step4_meteo_validation_accepts_existing_station_files_and_custom_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "prec").mkdir()
            (root / "temp").mkdir()
            (root / "pet").mkdir()
            (root / "station_prec.csv").write_text("date,p\n", encoding="utf-8")
            (root / "station_meta.csv").write_text("id,lon,lat\n", encoding="utf-8")
            config = {
                "precip_source": "custom_tif",
                "meteo": {
                    "precip_mode": "thiessen_station_only",
                    "temp_source": "custom_tif",
                    "pet_source": "custom_tif",
                    "station_prec": "station_prec.csv",
                    "station_meta": "station_meta.csv",
                    "custom_prec_dir": "prec",
                    "custom_temp_dir": "temp",
                    "custom_pet_dir": "pet",
                },
            }

            missing, warnings = wizard_step4_meteo_validation(config, self._context(root))

        self.assertEqual(missing, [])
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
