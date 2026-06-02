from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.meteo_status import (  # noqa: E402
    METEO_STATE_FILENAME,
    MeteoStateContext,
    clear_meteo_state,
    meteo_state_path,
    read_meteo_state,
    write_meteo_state,
)


class MeteoStatusServiceTests(unittest.TestCase):
    def _context(self, root: Path) -> MeteoStateContext:
        def build_profile_paths(config: dict[str, Any], profile: str) -> dict[str, Any]:
            return {"aligned_dir": root / profile / "aligned"}

        def write_json_file(path: Path, data: dict[str, Any]) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        return MeteoStateContext(
            current_profile=lambda config: str(config.get("profile", "daily")),
            build_profile_paths=build_profile_paths,
            read_json_file=lambda path: json.loads(path.read_text(encoding="utf-8")),
            write_json_file=write_json_file,
        )

    def test_meteo_state_path_uses_explicit_or_current_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)

            current_path = meteo_state_path({"profile": "hourly"}, context)
            explicit_path = meteo_state_path({"profile": "hourly"}, context, "daily")

        self.assertEqual(current_path, root / "hourly" / "aligned" / METEO_STATE_FILENAME)
        self.assertEqual(explicit_path, root / "daily" / "aligned" / METEO_STATE_FILENAME)

    def test_write_read_and_clear_meteo_state_round_trips_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            path = write_meteo_state({"profile": "daily"}, {"ok": True, "_state_path": "stale"}, context)
            data = read_meteo_state({"profile": "daily"}, context)

            clear_meteo_state({"profile": "daily"}, context)
            after_clear = read_meteo_state({"profile": "daily"}, context)

        self.assertEqual(path, root / "daily" / "aligned" / METEO_STATE_FILENAME)
        self.assertEqual(data, {"ok": True, "_state_path": str(path)})
        self.assertEqual(after_clear, {})
        self.assertFalse(path.exists())

    def test_read_meteo_state_returns_empty_for_missing_or_unreadable_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            missing = read_meteo_state({"profile": "daily"}, context)
            state_path = meteo_state_path({"profile": "daily"}, context)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{not-json", encoding="utf-8")
            broken = read_meteo_state({"profile": "daily"}, context)

        self.assertEqual(missing, {})
        self.assertEqual(broken, {})


if __name__ == "__main__":
    unittest.main()
