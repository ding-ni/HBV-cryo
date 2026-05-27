import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "HBV-Studio" / "profile_runner.py"


def _write_tif(path: Path, value: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(90.0, 35.0, 0.01, 0.01),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((2, 2), value, dtype=np.float32), 1)


class EventRuntimeExecutionTests(unittest.TestCase):
    def test_profile_runner_executes_independent_event_windows_and_writes_event_table(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbv_event_runtime_") as temp:
            root = Path(temp) / "event_workspace"
            gis = root / "数据" / "地理数据"
            aligned = root / "数据" / "模型输入"
            observed = root / "数据" / "观测数据" / "discharge.csv"
            results = root / "结果"
            _write_tif(gis / "flow_accumulation_masked.tif", 1.0)
            _write_tif(gis / "dem_1km.tif", 4800.0)

            events = [
                {
                    "event_id": "E202007",
                    "name": "event A",
                    "purpose": "calibration",
                    "run_start": "2020-07-01",
                    "score_start": "2020-07-03",
                    "score_end": "2020-07-05",
                    "run_end": "2020-07-06",
                    "weight": 1.0,
                },
                {
                    "event_id": "E202108",
                    "name": "event B",
                    "purpose": "validation",
                    "run_start": "2021-08-01",
                    "score_start": "2021-08-03",
                    "score_end": "2021-08-05",
                    "run_end": "2021-08-06",
                    "weight": 0.7,
                },
            ]
            dates = pd.DatetimeIndex(
                list(pd.date_range("2020-07-01", "2020-07-06", freq="D"))
                + list(pd.date_range("2021-08-01", "2021-08-06", freq="D"))
            )
            for index, day in enumerate(dates):
                token = day.strftime("%Y.%m.%d")
                _write_tif(aligned / "降水_本地导入" / f"P_{token}.tif", 3.0 + index)
                _write_tif(aligned / "气温" / f"T_{token}.tif", 4.0)
                _write_tif(aligned / "蒸散发" / f"PET_{token}.tif", 0.8)

            observed.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                {
                    "date": dates,
                    "discharge": [2.0, 2.2, 3.0, 4.0, 3.0, 2.2, 1.5, 1.8, 2.8, 3.5, 2.6, 1.9],
                }
            ).to_csv(observed, index=False)

            config = {
                "项目对象": "full_upstream_basin",
                "率定模式": "daily",
                "目标函数模式": "flood_event_calibration_v1",
                "运行目录": str(root),
                "流域名称": "event_runtime_smoke",
                "流域边界_shp": str(gis / "basin.shp"),
                "DEM_tif": str(gis / "dem_1km.tif"),
                "观测径流_csv": str(observed),
                "观测口径模式": "full_year",
                "时间步长_小时": 24,
                "时间": {
                    "预热开始": "2020-01-01",
                    "预热结束": "2020-01-02",
                    "率定开始": "2020-01-03",
                    "率定结束": "2020-01-04",
                    "验证开始": "2020-01-05",
                    "验证结束": "2021-12-31",
                },
                "任务时段模式": "event_windows",
                "事件资料模式": {"启用": True, "事件窗口资料": True, "初始条件策略": "event_warmup"},
                "洪水事件率定": {"启用": True, "事件窗口资料": True, "事件表": events},
                "气象策略": {"降水方案": "grid_only", "降水来源": "custom_tif", "降水源": "custom_tif"},
                "初始状态": {"SP": 0, "SM": 5, "UZ": 0, "LZ": 0, "WC": 0},
                "CFMAX分区阈值_m": 4900.0,
            }
            config_path = Path(temp) / "event_workspace.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--配置",
                    str(config_path),
                    "--率定模式",
                    "daily",
                    "--目标函数",
                    "flood_event_calibration_v1",
                    "--降水源",
                    "custom_tif",
                    "--冰川模式",
                    "off",
                    "--method",
                    "mc_only",
                    "--mc-samples",
                    "2",
                    "--workers",
                    "1",
                    "--maxiter",
                    "1",
                    "--popsize",
                    "2",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=180,
            )
            if proc.returncode != 0:
                self.fail(f"profile_runner failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

            run_dirs = sorted((results / "日尺度" / "运行记录").glob("hbv_cryo_*"))
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
            simulation = pd.read_csv(run_dir / "simulation.csv")
            event_metrics = pd.read_csv(run_dir / "flood_events.csv")

            self.assertTrue(metadata["event_mode"]["enabled"])
            self.assertEqual(metadata["event_mode"]["runtime_mode"], "independent_event_windows")
            self.assertFalse(metadata["event_mode"]["state_continuity_between_events"])
            self.assertFalse(metadata["initial_state"]["state_snapshot_available"])
            self.assertIn("事件窗口资料模式按场独立运行", metadata["flood_event_evaluation"]["notes"][0])
            self.assertEqual(len(simulation), 12)
            self.assertNotIn("2020-07-07", set(simulation["date"].astype(str)))
            self.assertEqual(set(event_metrics["event_id"]), {"E202007", "E202108"})
            self.assertEqual(set(["run_start", "score_start", "score_end", "run_end"]).issubset(event_metrics.columns), True)
            self.assertIn("weight", event_metrics.columns)


if __name__ == "__main__":
    unittest.main()
