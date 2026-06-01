import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
