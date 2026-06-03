(function () {
  function text(value, fallback = "") {
    const normalized = String(value ?? "").trim();
    return normalized || fallback;
  }

  function numberValue(value, fallback = 0) {
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric !== 0 ? numeric : fallback;
  }

  function selfCheckStartRequestState() {
    return {
      ready: true,
      requestPath: "/api/self-check/start",
      payload: {},
    };
  }

  function calibrationLoadState(model = {}) {
    const method = text(model.method, "mc_screen_de");
    const maxiter = Math.max(0, Number(model.maxiter) || 0);
    const popsize = Math.max(1, Number(model.popsize) || 1);
    const mcSamples = Math.max(0, Number(model.mcSamples ?? model.mc_samples) || 0);
    const workers = Math.max(1, Number(model.workers) || 1);
    const paramCount = Math.max(0, Number(model.paramCount ?? model.param_count) || 0);
    const population = popsize * paramCount;
    let estimated = 0;
    let label = "";
    if (method === "mc_only") {
      estimated = mcSamples;
      label = "快速筛选";
    } else if (method === "de") {
      estimated = (maxiter + 1) * population;
      label = "精细搜索";
    } else {
      estimated = mcSamples + (maxiter + 1) * population;
      label = "快速筛选 + 精细搜索";
    }
    const perWorker = workers > 0 ? estimated / workers : estimated;
    const level = estimated >= 12000 ? "heavy" : estimated >= 5000 ? "medium" : "light";
    return { method, maxiter, popsize, mcSamples, workers, population, estimated, perWorker, label, level };
  }

  function calibrationStartRequestState(model = {}) {
    const configPath = text(model.configPath ?? model.config_path);
    const quickTest = Boolean(model.quickTest ?? model.quick_test);
    return {
      ready: Boolean(configPath),
      reason: configPath ? "" : "missing-workspace",
      message: configPath ? "" : "请先选择工作区。",
      configPath,
      requestPath: "/api/calibration/start",
      payload: {
        config_path: configPath,
        calibration_mode: text(model.calibrationMode ?? model.calibration_mode, "daily"),
        objective_mode: text(model.objectiveMode ?? model.objective_mode, "daily_unified_professional_v1"),
        prec_source: text(model.precipSource ?? model.prec_source, "era5"),
        glacier_mode: text(model.glacierMode ?? model.glacier_mode, "inline"),
        workers: numberValue(model.workers, 4),
        maxiter: numberValue(model.maxiter, 24),
        popsize: numberValue(model.popsize, 6),
        seed: numberValue(model.seed, 42),
        method: text(model.method, "de"),
        mc_samples: numberValue(model.mcSamples ?? model.mc_samples, 300),
        param_bounds_profile: text(model.paramBoundsProfile ?? model.param_bounds_profile, "qtp_alpine_default"),
        init_preset_id: text(model.initPresetId ?? model.init_preset_id),
        init_bound_shrink: numberValue(model.initBoundShrink ?? model.init_bound_shrink, 0),
        debug_days: numberValue(model.debugDays ?? model.debug_days, 0),
        quick_test: quickTest,
        quick_days: numberValue(model.quickDays ?? model.quick_days, 30),
        refine_enabled: Boolean(model.refineEnabled ?? model.refine_enabled),
        refine_maxiter: Math.max(0, numberValue(model.refineMaxiter ?? model.refine_maxiter, 0)),
      },
    };
  }

  window.HBVStudioCalibrationView = {
    calibrationLoadState,
    calibrationStartRequestState,
    selfCheckStartRequestState,
  };
})();
