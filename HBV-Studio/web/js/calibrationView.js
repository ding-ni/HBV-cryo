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

  function calibrationSelfCheckGuidanceState() {
    return {
      smart: {
        text: "智能建议：系统自检只核对环境和脚本状态，不涉及率定策略。",
        className: "hint-box",
      },
      strategy: {
        text: "系统自检不会启动率定，仅核对本地运行环境。",
        className: "hint-box",
      },
      load: {
        text: "当前任务不涉及参数搜索负载。",
        className: "hint-box",
      },
    };
  }

  function calibrationQuickTestGuidanceState(model = {}) {
    const adviceHeadline = text(model.adviceHeadline ?? model.advice_headline);
    const quickDays = Math.max(1, Number(model.quickDays ?? model.quick_days) || 30);
    return {
      smart: {
        text: adviceHeadline ? `智能建议：${adviceHeadline}` : "智能建议：先完成输入完整性检查，再启动正式率定。",
        className: "hint-box",
      },
      strategy: {
        text: "输入预核算只执行限定时段前向计算，适合核对气象输入、地理数据和参数文件是否可用。",
        className: "hint-box",
      },
      load: {
        text: `当前只计算 ${quickDays} 天，不进行正式精细搜索。`,
        className: "hint-box",
      },
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

  function calibrationPlainGuideState(model = {}) {
    const kind = text(model.kind, "calibration");
    if (kind === "self_check") {
      return {
        text: "系统自检仅核对本地环境、依赖和关键脚本状态，不读取率定参数。",
        className: "hint-box",
      };
    }
    if (kind === "quick_test") {
      return {
        text: "输入预核算只执行限定时段前向计算，不做正式参数搜索，用于确认输入资料可用。",
        className: "hint-box status-ok",
      };
    }
    if (kind === "debug_calibration") {
      return {
        text: "快速试算（短窗口）会使用率定开始后的前 N 天进行搜索，仅作为参数敏感性的快速参考，不替代正式率定。",
        className: "hint-box status-ok",
      };
    }
    const method = text(model.method, "mc_screen_de");
    const objectiveMode = text(
      model.objectiveMode ?? model.objective_mode,
      text(model.currentObjectiveFamily ?? model.current_objective_family, "daily_unified_professional_v1"),
    );
    const floodEventObjectiveFamily = text(
      model.floodEventObjectiveFamily ?? model.flood_event_objective_family,
      "flood_event_calibration_v1",
    );
    const paramCount = Math.max(0, Number(model.paramCount ?? model.param_count) || 0);
    const loadInfo = model.loadInfo ?? model.load_info ?? calibrationLoadState({
      method,
      maxiter: model.maxiter,
      popsize: model.popsize,
      mcSamples: model.mcSamples ?? model.mc_samples,
      workers: model.workers,
      paramCount,
    });
    const methodText = method === "de"
      ? "当前策略直接进入精细搜索，步骤最少，但耗时较长。"
      : method === "mc_only"
        ? "当前策略仅快速筛选，用来快速看参数敏感性和候选区间。"
        : "当前策略先快速筛选，再把更好的候选送入精细搜索，是默认更稳妥的方案。";
    const objectiveText = objectiveMode === floodEventObjectiveFamily
      ? "当前评分标准为洪水事件率定；连续资料按完整时段运行并在事件窗口评分，事件资料模式按场独立预热并只要求事件内资料完整。"
      : "当前评分标准为综合水文目标函数，优先保证连续径流拟合，并兼顾冰雪融水过程。";
    return {
      text: `运行说明：快速筛选样本数表示前期候选参数组数；搜索轮数表示后续优化轮数；每轮候选数倍率=${loadInfo.popsize}，每轮样本数约为参数数 ${paramCount} × ${loadInfo.popsize} = ${loadInfo.population}。${objectiveText}${methodText}`,
      className: "hint-box",
    };
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
    calibrationPlainGuideState,
    calibrationQuickTestGuidanceState,
    calibrationSelfCheckGuidanceState,
    calibrationStartRequestState,
    selfCheckStartRequestState,
  };
})();
