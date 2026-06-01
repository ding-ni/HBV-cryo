import json
import sys
import tempfile
import unittest
import re
from pathlib import Path
from unittest import mock

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import build_portable_bundle as portable  # noqa: E402
import build_windows_installer as installer  # noqa: E402


class PackagingSurfaceTests(unittest.TestCase):
    def test_services_directory_is_collected_by_packaging_surfaces(self) -> None:
        self.assertIn("services", portable.STUDIO_DIRS)
        self.assertIn("services", installer.portable.STUDIO_DIRS)

    def test_service_modules_survive_packaging_copy_filter(self) -> None:
        services_src = STUDIO_DIR / "services"
        expected_modules = sorted(path.name for path in services_src.glob("*.py"))

        with tempfile.TemporaryDirectory() as tmp:
            services_dst = Path(tmp) / "services"
            portable.copy_tree(services_src, services_dst)
            copied_modules = sorted(path.name for path in services_dst.glob("*.py"))

        self.assertIn("api_routes.py", copied_modules)
        self.assertEqual(copied_modules, expected_modules)

    def test_frontend_js_modules_survive_packaging_copy_filter(self) -> None:
        web_src = STUDIO_DIR / "web"
        index_html = (web_src / "index.html").read_text(encoding="utf-8")
        js_scripts = [
            item.removeprefix("./")
            for item in re.findall(r'<script\s+src="([^"]+)"', index_html)
            if item.startswith("./js/")
        ]

        with tempfile.TemporaryDirectory() as tmp:
            web_dst = Path(tmp) / "web"
            portable.copy_tree(web_src, web_dst)

            for script in js_scripts:
                self.assertTrue((web_dst / script).is_file(), script)

    def test_p2_map_template_assets_survive_portable_copy_filter(self) -> None:
        templates_src = STUDIO_DIR / "templates"

        with tempfile.TemporaryDirectory() as tmp:
            templates_dst = Path(tmp) / "templates"
            portable.copy_tree(templates_src, templates_dst)

            for relative in (
                Path("assets") / "tuotuohe" / "tuotuohe_basin.shp",
                Path("assets") / "tuotuohe" / "glacier.shp",
            ):
                self.assertTrue((templates_dst / relative).is_file(), str(relative))

    def test_portable_workspace_configs_are_packaged_with_rebased_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_gui_root = Path(tmp) / "HBV-Studio"
            portable.write_portable_workspace(bundle_gui_root)

            packaged = bundle_gui_root / "workspaces" / "tuotuohe_test.json"
            self.assertTrue(packaged.is_file())
            config = json.loads(packaged.read_text(encoding="utf-8"))
            serialized = json.dumps(config, ensure_ascii=False)

        self.assertIn("__PROJECT_ROOT__", serialized)
        self.assertIn("__GUI_ROOT__", serialized)
        self.assertNotIn(str(portable.PROJECT_ROOT.resolve(strict=False)), serialized)
        self.assertNotIn(str(portable.GUI_ROOT.resolve(strict=False)), serialized)

    def test_portable_runtime_data_copy_keeps_geo_preview_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = root / "project"
            bundle_root = root / "bundle"
            workspace_name = "map_workspace"
            data_root = portable.runtime_workspace_root(project_root, workspace_name) / "data"
            gis_root = data_root / "gis"
            gis_root.mkdir(parents=True)
            observed_root = data_root / "observed"
            observed_root.mkdir(parents=True)

            for name in (
                "dem_1km.tif",
                "elevation_zone_low.tif",
                "glacier_mask.tif",
                "tuotuohe_basin.shp",
            ):
                (gis_root / name).write_bytes(b"map-resource")
            (observed_root / "discharge_tuotuohe.csv").write_text("date,Q\n", encoding="utf-8")

            with (
                mock.patch.object(portable, "PROJECT_ROOT", project_root),
                mock.patch.object(portable, "WORKSPACE_NAME", workspace_name),
                mock.patch.object(portable, "FALLBACK_TEMPLATE_NAME", workspace_name),
            ):
                portable._copy_bundle_runtime_data(bundle_root)

            copied_files = {path.name for path in bundle_root.rglob("*") if path.is_file()}

        for name in (
            "dem_1km.tif",
            "elevation_zone_low.tif",
            "glacier_mask.tif",
            "tuotuohe_basin.shp",
            "discharge_tuotuohe.csv",
        ):
            self.assertIn(name, copied_files)


if __name__ == "__main__":
    unittest.main()
