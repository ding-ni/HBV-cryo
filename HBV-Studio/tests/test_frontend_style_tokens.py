import re
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
STYLES_PATH = STUDIO_DIR / "web" / "styles.css"


def root_tokens(source: str) -> dict[str, str]:
    match = re.search(r":root\s*\{(?P<body>.*?)\n\}", source, re.S)
    if not match:
        raise AssertionError("Missing :root design token block")
    return dict(
        re.findall(
            r"^\s*(--[A-Za-z0-9_-]+)\s*:\s*([^;]+);",
            match.group("body"),
            re.M,
        )
    )


def rule_body(source: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}", source, re.S)
    if not match:
        raise AssertionError(f"Missing CSS rule for {selector}")
    return match.group("body")


class FrontendStyleTokenTests(unittest.TestCase):
    def test_scientific_dashboard_tokens_are_cold_neutral(self) -> None:
        styles = STYLES_PATH.read_text(encoding="utf-8")
        tokens = root_tokens(styles)

        expected = {
            "--accent": "#0e7490",
            "--accent-strong": "#155e63",
            "--accent-light": "rgba(14,116,144,0.10)",
            "--warm": "#ef4444",
            "--warm-light": "rgba(239,68,68,0.10)",
            "--bg": "#f1f5f9",
            "--panel-solid": "#ffffff",
            "--surface-muted": "#f8fafc",
            "--text": "#0f172a",
            "--muted": "#475569",
            "--line": "#e2e8f0",
            "--radius-xl": "8px",
            "--radius-lg": "8px",
            "--radius-md": "7px",
            "--radius-sm": "6px",
            "--control-height": "32px",
            "--control-height-primary": "36px",
            "--field-height": "36px",
        }

        for name, value in expected.items():
            self.assertEqual(tokens.get(name), value, name)

    def test_legacy_warm_paper_style_is_not_reintroduced(self) -> None:
        styles = STYLES_PATH.read_text(encoding="utf-8")

        legacy_fragments = [
            "#f5f1e7",
            "#fffbf5",
            "#21180d",
            "#70604a",
            "#0f766e",
            "#115e59",
            "#b45309",
            "#172026",
            "#5c6670",
            "#eef3f7",
            "#faf8f2",
            "#7a4f22",
            "rgba(15,118,110",
            "rgba(180,83,9",
            "rgba(49,65,80,0.16",
            "Georgia",
            "Noto Serif",
        ]
        for fragment in legacy_fragments:
            self.assertNotIn(fragment, styles)

        display_font = root_tokens(styles).get("--font-display", "")
        body_font = root_tokens(styles).get("--font-body", "")
        self.assertNotRegex(display_font, r"(?<!sans-)serif")
        self.assertNotRegex(body_font, r"(?<!sans-)serif")

    def test_rectangular_corner_radius_stays_instrument_panel_tight(self) -> None:
        styles = STYLES_PATH.read_text(encoding="utf-8")
        oversized = []
        for match in re.finditer(r"border-radius\s*:\s*(\d+)px", styles):
            value = int(match.group(1))
            if value > 8 and value != 999:
                oversized.append(match.group(0))

        self.assertEqual(oversized, [])

    def test_shared_controls_use_compact_height_tokens(self) -> None:
        styles = STYLES_PATH.read_text(encoding="utf-8")
        tokens = root_tokens(styles)

        self.assertEqual(tokens.get("--control-height"), "32px")
        self.assertEqual(tokens.get("--control-height-primary"), "36px")

        expected = {
            ".primary-button": [
                "min-height: var(--control-height-primary);",
                "padding: 7px 18px;",
                "font-size: 14px;",
            ],
            ".ghost-button": [
                "min-height: var(--control-height);",
                "padding: 6px 14px;",
                "font-size: 13px;",
            ],
            ".close-button": [
                "min-height: var(--control-height);",
                "padding: 5px 12px;",
            ],
            ".phase-chip": [
                "min-height: var(--control-height);",
                "padding: 5px 11px;",
            ],
        }

        for selector, declarations in expected.items():
            body = rule_body(styles, selector)
            for declaration in declarations:
                self.assertIn(declaration, body, selector)

    def test_form_fields_use_data_entry_height_tokens(self) -> None:
        styles = STYLES_PATH.read_text(encoding="utf-8")
        tokens = root_tokens(styles)

        self.assertEqual(tokens.get("--field-height"), "36px")

        field_selector = (
            'input[type="text"], input[type="number"], input[type="date"], '
            'input[type="datetime-local"], select'
        )
        field_body = rule_body(styles, field_selector)
        self.assertIn("min-height: var(--field-height);", field_body)
        self.assertIn("padding: 7px 12px;", field_body)
        self.assertIn("font-size: 14px;", field_body)

        textarea_body = rule_body(styles, "textarea")
        self.assertIn("min-height: calc(var(--field-height) * 2);", textarea_body)
        self.assertIn("resize: vertical;", textarea_body)

        browse_button_body = rule_body(styles, ".path-input .browse-button")
        self.assertIn("min-height: var(--field-height);", browse_button_body)
        self.assertIn("padding: 7px 12px;", browse_button_body)


if __name__ == "__main__":
    unittest.main()
