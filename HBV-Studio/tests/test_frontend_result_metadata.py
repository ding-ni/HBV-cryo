import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendResultMetadataTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_cache_module_boundary_and_replay_summaries(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/resultMetadata.js", "utf8"), context);

            const meta = context.window.HBVStudioResultMetadata;
            if (!meta) throw new Error("result metadata module was not exported");

            const cache = meta.dataCacheSummary({
              data_cache: {
                prec: { cache_hit: true },
                temp: { cache_hit: true, cache_hit_type: "covering_slice" },
                evap: { cache_hit: false },
              },
            });
            if (cache !== "已复用 2/3（精确 1 · 切片 1）") {
              throw new Error(`unexpected cache summary: ${cache}`);
            }
            const built = meta.dataCacheSummary({ data_cache: { prec: {}, temp: {} } });
            if (built !== "已建缓存 2 项") throw new Error(`unexpected built summary: ${built}`);
            if (meta.dataCacheSummary({}) !== "未记录") throw new Error("empty cache should be unrecorded");

            const glacierOff = meta.glacierModuleSummary({ optional_modules: { glacier: { enabled: false, mask_exists: false } } });
            if (glacierOff !== "关闭（未生成冰川掩膜）") throw new Error(`unexpected glacier summary: ${glacierOff}`);
            const glacierOn = meta.glacierModuleSummary({ optional_modules: { glacier: { enabled: true, reference_available: true } } });
            if (glacierOn !== "开启 · 已提供参考场") throw new Error(`unexpected glacier reference summary: ${glacierOn}`);
            if (meta.boundaryModuleSummary({ optional_modules: { boundary_inflow: { enabled: true } } }) !== "开启") {
              throw new Error("boundary module should be enabled");
            }

            if (!meta.boundaryEnabledFromMeta({ project_object_type: "interbasin_with_boundary" })) {
              throw new Error("project object type should enable boundary export");
            }
            if (!meta.boundaryEnabledFromMeta({ boundary_condition: { boundary_inflow_file: "boundary.csv" } })) {
              throw new Error("boundary file should enable boundary export");
            }
            if (meta.boundaryEnabledFromMeta({ project_object_type: "full_upstream_basin" })) {
              throw new Error("plain upstream basin should not enable boundary export");
            }

            const replay = meta.replayCompatibilityInfo({
              replay_context: {
                obs_replayed_from_source_run: true,
                boundary_replayed_from_source_run: true,
                source_run_path: "C:/runs/source/run-001",
              },
            }, { shortPath: value => String(value).split("/").pop() });
            if (replay.value !== "观测回放 + 边界回放" || !replay.detail.includes("源结果 run-001")) {
              throw new Error(`unexpected replay info: ${JSON.stringify(replay)}`);
            }
            const direct = meta.replayCompatibilityInfo({});
            if (direct.value !== "未启用" || direct.obsReplay || direct.boundaryReplay) {
              throw new Error(`unexpected direct replay info: ${JSON.stringify(direct)}`);
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_optimization_and_precip_summaries(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/resultMetadata.js", "utf8"), context);

            const meta = context.window.HBVStudioResultMetadata;

            const optimization = {
              method: "mc_screen_de",
              debug_days: 30,
              mc_samples: 120,
              maxiter: 45,
              workers: 6,
              selected_result_stage: "refine",
              objective_value: 0.812345,
              selected_stage_evaluations: 88,
              stage_stats: { refine: { requested: true, valid: true, nit: 5 } },
            };
            if (meta.optimizationResultLabel({ selected_result_stage: "global", polish: true }) !== "精细搜索结果（含末端精修）") {
              throw new Error("global polish result label mismatch");
            }
            if (meta.optimizationRefineSummary(optimization) !== "已执行（5 代）") {
              throw new Error("refine summary mismatch");
            }
            const skipped = meta.optimizationRefineSummary({
              stage_stats: { refine: { requested: true, skipped_reason: "global_result_invalid" } },
            });
            if (skipped !== "已跳过（全局阶段结果无效）") throw new Error(`unexpected skipped summary: ${skipped}`);
            if (meta.optimizationPolishSummary({ polish: true, requested_polish: false }) !== "已启用（单线程自动开启）") {
              throw new Error("polish auto summary mismatch");
            }

            const summary = meta.optimizationSummary({ optimization }, {
              optimizationMethodLabel: () => "快速筛选 + 精细搜索 + 局部精修",
              formatNumber: (value, digits) => Number(value).toFixed(digits),
            });
            const expected = "快速筛选 + 精细搜索 + 局部精修 · 辅助计算窗口 30 天 · 随机样本 120 · 最大迭代 45 · 线程 6 · 最终采用 局部精修结果 · 综合评分值 0.8123 · 最终阶段评估 88 · 局部精修 已执行（5 代）";
            if (summary !== expected) throw new Error(`unexpected optimization summary: ${summary}`);

            const precip = meta.runPrecipSummary({
              data_sources: { runtime_prec_source: "cmfd", prec_dir: "C:/data/cmfd" },
            }, {
              dataPathAlias: path => `目录:${String(path).split("/").pop()}`,
              getConfiguredPrecipSourceLabel: source => source === "cmfd" ? "CMFD 本地原始文件" : source,
              getRuntimePrecipDirectoryLabel: source => `运行目录:${source}`,
            });
            if (precip !== "CMFD 本地原始文件 · 目录:cmfd") {
              throw new Error(`unexpected precip summary: ${precip}`);
            }
            const fallbackPrecip = meta.runPrecipSummary({ data_sources: { configured_precip_source: "era5" } });
            if (fallbackPrecip !== "ERA5 自动下载降水 · 工程降水目录（ERA5 自动下载）") {
              throw new Error(`unexpected fallback precip summary: ${fallbackPrecip}`);
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
