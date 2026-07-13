import json
import subprocess
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
    def test_installer_manifest_parses_git_left_right_counts_in_correct_direction(self) -> None:
        self.assertEqual(installer.parse_ahead_behind_counts("3\t2"), (3, 2))
        self.assertEqual(installer.parse_ahead_behind_counts("invalid"), (None, None))

    def test_portable_builder_help_does_not_start_a_build(self) -> None:
        result = subprocess.run(
            [sys.executable, str(STUDIO_DIR / "build_portable_bundle.py"), "--help"],
            cwd=str(STUDIO_DIR.parent),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Build the portable HBVStudio demo bundle", result.stdout)

    def test_runtime_entrypoint_scripts_are_collected_by_packaging_surfaces(self) -> None:
        expected_scripts = (
            "studio_service.py",
            "create_hourly_workspace.py",
            "forecast_run.py",
            "profile_runner.py",
            "initial_state_sensitivity_runner.py",
            "forward_run.py",
            "precipitation_strategy_runner.py",
        )

        for script in expected_scripts:
            self.assertTrue((STUDIO_DIR / script).is_file(), script)
            self.assertIn(script, portable.STUDIO_FILES)
            self.assertIn(script, installer.portable.STUDIO_FILES)

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

    def test_installer_stage_collects_geo_frontend_services_and_base_layers(self) -> None:
        web_src = STUDIO_DIR / "web"
        script_sources = re.findall(r'<script\s+src="([^"]+)"', (web_src / "index.html").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = root / "project"
            gui_root = project_root / "HBV-Studio"
            bundle_root = root / "stage" / "HBVStudio"
            common_source = project_root / "公共"
            prep_source = project_root / "数据准备"
            config_source = project_root / "配置"
            dem_source_dir = project_root / "基础数据" / "DEM源"
            glacier_source_dir = project_root / "基础数据" / "冰川源" / "Second_Glacier_Inventory_China"

            for path in (
                gui_root / "services",
                gui_root / "web" / "js",
                gui_root / "templates",
                gui_root / "installer_assets",
                project_root / "HBV-Cryo",
                common_source,
                prep_source,
                config_source,
                dem_source_dir,
                glacier_source_dir,
            ):
                path.mkdir(parents=True, exist_ok=True)

            entrypoint_scripts = [
                "studio_service.py",
                "create_hourly_workspace.py",
                "forecast_run.py",
                "profile_runner.py",
                "initial_state_sensitivity_runner.py",
                "forward_run.py",
                "precipitation_strategy_runner.py",
            ]
            for script in entrypoint_scripts:
                (gui_root / script).write_text(f"# {script}\n", encoding="utf-8")
            (gui_root / "services" / "geo_overview.py").write_text("# geo\n", encoding="utf-8")
            (gui_root / "web" / "index.html").write_text(
                "\n".join(f'<script src="{source}"></script>' for source in script_sources),
                encoding="utf-8",
            )
            for source in script_sources:
                relative = Path(source.removeprefix("./"))
                if source.startswith("./") and relative.parts:
                    target = gui_root / "web" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"// packaged script: {source}\n", encoding="utf-8")
            (dem_source_dir / installer.DEFAULT_DEM_NAME).write_bytes(b"dem")
            for suffix in (".shp", ".dbf", ".shx", ".prj"):
                (glacier_source_dir / f"glacier{suffix}").write_bytes(b"glacier")
            (project_root / "系统自检.py").write_text("# check\n", encoding="utf-8")

            with (
                mock.patch.object(installer, "PROJECT_ROOT", project_root),
                mock.patch.object(installer, "GUI_ROOT", gui_root),
                mock.patch.object(installer, "COMMON_SOURCE", common_source),
                mock.patch.object(installer, "PREP_SOURCE", prep_source),
                mock.patch.object(installer, "CONFIG_SOURCE", config_source),
                mock.patch.object(installer, "DEM_SOURCE_DIR", dem_source_dir),
                mock.patch.object(installer, "GLACIER_SOURCE_DIR", glacier_source_dir),
                mock.patch.object(installer.portable, "STUDIO_FILES", entrypoint_scripts),
                mock.patch.object(installer.portable, "STUDIO_DIRS", ["services"]),
            ):
                installer.copy_installer_files(bundle_root)

            expected_files = [
                bundle_root / "HBV-Studio" / "create_hourly_workspace.py",
                bundle_root / "HBV-Studio" / "forecast_run.py",
                bundle_root / "HBV-Studio" / "services" / "geo_overview.py",
                bundle_root / installer.CN_BASE_DATA / installer.CN_DEM_DIR / installer.DEFAULT_DEM_NAME,
                bundle_root / installer.CN_BASE_DATA / "冰川源" / glacier_source_dir.name / "glacier.shp",
            ]
            expected_files.extend(
                bundle_root / "HBV-Studio" / "web" / Path(source.removeprefix("./"))
                for source in script_sources
                if source.startswith("./")
            )

            for path in expected_files:
                self.assertTrue(path.is_file(), str(path))


if __name__ == "__main__":
    unittest.main()
