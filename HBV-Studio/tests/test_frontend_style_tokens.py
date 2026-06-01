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


if __name__ == "__main__":
    unittest.main()
