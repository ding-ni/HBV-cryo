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

  window.HBVStudioParameterLibrary = {
    normalizeKey,
    scopeLabel,
    renderPresetOptions,
    manualContextWarning,
    taskContextWarnings,
    renderTaskContextHint,
  };
})();
