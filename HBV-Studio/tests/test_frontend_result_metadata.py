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

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_component_fraction_and_ice_contribution_analysis(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/resultMetadata.js", "utf8"), context);

            const meta = context.window.HBVStudioResultMetadata;

            const report = meta.componentFractionReport({
              diagnostics: {
                component_fraction_report: {
                  rain_fraction: 0.25,
                  snow_fraction: 0.35,
                  ice_fraction: 0.40,
                  evaluation_period: "local_runoff_calibration_period",
                },
              },
            });
            const text = meta.componentFractionText(report);
            if (text !== "降雨 25.0% / 融雪 35.0% / 融冰 40.0%") {
              throw new Error(`unexpected component fraction text: ${text}`);
            }
            const basis = meta.componentFractionBasisText(report);
            if (basis !== "率定期本地径流口径，不含上游边界入流") {
              throw new Error(`unexpected basis text: ${basis}`);
            }
            const boundaryReport = meta.componentFractionReport({
              diagnostics: {
                component_fraction_report: {
                  boundary_inflow_fraction: 0.68,
                  local_runoff_fraction: 0.32,
                  local_rain_fraction: 0.775,
                  local_snow_fraction: 0.003,
                  local_ice_fraction: 0.222,
                  evaluation_period: "total_runoff_calibration_period",
                },
              },
            });
            const boundaryText = meta.componentFractionText(boundaryReport);
            if (boundaryText !== "边界 68.0% / 区间 32.0%") {
              throw new Error(`unexpected boundary component text: ${boundaryText}`);
            }
            const boundaryBasis = meta.componentFractionBasisText(boundaryReport);
            if (!boundaryBasis.includes("区间本地产流内部：降雨77.5% / 融雪0.3% / 融冰22.2%")) {
              throw new Error(`unexpected boundary basis text: ${boundaryBasis}`);
            }
            if (meta.componentFractionText({}) !== "未记录") {
              throw new Error("empty component fraction should be unrecorded");
            }

            const fallbackGlacierReport = meta.glacierFractionReport({
              optional_modules: { glacier: { fraction_report: { result: { f_ice: 0.18 } } } },
            });
            if (meta.glacierFractionValue(fallbackGlacierReport) !== 0.18) {
              throw new Error("glacier fraction fallback value mismatch");
            }

            const analysis = meta.analyzeIceContribution({
              metadata: {
                optional_modules: { glacier: { enabled: true } },
                diagnostics: { glacier_fraction_report: { f_ice: 0.22, window: [0.10, 0.20] } },
                objective_terms: { cryo_consistency: { ice_dominance_guard: { penalty: 0.3 } } },
              },
              series: {
                q_ice: [1, 2, null, "bad"],
                q_total: [10, 10],
                q_local: [5, 5],
                q_rain: [3, 3],
                q_snow: [2, 2],
              },
            });
            if (analysis.state !== "valid_q_ice" || analysis.qIce.sum !== 3 || analysis.qIce.nonzero !== 2) {
              throw new Error(`unexpected valid analysis: ${JSON.stringify(analysis)}`);
            }
            if (analysis.qIceToTotal !== 0.15 || analysis.qIceToLocal !== 0.3 || analysis.guardUpper !== 0.35) {
              throw new Error(`unexpected ratios or guard: ${JSON.stringify(analysis)}`);
            }
            const detail = meta.iceContributionDetailText(analysis);
            if (detail !== "降雨产流占模拟总流量 30.0% · 融雪径流占模拟总流量 20.0% · 裸冰融化占模拟总流量 15.0%") {
              throw new Error(`unexpected detail text: ${detail}`);
            }

            const missing = meta.analyzeIceContribution({
              metadata: { optional_modules: { glacier: { enabled: true } } },
              series: {},
            });
            if (missing.state !== "missing_q_ice" || !missing.message.includes("缺少裸冰融化流量")) {
              throw new Error(`unexpected missing q_ice state: ${JSON.stringify(missing)}`);
            }
            const noGlacier = meta.analyzeIceContribution({ metadata: {}, series: { q_ice: [1] } });
            if (noGlacier.enabled || noGlacier.state !== "not_applicable_no_glacier") {
              throw new Error(`unexpected no-glacier state: ${JSON.stringify(noGlacier)}`);
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
