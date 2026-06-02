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

  function defaultSamePath(a, b) {
    return String(a || "") === String(b || "");
  }

  function filterGroup(label, options, attrName, isActive, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    return `
      <div class="results-filter-group">
        <span class="results-filter-label">${escapeHtml(label)}</span>
        ${(options || []).map(item => `
          <button class="phase-chip ${isActive(item) ? "active" : ""}" ${attrName}="${escapeHtml(item.value ?? item.path ?? "")}" ${item.disabled ? "disabled" : ""}>
            ${escapeHtml(item.label)}
          </button>
        `).join("")}
      </div>
    `;
  }

  function renderFilterToolbar(model = {}, helpers = {}) {
    const samePath = helpers.samePath || defaultSamePath;
    return [
      filterGroup(
        "工作区",
        model.workspaceOptions || [],
        "data-run-filter-path",
        item => samePath(item.path || "", model.selectedWorkspacePath || "") || (!item.path && !model.selectedWorkspacePath),
        helpers
      ),
      filterGroup(
        "率定方案",
        model.profileOptions || [],
        "data-run-filter-profile",
        item => String(item.value || "") === String(model.selectedProfile || ""),
        helpers
      ),
      filterGroup(
        "结果阶段",
        model.stageOptions || [],
        "data-run-filter-type",
        item => String(item.value || "") === String(model.selectedType || ""),
        helpers
      ),
      filterGroup(
        "手调能力",
        model.editabilityOptions || [],
        "data-run-filter-editability",
        item => String(item.value || "all") === String(model.selectedEditability || "all"),
        helpers
      ),
    ].join("");
  }

  function resultsFilterHint(model = {}) {
    const breakdown = String(model.breakdown || "").trim();
    const totalRuns = Number(model.totalRuns || 0);
    const shownCount = Number(model.shownCount || 0);
    const suffix = breakdown ? ` 其中 ${breakdown}。` : "";
    if (!model.filtersActive) {
      return {
        text: `当前显示全部结果，共 ${totalRuns} 组。${suffix}`,
        className: "hint-box",
      };
    }
    const workspaceText = model.workspaceText || "全部工作区";
    const profileText = model.profileText || "全部尺度";
    const stageText = model.stageText || "全部阶段";
    const abilityText = model.abilityText || "全部手调能力";
    return {
      text: `当前筛选：${workspaceText} / ${profileText} / ${stageText} / ${abilityText}，共 ${shownCount} 组。${suffix}`,
      className: shownCount ? "hint-box status-ok" : "hint-box status-warn",
    };
  }

  function runProfileValue(run = {}) {
    return String(run?.calibration_profile || (Number(run?.time_step_hours) === 1 ? "hourly" : "daily") || "").trim().toLowerCase();
  }

  function filterRuns(runs = [], filters = {}, helpers = {}) {
    const samePath = helpers.samePath || defaultSamePath;
    const runTypeValue = helpers.runTypeValue || (run => String(run?.run_type || run?.type || "").trim().toLowerCase());
    const workspacePath = String(filters.workspacePath || "").trim();
    const profile = String(filters.profile || "").trim().toLowerCase();
    const type = String(filters.type || "").trim().toLowerCase();
    const editability = String(filters.editability || "all").trim().toLowerCase() || "all";
    return (Array.isArray(runs) ? runs : []).filter(run => {
      if (workspacePath && !samePath(run?.workspace_config, workspacePath)) return false;
      if (profile && runProfileValue(run) !== profile) return false;
      if (type && runTypeValue(run) !== type) return false;
      if (editability === "editable" && !run?.studio_compatible) return false;
      if (editability === "readonly" && run?.studio_compatible) return false;
      return true;
    });
  }

  function resultsFilterBreakdown(runs = [], helpers = {}) {
    const runTypeValue = helpers.runTypeValue || (run => String(run?.run_type || run?.type || "").trim().toLowerCase());
    const counts = (Array.isArray(runs) ? runs : []).reduce((acc, run) => {
      const key = runTypeValue(run);
      acc[key] = Number(acc[key] || 0) + 1;
      return acc;
    }, {});
    const entries = [
      ["calibration", "正式率定"],
      ["manual_starter", "手调起点"],
      ["manual_result", "手调结果"],
      ["forecast_restart", "连续状态预报"],
      ["legacy", "历史结果"],
    ].filter(([key]) => counts[key]).map(([key, label]) => ({
      key,
      label,
      count: counts[key],
      text: `${label} ${counts[key]}`,
    }));
    return {
      counts,
      entries,
      text: entries.map(item => item.text).join(" / "),
    };
  }

  function alignedRunFiltersForSelection(run = null, filters = {}, currentlyVisibleRuns = [], helpers = {}) {
    const samePath = helpers.samePath || defaultSamePath;
    const runTypeValue = helpers.runTypeValue || (item => String(item?.run_type || item?.type || "").trim().toLowerCase());
    const next = {
      workspacePath: String(filters.workspacePath || "").trim(),
      profile: String(filters.profile || "").trim().toLowerCase(),
      type: String(filters.type || "").trim().toLowerCase(),
      editability: String(filters.editability || "all").trim().toLowerCase() || "all",
    };
    if (!run) return { changed: false, filters: next };
    let changed = false;
    const workspacePath = String(run.workspace_config || "").trim();
    const currentSelection = String(run.path || "").trim();
    if (workspacePath && next.workspacePath && !samePath(workspacePath, next.workspacePath)) {
      next.workspacePath = workspacePath;
      changed = true;
    } else if (workspacePath && !next.workspacePath) {
      const visible = Array.isArray(currentlyVisibleRuns) ? currentlyVisibleRuns : [];
      if (currentSelection && !visible.some(item => samePath(item?.path, currentSelection))) {
        next.workspacePath = workspacePath;
        changed = true;
      }
    }
    const profile = runProfileValue(run);
    if (next.profile && profile && profile !== next.profile) {
      next.profile = "";
      changed = true;
    }
    const type = runTypeValue(run);
    if (next.type && type && type !== next.type) {
      next.type = "";
      changed = true;
    }
    if ((next.editability === "editable" && !run.studio_compatible) || (next.editability === "readonly" && run.studio_compatible)) {
      next.editability = "all";
      changed = true;
    }
    return { changed, filters: next };
  }

  function runsForWorkspace(runs = [], path = "", helpers = {}) {
    const samePath = helpers.samePath || defaultSamePath;
    return (Array.isArray(runs) ? runs : []).filter(run => samePath(run?.workspace_config, path));
  }

  function selectedRunPath(model = {}) {
    return String(model.selectedRunPath || model.currentRun?.run?.path || model.currentRun?.path || "").trim();
  }

  function clearRunComparisonState() {
    return {
      statePatch: {
        compareSeries: null,
        compareMetrics: null,
        compareLabel: "",
        comparePresetId: "",
        compareAdjusted: false,
      },
    };
  }

  function runComparisonClearViewState(runData = null, options = {}) {
    const meta = runData?.metadata || {};
    const metrics = meta.metrics || {};
    return {
      statePatch: clearRunComparisonState().statePatch,
      summary: {
        visible: false,
        text: "",
        className: "hint-box",
      },
      shouldRestoreRun: Boolean(runData),
      chartData: runData || null,
      calibrationMetrics: metrics.calibration || {},
      validationMetrics: metrics.validation || {},
      metricMetadata: meta,
      shouldToast: !options.silent,
      toastText: "已清除参数集对比。",
    };
  }

  function clearRunDetailState() {
    const comparison = clearRunComparisonState().statePatch;
    return {
      statePatch: {
        currentRun: null,
        selectedRunPath: "",
        _runData: null,
        _runParams: null,
        _runOrigParams: null,
        ...comparison,
        lastRunExportPath: "",
        runManualPresets: [],
        runManualPresetConfigPath: "",
      },
    };
  }

  function clearRunDetailViewState(message = "请先从左侧选择一个结果。") {
    const entryMessage = String(message || "请先从左侧选择一个结果。").trim() || "请先从左侧选择一个结果。";
    return {
      statePatch: clearRunDetailState().statePatch,
      domUpdates: [
        { selector: "#results-metric-strip", html: "" },
        { selector: "#run-engineering-summary", html: "" },
        { selector: "#run-engineering-actions", html: "" },
        { selector: "#run-engineering-note", text: "", className: "hint-box" },
        { selector: "#run-export-start", value: "" },
        { selector: "#run-export-end", value: "" },
        { selector: "#btn-run-export", disabled: true },
        { selector: "#btn-open-export-file", disabled: true },
        { selector: "#run-export-hint", text: "选择一个结果后，可按时间范围导出 Excel。", className: "hint-box" },
        { selector: "#metadata-grid", html: "" },
        { selector: "#param-sliders", html: '<div class="hint-box">当前尚未选择结果。</div>' },
        { selector: "#btn-resimulate", disabled: true },
        { selector: "#btn-reset-params", disabled: true },
        { selector: "#resim-hint", visible: true, text: "请选择一个可调结果后再进行保存并重算。", className: "hint-box status-warn" },
        { selector: "#manual-preset-name", value: "" },
        { selector: "#manual-preset-select", value: "" },
        { selector: "#resim-log", visible: false, text: "" },
        { selector: "#flood-event-chart-panel", visible: false },
        { selector: "#results-entry-hint", text: entryMessage, className: "hint-box status-warn" },
      ],
      chartIds: ["hydrograph-chart", "component-chart", "residual-chart", "flood-event-chart"],
      chartFallbackHtml: '<div class="hint-box">当前没有可显示的结果图表。</div>',
      shouldRenderRunExportFields: true,
      shouldRenderManualPresetOptions: true,
      shouldUpdateManualPresetControls: true,
      shouldRenderManualPresetDiff: true,
      shouldUpdateCompareSummary: true,
      shouldUpdateManualStarterButtons: true,
      shouldUpdateSidebar: true,
    };
  }

  function runDetailState(data = null, context = {}, helpers = {}) {
    const isStudioEditableRun = helpers.isStudioEditableRun || (() => false);
    const detailData = data || null;
    const meta = detailData?.metadata || {};
    const metrics = meta.metrics || {};
    const editable = Object.prototype.hasOwnProperty.call(context, "editable")
      ? Boolean(context.editable)
      : Boolean(isStudioEditableRun(detailData));
    const params = meta.optimized_params || {};
    const resolvedRunPath = String(
      detailData?.run?.path ||
      detailData?.path ||
      context.selectedRunPath ||
      "",
    ).trim();
    return {
      editable,
      selectedRunPath: resolvedRunPath,
      metadata: meta,
      calibrationMetrics: metrics.calibration || {},
      validationMetrics: metrics.validation || {},
      domUpdates: [
        { selector: "#btn-resimulate", disabled: !editable },
        { selector: "#btn-reset-params", disabled: !editable },
        {
          selector: "#resim-hint",
          visible: !editable,
          text: editable ? "" : "该结果不是可调结果，只支持查看，不支持滑块重算。",
          className: editable ? "hint-box" : "hint-box status-warn",
        },
        { selector: "#resim-log", visible: false, text: "" },
        { selector: "#manual-preset-name", value: "" },
      ],
      shouldUpdateManualPresetControls: true,
      shouldRenderManualPresetDiff: true,
      shouldUpdateCompareSummary: true,
      shouldUpdateManualStarterButtons: true,
      statePatch: {
        _runData: detailData,
        _runParams: editable ? { ...params } : null,
        _runOrigParams: editable ? { ...params } : null,
        ...clearRunComparisonState().statePatch,
        selectedRunPath: resolvedRunPath,
        currentRun: detailData,
        lastRunExportPath: "",
      },
    };
  }

  function presetIdentity(preset = {}) {
    return String(preset?.id || preset?.parameter_set_id || "").trim();
  }

  function runComparisonSuccessState(preset = {}, resultData = {}) {
    const qSim = Array.isArray(resultData?.q_sim) ? resultData.q_sim : [];
    const qObs = Array.isArray(resultData?.q_obs) ? resultData.q_obs : [];
    const label = String(preset?.name || "参数集").trim() || "参数集";
    return {
      statePatch: {
        compareLabel: label,
        comparePresetId: presetIdentity(preset),
        compareMetrics: resultData?.metrics || {},
        compareAdjusted: Boolean(resultData?.runtime?.params_adjusted),
        compareSeries: {
          dates: Array.isArray(resultData?.dates) ? resultData.dates : [],
          q_sim: qSim,
          residuals: qSim.map((s, i) => (s != null && qObs[i] != null) ? s - qObs[i] : null),
        },
      },
      toastText: `已生成参数集“${label}”的对比曲线。`,
    };
  }

  function runComparisonPreflight(preset = null, runData = null, helpers = {}) {
    const isStudioEditableRun = helpers.isStudioEditableRun || (() => false);
    if (!preset) {
      return {
        ok: false,
        reason: "missing-preset",
        message: "请先选择一个参数集。",
      };
    }
    if (!runData || !isStudioEditableRun(runData)) {
      return {
        ok: false,
        reason: "unsupported-run",
        message: "当前结果不支持参数集对比。",
      };
    }
    return {
      ok: true,
      reason: "",
      message: "",
    };
  }

  function runComparisonRequestContext(preset = {}, runData = {}) {
    const runPath = String(runData?.run?.path || "").trim();
    const presetId = presetIdentity(preset);
    return {
      runPath,
      presetId,
      payload: {
        run_path: runPath,
        params: preset?.params || {},
      },
    };
  }

  function runComparisonRequestStillCurrent(request = {}, runData = null, preset = null, helpers = {}) {
    const samePath = helpers.samePath || defaultSamePath;
    const requestRunPath = String(request?.runPath || "").trim();
    const currentRunPath = String(runData?.run?.path || "").trim();
    if (!samePath(requestRunPath, currentRunPath)) return false;
    const requestPresetId = String(request?.presetId || "").trim();
    const currentPresetId = presetIdentity(preset);
    return !(requestPresetId && currentPresetId && requestPresetId !== currentPresetId);
  }

  function runComparisonErrorState(error = {}, helpers = {}) {
    const message = error?.message || String(error || "未知错误");
    const compareErrorView = helpers.compareErrorView || (err => ({
      visible: true,
      className: "hint-box status-fail",
      text: `参数集对比失败：${err?.message || String(err || "未知错误")}`,
    }));
    return {
      statePatch: clearRunComparisonState().statePatch,
      summary: compareErrorView(error),
      shouldRestoreRun: true,
      toastText: message,
    };
  }

  function forwardSimulationPreflight(runData = null, params = null, helpers = {}) {
    const isStudioEditableRun = helpers.isStudioEditableRun || (() => false);
    if (!runData || !params || !isStudioEditableRun(runData)) {
      return {
        ok: false,
        reason: "unsupported-run",
        message: "该结果不支持保存并重算。",
      };
    }
    return {
      ok: true,
      reason: "",
      message: "",
    };
  }

  function forwardSimulationStartState() {
    return {
      hint: {
        visible: true,
        text: "正在创建保存并重算任务...",
        className: "hint-box status-warn",
      },
      log: {
        visible: true,
        text: "",
      },
    };
  }

  function forwardSimulationErrorState(error = {}) {
    const message = error?.message || String(error || "未知错误");
    return {
      hint: {
        visible: true,
        text: `模拟失败：${message}`,
        className: "hint-box status-fail",
      },
      log: {
        visible: false,
      },
    };
  }

  function forwardSimulationRequestContext(runData = {}, params = {}, options = {}) {
    const runPath = String(runData?.run?.path || "").trim();
    return {
      runPath,
      payload: {
        run_path: runPath,
        params: params || {},
        save_run: options.saveRun !== false,
      },
    };
  }

  function forwardSimulationTaskUiState(task = null, options = {}, helpers = {}) {
    const formatDurationSeconds = helpers.formatDurationSeconds || (value => `${Math.max(0, Math.round(Number(value) || 0))}s`);
    const formatNumber = helpers.formatNumber || ((value, digits = 4) => {
      const numeric = Number(value);
      return Number.isFinite(numeric) ? numeric.toFixed(digits) : "—";
    });
    if (!task) {
      return {
        shouldRender: false,
        log: { visible: false, lines: [] },
        button: { disabled: false },
        hint: { update: false, visible: false, text: "", className: "" },
      };
    }
    const logs = Array.isArray(task.output) ? task.output : [];
    const createdAt = Number(task.created_at);
    const nowSeconds = Number.isFinite(Number(options.nowSeconds)) ? Number(options.nowSeconds) : Date.now() / 1000;
    const elapsed = Number.isFinite(createdAt) && createdAt > 0
      ? Math.max(0, Math.round(nowSeconds - createdAt))
      : null;
    const base = {
      shouldRender: true,
      log: { visible: logs.length > 0, lines: logs.slice(-40) },
      button: { disabled: false },
      hint: { update: false, visible: false, text: "", className: "" },
    };
    if (task.status === "running") {
      const stage = task.ui_progress?.stage || "正在保存并重算当前结果";
      return {
        ...base,
        button: { disabled: true },
        hint: {
          update: true,
          visible: true,
          text: `${stage}${elapsed !== null ? ` · 已耗时 ${formatDurationSeconds(elapsed)}` : ""}`,
          className: "hint-box status-warn",
        },
      };
    }
    if (task.status === "completed" && task.result) {
      const m = task.result.metrics || {};
      return {
        ...base,
        hint: {
          update: true,
          visible: true,
          text: task.result.run_path
            ? `保存完成：已生成新结果，率定纳什效率系数=${formatNumber(m.nse_cal, 4)}，验证纳什效率系数=${formatNumber(m.nse_val, 4)}`
            : `模拟完成：率定纳什效率系数=${formatNumber(m.nse_cal, 4)}，验证纳什效率系数=${formatNumber(m.nse_val, 4)}`,
          className: "hint-box status-ok",
        },
      };
    }
    if (task.status === "failed") {
      return {
        ...base,
        hint: {
          update: true,
          visible: true,
          text: logs.length ? logs[logs.length - 1] : "保存并重算失败。",
          className: "hint-box status-fail",
        },
      };
    }
    return base;
  }

  function forwardSimulationResultState(result = null) {
    if (!result) {
      return {
        ok: false,
        chartData: null,
        calibrationMetrics: {},
        validationMetrics: {},
      };
    }
    const qSim = Array.isArray(result.q_sim) ? result.q_sim : [];
    const qObs = Array.isArray(result.q_obs) ? result.q_obs : [];
    const metrics = result.metrics || {};
    return {
      ok: true,
      chartData: {
        series: {
          dates: Array.isArray(result.dates) ? result.dates : [],
          q_sim: qSim,
          q_obs: qObs,
          q_rain: result.q_rain,
          q_snow: result.q_snow,
          q_ice: result.q_ice,
          q_boundary_inflow: result.q_boundary_inflow,
          residuals: qSim.map((sim, index) => (sim != null && qObs[index] != null) ? sim - qObs[index] : null),
        },
      },
      calibrationMetrics: {
        nse: metrics.nse_cal,
        kge: metrics.kge_cal,
        pbias: metrics.pbias_cal,
      },
      validationMetrics: {
        nse: metrics.nse_val,
      },
    };
  }

  function runManualPresetLoadStartState(path = "", currentConfigPath = "", helpers = {}) {
    const samePath = helpers.samePath || defaultSamePath;
    const targetPath = String(path || "").trim();
    const changed = !samePath(targetPath, currentConfigPath);
    const statePatch = { runManualPresetConfigPath: targetPath };
    if (!targetPath || changed) statePatch.runManualPresets = [];
    return {
      path: targetPath,
      changed,
      shouldRequest: Boolean(targetPath),
      shouldRender: !targetPath || changed,
      statePatch,
    };
  }

  function runManualPresetLoadSuccessState(responseData = {}) {
    const presets = Array.isArray(responseData?.presets) ? responseData.presets : [];
    return {
      presets,
      statePatch: {
        runManualPresets: presets,
      },
    };
  }

  function runManualPresetLoadErrorState() {
    return {
      presets: [],
      statePatch: {
        runManualPresets: [],
      },
    };
  }

  function workspaceHasEditableRun(runs = [], path = "", helpers = {}) {
    return runsForWorkspace(runs, path, helpers).some(run => run?.studio_compatible);
  }

  function latestEditableRunPath(runs = []) {
    const items = Array.isArray(runs) ? runs : [];
    const editable = items.find(run => run?.studio_compatible);
    return editable?.path || items[0]?.path || "";
  }

  function runListState(model = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const totalRuns = Number(model.totalRuns || 0);
    const visibleCount = Number(model.visibleCount || 0);
    const workspaceFilterPath = String(model.workspaceFilterPath || "").trim();
    const workspaceRunCount = Number(model.workspaceRunCount || 0);
    const workspaceFilterLabel = String(model.workspaceFilterLabel || "").trim();
    const manualStarterWorkspaceLabel = String(model.manualStarterWorkspaceLabel || "").trim();
    const hasCurrentRun = Boolean(model.hasCurrentRun);
    if (!totalRuns) {
      return {
        status: "empty-all",
        listHtml: '<div class="hint-box">暂无结果。</div>',
        hintText: manualStarterWorkspaceLabel
          ? `工作区“${manualStarterWorkspaceLabel}”当前还没有结果。可直接生成“手调起点”，不必先做正式率定。`
          : "还没有结果。选择工作区后，可直接生成“手调起点”进入手动调参。",
        hintClassName: "hint-box status-warn",
        updateHint: true,
      };
    }
    if (!visibleCount) {
      const workspaceEmpty = Boolean(workspaceFilterPath) && workspaceRunCount === 0;
      return {
        status: workspaceEmpty ? "empty-workspace" : "empty-filter",
        listHtml: workspaceEmpty
          ? `<div class="hint-box status-warn">工作区“${escapeHtml(workspaceFilterLabel)}”当前还没有结果。可直接生成“手调起点”，或启动正式率定。</div>`
          : '<div class="hint-box status-warn">当前筛选下没有结果。可切换筛选条件，或先回到“全部结果”查看。</div>',
        hintText: workspaceEmpty
          ? `工作区“${workspaceFilterLabel}”当前还没有结果。可直接生成“手调起点”继续。`
          : workspaceFilterPath
            ? `工作区“${workspaceFilterLabel}”有结果，但当前筛选条件下没有匹配项。可放宽筛选后再查看。`
            : "当前筛选下没有结果。可切换筛选条件后再查看。",
        hintClassName: "hint-box status-warn",
        updateHint: true,
      };
    }
    if (!hasCurrentRun) {
      return {
        status: "ready",
        listHtml: "",
        hintText: workspaceFilterPath
          ? `先从左侧选择“${workspaceFilterLabel}”的一个结果。选中后即可在下方继续手动调参并重算结果。`
          : "先从左侧选择一个结果，或点击“打开最新结果”。选中后即可在下方手动调参并重算结果。",
        hintClassName: "hint-box",
        updateHint: true,
      };
    }
    return { status: "ready", listHtml: "", hintText: "", hintClassName: "", updateHint: false };
  }

  function manualStarterControlState(model = {}) {
    const calibrationWorkspacePath = String(model.calibrationWorkspacePath || "").trim();
    const resultsWorkspacePath = String(model.resultsWorkspacePath || "").trim();
    const hasRunningCalibrationTask = Boolean(model.runningCalibrationTask);
    const hasRunningResultsTask = Boolean(model.runningResultsTask);
    const totalRuns = Number(model.totalRuns || 0);
    const resultsWorkspaceRunCount = Number(model.resultsWorkspaceRunCount || 0);
    const workspaceFilterActive = Boolean(model.workspaceFilterActive);
    const showResultsStarter = Boolean(resultsWorkspacePath) && (!totalRuns || (workspaceFilterActive && resultsWorkspaceRunCount === 0));
    return {
      calibration: {
        disabled: !calibrationWorkspacePath || hasRunningCalibrationTask,
        text: hasRunningCalibrationTask ? "正在生成手调起点..." : "生成手调起点",
      },
      results: {
        visible: showResultsStarter,
        disabled: !resultsWorkspacePath || hasRunningResultsTask,
        text: hasRunningResultsTask ? "正在生成手调起点..." : "生成手调起点",
      },
    };
  }

  function renderMetricStrip(items = [], helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    return (items || []).map(item => `
      <div class="metric-tile">
        <span>${escapeHtml(item.l)}</span>
        <strong>${escapeHtml(item.v)}</strong>
      </div>
    `).join("");
  }

  function resultMetricItems(calibration = {}, validation = {}, meta = {}, helpers = {}) {
    const profileLabel = helpers.profileLabel || (value => value || "—");
    const formatNumber = helpers.formatNumber || defaultFormatNumber;
    const eventMetricItems = helpers.eventMetricItems || (() => []);
    return [
      { l: "模式", v: profileLabel(meta.calibration_profile) },
      { l: "步长", v: `${formatNumber(meta.time_config?.time_step_hours, 0)} 小时` },
      { l: "率定纳什效率系数", v: formatNumber(calibration.nse, 4) },
      { l: "验证纳什效率系数", v: formatNumber(validation.nse, 4) },
      { l: "率定 KGE 综合效率", v: formatNumber(calibration.kge, 4) },
      { l: "率定水量偏差", v: `${formatNumber(calibration.pbias, 2)}%` },
      ...eventMetricItems(meta),
    ];
  }

  function defaultFormatNumber(value, digits = 4) {
    const num = Number(value);
    return Number.isFinite(num) ? num.toFixed(digits) : "—";
  }

  function defaultMetricValue(value, digits = 2, suffix = "") {
    const num = Number(value);
    return Number.isFinite(num) ? `${num.toFixed(digits)}${suffix}` : "—";
  }

  const DEFAULT_RESULT_CHART_COLORS = Object.freeze({
    qObs: "#1e293b",
    qSim: "#0e7490",
    qRain: "#2563eb",
    qSnow: "#38bdf8",
    qIce: "#06b6d4",
    boundary: "#64748b",
    residual: "#b91c1c",
  });

  const RUN_EXPORT_FIELDS = Object.freeze([
    { key: "q_sim", label: "模拟总流量", checked: true },
    { key: "q_obs", label: "观测流量", checked: true },
    { key: "q_rain", label: "降雨产流", checked: true },
    { key: "q_snow", label: "融雪流量", checked: true },
    { key: "q_ice", label: "裸冰融化流量", checked: true },
    { key: "q_boundary_inflow", label: "边界入流", checked: false },
  ]);

  function defaultHydrologySummaryValue(summary = {}, key, fallback = "—") {
    const value = summary?.[key];
    return value === undefined || value === null || value === "" ? fallback : value;
  }

  function metadataItem(label, value, detail = "", helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const displayValue = value === undefined || value === null || value === "" ? "—" : String(value);
    return `
      <div class="list-item metadata-list-item">
        <strong>${escapeHtml(label)}</strong>
        <small>${escapeHtml(displayValue)}</small>
        ${detail ? `<em>${escapeHtml(detail)}</em>` : ""}
      </div>
    `;
  }

  function metadataSection(title, rows = [], helpers = {}) {
    const content = (rows || []).map(row => metadataItem(row?.[0], row?.[1], row?.[2], helpers)).join("");
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    return `
      <section class="metadata-section">
        <h4>${escapeHtml(title)}</h4>
        <div class="metadata-section-grid">${content}</div>
      </section>
    `;
  }

  function renderRunCard(run = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const samePath = helpers.samePath || defaultSamePath;
    const formatNumber = helpers.formatNumber || defaultFormatNumber;
    const formatMetricValue = helpers.formatMetricValue || defaultMetricValue;
    const hydrologySummaryValue = helpers.hydrologySummaryValue || defaultHydrologySummaryValue;
    const runWorkspaceName = helpers.runWorkspaceName || (() => "未命名工作区");
    const runTypeBadge = helpers.runTypeBadge || (() => "");
    const objectiveVersionBadge = helpers.objectiveVersionBadge || (() => "");
    const runDisplayName = helpers.runDisplayName || (item => item?.display_name || item?.name || "未命名结果");
    const runDisplaySubtitle = helpers.runDisplaySubtitle || (() => "");
    const selectedRunPath = String(helpers.selectedRunPath || "");
    const runWorkspaceFilterPath = String(helpers.runWorkspaceFilterPath || "");
    const hydro = run.hydrology_summary || {};
    return `
    <article class="list-item run-card ${selectedRunPath && samePath(selectedRunPath, run.path) ? "selected" : ""}" data-run-path="${escapeHtml(run.path)}">
      <div class="run-card-topline">
        <span class="run-card-kicker">${escapeHtml(runWorkspaceName(run))}</span>
        <div class="run-card-badges">
          ${runTypeBadge(run)}
          ${objectiveVersionBadge(run)}
          ${run.studio_compatible ? '<span class="status-badge status-ok">可继续手调</span>' : '<span class="status-badge status-warn">仅查看</span>'}
        </div>
      </div>
      <div class="list-item-head run-card-head">
        <div class="run-card-titlebox">
          <strong>${escapeHtml(runDisplayName(run))}</strong>
          ${runDisplaySubtitle(run) ? `<small class="run-card-subtitle">${escapeHtml(runDisplaySubtitle(run))}</small>` : ""}
        </div>
        <div class="run-card-score">
          <span>NSE 率定 / 验证</span>
          <strong>${escapeHtml(`${formatNumber(run?.nse_cal, 4)} / ${formatNumber(run?.nse_val, 4)}`)}</strong>
          <small>${escapeHtml(`PBIAS ${formatMetricValue(run?.pbias_cal, 2, "%")} / ${formatMetricValue(run?.pbias_val, 2, "%")}`)}</small>
        </div>
      </div>
      <div class="run-card-meta">
        <span class="run-meta-pill">${escapeHtml(hydrologySummaryValue(hydro, "workflow_label_zh", "单流程参数率定"))}</span>
        <span class="run-meta-pill">${escapeHtml(hydrologySummaryValue(hydro, "objective_label_zh", "综合水文目标函数"))}</span>
        <span class="run-meta-pill">${escapeHtml(hydrologySummaryValue(hydro, "flow_status_zh", "径流拟合未达标"))}</span>
      </div>
      <div class="workspace-card-actions run-card-actions">
        ${run.workspace_config && !samePath(run.workspace_config, runWorkspaceFilterPath) ? `<button class="ghost-button" data-filter-run-workspace="${escapeHtml(run.workspace_config)}">只看本工作区</button>` : ""}
        <button class="ghost-button" data-rename-run="${escapeHtml(run.path)}">${run.has_custom_title ? "修改标题" : "命名结果"}</button>
        <button class="ghost-button" data-open-run-dir="${escapeHtml(run.path)}">打开目录</button>
        <button class="ghost-button" data-delete-run="${escapeHtml(run.path)}">删除</button>
      </div>
    </article>
  `;
  }

  function renderRunCards(runs = [], helpers = {}) {
    const items = Array.isArray(runs) ? runs : [];
    return items.map(run => renderRunCard(run, helpers)).join("");
  }

  function hydrologySummaryFor(data = {}) {
    const metadata = data?.metadata || {};
    return data?.hydrology_summary || data?.run?.hydrology_summary || metadata?.hydrology_summary || {};
  }

  function runStepHours(data = {}) {
    const hours = Number(data?.metadata?.time_config?.time_step_hours || data?.run?.time_step_hours || 24);
    return hours <= 1.5 ? 1 : 24;
  }

  function renderEngineeringCards(cards = [], helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    return (cards || []).map(card => `
      <article class="engineering-card">
        <span>${escapeHtml(card.label || "")}</span>
        <strong>${escapeHtml(card.value || "—")}</strong>
        <small>${escapeHtml(card.detail || "—")}</small>
      </article>
    `).join("");
  }

  function renderRunEngineeringSummary(data = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const samePath = helpers.samePath || defaultSamePath;
    const hydrologySummaryValue = helpers.hydrologySummaryValue || defaultHydrologySummaryValue;
    const isStudioEditableRun = helpers.isStudioEditableRun || (() => false);
    const replayCompatibilityInfo = helpers.replayCompatibilityInfo || (() => ({}));
    const componentFractionReport = helpers.componentFractionReport || (() => ({}));
    const componentFractionText = helpers.componentFractionText || (() => "—");
    const componentFractionBasisText = helpers.componentFractionBasisText || (() => "—");
    const floodEventEvaluation = helpers.floodEventEvaluation || (() => ({}));
    const floodEventStatusText = helpers.floodEventStatusText || (() => "—");
    const runTypeLabel = helpers.runTypeLabel || ((value, fallback = "结果") => fallback || value || "结果");
    const shortPath = helpers.shortPath || (value => String(value || "").replace(/\\/g, "/").split("/").pop() || "—");
    const meta = data?.metadata || {};
    const summary = hydrologySummaryFor(data);
    const editable = isStudioEditableRun(data);
    const manual = Boolean(meta?.manual_result?.enabled);
    const starter = Boolean(meta?.starter_result?.enabled);
    const workspaceConfig = meta.workspace_config || data?.run?.workspace_config || "";
    const replayInfo = replayCompatibilityInfo(meta) || {};
    const reliabilityFlag = String(meta?.reliability_flag || "ok").trim();
    const isDegraded = reliabilityFlag !== "ok";
    const reportPath = summary.diagnostics_detail_path || summary.diagnostics_detail_display_path || "";
    const componentReport = componentFractionReport(meta);
    const floodEval = floodEventEvaluation(meta);
    const cards = [
      { label: "率定流程", value: hydrologySummaryValue(summary, "workflow_label_zh", runTypeLabel(data?.run?.run_type, manual ? "手调结果" : starter ? "手调起点" : editable ? "单流程参数率定" : "历史率定结果")), detail: "当前页面显示水文摘要，详细数据见本地结果目录" },
      { label: "评分标准", value: hydrologySummaryValue(summary, "objective_label_zh", "综合水文目标函数"), detail: "径流拟合与三水源构成综合评分" },
      { label: "径流拟合", value: hydrologySummaryValue(summary, "flow_status_zh"), detail: "综合 NSE、KGE、PBIAS 径流指标" },
      ...(floodEval?.enabled ? [{ label: "洪水事件", value: floodEventStatusText(floodEval), detail: floodEval.objective_enabled ? "本次按事件窗口参与率定评分" : "本次输出逐场洪水诊断" }] : []),
      { label: "三水源构成", value: componentFractionText(componentReport), detail: componentFractionBasisText(componentReport) },
      { label: "结果说明", value: reportPath ? shortPath(summary.diagnostics_detail_display_path || reportPath) : "结果目录内生成", detail: "水文模拟结果说明已保存至本地结果目录" },
    ];
    const actionButtons = [
      data?.run?.path ? `<button class="ghost-button" data-rename-run="${escapeHtml(data.run.path)}">${data?.run?.has_custom_title ? "修改标题" : "命名结果"}</button>` : "",
      data?.run?.path ? `<button class="ghost-button" data-run-summary-open-dir="${escapeHtml(data.run.path)}">打开结果目录</button>` : "",
      reportPath ? `<button class="ghost-button" data-run-summary-open-report="${escapeHtml(reportPath)}">打开过程复核报告</button>` : "",
      workspaceConfig && !samePath(workspaceConfig, helpers.runWorkspaceFilterPath || "") ? `<button class="ghost-button" data-run-summary-filter-workspace="${escapeHtml(workspaceConfig)}">只看本工作区</button>` : "",
      workspaceConfig ? `<button class="ghost-button" data-run-summary-open-workspace="${escapeHtml(workspaceConfig)}">回到工作区配置</button>` : "",
      data?.run?.path ? `<button class="ghost-button" data-delete-run="${escapeHtml(data.run.path)}">删除当前结果</button>` : "",
    ].filter(Boolean);
    const noteParts = [
      "结果页已压缩为水文摘要；完整过程复核和逐年分析保存在本地过程复核报告中。",
      editable
        ? (manual ? "该结果来自手动调参后的保存重算，可继续在此基础上调整。" : starter ? "该结果是系统生成的手调起点，可作为后续人工复核起点。" : "该结果保留工作区配置和参数边界，可继续手动调参与保存重算。")
        : "当前结果仅支持查看。",
    ];
    if (replayInfo.obsReplay) {
      noteParts.push("观测序列已从源结果回放恢复，即使当前工作区原始观测 CSV 缺失，也能继续打开和重算。");
    }
    if (replayInfo.boundaryReplay) {
      noteParts.push("上游边界入流已从源结果回放恢复；当前继续修改 Muskingum 路由参数时，不会重新路由原始边界 CSV。");
    }
    if (isDegraded) {
      const degradedReason = Array.isArray(meta?.reliability_notes) ? meta.reliability_notes.join("；") : "";
      noteParts.push(`当前结果可靠性降级${degradedReason ? `：${degradedReason}` : "。"} `);
    }
    if (meta?.project_object_type === "regression_validation" || String(data?.run?.path || "").includes("HBVStudio_Demo")) {
      noteParts.push("当前结果仅代表本次工程配置下的一次率定结果，请结合输入数据、参数设置和本地过程复核报告综合判断。");
    }
    return {
      summaryHtml: renderEngineeringCards(cards, helpers),
      actionsHtml: actionButtons.join(""),
      noteText: noteParts.join(""),
      noteClassName: `hint-box ${(!editable || replayInfo.boundaryReplay || isDegraded) ? "status-warn" : "status-ok"}`.trim(),
    };
  }

  function renderRunDetailMetadata(data = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const meta = data?.metadata || {};
    const run = data?.run || {};
    const summary = hydrologySummaryFor(data);
    const timeCfg = meta.time_config || {};
    const seriesRange = data.series_range || {};
    const paramBoundsProfileLabels = helpers.paramBoundsProfileLabels || {};
    const hydrologySummaryValue = helpers.hydrologySummaryValue || defaultHydrologySummaryValue;
    const componentFractionReport = helpers.componentFractionReport || (() => ({}));
    const componentFractionText = helpers.componentFractionText || (() => "—");
    const componentFractionBasisText = helpers.componentFractionBasisText || (() => "—");
    const floodEventRows = helpers.floodEventRows || (() => []);
    const restartStateRows = helpers.restartStateRows || (() => []);
    const isStudioEditableRun = helpers.isStudioEditableRun || (() => false);
    const runTypeLabel = helpers.runTypeLabel || ((value, fallback = "查看结果") => fallback || value || "查看结果");
    const workspaceLabelByPath = helpers.workspaceLabelByPath || (() => "未命名工作区");
    const timeRangeText = helpers.timeRangeText || ((start, end) => [start || "—", end || "—"].join(" 至 "));
    const shortPath = helpers.shortPath || (value => String(value || "").replace(/\\/g, "/").split("/").pop() || "—");
    const runMetricsText = helpers.runMetricsText || (() => "");
    const compactTimeText = helpers.compactTimeText || (value => String(value || ""));
    const currentRunStepHours = helpers.currentRunStepHours || runStepHours;
    const editable = isStudioEditableRun(data);
    const manual = Boolean(meta?.manual_result?.enabled);
    const starter = Boolean(meta?.starter_result?.enabled);
    const stepHours = currentRunStepHours(data);
    const reportPath = summary.diagnostics_detail_path || summary.diagnostics_detail_display_path || "";
    const reportDisplayPath = summary.diagnostics_detail_display_path || summary.diagnostics_detail_path || "";
    const componentReport = componentFractionReport(meta);
    const restartRows = restartStateRows(meta) || [];
    const floodRows = floodEventRows(meta) || [];
    const metadataHtml = [
      metadataSection("水文结果摘要", [
        ["率定流程", hydrologySummaryValue(summary, "workflow_label_zh", "单流程参数率定")],
        ["评分标准", hydrologySummaryValue(summary, "objective_label_zh", "综合水文目标函数")],
        ["参数范围", meta.param_bounds_profile_label || meta.parameter_profile?.bounds_profile_label || paramBoundsProfileLabels[meta.param_bounds_profile] || paramBoundsProfileLabels[meta.parameter_profile?.bounds_profile] || "当前运行范围"],
        ["径流拟合", hydrologySummaryValue(summary, "flow_status_zh")],
        ["三水源构成", componentFractionText(componentReport)],
        ["口径", componentFractionBasisText(componentReport)],
        ["结果说明", hydrologySummaryValue(summary, "diagnostics_detail_note", "水文模拟结果说明已保存至本地结果目录。")],
        ["说明文件", reportDisplayPath ? shortPath(reportDisplayPath) : "结果目录内生成"],
        ["运行时间", meta.run_time],
        ["结果类型", run.run_type_label || runTypeLabel(run.run_type, manual ? "手调结果" : starter ? "手调起点" : run.run_origin === "studio" ? "可调结果" : "查看结果")],
        ["所属工作区", workspaceLabelByPath(meta.workspace_config || run.workspace_config)],
        ["率定时段", timeRangeText(timeCfg.calib_start, timeCfg.calib_end, stepHours)],
        ["验证时段", timeRangeText(timeCfg.valid_start, timeCfg.valid_end, stepHours)],
      ], helpers),
      restartRows.length ? metadataSection("起报状态与预报", restartRows, helpers) : "",
      floodRows.length ? metadataSection("洪水事件评价", floodRows, helpers) : "",
      `
        <section class="metadata-section">
          <h4>本地过程复核报告</h4>
          <div class="hint-box">页面显示摘要信息。详细水文过程复核已写入本地结果目录，供专业复核使用。</div>
          <div class="workspace-card-actions" style="margin-top:10px">
            ${run.path ? `<button class="ghost-button" data-run-detail-open-dir="${escapeHtml(run.path)}">打开结果目录</button>` : ""}
            ${reportPath ? `<button class="ghost-button" data-run-detail-open-report="${escapeHtml(reportPath)}">打开过程复核报告</button>` : ""}
          </div>
        </section>
      `,
    ].join("");
    const periodHint = runMetricsText(run);
    const baseText = editable
      ? manual
        ? "当前结果来自一次手调后的保存结果。继续改参数后，再点“保存并重算”，左侧会新增一条结果记录，图表和指标也会切换到最新结果。"
        : starter
          ? "当前结果是系统生成的手调起点。直接在下方改参数值，再点“保存并重算”，左侧会新增一条结果记录。"
          : "当前结果支持继续手调。直接在下方改参数值，再点“保存并重算”，左侧会新增一条结果记录，图表和指标也会切换到最新结果。"
      : "当前结果只支持查看。若要手动调参，请选择一个可调结果。";
    const legacyWarmupWarning = seriesRange.warmup_start && seriesRange.actual_start && !seriesRange.warmup_covered
      ? `当前这个历史结果实际从 ${compactTimeText(seriesRange.actual_start, stepHours)} 开始保存，未包含预热段；如果需要导出或查看预热期，请用新版程序重新生成一次结果。`
      : "";
    return {
      metadataHtml,
      hintText: [
        baseText,
        periodHint ? `当前图表与导出都覆盖${periodHint}。` : "",
        legacyWarmupWarning,
        "结果页只显示简要水文解释；完整过程复核请打开本地过程复核报告。",
      ].filter(Boolean).join(" "),
      hintClassName: `hint-box ${(editable && !legacyWarmupWarning) ? "status-ok" : "status-warn"}`.trim(),
    };
  }

  function renderRunExportFields(fields = [], helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    return (fields || []).map(field => `
      <label class="phase-chip" style="cursor:pointer">
        <input type="checkbox" data-run-export-field="${escapeHtml(field.key)}" ${field.checked ? "checked" : ""} style="margin-right:6px">
        ${escapeHtml(field.label)}
      </label>
    `).join("");
  }

  function runExportFields(options = {}) {
    const boundaryEnabled = Boolean(options.boundaryEnabled);
    return RUN_EXPORT_FIELDS
      .filter(field => field.key !== "q_boundary_inflow" || boundaryEnabled)
      .map(field => ({ ...field }));
  }

  function selectedRunExportFields(inputs = []) {
    return (Array.isArray(inputs) ? inputs : [])
      .filter(input => Boolean(input?.checked))
      .map(input => String(input?.dataset?.runExportField || "").trim())
      .filter(Boolean);
  }

  function resultChartPayloads(data = {}, options = {}, helpers = {}) {
    const palette = helpers.colors || DEFAULT_RESULT_CHART_COLORS;
    const series = data?.series || {};
    const dates = Array.isArray(series.dates) ? series.dates : [];
    const compare = options.compareSeries || null;
    const compareLabel = String(options.compareLabel || "").trim();
    const boundaryEnabled = Boolean(options.boundaryEnabled);
    const baseLayout = {
      margin: { t: 10, r: 10, b: 40, l: 55 },
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      xaxis: { title: "日期" },
      yaxis: { title: "流量 m\u00B3/s" },
      legend: { orientation: "h", y: 1.12 },
    };
    const hydrographTraces = [
      { x: dates, y: series.q_obs || [], name: "实测流量", mode: "lines", line: { color: palette.qObs, width: 1.6 } },
      { x: dates, y: series.q_sim || [], name: "模拟流量", mode: "lines", line: { color: palette.qSim, width: 1.8 } },
    ];
    if (compare?.q_sim?.length) {
      hydrographTraces.push({
        x: compare.dates || dates,
        y: compare.q_sim,
        name: compareLabel ? `对比：${compareLabel}` : "对比模拟",
        mode: "lines",
        line: { color: "#5b4a3a", width: 1.6, dash: "dash" },
      });
    }
    if (boundaryEnabled) {
      hydrographTraces.push({ x: dates, y: series.q_boundary_inflow || [], name: "边界入流", mode: "lines", line: { color: palette.boundary, width: 1.2 } });
    }
    const residualTraces = [
      { x: dates, y: series.residuals || [], name: "当前残差", mode: "lines", line: { color: palette.residual } },
    ];
    if (compare?.residuals?.length) {
      residualTraces.push({
        x: compare.dates || dates,
        y: compare.residuals,
        name: "对比残差",
        mode: "lines",
        line: { color: "#6f6255", width: 1.4, dash: "dash" },
      });
    }
    return {
      hydrograph: {
        traces: hydrographTraces,
        layout: baseLayout,
      },
      component: {
        traces: [
          { x: dates, y: series.q_rain || [], name: "降雨产流", mode: "lines", line: { color: palette.qRain } },
          { x: dates, y: series.q_snow || [], name: "融雪流量", mode: "lines", line: { color: palette.qSnow } },
          { x: dates, y: series.q_ice || [], name: "裸冰融化流量", mode: "lines", line: { color: palette.qIce } },
        ],
        layout: { ...baseLayout, yaxis: { title: "流量 m\u00B3/s" } },
      },
      residual: {
        traces: residualTraces,
        layout: { ...baseLayout, yaxis: { title: "残差 m\u00B3/s" } },
      },
    };
  }

  function runExportPanelState(data = {}, options = {}, helpers = {}) {
    const formatInputTime = helpers.formatInputTime || (value => String(value || "").trim());
    const stepHours = runStepHours(data);
    const hourly = stepHours <= 1.5;
    const timeCfg = data?.metadata?.time_config || {};
    const dates = Array.isArray(data?.series?.dates) ? data.series.dates : [];
    const startValue = timeCfg.warmup_start || timeCfg.calib_start || dates[0] || "";
    const endValue = timeCfg.valid_end || dates[dates.length - 1] || "";
    const hasRunPath = Boolean(data?.run?.path);
    const hasExportPath = Boolean(options.lastExportPath);
    const start = {
      type: hourly ? "datetime-local" : "date",
      step: hourly ? "60" : "",
      value: formatInputTime(startValue, hourly),
    };
    const end = {
      type: hourly ? "datetime-local" : "date",
      step: hourly ? "60" : "",
      value: formatInputTime(endValue, hourly),
    };
    const exportDisabled = !hasRunPath;
    const openDisabled = !hasExportPath;
    const hintText = hasRunPath
      ? hourly
        ? "当前结果已保存预热至验证全时段。默认已带入全时段，小时结果会导出到当前结果目录下的“导出”子目录，时间范围按分钟精度填写。"
        : "当前结果已保存预热至验证全时段。默认已带入全时段，日尺度结果会导出到当前结果目录下的“导出”子目录。"
      : "选择一个结果后，可按时间范围导出 Excel。";
    const hintClassName = "hint-box";
    return {
      stepHours,
      hourly,
      start,
      end,
      exportDisabled,
      openDisabled,
      hintText,
      hintClassName,
      domUpdates: [
        { selector: "#run-export-start", type: start.type, step: start.step, value: start.value },
        { selector: "#run-export-end", type: end.type, step: end.step, value: end.value },
        { selector: "#btn-run-export", disabled: exportDisabled },
        { selector: "#btn-open-export-file", disabled: openDisabled },
        { selector: "#run-export-hint", text: hintText, className: hintClassName },
      ],
    };
  }

  function runExportPayload(data = {}, fields = [], range = {}, helpers = {}) {
    const fromInputTime = helpers.fromInputTime || ((value) => String(value || "").trim());
    const runPath = String(data?.run?.path || "").trim();
    const selectedFields = (Array.isArray(fields) ? fields : [])
      .map(field => String(field || "").trim())
      .filter(Boolean);
    if (!runPath) {
      return {
        ok: false,
        reason: "missing-run",
        message: "请先选择一个结果。",
        payload: null,
      };
    }
    if (!selectedFields.length) {
      return {
        ok: false,
        reason: "missing-fields",
        message: "请至少勾选一个导出字段。",
        payload: null,
      };
    }
    const hourly = runStepHours(data) <= 1.5;
    return {
      ok: true,
      reason: "",
      message: "",
      hourly,
      payload: {
        path: runPath,
        start_date: fromInputTime(range.start, hourly),
        end_date: fromInputTime(range.end, hourly),
        fields: selectedFields,
      },
    };
  }

  function runExportSuccess(responseData = {}, helpers = {}) {
    const shortPath = helpers.shortPath || (value => String(value || ""));
    const exportPath = String(responseData?.path || "");
    const rowCount = Number(responseData?.row_count || 0);
    const displayPath = responseData?.display_path || shortPath(exportPath);
    const openExportDisabled = !exportPath;
    const hintText = `已导出 ${rowCount} 行到 ${displayPath}。`;
    const hintClassName = "hint-box status-ok";
    return {
      exportPath,
      rowCount,
      displayPath,
      openExportDisabled,
      hintText,
      hintClassName,
      toastText: `Excel 已导出：${rowCount} 行`,
      domUpdates: [
        { selector: "#btn-open-export-file", disabled: openExportDisabled },
        { selector: "#run-export-hint", text: hintText, className: hintClassName },
      ],
      statePatch: {
        lastRunExportPath: exportPath,
      },
    };
  }

  window.HBVStudioResultsView = {
    alignedRunFiltersForSelection,
    clearRunComparisonState,
    clearRunDetailState,
    clearRunDetailViewState,
    filterRuns,
    forwardSimulationErrorState,
    forwardSimulationPreflight,
    forwardSimulationRequestContext,
    forwardSimulationResultState,
    forwardSimulationStartState,
    forwardSimulationTaskUiState,
    latestEditableRunPath,
    manualStarterControlState,
    resultMetricItems,
    renderFilterToolbar,
    renderMetricStrip,
    renderRunCard,
    renderRunCards,
    renderRunDetailMetadata,
    renderRunEngineeringSummary,
    renderRunExportFields,
    resultChartPayloads,
    resultsFilterBreakdown,
    resultsFilterHint,
    runExportFields,
    runExportPanelState,
    runExportPayload,
    runExportSuccess,
    runComparisonClearViewState,
    runComparisonErrorState,
    runComparisonPreflight,
    runComparisonRequestContext,
    runComparisonRequestStillCurrent,
    runComparisonSuccessState,
    runDetailState,
    runListState,
    runManualPresetLoadErrorState,
    runManualPresetLoadStartState,
    runManualPresetLoadSuccessState,
    runProfileValue,
    runsForWorkspace,
    selectedRunExportFields,
    selectedRunPath,
    runStepHours,
    workspaceHasEditableRun,
  };
})();
