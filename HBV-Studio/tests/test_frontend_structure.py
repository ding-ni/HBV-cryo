import re
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = STUDIO_DIR / "web"


def js_object_keys(source: str, const_name: str) -> set[str]:
    match = re.search(rf"const\s+{re.escape(const_name)}\s*=\s*\{{(?P<body>.*?)\n\}};", source, re.S)
    if not match:
        raise AssertionError(f"Missing JS object: {const_name}")
    return set(re.findall(r"^\s*([A-Za-z0-9_]+)\s*:", match.group("body"), re.M))


class FrontendStructureTests(unittest.TestCase):
    def test_views_have_metadata_navigation_and_renderers(self) -> None:
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

        metadata_views = js_object_keys(app_js, "viewMeta")
        renderer_views = js_object_keys(app_js, "viewRenderers")
        nav_views = set(re.findall(r'data-view-target="([^"]+)"', index_html))
        section_views = set(re.findall(r'<section\s+class="view[^"]*"\s+data-view="([^"]+)"', index_html))

        self.assertEqual(metadata_views, nav_views)
        self.assertEqual(metadata_views, section_views)
        self.assertEqual(metadata_views, renderer_views)

    def test_set_view_uses_renderer_registry(self) -> None:
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        set_view = re.search(r"function\s+setView\(view\)\s*\{(?P<body>.*?)\n\}", app_js, re.S)
        self.assertIsNotNone(set_view)
        body = set_view.group("body")

        self.assertIn("renderView(view)", body)
        self.assertNotIn('view === "forecast"', body)


if __name__ == "__main__":
    unittest.main()
