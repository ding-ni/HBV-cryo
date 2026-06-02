from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.meteo_config import (  # noqa: E402
    METEO_KEY,
    METEO_PRECIP_SOURCE_KEY,
    METEO_PRECIP_SOURCE_LEGACY_KEY,
    configured_precip_source,
    display_precip_source_label,
    display_runtime_precip_label,
    effective_precip_source,
    resolve_precip_source,
)


class MeteoConfigServiceTests(unittest.TestCase):
    def test_configured_precip_source_prefers_canonical_meteo_source(self) -> None:
        config = {
            "\u9ed8\u8ba4\u964d\u6c34\u6e90": "era5",
            METEO_KEY: {
                METEO_PRECIP_SOURCE_KEY: " CMFD ",
                METEO_PRECIP_SOURCE_LEGACY_KEY: "mswep",
            },
        }

        self.assertEqual(configured_precip_source(config), "cmfd")

    def test_configured_precip_source_keeps_top_level_source_over_stale_legacy_mswep(self) -> None:
        config = {
            "\u9ed8\u8ba4\u964d\u6c34\u6e90": "custom_tif",
            METEO_KEY: {METEO_PRECIP_SOURCE_LEGACY_KEY: "mswep"},
        }

        self.assertEqual(configured_precip_source(config), "custom_tif")

    def test_resolve_precip_source_accepts_explicit_valid_source_then_config_fallback(self) -> None:
        config = {METEO_KEY: {METEO_PRECIP_SOURCE_KEY: "bad-source"}}

        self.assertEqual(resolve_precip_source(config, " MSWEP "), "mswep")
        self.assertEqual(resolve_precip_source({METEO_KEY: {METEO_PRECIP_SOURCE_KEY: "cmfd"}}, None), "cmfd")
        self.assertEqual(resolve_precip_source(config, None), "era5")

    def test_effective_precip_source_maps_non_runtime_custom_source_to_era5(self) -> None:
        self.assertEqual(effective_precip_source("era5"), "era5")
        self.assertEqual(effective_precip_source("CMFD"), "cmfd")
        self.assertEqual(effective_precip_source("mswep"), "mswep")
        self.assertEqual(effective_precip_source("custom_tif"), "era5")
        self.assertEqual(effective_precip_source("unknown"), "era5")

    def test_display_labels_match_existing_product_text(self) -> None:
        self.assertEqual(display_precip_source_label("era5"), "ERA5 \u81ea\u52a8\u4e0b\u8f7d\u964d\u6c34")
        self.assertEqual(display_precip_source_label("custom_tif"), "\u672c\u5730\u964d\u6c34\u6805\u683c\u76ee\u5f55")
        self.assertEqual(display_precip_source_label("custom"), "custom")
        self.assertEqual(display_precip_source_label(""), "MSWEP \u683c\u70b9\u964d\u6c34")

    def test_display_runtime_precip_label_uses_custom_directory_text_only_for_custom_tif(self) -> None:
        custom_config = {METEO_KEY: {METEO_PRECIP_SOURCE_KEY: "custom_tif"}}
        cmfd_config = {METEO_KEY: {METEO_PRECIP_SOURCE_KEY: "cmfd"}}

        self.assertEqual(
            display_runtime_precip_label(custom_config),
            "\u5de5\u7a0b\u72ec\u7acb\u964d\u6c34\u76ee\u5f55\uff08\u672c\u5730\u5bfc\u5165\uff09",
        )
        self.assertEqual(display_runtime_precip_label(cmfd_config), "CMFD \u672c\u5730\u539f\u59cb\u6587\u4ef6")


if __name__ == "__main__":
    unittest.main()
