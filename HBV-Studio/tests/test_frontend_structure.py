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


def frontend_module_contracts(source: str) -> list[dict[str, object]]:
    match = re.search(r"const\s+frontendModuleContracts\s*=\s*\[(?P<body>.*?)\n\];", source, re.S)
    if not match:
        raise AssertionError("Missing JS object: frontendModuleContracts")
    contracts = []
    for item in re.finditer(
        r"\{\s*script:\s*\"(?P<script>[^\"]+)\",\s*global:\s*\"(?P<global>[^\"]+)\",\s*exports:\s*\[(?P<exports>.*?)\],\s*\}",
        match.group("body"),
        re.S,
    ):
        contracts.append({
            "script": item.group("script"),
            "global": item.group("global"),
            "exports": re.findall(r"\"([A-Za-z0-9_]+)\"", item.group("exports")),
        })
    if not contracts:
        raise AssertionError("No frontend module contracts found")
    return contracts


def script_sources(index_html: str) -> list[str]:
    return re.findall(r'<script\s+src="([^"]+)"', index_html)


def exported_module_members(module_source: str, global_name: str) -> set[str]:
    match = re.search(rf"window\.{re.escape(global_name)}\s*=\s*\{{(?P<body>.*?)\n\s*\}};", module_source, re.S)
    if not match:
        raise AssertionError(f"Missing frontend module export: {global_name}")
    return set(re.findall(r"^\s*([A-Za-z0-9_]+)\s*,?\s*$", match.group("body"), re.M))


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

    def test_frontend_module_contracts_match_loaded_scripts(self) -> None:
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        contracts = frontend_module_contracts(app_js)
        scripts = script_sources(index_html)

        self.assertIn("./app.js", scripts)
        app_index = scripts.index("./app.js")
        for contract in contracts:
            script = str(contract["script"])
            self.assertIn(script, scripts)
            self.assertLess(scripts.index(script), app_index, script)

    def test_frontend_module_contracts_match_actual_exports(self) -> None:
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        for contract in frontend_module_contracts(app_js):
            script_path = WEB_DIR / str(contract["script"]).removeprefix("./")
            module_source = script_path.read_text(encoding="utf-8")
            exported = exported_module_members(module_source, str(contract["global"]))
            self.assertEqual(set(contract["exports"]), exported, str(script_path))

    def test_app_uses_only_registered_frontend_module_globals(self) -> None:
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        registered = {str(contract["global"]) for contract in frontend_module_contracts(app_js)}
        referenced = set(re.findall(r"window\.(HBVStudio[A-Za-z0-9_]+)", app_js))
        self.assertTrue(referenced <= registered, referenced - registered)


if __name__ == "__main__":
    unittest.main()
