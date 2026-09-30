from __future__ import annotations

import ast
import contextlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


PUBLIC_SOURCE = Path(__file__).resolve().parents[2] / "公共" / "公共函数.py"


class NetCDFDatasetLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        tree = ast.parse(PUBLIC_SOURCE.read_text(encoding="utf-8-sig"))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "open_netcdf_dataset_safe"
        )
        self.source = Path("观测资料") / "气温.nc"
        self.ascii_copy = Path("ascii_cache") / "temperature.nc"
        self.temp_dir = Path("ascii_cache") / "temporary_dataset"
        self.short_path = mock.Mock(return_value=None)
        self.copy_file = mock.Mock(return_value=(self.ascii_copy, self.temp_dir))
        self.cleanup = mock.Mock()
        self.dataset = mock.Mock(name="dataset")
        self.xr = types.ModuleType("xarray")
        self.xr.open_dataset = mock.Mock(return_value=self.dataset)
        namespace = {
            "contextlib": contextlib,
            "Path": Path,
            "_windows_short_path": self.short_path,
            "_copy_file_to_ascii_temp": self.copy_file,
            "shutil": types.SimpleNamespace(rmtree=self.cleanup),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(PUBLIC_SOURCE), "exec"), namespace)
        self.open_dataset = namespace["open_netcdf_dataset_safe"]
        module_patch = mock.patch.dict(sys.modules, {"xarray": self.xr})
        module_patch.start()
        self.addCleanup(module_patch.stop)

    def _use_ascii_fallback(self) -> None:
        self.xr.open_dataset.side_effect = [FileNotFoundError("Unicode path cannot be opened"), self.dataset]

    def test_original_path_success_closes_once_and_forwards_open_options(self) -> None:
        with self.open_dataset(self.source, engine="netcdf4", cache=False) as dataset:
            self.assertIs(dataset, self.dataset)
            self.dataset.close.assert_not_called()
        self.xr.open_dataset.assert_called_once_with(self.source.resolve(strict=False), engine="netcdf4", cache=False)
        self.dataset.close.assert_called_once_with()
        self.copy_file.assert_not_called()
        self.cleanup.assert_not_called()

    def test_processing_error_after_original_open_is_preserved_without_retry(self) -> None:
        error = ValueError("CRS or raster processing failed")
        with self.assertRaises(ValueError) as raised:
            with self.open_dataset(self.source):
                raise error
        self.assertIs(raised.exception, error)
        self.assertEqual(self.xr.open_dataset.call_count, 1)
        self.dataset.close.assert_called_once_with()
        self.copy_file.assert_not_called()
        self.cleanup.assert_not_called()

    def test_processing_error_after_short_path_open_does_not_try_ascii_copy(self) -> None:
        self.short_path.return_value = "short_path/temperature.nc"
        self.xr.open_dataset.side_effect = [FileNotFoundError("original path"), self.dataset]
        error = ValueError("processing failed after short path opened")
        with self.assertRaises(ValueError) as raised:
            with self.open_dataset(self.source):
                raise error
        self.assertIs(raised.exception, error)
        self.assertEqual(self.xr.open_dataset.call_count, 2)
        self.dataset.close.assert_called_once_with()
        self.copy_file.assert_not_called()
        self.cleanup.assert_not_called()

    def test_ascii_fallback_success_closes_and_cleans_temporary_directory(self) -> None:
        self._use_ascii_fallback()
        with self.open_dataset(self.source) as dataset:
            self.assertIs(dataset, self.dataset)
            self.cleanup.assert_not_called()
        self.assertEqual(self.xr.open_dataset.call_count, 2)
        self.xr.open_dataset.assert_called_with(self.ascii_copy, engine="netcdf4")
        self.dataset.close.assert_called_once_with()
        self.cleanup.assert_called_once_with(self.temp_dir, ignore_errors=True)

    def test_processing_error_after_ascii_open_keeps_original_error_and_cleans(self) -> None:
        self._use_ascii_fallback()
        error = ValueError("raster processing failed after ASCII file opened")
        with self.assertRaises(ValueError) as raised:
            with self.open_dataset(self.source):
                raise error
        self.assertIs(raised.exception, error)
        self.assertEqual(self.xr.open_dataset.call_count, 2)
        self.copy_file.assert_called_once_with(self.source.resolve(strict=False))
        self.dataset.close.assert_called_once_with()
        self.cleanup.assert_called_once_with(self.temp_dir, ignore_errors=True)

    def test_all_open_failures_report_each_path_keep_cause_and_clean_ascii_copy(self) -> None:
        self.short_path.return_value = "short_path/temperature.nc"
        last_error = OSError("ASCII file has invalid NetCDF contents")
        self.xr.open_dataset.side_effect = [FileNotFoundError("original path missing"), OSError("short path failed"), last_error]
        with self.assertRaises(RuntimeError) as raised:
            with self.open_dataset(self.source):
                self.fail("No dataset should be yielded when every open fails")
        self.assertIs(raised.exception.__cause__, last_error)
        for detail in ("无法打开 NetCDF", "original path missing", "short path failed", "invalid NetCDF contents", str(self.ascii_copy)):
            self.assertIn(detail, str(raised.exception))
        self.assertEqual(self.xr.open_dataset.call_count, 3)
        self.dataset.close.assert_not_called()
        self.cleanup.assert_called_once_with(self.temp_dir, ignore_errors=True)

    def test_ascii_copy_creation_failure_is_reported_without_yielding(self) -> None:
        self.xr.open_dataset.side_effect = FileNotFoundError("source cannot be opened")
        copy_error = OSError("Cannot create ASCII copy")
        self.copy_file.side_effect = copy_error
        with self.assertRaises(RuntimeError) as raised:
            with self.open_dataset(self.source):
                self.fail("No dataset should be yielded when copying fails")
        self.assertIs(raised.exception.__cause__, copy_error)
        self.assertIn("source cannot be opened", str(raised.exception))
        self.assertIn("Cannot create ASCII copy", str(raised.exception))
        self.assertEqual(self.xr.open_dataset.call_count, 1)
        self.dataset.close.assert_not_called()
        self.cleanup.assert_not_called()

    def test_keyboard_interrupt_after_ascii_open_closes_and_cleans_without_retry(self) -> None:
        self._use_ascii_fallback()
        with self.assertRaises(KeyboardInterrupt):
            with self.open_dataset(self.source):
                raise KeyboardInterrupt()
        self.assertEqual(self.xr.open_dataset.call_count, 2)
        self.dataset.close.assert_called_once_with()
        self.cleanup.assert_called_once_with(self.temp_dir, ignore_errors=True)

    def test_close_error_after_success_is_not_misreported_as_an_open_failure(self) -> None:
        self._use_ascii_fallback()
        close_error = OSError("Dataset close failed")
        self.dataset.close.side_effect = close_error
        with self.assertRaises(OSError) as raised:
            with self.open_dataset(self.source):
                pass
        self.assertIs(raised.exception, close_error)
        self.assertEqual(self.xr.open_dataset.call_count, 2)
        self.dataset.close.assert_called_once_with()
        self.cleanup.assert_called_once_with(self.temp_dir, ignore_errors=True)

    def test_close_error_does_not_hide_an_existing_processing_error(self) -> None:
        self._use_ascii_fallback()
        self.dataset.close.side_effect = OSError("Dataset close also failed")
        processing_error = ValueError("Primary processing failure")
        with self.assertRaises(ValueError) as raised:
            with self.open_dataset(self.source):
                raise processing_error
        self.assertIs(raised.exception, processing_error)
        self.assertEqual(self.xr.open_dataset.call_count, 2)
        self.dataset.close.assert_called_once_with()
        self.cleanup.assert_called_once_with(self.temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
