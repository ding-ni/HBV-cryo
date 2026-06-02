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

  function formatMetricNumber(value, digits = 4) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toFixed(digits) : "—";
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

  function manualPresetDiffView(preset, baseline = {}, options = {}, helpers = {}) {
    const summary = manualPresetDiffSummary(preset, baseline, helpers);
    if (!summary.visible) {
      return { visible: false, className: "", text: "", diffCount: 0 };
    }
    const name = preset?.name || "未命名参数集";
    const contextWarning = String(options.contextWarning || "").trim();
    const className = `hint-box ${contextWarning ? "status-warn" : ""}`.trim();
    if (!summary.diffs.length) {
      return {
        visible: true,
        className,
        text: `参数集“${name}”与当前率定参数一致。${contextWarning ? ` ${contextWarning}` : ""}`,
        diffCount: 0,
      };
    }
    const preview = summary.preview.split(" -> ").join(" → ").split("; ").join("；");
    return {
      visible: true,
      className,
      text: `参数集“${name}”与当前率定值相比有 ${summary.diffs.length} 个参数不同。${preview}${contextWarning ? ` ${contextWarning}` : ""}`,
      diffCount: summary.diffs.length,
    };
  }

  function manualPresetDiffPanelState(preset, baseline = {}, options = {}, helpers = {}) {
    const view = manualPresetDiffView(preset, baseline, options, helpers);
    return view.visible
      ? view
      : { visible: false, className: "hint-box", text: "", diffCount: 0 };
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

  function compareMetricSummary(label, currentValue, baselineValue, digits = 4) {
    const current = finiteNumber(currentValue);
    const baseline = finiteNumber(baselineValue);
    const currentText = formatMetricNumber(current, digits);
    if (current === null && baseline === null) return `${label}：${currentText}（当前结果和对比参数集都没有该指标）`;
    if (current === null) return `${label}：${currentText}（该参数集未产生该指标）`;
    if (baseline === null) return `${label}：${currentText}（当前结果无可比指标）`;
    const delta = current - baseline;
    return `${label}：${currentText}（较当前 ${delta >= 0 ? "+" : ""}${formatMetricNumber(delta, digits)}）`;
  }

  function manualPresetCompareView(options = {}, helpers = {}) {
    const summary = manualPresetCompareSummary(options, helpers);
    if (!summary.visible) {
      return { visible: false, className: "", text: "", summary };
    }
    return {
      visible: true,
      className: `hint-box ${summary.statusClass}`.trim(),
      text: summary.lines.join(" "),
      summary,
    };
  }

  function manualPresetComparePanelState(options = {}) {
    const runData = options.runData || null;
    const compareMetrics = options.compareMetrics || null;
    const compareLabel = String(options.compareLabel || "").trim();
    if (!runData || !compareMetrics || !compareLabel) {
      return { visible: false, className: "hint-box", text: "" };
    }
    const baseMeta = runData.metadata || {};
    const baseMetrics = baseMeta.metrics || {};
    const view = manualPresetCompareView(
      {
        label: compareLabel,
        compareMetrics,
        baseCalibration: baseMetrics.calibration || {},
        baseValidation: baseMetrics.validation || {},
        adjusted: options.adjusted,
      },
      {
        title: label => `当前正在对比参数集“${label}”。`,
        metricSummary: (label, currentValue, baselineValue) => `${compareMetricSummary(label, currentValue, baselineValue)}。`,
        calibrationLabel: "率定纳什效率系数",
        validationLabel: "验证纳什效率系数",
        adjustedNote: () => "该参数集在运行前已按约束自动修正。",
      },
    );
    return view.visible
      ? { visible: true, className: view.className, text: view.text, summary: view.summary }
      : { visible: false, className: "hint-box", text: "", summary: view.summary };
  }

  function manualPresetComparePendingView(preset = {}) {
    return {
      visible: true,
      className: "hint-box",
      text: `正在计算参数集“${preset?.name || "参数集"}”的对比结果...`,
    };
  }

  function manualPresetCompareErrorView(error = {}) {
    const message = error?.message || String(error || "未知错误");
    return {
      visible: true,
      className: "hint-box status-fail",
      text: `参数集对比失败：${message}`,
    };
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

  function manualPresetConfigPathFromRunData(data = null) {
    return String(data?.metadata?.workspace_config || data?.run?.workspace_config || "").trim();
  }

  function manualPresetProfileState(configPath = "", explicitProfile = "", context = {}, helpers = {}) {
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const normalizeProfile = helpers.normalizeProfile || ((value, fallback = "") => {
      const profile = normalizeKey(value);
      return profile || fallback;
    });
    const path = String(configPath || "").trim();
    const explicit = normalizeProfile(explicitProfile, "");
    if (explicit) return { path, profile: explicit, source: "explicit" };

    const runConfigPath = String(context.runConfigPath || "").trim();
    if (path && runConfigPath && samePath(path, runConfigPath)) {
      const runProfile = normalizeProfile(context.runCalibrationProfile, "");
      if (runProfile) return { path, profile: runProfile, source: "run" };
    }

    const taskConfigPath = String(context.taskConfigPath || "").trim();
    if (path && taskConfigPath && samePath(path, taskConfigPath)) {
      const workspaceProfile = normalizeProfile(context.workspaceProfile, "");
      if (workspaceProfile) return { path, profile: workspaceProfile, source: "workspace" };
    }

    return {
      path,
      profile: normalizeProfile(context.runCalibrationProfile || context.workspaceProfile, "daily"),
      source: "fallback",
    };
  }

  function taskManualPresetLoadStartState(path = "", currentConfigPath = "", helpers = {}) {
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const targetPath = String(path || "").trim();
    const changed = !samePath(targetPath, currentConfigPath);
    const statePatch = { taskManualPresetConfigPath: targetPath };
    if (!targetPath || changed) statePatch.taskManualPresets = [];
    return {
      path: targetPath,
      changed,
      shouldRequest: Boolean(targetPath),
      shouldRender: !targetPath || changed,
      statePatch,
    };
  }

  function taskManualPresetLoadSuccessState(responseData = {}) {
    const presets = Array.isArray(responseData?.presets) ? responseData.presets : [];
    return {
      presets,
      statePatch: {
        taskManualPresets: presets,
      },
    };
  }

  function taskManualPresetLoadErrorState() {
    return {
      presets: [],
      statePatch: {
        taskManualPresets: [],
      },
    };
  }

  function manualPresetTaskSyncState(configPath = "", taskConfigPath = "", context = {}, helpers = {}) {
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const sourceConfigPath = String(configPath || "").trim();
    const targetConfigPath = String(taskConfigPath || "").trim();
    const calibrationProfile = String(
      context.workspaceProfile
      || context.runCalibrationProfile
      || "daily",
    ).trim() || "daily";
    return {
      sourceConfigPath,
      targetConfigPath,
      shouldSync: Boolean(sourceConfigPath && targetConfigPath && samePath(sourceConfigPath, targetConfigPath)),
      calibrationProfile,
    };
  }

  function shouldClearManualPresetComparison(currentPreset = null, comparePresetId = "") {
    const compareId = String(comparePresetId || "").trim();
    if (!compareId) return false;
    const currentId = String(currentPreset?.id || currentPreset?.parameter_set_id || "").trim();
    return currentId !== compareId;
  }

  function manualPresetSelectionChangeState(preset = null, comparePresetId = "") {
    return {
      inputName: preset?.name || "",
      shouldClearComparison: shouldClearManualPresetComparison(preset, comparePresetId),
      clearComparisonOptions: { silent: true },
    };
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

  function manualPresetControlViewState(options = {}) {
    const controlState = manualPresetControlState(options);
    const baseSelectors = [
      "#manual-preset-name",
      "#manual-preset-scope",
      "#manual-preset-select",
      "#btn-save-manual-preset",
    ];
    const presetActionSelectors = [
      "#btn-load-manual-preset",
      "#btn-delete-manual-preset",
      "#btn-compare-manual-preset",
    ];
    return {
      ...controlState,
      controls: [
        ...baseSelectors.map(selector => ({ selector, disabled: !controlState.baseEnabled })),
        ...presetActionSelectors.map(selector => ({ selector, disabled: !controlState.presetActionEnabled })),
        { selector: "#btn-clear-manual-compare", disabled: !controlState.clearCompareEnabled },
      ],
    };
  }

  function manualPresetSavePreflight(options = {}, helpers = {}) {
    const isEditable = Object.prototype.hasOwnProperty.call(options, "editable")
      ? Boolean(options.editable)
      : Boolean(helpers.isStudioEditableRun?.(options.runData));
    const configPath = String(options.configPath || "").trim();
    const name = String(options.name || "").trim();
    if (!options.runData || !options.params || !isEditable) {
      return {
        ok: false,
        reason: "unsupported-run",
        message: "当前结果不支持保存手调参数集。",
        configPath,
        name,
      };
    }
    if (!configPath) {
      return {
        ok: false,
        reason: "missing-config",
        message: "缺少工作区配置路径，无法保存参数集。",
        configPath,
        name,
      };
    }
    if (!name) {
      return {
        ok: false,
        reason: "missing-name",
        message: "请输入参数集名称。",
        configPath,
        name,
      };
    }
    return {
      ok: true,
      reason: "",
      message: "",
      configPath,
      name,
    };
  }

  function manualPresetLoadPreflight(preset = null) {
    if (!preset) {
      return {
        ok: false,
        reason: "missing-preset",
        message: "请先选择一个参数集。",
        preset: null,
        presetName: "",
      };
    }
    return {
      ok: true,
      reason: "",
      message: "",
      preset,
      presetName: String(preset?.name || "参数集").trim() || "参数集",
    };
  }

  function manualPresetDeletePreflight(configPath = "", preset = null) {
    const path = String(configPath || "").trim();
    if (!preset || !path) {
      return {
        ok: false,
        reason: !preset ? "missing-preset" : "missing-config",
        message: "请先选择一个参数集。",
        configPath: path,
        preset: preset || null,
        presetId: "",
        presetName: "",
      };
    }
    return {
      ok: true,
      reason: "",
      message: "",
      configPath: path,
      preset,
      presetId: String(preset?.id || preset?.parameter_set_id || "").trim(),
      presetName: String(preset?.name || "参数集").trim() || "参数集",
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

  function manualPresetSaveSuccessState(responseData = {}, fallbackName = "") {
    const preset = responseData?.preset || {};
    const savedId = String(preset.id || preset.parameter_set_id || "").trim();
    const scopeLabel = normalizeKey(preset.scope) === "global" ? "公共参数库" : "当前工作区";
    const presetName = String(preset.name || fallbackName || "参数集").trim() || "参数集";
    return {
      savedId,
      presetName,
      scopeLabel,
      toastText: `已保存到${scopeLabel}：${presetName}${preset.params_adjusted ? "（已按约束自动修正）" : ""}`,
    };
  }

  function manualPresetLoadSuccessState(preset = {}, presetName = "") {
    const resolvedName = String(presetName || preset?.name || "参数集").trim() || "参数集";
    return {
      inputName: resolvedName,
      toastText: `已载入参数集：${resolvedName}${preset?.params_adjusted ? "（已按约束自动修正）" : ""}`,
    };
  }

  function manualPresetDeleteViewState(presetName = "") {
    const resolvedName = String(presetName || "参数集").trim() || "参数集";
    return {
      presetName: resolvedName,
      confirmText: `确定删除参数集“${resolvedName}”吗？`,
      toastText: `已删除参数集：${resolvedName}`,
    };
  }

  function manualPresetDeleteSuccessState(preflight = {}, comparePresetId = "") {
    const preset = preflight?.preset || {};
    const presetId = String(preflight?.presetId || preset?.id || preset?.parameter_set_id || "").trim();
    const compareId = String(comparePresetId || "").trim();
    return {
      inputName: "",
      shouldClearComparison: Boolean(presetId && compareId && presetId === compareId),
      clearComparisonOptions: { silent: true },
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

  function manualPresetApplyState(currentParams = null, originalParams = null, preset = null, options = {}) {
    if (!preset || !currentParams || !originalParams) {
      return {
        applied: false,
        params: currentParams,
        paramUpdates: [],
        hint: { visible: false, className: "", text: "" },
        presetName: "",
      };
    }
    const presetName = String(preset?.name || "参数集").trim() || "参数集";
    const result = manualPresetAppliedParams(currentParams, originalParams, preset);
    const contextWarning = String(options.contextWarning || "").trim();
    return {
      applied: true,
      params: result.params,
      paramUpdates: result.applied,
      hint: {
        visible: true,
        className: `hint-box ${contextWarning ? "status-warn" : "status-ok"}`.trim(),
        text: `已载入参数集：${presetName}${preset.params_adjusted ? "（已按约束自动修正）" : ""}${contextWarning ? `。${contextWarning}` : ""}`,
      },
      presetName,
    };
  }

  function manualParamUpdateState(currentParams = null, originalParams = null, name = "", value = null) {
    const paramName = String(name || "").trim();
    const numeric = Number(value);
    if (!paramName || !Number.isFinite(numeric) || !currentParams || typeof currentParams !== "object") {
      return {
        applied: false,
        params: currentParams,
        name: paramName,
        value: null,
        changed: false,
      };
    }
    const originals = originalParams && typeof originalParams === "object" ? originalParams : {};
    const params = { ...currentParams, [paramName]: numeric };
    return {
      applied: true,
      params,
      name: paramName,
      value: numeric,
      changed: Math.abs(numeric - Number(originals[paramName])) > 1e-8,
    };
  }

  function manualParamResetState(originalParams = null) {
    if (!originalParams || typeof originalParams !== "object") {
      return {
        reset: false,
        params: originalParams,
        paramUpdates: [],
        hint: { visible: false, className: "", text: "" },
      };
    }
    const params = { ...originalParams };
    return {
      reset: true,
      params,
      paramUpdates: Object.entries(params).map(([name, value]) => ({ name, value, changed: false })),
      hint: { visible: false, className: "hint-box", text: "" },
    };
  }

  function manualParamResetViewState(originalParams = null, runData = null) {
    const reset = manualParamResetState(originalParams);
    const meta = runData?.metadata || {};
    const metrics = meta.metrics || {};
    return {
      ...reset,
      shouldRestoreRun: Boolean(reset.reset && runData),
      chartData: reset.reset ? (runData || null) : null,
      shouldUpdateMetrics: Boolean(reset.reset),
      calibrationMetrics: metrics.calibration || {},
      validationMetrics: metrics.validation || {},
      metricMetadata: meta,
    };
  }

  function manualGroupParamNames(group = "all", names = [], groupParams = {}) {
    const paramNames = Array.isArray(names) ? names : [];
    if (normalizeKey(group) === "all") return paramNames.slice();
    const allowed = new Set(groupParams?.[group] || []);
    return paramNames.filter(name => allowed.has(name));
  }

  function manualPhaseGuide(group = "all", paramNames = [], groupMeta = {}, groupParams = {}) {
    const meta = groupMeta?.[group] || groupMeta?.all || { title: "参数", guide: "" };
    const shown = manualGroupParamNames(group, paramNames, groupParams);
    const suffix = shown.length ? ` 当前显示 ${shown.length} 个参数。` : " 当前结果中没有这一组参数。";
    return {
      text: `${meta.title}：${meta.guide}${suffix}`,
      className: `hint-box ${shown.length ? "" : "status-warn"}`.trim(),
      shownParamNames: shown,
    };
  }

  function manualChangeSummary(currentParams = null, originalParams = null, group = "all", groupParams = {}) {
    if (!currentParams || !originalParams) {
      return { visible: false, className: "", text: "", changed: [], visibleChanged: [] };
    }
    const changed = Object.keys(currentParams).filter(name =>
      Math.abs(Number(currentParams[name]) - Number(originalParams[name])) > 1e-8
    );
    if (!changed.length) {
      return { visible: false, className: "", text: "", changed: [], visibleChanged: [] };
    }
    const visibleChanged = manualGroupParamNames(group, changed, groupParams);
    return {
      visible: true,
      className: "hint-box status-warn",
      text: `已修改 ${changed.length} 个参数。${visibleChanged.length ? `当前分组中已改动：${visibleChanged.join("、")}` : "当前分组内暂无改动参数。"}`,
      changed,
      visibleChanged,
    };
  }

  function manualChangeSummaryPanelState(currentParams = null, originalParams = null, group = "all", groupParams = {}) {
    const summary = manualChangeSummary(currentParams, originalParams, group, groupParams);
    return summary.visible
      ? summary
      : { visible: false, className: "hint-box", text: "", changed: [], visibleChanged: [] };
  }

  function normalizeBoundPair(value) {
    if (!Array.isArray(value) || value.length < 2) return [0, 1];
    const lo = Number(value[0]);
    const hi = Number(value[1]);
    return [
      Number.isFinite(lo) ? lo : 0,
      Number.isFinite(hi) ? hi : 1,
    ];
  }

  function renderParamSliders(options = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const editable = Boolean(options.editable);
    const params = options.params && typeof options.params === "object" ? options.params : {};
    const bounds = options.bounds && typeof options.bounds === "object" ? options.bounds : {};
    const labels = options.labels && typeof options.labels === "object" ? options.labels : {};
    const group = options.group || "all";
    const groupParams = options.groupParams || {};
    if (!editable) {
      return {
        status: "readonly",
        html: '<div class="hint-box status-warn">该结果缺少继续手调所需的参数边界信息，暂时只能查看，不能手动调参。</div>',
        paramNames: [],
        shownParamNames: [],
      };
    }
    const paramNames = Object.keys(params);
    if (!paramNames.length) {
      return {
        status: "empty",
        html: '<div class="hint-box">无参数信息。</div>',
        paramNames,
        shownParamNames: [],
      };
    }
    const shownParamNames = manualGroupParamNames(group, paramNames, groupParams);
    if (!shownParamNames.length) {
      return {
        status: "group-empty",
        html: '<div class="hint-box status-warn">当前分组没有可调参数，请切换到其他参数组。</div>',
        paramNames,
        shownParamNames,
      };
    }
    const html = shownParamNames.map(name => {
      const val = params[name];
      const [lo, hi] = normalizeBoundPair(bounds[name]);
      const step = Math.max((hi - lo) / 1000, 1e-6);
      const label = labels[name] || name;
      return `
        <div class="param-slider-item" data-param="${escapeHtml(name)}">
          <div class="param-slider-head">
            <strong>${escapeHtml(name)}</strong>
            <span style="flex:1;margin-left:6px;font-size:11px;color:var(--muted)">${escapeHtml(label)}</span>
            <input class="param-value" type="number" step="${step}" min="${lo}" max="${hi}" value="${escapeHtml(val)}" data-param-input="${escapeHtml(name)}">
          </div>
          <input type="range" min="${lo}" max="${hi}" step="${step}" value="${escapeHtml(val)}" data-param-slider="${escapeHtml(name)}">
          <div class="param-slider-bounds"><span>${lo}</span><span>${hi}</span></div>
        </div>`;
    }).join("");
    return {
      status: "ready",
      html,
      paramNames,
      shownParamNames,
    };
  }

  function manualContextFromRunData(data = {}, helpers = {}) {
    const meta = data?.metadata || data || {};
    const dataSources = meta.data_sources || {};
    const effectiveObjectiveMode = helpers.effectiveObjectiveMode || (value => {
      const item = value || {};
      return normalizeKey(
        item.effective_objective_mode
        || item.optimization?.effective_objective_mode
        || item.objective_profile?.type
        || item.objective?.type
        || item.optimization?.objective_mode
      );
    });
    return {
      objective_mode: effectiveObjectiveMode(meta),
      prec_source: normalizeKey(
        dataSources.runtime_prec_source
        || dataSources.prec_source
        || dataSources.configured_precip_source
      ),
      glacier_mode: normalizeKey(dataSources.glacier_mode),
      param_bounds_profile: normalizeKey(meta.param_bounds_profile || meta.parameter_profile?.bounds_profile),
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

  function manualPresetContextWarningState(preset = null, runData = null, helpers = {}) {
    if (!preset || !runData?.metadata) return { text: "" };
    const current = manualContextFromRunData(runData, {
      effectiveObjectiveMode: helpers.effectiveObjectiveMode,
    });
    return {
      text: manualContextWarning(preset, current, helpers),
      current,
    };
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

  function taskPresetContext(options = {}) {
    const workspace = options.workspace || {};
    const profile = String(options.profile || workspace.率定模式 || "daily").trim() || "daily";
    const meteo = workspace.气象策略 || {};
    const defaultStep = normalizeKey(profile) === "hourly" ? 1 : 24;
    const timeStepHours = Number(workspace.时间步长_小时 || workspace.time_step_hours || defaultStep);
    const precipitationMode = options.precipitationMode
      || meteo.降水方案
      || meteo.precipitation_mode
      || "grid_only";
    return {
      profile,
      time_step_hours: Number.isFinite(timeStepHours) ? timeStepHours : defaultStep,
      objective_mode: options.objectiveMode || options.defaultObjectiveMode || "",
      prec_source: options.precSource || "",
      glacier_mode: options.glacierMode || "inline",
      param_bounds_profile: normalizeKey(profile) === "daily"
        ? (options.paramBoundsProfile || "qtp_alpine_default")
        : "hourly_step",
      precipitation_mode: precipitationMode,
      task_time_basis: options.taskTimeBasis
        || workspace.任务时段模式
        || workspace.time_basis
        || "continuous",
    };
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
    manualPresetDiffView,
    manualPresetDiffPanelState,
    compareMetricSummary,
    manualPresetCompareSummary,
    manualPresetCompareView,
    manualPresetComparePanelState,
    manualPresetComparePendingView,
    manualPresetCompareErrorView,
    findPresetById,
    manualPresetListPath,
    manualPresetConfigPathFromRunData,
    manualPresetProfileState,
    taskManualPresetLoadErrorState,
    taskManualPresetLoadStartState,
    taskManualPresetLoadSuccessState,
    manualPresetTaskSyncState,
    shouldClearManualPresetComparison,
    manualPresetSelectionChangeState,
    manualPresetControlState,
    manualPresetControlViewState,
    manualPresetSavePreflight,
    manualPresetLoadPreflight,
    manualPresetDeletePreflight,
    manualPresetSavePayload,
    manualPresetDeletePayload,
    manualPresetSaveSuccessState,
    manualPresetLoadSuccessState,
    manualPresetDeleteViewState,
    manualPresetDeleteSuccessState,
    manualPresetAppliedParams,
    manualPresetApplyState,
    manualParamUpdateState,
    manualParamResetState,
    manualParamResetViewState,
    manualGroupParamNames,
    manualPhaseGuide,
    manualChangeSummary,
    manualChangeSummaryPanelState,
    renderParamSliders,
    manualContextFromRunData,
    manualContextWarning,
    manualPresetContextWarningState,
    taskPresetContext,
    taskContextWarnings,
    renderTaskContextHint,
    forecastParameterContext,
  };
})();
