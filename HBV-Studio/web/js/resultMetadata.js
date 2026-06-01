(function () {
  function defaultShortPath(value) {
    if (!value) return "—";
    return String(value).replace(/\\/g, "/").replace(/^.*\/([^/]+)$/, "$1");
  }

  function defaultFormatNumber(value, digits = 3) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return Number(value).toFixed(digits);
  }

  function defaultDataPathAlias(path, fallback = "—") {
    return defaultShortPath(path) || fallback;
  }

  function normalizePrecipSourceKey(source, fallback = "mswep") {
    const key = String(source || "").trim().toLowerCase();
    return key || fallback;
  }

  function defaultConfiguredPrecipSourceLabel(source = "era5") {
    const key = normalizePrecipSourceKey(source, "");
    if (key === "custom_tif") return "本地降水栅格目录";
    if (key === "era5") return "ERA5 自动下载降水";
    if (key === "cmfd") return "CMFD 本地原始文件";
    return "MSWEP 本地原始文件";
  }

  function defaultRuntimePrecipDirectoryLabel(source = "era5") {
    const key = normalizePrecipSourceKey(source, "");
    if (key === "custom_tif") return "工程独立降水目录（本地导入）";
    if (key === "era5") return "工程降水目录（ERA5 自动下载）";
    if (key === "cmfd") return "工程降水目录（CMFD 本地原始文件）";
    return "工程降水目录（MSWEP 本地原始文件）";
  }

  function defaultOptimizationMethodLabel(optimization = {}) {
    const explicit = String(optimization?.method_label || "").trim();
    if (explicit) return explicit;
    const method = String(optimization?.method || "").trim().toLowerCase();
    return ({
      manual_adjustment: "手调后重算",
      manual_start: "手调起点",
      mc_screen_de: "快速筛选 + 精细搜索",
      de: "精细搜索（差分进化）",
      mc_only: "仅快速筛选",
    })[method] || String(method || "未设置");
  }

  function dataCacheSummary(meta) {
    const cache = meta?.data_cache || {};
    const items = ["prec", "temp", "evap"].filter(key => cache[key]);
    if (!items.length) return "未记录";
    const exactHits = items.filter(key => cache[key]?.cache_hit && (!cache[key]?.cache_hit_type || cache[key]?.cache_hit_type === "exact")).length;
    const coveringHits = items.filter(key => cache[key]?.cache_hit && cache[key]?.cache_hit_type === "covering_slice").length;
    const hits = exactHits + coveringHits;
    if (!hits) return `已建缓存 ${items.length} 项`;
    if (coveringHits > 0) return `已复用 ${hits}/${items.length}（精确 ${exactHits} · 切片 ${coveringHits}）`;
    return `已复用 ${hits}/${items.length}`;
  }

  function glacierModuleSummary(meta) {
    const glacier = meta?.optional_modules?.glacier || {};
    if (!glacier.enabled) {
      return glacier.mask_exists === false ? "关闭（未生成冰川掩膜）" : "关闭";
    }
    return glacier.reference_available ? "开启 · 已提供参考场" : "开启";
  }

  function boundaryModuleSummary(meta) {
    return meta?.optional_modules?.boundary_inflow?.enabled ? "开启" : "关闭";
  }

  function boundaryEnabledFromMeta(meta) {
    return Boolean(
      meta?.project_object_type === "interbasin_with_boundary"
      || meta?.optional_modules?.boundary_inflow?.enabled
      || meta?.boundary_condition?.enabled
      || meta?.boundary_condition?.boundary_inflow_file
    );
  }

  function replayCompatibilityInfo(meta, helpers = {}) {
    const shortPath = helpers.shortPath || defaultShortPath;
    const replay = meta?.replay_context || {};
    const obsReplay = Boolean(replay.obs_replayed_from_source_run);
    const boundaryReplay = Boolean(replay.boundary_replayed_from_source_run);
    if (!obsReplay && !boundaryReplay) {
      return {
        value: "未启用",
        detail: "当前结果直接使用现工作区输入",
        obsReplay: false,
        boundaryReplay: false,
      };
    }
    const labels = [];
    const details = [];
    if (obsReplay) {
      labels.push("观测回放");
      details.push("观测序列来自源结果");
    }
    if (boundaryReplay) {
      labels.push("边界回放");
      details.push("上游边界沿用源结果已汇流序列");
    }
    if (replay.source_run_path) {
      details.push(`源结果 ${shortPath(replay.source_run_path)}`);
    }
    return {
      value: labels.join(" + "),
      detail: details.join("；"),
      obsReplay,
      boundaryReplay,
    };
  }

  function optimizationResultLabel(optimization) {
    const stage = String(optimization?.selected_result_stage || "").trim().toLowerCase();
    if (stage === "global") return optimization?.polish ? "精细搜索结果（含末端精修）" : "精细搜索结果";
    if (stage === "refine") return "局部精修结果";
    if (stage === "mc") return "快速筛选结果";
    return String(optimization?.selected_result_label || "").trim();
  }

  function optimizationRefineSummary(optimization) {
    const refine = optimization?.stage_stats?.refine;
    if (!refine?.requested) {
      if (optimization?.polish) return "未启用独立局部精修，仅执行全局末端精修（polish）";
      return "未启用";
    }
    if (refine?.valid) {
      const nit = Number(refine.nit || 0);
      return nit > 0 ? `已执行（${nit} 代）` : "已执行";
    }
    if (String(refine?.skipped_reason || "").trim().toLowerCase() === "global_result_invalid") {
      return "已跳过（全局阶段结果无效）";
    }
    if (refine && refine.success === false) return "执行失败";
    return "未产出有效结果";
  }

  function optimizationPolishSummary(optimization) {
    if (!optimization) return "未记录";
    if (optimization.polish) {
      return optimization.requested_polish ? "已启用（显式请求）" : "已启用（单线程自动开启）";
    }
    if (optimization.requested_polish) return "请求启用但未生效";
    return "未启用";
  }

  function optimizationSummary(meta, helpers = {}) {
    const optimizationMethodLabel = helpers.optimizationMethodLabel || defaultOptimizationMethodLabel;
    const formatNumber = helpers.formatNumber || defaultFormatNumber;
    const optimization = meta?.optimization || {};
    const parts = [optimizationMethodLabel(optimization)];
    if (Number(optimization.debug_days || 0) > 0) parts.push(`辅助计算窗口 ${optimization.debug_days} 天`);
    if (String(optimization.method || "").trim().toLowerCase() !== "de" && Number(optimization.mc_samples || 0) > 0) {
      parts.push(`随机样本 ${optimization.mc_samples}`);
    }
    if (String(optimization.method || "").trim().toLowerCase() !== "mc_only" && Number(optimization.maxiter || 0) > 0) {
      parts.push(`最大迭代 ${optimization.maxiter}`);
    }
    if (Number(optimization.workers || 0) > 0) parts.push(`线程 ${optimization.workers}`);
    if (optimizationResultLabel(optimization)) parts.push(`最终采用 ${optimizationResultLabel(optimization)}`);
    if (optimization.objective_value !== undefined && optimization.objective_value !== null) {
      parts.push(`综合评分值 ${formatNumber(optimization.objective_value, 4)}`);
    }
    if (Number(optimization.selected_stage_evaluations || 0) > 0) {
      parts.push(`最终阶段评估 ${optimization.selected_stage_evaluations}`);
    }
    const refineSummary = optimizationRefineSummary(optimization);
    if (optimization?.stage_stats?.refine?.requested) {
      parts.push(`局部精修 ${refineSummary}`);
    } else if (optimization.polish) {
      parts.push("全局末端精修（polish）");
    }
    return parts.filter(Boolean).join(" · ");
  }

  function runPrecipSummary(meta, helpers = {}) {
    const dataPathAlias = helpers.dataPathAlias || defaultDataPathAlias;
    const getConfiguredPrecipSourceLabel = helpers.getConfiguredPrecipSourceLabel || defaultConfiguredPrecipSourceLabel;
    const getRuntimePrecipDirectoryLabel = helpers.getRuntimePrecipDirectoryLabel || defaultRuntimePrecipDirectoryLabel;
    const sources = meta?.data_sources || {};
    const runtimeSource = String(sources.runtime_prec_source || sources.prec_source || sources.configured_precip_source || "").trim().toLowerCase();
    const sourceLabel = getConfiguredPrecipSourceLabel(runtimeSource || "era5");
    const directoryLabel = sources.prec_dir ? dataPathAlias(sources.prec_dir) : getRuntimePrecipDirectoryLabel(runtimeSource || "era5");
    return `${sourceLabel} · ${directoryLabel}`;
  }

  window.HBVStudioResultMetadata = {
    boundaryEnabledFromMeta,
    boundaryModuleSummary,
    dataCacheSummary,
    glacierModuleSummary,
    optimizationPolishSummary,
    optimizationRefineSummary,
    optimizationResultLabel,
    optimizationSummary,
    replayCompatibilityInfo,
    runPrecipSummary,
  };
})();
