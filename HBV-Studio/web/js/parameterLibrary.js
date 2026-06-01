(function () {
  function defaultEscapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function normalizeKey(value) {
    return String(value || "").trim().toLowerCase();
  }

  function finiteNumber(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function scopeLabel(scope, { short = false } = {}) {
    return normalizeKey(scope) === "global"
      ? (short ? "公共" : "公共参数库")
      : (short ? "本工作区" : "当前工作区参数集");
  }

  function renderPresetOptions(select, presets = [], placeholder = "选择参数集", helpers = {}) {
    if (!select) return;
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const presetOptions = presets.map(preset =>
      `<option value="${escapeHtml(preset.id || preset.parameter_set_id || "")}">${escapeHtml(scopeLabel(preset.scope, { short: true }))} · ${escapeHtml(preset.name || "未命名参数集")}</option>`
    ).join("");
    const current = select.value;
    select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>${presetOptions}`;
    const hasCurrent = presets.some(preset =>
      String(preset.id || "") === String(current) || String(preset.parameter_set_id || "") === String(current)
    );
    select.value = hasCurrent ? current : "";
  }

  function manualPresetDiffSummary(preset, baseline = {}, helpers = {}) {
    const params = preset && typeof preset.params === "object" ? preset.params : {};
    const baselineParams = baseline && typeof baseline === "object" ? baseline : {};
    const formatNumber = helpers.formatNumber || ((value, digits = 4) => Number(value).toFixed(digits));
    const limit = Number.isFinite(Number(helpers.limit)) && Number(helpers.limit) > 0 ? Number(helpers.limit) : 8;
    if (!preset || !Object.keys(baselineParams).length) {
      return { visible: false, diffs: [], preview: "" };
    }
    const diffs = Object.entries(params)
      .filter(([name, value]) => Number.isFinite(Number(baselineParams[name])) && Math.abs(Number(value) - Number(baselineParams[name])) > 1e-8)
      .map(([name, value]) => ({
        name,
        from: Number(baselineParams[name]),
        to: Number(value),
        delta: Number(value) - Number(baselineParams[name]),
      }))
      .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
    const preview = diffs.slice(0, limit).map(item =>
      `${item.name}: ${formatNumber(item.from, 4)} -> ${formatNumber(item.to, 4)} (${item.delta > 0 ? "+" : ""}${formatNumber(item.delta, 4)})`
    ).join("; ");
    return { visible: true, diffs, preview };
  }

  function manualPresetCompareSummary(options = {}, helpers = {}) {
    const label = String(options.label || "").trim();
    const compareMetrics = options.compareMetrics || null;
    if (!compareMetrics || !label) {
      return { visible: false, statusClass: "", lines: [], deltaCalibration: null, deltaValidation: null };
    }
    const baseCalibration = options.baseCalibration || {};
    const baseValidation = options.baseValidation || {};
    const title = helpers.title || (value => String(value || ""));
    const metricSummary = helpers.metricSummary || ((metricLabel, currentValue) => `${metricLabel}: ${currentValue}`);
    const adjustedNote = helpers.adjustedNote || (() => "");
    const calibrationLabel = helpers.calibrationLabel || "calibration";
    const validationLabel = helpers.validationLabel || "validation";
    const cmpCal = finiteNumber(compareMetrics.nse_cal);
    const cmpVal = finiteNumber(compareMetrics.nse_val);
    const baseCal = finiteNumber(baseCalibration.nse);
    const baseVal = finiteNumber(baseValidation.nse);
    const deltaCalibration = (cmpCal !== null && baseCal !== null) ? (cmpCal - baseCal) : null;
    const deltaValidation = (cmpVal !== null && baseVal !== null) ? (cmpVal - baseVal) : null;
    let statusClass = "";
    if (deltaCalibration !== null) statusClass = deltaCalibration >= 0 ? "status-ok" : "status-warn";
    else if (deltaValidation !== null) statusClass = deltaValidation >= 0 ? "status-ok" : "status-warn";
    const lines = [
      title(label),
      metricSummary(calibrationLabel, compareMetrics.nse_cal, baseCalibration.nse),
      metricSummary(validationLabel, compareMetrics.nse_val, baseValidation.nse),
      options.adjusted ? adjustedNote() : "",
    ].filter(Boolean);
    return { visible: true, statusClass, lines, deltaCalibration, deltaValidation };
  }

  function findPresetById(presets = [], presetId = "") {
    const target = String(presetId || "").trim();
    if (!target || !Array.isArray(presets)) return null;
    return presets.find(preset =>
      String(preset?.id || "").trim() === target || String(preset?.parameter_set_id || "").trim() === target
    ) || null;
  }

  function manualPresetListPath(configPath = "", calibrationProfile = "", scope = "all") {
    return `/api/manual-presets?config_path=${encodeURIComponent(String(configPath || "").trim())}&calibration_profile=${encodeURIComponent(String(calibrationProfile || "").trim())}&scope=${encodeURIComponent(String(scope || "all").trim())}`;
  }

  function shouldClearManualPresetComparison(currentPreset = null, comparePresetId = "") {
    const compareId = String(comparePresetId || "").trim();
    if (!compareId) return false;
    const currentId = String(currentPreset?.id || currentPreset?.parameter_set_id || "").trim();
    return currentId !== compareId;
  }

  function manualPresetControlState(options = {}) {
    const enabled = Boolean(options.editable && options.configPath);
    const hasPreset = Boolean(options.preset);
    const hasCompare = Boolean(options.compareSeries || options.compareMetrics);
    return {
      baseEnabled: enabled,
      presetActionEnabled: enabled && hasPreset,
      clearCompareEnabled: hasCompare,
    };
  }

  function manualPresetSavePayload(options = {}) {
    const runData = options.runData || {};
    const metadata = runData.metadata || {};
    const dataSources = metadata.data_sources || {};
    return {
      config_path: String(options.configPath || "").trim(),
      scope: options.scope || "workspace",
      run_path: runData.run?.path || "",
      calibration_profile: metadata.calibration_profile || options.workspaceProfile || "daily",
      objective_mode: options.objectiveMode || "daily_unified_professional_v1",
      param_bounds_profile: metadata.param_bounds_profile
        || metadata.parameter_profile?.bounds_profile
        || options.paramBoundsProfile
        || "qtp_alpine_default",
      prec_source: normalizeKey(
        dataSources.runtime_prec_source
        || dataSources.prec_source
        || dataSources.configured_precip_source
        || options.runtimePrecipSource
        || "era5"
      ),
      glacier_mode: dataSources.glacier_mode || options.glacierMode || "inline",
      name: String(options.name || "").trim(),
      params: options.params || {},
    };
  }

  function manualPresetDeletePayload(configPath = "", preset = {}) {
    return {
      config_path: String(configPath || "").trim(),
      preset_id: String(preset?.id || preset?.parameter_set_id || "").trim(),
      scope: preset?.scope || "workspace",
    };
  }

  function manualPresetAppliedParams(currentParams = {}, originalParams = {}, preset = {}) {
    const params = preset && typeof preset.params === "object" ? preset.params : {};
    const baseParams = currentParams && typeof currentParams === "object" ? currentParams : {};
    const originals = originalParams && typeof originalParams === "object" ? originalParams : {};
    const applied = Object.entries(params).map(([name, value]) => ({
      name,
      value,
      changed: Math.abs(Number(value) - Number(originals[name])) > 1e-8,
    }));
    return {
      params: { ...baseParams, ...params },
      applied,
    };
  }

  function manualContextWarning(preset, current = {}, helpers = {}) {
    if (!preset) return "";
    const objectiveLabel = helpers.objectiveLabel || (value => value || "未记录");
    const precipSourceLabel = helpers.precipSourceLabel || (value => value || "未记录");
    const boundsLabel = helpers.boundsLabel || (value => value || "未记录");
    const warnings = [];
    const presetObjective = normalizeKey(preset.objective_mode);
    const currentObjective = normalizeKey(current.objective_mode);
    if (presetObjective && currentObjective && presetObjective !== currentObjective) {
      warnings.push(`目标函数模式不同（参数集 ${objectiveLabel(presetObjective)}，当前 ${objectiveLabel(currentObjective)}）`);
    }
    const presetPrecip = normalizeKey(preset.prec_source || preset.meteo_source);
    const currentPrecip = normalizeKey(current.prec_source);
    if (presetPrecip && currentPrecip && presetPrecip !== currentPrecip) {
      warnings.push(`降水驱动不同（参数集 ${precipSourceLabel(presetPrecip)}，当前 ${precipSourceLabel(currentPrecip)}）`);
    }
    const presetGlacier = normalizeKey(preset.glacier_mode);
    const currentGlacier = normalizeKey(current.glacier_mode);
    if (presetGlacier && currentGlacier && presetGlacier !== currentGlacier) {
      warnings.push(`冰川模式不同（参数集 ${presetGlacier}，当前 ${currentGlacier}）`);
    }
    const presetBounds = normalizeKey(preset.param_bounds_profile);
    const currentBounds = normalizeKey(current.param_bounds_profile);
    if (presetBounds && currentBounds && presetBounds !== currentBounds) {
      warnings.push(`参数范围不同（参数集 ${boundsLabel(presetBounds)}，当前 ${boundsLabel(currentBounds)}）`);
    }
    return warnings.length ? `注意：${warnings.join("；")}。` : "";
  }

  function taskContextWarnings(preset, current = {}, helpers = {}) {
    if (!preset) return [];
    const ctx = preset.context || {};
    const profileLabel = helpers.profileLabel || (value => value || "未记录");
    const objectiveLabel = helpers.objectiveLabel || (value => value || "未记录");
    const precipSourceLabel = helpers.precipSourceLabel || (value => value || "未记录");
    const stationPrecipModeLabel = helpers.stationPrecipModeLabel || (value => value || "未记录");
    const timeBasisLabel = helpers.timeBasisLabel || (value => value || "未记录");
    const formatNumber = helpers.formatNumber || ((value, digits = 0) => Number(value).toFixed(digits));
    const boundsLabels = helpers.paramBoundsProfileLabels || {};
    const warnings = [];
    const presetProfile = normalizeKey(preset.calibration_profile || ctx.calibration_profile);
    if (presetProfile && current.profile && presetProfile !== normalizeKey(current.profile)) {
      warnings.push(`时间尺度不同（参数集 ${profileLabel(presetProfile)}，当前 ${profileLabel(current.profile)}）`);
    }
    const presetStep = Number(ctx.time_step_hours || preset.time_step_hours || 0);
    const currentStep = Number(current.time_step_hours || 0);
    if (Number.isFinite(presetStep) && presetStep > 0 && Number.isFinite(currentStep) && currentStep > 0 && Math.abs(presetStep - currentStep) > 0.01) {
      warnings.push(`时间步长不同（参数集 ${formatNumber(presetStep, 0)} 小时，当前 ${formatNumber(currentStep, 0)} 小时）`);
    }
    const presetObjective = normalizeKey(preset.objective_mode);
    if (presetObjective && normalizeKey(current.objective_mode) && presetObjective !== normalizeKey(current.objective_mode)) {
      warnings.push(`率定目标不同（参数集 ${objectiveLabel(presetObjective)}，当前 ${objectiveLabel(current.objective_mode)}）`);
    }
    const presetPrecip = normalizeKey(preset.prec_source || preset.meteo_source);
    if (presetPrecip && normalizeKey(current.prec_source) && presetPrecip !== normalizeKey(current.prec_source)) {
      warnings.push(`降水驱动不同（参数集 ${precipSourceLabel(presetPrecip)}，当前 ${precipSourceLabel(current.prec_source)}）`);
    }
    const presetGlacier = normalizeKey(preset.glacier_mode);
    if (presetGlacier && normalizeKey(current.glacier_mode) && presetGlacier !== normalizeKey(current.glacier_mode)) {
      warnings.push(`冰川模式不同（参数集 ${presetGlacier === "off" ? "关闭" : "开启"}，当前 ${current.glacier_mode === "off" ? "关闭" : "开启"}）`);
    }
    const presetBounds = normalizeKey(preset.param_bounds_profile);
    if (presetBounds && normalizeKey(current.param_bounds_profile) && presetBounds !== normalizeKey(current.param_bounds_profile)) {
      warnings.push(`参数范围不同（参数集 ${boundsLabels[presetBounds] || presetBounds}，当前 ${boundsLabels[current.param_bounds_profile] || current.param_bounds_profile}）`);
    }
    const presetPrecipMode = normalizeKey(ctx.precipitation_mode || preset.precipitation_strategy);
    if (presetPrecipMode && normalizeKey(current.precipitation_mode) && presetPrecipMode !== normalizeKey(current.precipitation_mode)) {
      warnings.push(`降水方案不同（参数集 ${stationPrecipModeLabel(presetPrecipMode)}，当前 ${stationPrecipModeLabel(current.precipitation_mode)}）`);
    }
    const presetTimeBasis = normalizeKey(ctx.task_time_basis);
    if (presetTimeBasis && normalizeKey(current.task_time_basis) && presetTimeBasis !== normalizeKey(current.task_time_basis)) {
      warnings.push(`资料时段口径不同（参数集 ${timeBasisLabel(presetTimeBasis)}，当前 ${timeBasisLabel(current.task_time_basis)}）`);
    }
    return warnings;
  }

  function renderTaskContextHint(host, preset, current = {}, helpers = {}) {
    if (!host) return;
    if (!preset) {
      host.style.display = "none";
      host.textContent = "";
      return;
    }
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const profileLabel = helpers.profileLabel || (value => value || "未记录");
    const objectiveLabel = helpers.objectiveLabel || (value => value || "未记录");
    const precipSourceLabel = helpers.precipSourceLabel || (value => value || "未记录");
    const stationPrecipModeLabel = helpers.stationPrecipModeLabel || (value => value || "未记录");
    const warnings = taskContextWarnings(preset, current, helpers);
    const ctx = preset.context || {};
    const sourceWorkspace = ctx.workspace_name || preset.source_workspace || "未记录来源工作区";
    const currentText = [
      profileLabel(current.profile),
      objectiveLabel(current.objective_mode),
      precipSourceLabel(current.prec_source),
      stationPrecipModeLabel(current.precipitation_mode),
    ].join("，");
    host.style.display = "";
    if (warnings.length) {
      host.className = "hint-box status-warn";
      host.innerHTML = `
        <strong>${escapeHtml(scopeLabel(preset.scope))}：${escapeHtml(preset.name || "未命名参数集")}</strong><br>
        来源工作区：${escapeHtml(sourceWorkspace)}。当前率定设置：${escapeHtml(currentText)}。<br>
        注意：${warnings.map(item => escapeHtml(item)).join("；")}。可以作为初值继续试算，但建议保留适度初值搜索范围，并在结果页复核径流过程和水量偏差。
      `;
    } else {
      host.className = "hint-box status-ok";
      host.innerHTML = `
        <strong>${escapeHtml(scopeLabel(preset.scope))}：${escapeHtml(preset.name || "未命名参数集")}</strong><br>
        来源工作区：${escapeHtml(sourceWorkspace)}。参数集上下文与当前率定设置基本一致，可作为本次自动率定初值；仍建议保留适度初值搜索范围。
      `;
    }
  }

  function forecastParameterContext(run = {}, current = {}, helpers = {}) {
    const profileLabel = helpers.profileLabel || (value => value || "未记录");
    const objectiveLabel = helpers.objectiveLabel || (value => value || "未记录");
    const precipSourceLabel = helpers.precipSourceLabel || (value => value || "未记录");
    const stationPrecipModeLabel = helpers.stationPrecipModeLabel || (value => value || "未记录");
    const formatNumber = helpers.formatNumber || ((value, digits = 0) => Number(value).toFixed(digits));
    const samePath = helpers.samePath || ((a, b) => normalizeKey(a) === normalizeKey(b));
    const context = run.parameter_context || {};
    const source = Object.keys(context).length ? context : (run.source_parameter_summary || {});
    const sourceWorkspace = source.source_workspace || run.workspace_name || current.workspace_name || "未记录来源工作区";
    const sourceConfig = source.source_workspace_config || run.workspace_config || "";
    const currentConfig = current.workspace_config || "";
    const rows = [];

    const profile = source.calibration_profile || run.calibration_profile || "";
    if (profile) rows.push(["计算尺度", profileLabel(profile)]);
    const step = Number(source.time_step_hours || run.time_step_hours || run.time_config?.time_step_hours || 0);
    if (Number.isFinite(step) && step > 0) rows.push(["时间步长", `${formatNumber(step, 0)} 小时`]);
    const objective = source.objective_mode || run.effective_objective_mode || run.objective_family || run.recorded_objective_family || "";
    if (objective) rows.push(["率定目标", objectiveLabel(objective)]);
    const precip = source.prec_source || run.runtime_prec_source || run.prec_source || "";
    if (precip) rows.push(["降水驱动", precipSourceLabel(precip)]);
    const precipMode = source.precipitation_strategy || source.precipitation_mode || "";
    if (precipMode) rows.push(["降水方案", stationPrecipModeLabel(precipMode)]);
    const glacierMode = source.glacier_mode || "";
    if (glacierMode) rows.push(["冰川模式", glacierMode === "off" ? "关闭" : "开启"]);
    const paramCount = Number(source.parameter_count || run.optimized_param_count || 0);
    if (Number.isFinite(paramCount) && paramCount > 0) rows.push(["参数数量", `${formatNumber(paramCount, 0)} 项`]);

    const warnings = [];
    if (sourceConfig && currentConfig && !samePath(sourceConfig, currentConfig)) {
      warnings.push("当前打开工作区与源结果工作区不同，本次预报仍以源结果保存的参数和起报状态为准");
    }
    const status = warnings.length ? "warn" : "ok";
    const note = warnings.length
      ? `${warnings.join("；")}。公共参数集适合用于新模拟或手调起点，不在连续状态预报中单独替换源结果状态。`
      : "连续状态预报读取同一源结果中的参数和起报状态，不重新率定参数。";
    return {
      status,
      source_workspace: sourceWorkspace,
      source_workspace_config: sourceConfig,
      rows,
      warnings,
      note,
    };
  }

  window.HBVStudioParameterLibrary = {
    normalizeKey,
    scopeLabel,
    renderPresetOptions,
    manualPresetDiffSummary,
    manualPresetCompareSummary,
    findPresetById,
    manualPresetListPath,
    shouldClearManualPresetComparison,
    manualPresetControlState,
    manualPresetSavePayload,
    manualPresetDeletePayload,
    manualPresetAppliedParams,
    manualContextWarning,
    taskContextWarnings,
    renderTaskContextHint,
    forecastParameterContext,
  };
})();
