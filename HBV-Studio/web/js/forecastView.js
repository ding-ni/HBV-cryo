(function () {
  function defaultEscapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function finiteSeries(values) {
    return Array.isArray(values) && values.some(value => Number.isFinite(Number(value)));
  }

  function chartColors() {
    return window.HBVStudioChartPalette?.chartColors?.() || {
      qObs: "#1e293b",
      qSim: "#0e7490",
      qRain: "#2563eb",
      qSnow: "#38bdf8",
      qIce: "#06b6d4",
      boundary: "#64748b",
    };
  }

  function forecastStepHours(run = {}) {
    return Number(run?.time_step_hours || run?.time_config?.time_step_hours || 24);
  }

  function forecastInputType(run = {}) {
    return forecastStepHours(run) <= 1.5 ? "datetime-local" : "date";
  }

  function parseForecastTime(value) {
    const raw = String(value || "").trim();
    if (!raw) return null;
    const dateOnly = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (dateOnly) {
      return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]), 0, 0, 0, 0);
    }
    const normalized = raw.replace(" ", "T");
    const dt = new Date(normalized);
    return Number.isNaN(dt.getTime()) ? null : dt;
  }

  function formatForecastInputTime(date, stepHours) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";
    const pad = value => String(value).padStart(2, "0");
    const y = date.getFullYear();
    const m = pad(date.getMonth() + 1);
    const d = pad(date.getDate());
    if (Number(stepHours || 24) <= 1.5) {
      return `${y}-${m}-${d}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }
    return `${y}-${m}-${d}`;
  }

  function forecastSuggestedStart(run = {}) {
    const stepHours = forecastStepHours(run);
    const stateTime = run?.state_snapshot_time || run?.time_config?.forecast_end || run?.time_config?.valid_end || run?.time_config?.calib_end || "";
    const dt = parseForecastTime(stateTime);
    if (!dt) return "";
    dt.setMinutes(dt.getMinutes() + Math.round(stepHours * 60));
    return formatForecastInputTime(dt, stepHours);
  }

  function forecastTimeComparable(value, run = {}) {
    const stepHours = forecastStepHours(run);
    const dt = parseForecastTime(value);
    return dt ? formatForecastInputTime(dt, stepHours) : String(value || "").trim();
  }

  function forecastCandidateRuns(runs = [], helpers = {}) {
    const runTypeValue = helpers.runTypeValue || (run => run?.run_type || run?.kind || "");
    const allowed = new Set(["calibration", "manual_result", "manual_starter", "forecast_restart"]);
    const items = Array.isArray(runs) ? runs : [];
    return items.filter(run => Boolean(run?.path) && allowed.has(runTypeValue(run)));
  }

  function forecastRunReady(run = null) {
    if (!run) return false;
    if (run.forecast_source_ready !== undefined) return Boolean(run.forecast_source_ready);
    return Boolean(run.path && run.studio_compatible);
  }

  function forecastRunReadinessText(run = null, helpers = {}) {
    const isReady = helpers.forecastRunReady || forecastRunReady;
    if (!run) return "未选择源结果";
    if (isReady(run)) return "可起报";
    if (run.optimized_params_available === false) return "缺少率定参数";
    if (run.state_snapshot_available === false) return "缺少起报状态";
    return "需用新版结果";
  }

  function pickForecastSourceRun(candidates = [], preferredPath = "", helpers = {}) {
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const isReady = helpers.forecastRunReady || forecastRunReady;
    const items = Array.isArray(candidates) ? candidates : [];
    const targetPath = String(preferredPath || "").trim();
    if (targetPath) {
      const matched = items.find(run => samePath(run?.path, targetPath));
      if (matched) return matched;
    }
    return items.find(isReady) || items[0] || null;
  }

  function forecastSelectedSourceRun(candidates = [], selectedPath = "", helpers = {}) {
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const items = Array.isArray(candidates) ? candidates : [];
    const targetPath = String(selectedPath || "").trim();
    if (!targetPath) return null;
    return items.find(run => samePath(run?.path, targetPath)) || null;
  }

  function forecastSourceSelectionState(path = "") {
    return {
      statePatch: {
        forecastSourceRunPath: String(path || "").trim(),
      },
    };
  }

  function forecastSourceOptionsState(candidates = [], preferredPath = "", helpers = {}) {
    const selected = pickForecastSourceRun(candidates, preferredPath, helpers);
    const selectedPath = selected?.path || "";
    return {
      selected,
      selectedPath,
      statePatch: forecastSourceSelectionState(selectedPath).statePatch,
    };
  }

  function forecastResultRuns(runs = [], helpers = {}) {
    const runTypeValue = helpers.runTypeValue || (run => run?.run_type || run?.kind || "");
    const items = Array.isArray(runs) ? runs : [];
    return items
      .filter(run => runTypeValue(run) === "forecast_restart" && run?.path)
      .sort((a, b) => Number(b?.updated_at || 0) - Number(a?.updated_at || 0));
  }

  function forecastSelectedResultRun(runs = [], selectedPath = "", helpers = {}) {
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const items = Array.isArray(runs) ? runs : [];
    const targetPath = String(selectedPath || "").trim();
    if (targetPath) {
      const matched = items.find(run => samePath(run?.path, targetPath));
      if (matched) return matched;
    }
    return items[0] || null;
  }

  function forecastResultPanelState(runs = [], selectedPath = "", context = {}, helpers = {}) {
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const items = Array.isArray(runs) ? runs : [];
    if (!items.length) {
      return {
        hasRuns: false,
        selected: null,
        selectedPath: "",
        selectDisabled: true,
        renderMode: "empty",
        loadPath: "",
        statePatch: forecastResultSelectionState("").statePatch,
      };
    }
    const selected = forecastSelectedResultRun(items, selectedPath, { samePath }) || items[0];
    const resolvedPath = selected?.path || "";
    const currentData = context?.currentData || null;
    const loadingPath = String(context?.loadingPath || "").trim();
    let renderMode = "load";
    if (currentData?.run?.path && samePath(currentData.run.path, resolvedPath)) {
      renderMode = "detail";
    } else if (loadingPath && samePath(loadingPath, resolvedPath)) {
      renderMode = "loading";
    }
    return {
      hasRuns: true,
      selected,
      selectedPath: resolvedPath,
      selectDisabled: false,
      renderMode,
      loadPath: renderMode === "load" ? resolvedPath : "",
      statePatch: {
        forecastResultRunPath: resolvedPath,
      },
    };
  }

  function forecastResultDetailState(data = null, selectedRun = null) {
    const dataRun = data?.run || null;
    const hasDetail = Boolean(dataRun?.path);
    return {
      renderMode: hasDetail ? "detail" : "empty",
      buttonRun: dataRun || selectedRun || null,
      detailData: hasDetail ? data : null,
    };
  }

  function forecastResultLoadStartState(path = "") {
    const targetPath = String(path || "").trim();
    if (!targetPath) {
      return {
        ok: false,
        targetPath: "",
        statePatch: null,
        buttonRun: null,
      };
    }
    return {
      ok: true,
      targetPath,
      statePatch: {
        forecastResultRunPath: targetPath,
        forecastResultLoadingPath: targetPath,
        lastForecastExportPath: "",
      },
      buttonRun: { path: targetPath },
    };
  }

  function forecastResultLoadSuccessState(data = null) {
    return {
      statePatch: {
        forecastResultData: data || null,
        forecastResultLoadingPath: "",
      },
      detailData: data || null,
    };
  }

  function forecastResultLoadErrorState() {
    return {
      statePatch: {
        forecastResultData: null,
        forecastResultLoadingPath: "",
      },
      buttonRun: null,
    };
  }

  function forecastResultSelectionState(path = "") {
    return {
      statePatch: {
        forecastResultRunPath: String(path || "").trim(),
        forecastResultData: null,
        forecastResultLoadingPath: "",
        lastForecastExportPath: "",
      },
    };
  }

  function forecastCompletedResultState(task = null) {
    const runPath = String(
      task?.result?.run_path ||
      task?.run_path ||
      task?.detected_runs?.[0] ||
      "",
    ).trim();
    if (!runPath) {
      return { ok: false, runPath: "", statePatch: null };
    }
    return {
      ok: true,
      runPath,
      statePatch: forecastResultSelectionState(runPath).statePatch,
    };
  }

  function forecastInputPayload(run = {}, fields = {}, options = {}) {
    const text = value => String(value || "").trim();
    return {
      source_run: text(run?.path),
      config_path: text(run?.workspace_config || options.fallbackConfigPath || ""),
      forecast_start: text(fields.forecast_start),
      forecast_end: text(fields.forecast_end),
      forecast_prec_dir: text(fields.forecast_prec_dir),
      forecast_temp_dir: text(fields.forecast_temp_dir),
      forecast_evap_dir: text(fields.forecast_evap_dir),
      time_step_hours: forecastStepHours(run),
    };
  }

  function forecastRestartPayload(run = {}, fields = {}, options = {}) {
    const text = value => String(value || "").trim();
    const input = forecastInputPayload(run, fields, options);
    return {
      source_run: input.source_run,
      config_path: input.config_path,
      forecast_start: input.forecast_start,
      forecast_end: input.forecast_end,
      forecast_prec_dir: input.forecast_prec_dir,
      forecast_temp_dir: input.forecast_temp_dir,
      forecast_evap_dir: input.forecast_evap_dir,
      profile: text(options.profile),
      objective_mode: text(run?.effective_objective_mode || run?.objective_family || run?.recorded_objective_family || options.defaultObjectiveMode || ""),
      prec_source: "custom_tif",
      glacier_mode: text(fields.glacier_mode || options.glacierMode || "inline") || "inline",
    };
  }

  function forecastRestartPreflight(run = null, fields = {}, helpers = {}) {
    const text = value => String(value || "").trim();
    const isReady = helpers.forecastRunReady || forecastRunReady;
    const suggestedStart = helpers.forecastSuggestedStart || forecastSuggestedStart;
    const timeComparable = helpers.forecastTimeComparable || forecastTimeComparable;
    if (!run) {
      return { ok: false, message: "请先选择源结果。" };
    }
    if (!isReady(run)) {
      return { ok: false, message: "源结果缺少率定参数或起报状态，不能启动连续状态预报。" };
    }
    const forecastStart = text(fields.forecast_start);
    const forecastEnd = text(fields.forecast_end);
    const precDir = text(fields.forecast_prec_dir);
    const tempDir = text(fields.forecast_temp_dir);
    const evapDir = text(fields.forecast_evap_dir);
    if (!forecastEnd) {
      return { ok: false, message: "请填写预报结束时间。" };
    }
    const expectedStart = suggestedStart(run);
    if (forecastStart && expectedStart && timeComparable(forecastStart, run) !== timeComparable(expectedStart, run)) {
      return {
        ok: false,
        message: `预报开始时间必须紧接源结果保存状态，当前应从 ${expectedStart.replace("T", " ")} 起报。`,
        expectedStart,
      };
    }
    if (!precDir || !tempDir || !evapDir) {
      return { ok: false, message: "请完整选择预报降水、气温和潜在蒸散发栅格目录。" };
    }
    return { ok: true, message: "", expectedStart };
  }

  function forecastInputCheckError(error = null) {
    const rawMessage = error?.message || (typeof error === "string" ? error : "");
    const message = String(rawMessage || "预报气象输入检查失败。").trim() || "预报气象输入检查失败。";
    return {
      status: "fail",
      headline: "预报气象输入检查失败。",
      errors: [message],
      warnings: [],
      items: [],
      variables: [],
    };
  }

  function forecastInputCheckDecision(check = null) {
    if (!check || check.status === "fail") {
      return {
        blocked: true,
        isError: true,
        message: check?.errors?.[0] || "预报气象输入检查未通过。",
      };
    }
    if (check.status === "warn") {
      return {
        blocked: false,
        isError: false,
        message: check?.warnings?.[0] || "预报气象目录存在提示，系统将按预报窗口筛选归档。",
      };
    }
    return {
      blocked: false,
      isError: false,
      message: "",
    };
  }

  function forecastResultExportPayload(data = {}, selectedRun = null, helpers = {}) {
    const boundaryEnabledFromMeta = helpers.boundaryEnabledFromMeta || (() => false);
    const runPath = String(data?.run?.path || selectedRun?.path || "").trim();
    if (!runPath) return null;
    const meta = data?.metadata || {};
    const series = data?.series || {};
    const dates = Array.isArray(series.dates) ? series.dates : [];
    const start = meta.time_config?.forecast_start || meta.forecast_result?.forecast_start || dates[0] || "";
    const end = meta.time_config?.forecast_end || meta.forecast_result?.forecast_end || dates.slice(-1)[0] || "";
    const fields = ["q_sim", "q_rain", "q_snow", "q_ice"];
    if (boundaryEnabledFromMeta(meta)) fields.push("q_boundary_inflow");
    return {
      path: runPath,
      start_date: start,
      end_date: end,
      fields,
    };
  }

  function forecastResultExportSuccess(responseData = {}, lastExportPath = "", helpers = {}) {
    const shortPath = helpers.shortPath || (value => String(value || ""));
    const rowCount = Number(responseData?.row_count || 0);
    const displayPath = responseData?.display_path || shortPath(lastExportPath);
    return {
      rowCount,
      displayPath,
      hintText: `已导出 ${rowCount} 行到 ${displayPath}。`,
      toastText: `预报结果 Excel 已导出：${rowCount} 行`,
    };
  }

  function forecastResultExportState(responseData = {}) {
    const exportPath = String(responseData?.path || "");
    return {
      exportPath,
      statePatch: {
        lastForecastExportPath: exportPath,
      },
    };
  }

  function forecastResultButtonState(run = null, lastExportPath = "") {
    const hasRun = Boolean(run?.path);
    const hasExportPath = Boolean(lastExportPath);
    return {
      openResultDisabled: !hasRun,
      openResultDirDisabled: !hasRun,
      exportExcelDisabled: !hasRun,
      openExportFileDisabled: !hasExportPath,
    };
  }

  function renderForecastResultOptions(runs = [], selectedPath = "", helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const timeRangeText = helpers.timeRangeText || ((start, end) => [start, end].filter(Boolean).join(" ~ ") || "—");
    const forecastFriendlyRunName = helpers.forecastFriendlyRunName || (run => run?.display_name || run?.name || "连续状态预报结果");
    const items = Array.isArray(runs) ? runs : [];
    const selected = forecastSelectedResultRun(items, selectedPath, { samePath });
    return {
      selected,
      html: items.length
        ? items.map(run => {
          const range = timeRangeText(
            run?.time_config?.forecast_start,
            run?.time_config?.forecast_end,
            run?.time_step_hours || run?.time_config?.time_step_hours || 24,
          );
          const friendly = forecastFriendlyRunName(run);
          const label = range && range !== "—" && !friendly.includes(range) ? `${friendly} · ${range}` : friendly;
          return `
            <option value="${escapeHtml(run?.path || "")}" ${selected && samePath(run?.path, selected.path) ? "selected" : ""}>
              ${escapeHtml(label)}
            </option>
          `;
        }).join("")
        : '<option value="">暂无连续状态预报结果</option>',
    };
  }

  function forecastArchiveManifest(archive = {}) {
    return archive?.manifest || {};
  }

  function forecastArchiveVariables(archive = {}) {
    return forecastArchiveManifest(archive).variables || archive?.variables || {};
  }

  function forecastArchiveVariableItems(archive = {}, helpers = {}) {
    const timeRangeText = helpers.timeRangeText || ((start, end) => [start, end].filter(Boolean).join(" ~ ") || "—");
    const shortPath = helpers.shortPath || defaultShortPath;
    const manifest = forecastArchiveManifest(archive);
    const variables = forecastArchiveVariables(archive);
    const labels = { prec: "降水", temp: "气温", evap: "潜在蒸散发" };
    return ["prec", "temp", "evap"].map(key => {
      const item = variables?.[key] || {};
      if (!item || !Object.keys(item).length) return null;
      const label = item.label || labels[key] || key;
      const expected = Number(item.expected_steps ?? manifest.expected_steps ?? 0);
      const archived = Number(item.archived_files ?? item.file_count ?? 0);
      const outside = Number(item.out_of_window_files ?? 0);
      const value = expected > 0
        ? `${archived || 0}/${expected} 个时步`
        : archived > 0 ? `${archived} 个文件` : "已归档";
      const detailParts = [];
      if (item.first_time || item.last_time) detailParts.push(`时段：${timeRangeText(item.first_time, item.last_time)}`);
      if (outside > 0) detailParts.push(`窗口外 ${outside} 个文件未纳入`);
      if (item.archive_dir) detailParts.push(`归档：${shortPath(item.archive_dir)}`);
      return { key, label, value, detail: detailParts.join("；") || "已纳入本次预报计算" };
    }).filter(Boolean);
  }

  function forecastArchiveSummaryText(archive = {}, fallback = "未记录预报气象归档", helpers = {}) {
    const manifest = forecastArchiveManifest(archive);
    const items = forecastArchiveVariableItems(archive, helpers);
    if (!archive?.manifest_path && !items.length) return fallback;
    const expected = Number(manifest.expected_steps || items[0]?.value?.match(/\d+\/(\d+)/)?.[1] || 0);
    if (expected > 0) return `已归档 ${expected} 个预报时步`;
    return "已归档预报气象";
  }

  function forecastArchiveDetailText(archive = {}, fallback = "预报完成后将归档实际使用的降水、气温和潜在蒸散发栅格", helpers = {}) {
    const items = forecastArchiveVariableItems(archive, helpers);
    if (!archive?.manifest_path && !items.length) return fallback;
    const timeRangeText = helpers.timeRangeText || ((start, end) => [start, end].filter(Boolean).join(" ~ ") || "—");
    const manifest = forecastArchiveManifest(archive);
    const parts = [];
    if (manifest.forecast_start || manifest.forecast_end) {
      parts.push(`窗口：${timeRangeText(manifest.forecast_start, manifest.forecast_end)}`);
    }
    if (items.length) {
      parts.push(items.map(item => `${item.label}${item.value}`).join("，"));
    }
    if (archive?.manifest_path) {
      parts.push("输入归档清单已保存");
    }
    return parts.join("；") || "已保存本次预报实际使用的气象输入";
  }

  function forecastParameterSourceSummary(source = {}, fallback = {}, helpers = {}) {
    const objectiveLabel = helpers.objectiveLabel || (value => String(value || ""));
    const profileLabel = helpers.profileLabel || (value => String(value || ""));
    const readableRunReferenceName = helpers.readableRunReferenceName || ((value, fallbackText = "") => String(value || fallbackText || "").trim());
    const params = fallback?.optimized_params || {};
    const count = Number(source.parameter_count ?? fallback.optimized_param_count ?? (params && typeof params === "object" ? Object.keys(params).length : 0));
    const label = source.parameter_source_label || "源结果参数";
    const objectiveRaw = source.objective_mode || fallback.effective_objective_mode || fallback.objective_family || fallback.recorded_objective_family || "";
    const objective = objectiveRaw ? objectiveLabel(objectiveRaw) : "";
    const profile = source.calibration_profile || fallback.calibration_profile || "";
    const sourceName = source.source_run_name || fallback.source_run_name || "";
    const sourceLabel = readableRunReferenceName(sourceName, fallback.workspace_name || fallback.source_workspace || "");
    const detailParts = [];
    if (sourceLabel) detailParts.push(`来源：${sourceLabel}`);
    if (profile) detailParts.push(profileLabel(profile));
    if (objective) detailParts.push(`目标函数：${objective}`);
    if (source.state_snapshot_time) detailParts.push(`状态时刻：${source.state_snapshot_time}`);
    return {
      value: `${label}${count > 0 ? `（${count} 项）` : ""}`,
      detail: detailParts.join("；") || "读取源结果保存的最优参数，不重新率定",
    };
  }

  function renderForecastSourceOptions(candidates = [], selectedPath = "", helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const forecastFriendlyRunName = helpers.forecastFriendlyRunName || (run => run?.display_name || run?.name || "未命名结果");
    const readinessText = helpers.forecastRunReadinessText || forecastRunReadinessText;
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const items = Array.isArray(candidates) ? candidates : [];
    return {
      disabled: !items.length,
      html: items.length
        ? items.map(run => {
          const label = `${forecastFriendlyRunName(run)} · ${readinessText(run)}`;
          return `<option value="${escapeHtml(run?.path || "")}" ${samePath(run?.path, selectedPath) ? "selected" : ""}>${escapeHtml(label)}</option>`;
        }).join("")
        : '<option value="">暂无可选源结果</option>',
    };
  }

  function renderForecastSourceSummary(run = null, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const sourceReady = helpers.forecastRunReady || forecastRunReady;
    const readinessText = helpers.forecastRunReadinessText || forecastRunReadinessText;
    const runTypeValue = helpers.runTypeValue || (item => item?.run_type || "");
    const runTypeLabel = helpers.runTypeLabel || (value => value || "结果");
    const profileLabel = helpers.profileLabel || (value => value || "—");
    const runProfileValue = helpers.runProfileValue || (item => item?.calibration_profile || "");
    const objectiveLabel = helpers.objectiveLabel || (value => value || "—");
    const runDisplayName = helpers.runDisplayName || (item => item?.display_name || item?.name || "未命名结果");
    const forecastFriendlyRunName = helpers.forecastFriendlyRunName || runDisplayName;
    const forecastSuggestedStart = helpers.forecastSuggestedStart || (() => "");
    const forecastArchiveSummaryTextHelper = helpers.forecastArchiveSummaryText || forecastArchiveSummaryText;
    const forecastArchiveDetailTextHelper = helpers.forecastArchiveDetailText || forecastArchiveDetailText;
    const forecastParameterSourceSummaryHelper = helpers.forecastParameterSourceSummary || forecastParameterSourceSummary;
    const forecastParameterContextHtml = helpers.forecastParameterContextHtml || (() => "");
    const runWorkspaceName = helpers.runWorkspaceName || (() => "");
    if (!run) {
      return {
        html: '<div class="hint-box status-warn" style="margin-top:12px">当前没有可作为预报起点的率定或手调结果。</div>',
        hintText: "完成一次新版率定或手调重算后，可在这里直接接入未来气象驱动。",
        hintClassName: "hint-box status-warn",
        ready: false,
        suggestedStart: "",
      };
    }
    const ready = sourceReady(run);
    const stateTime = run.state_snapshot_time || run.time_config?.forecast_end || run.time_config?.valid_end || run.time_config?.calib_end || "";
    const sourceStateTime = run.source_state_snapshot_time || "";
    const sourceType = runTypeLabel(runTypeValue(run));
    const objective = objectiveLabel(run.effective_objective_mode || run.objective_family || run.recorded_objective_family || "");
    const archive = run.forecast_input_archive || {};
    const parameterSource = forecastParameterSourceSummaryHelper(run.source_parameter_summary || {}, run);
    const archiveText = forecastArchiveSummaryTextHelper(archive, runTypeValue(run) === "forecast_restart" ? "未记录气象归档" : "待本次预报生成");
    const archiveDetail = forecastArchiveDetailTextHelper(archive);
    const suggestedStart = forecastSuggestedStart(run);
    return {
      html: `
        <div class="forecast-source-card ${ready ? "status-ok" : "status-warn"}">
          <div class="forecast-source-card-head">
            <strong title="${escapeHtml(runDisplayName(run))}">${escapeHtml(forecastFriendlyRunName(run))}</strong>
            <span class="status-badge ${ready ? "status-ok" : "status-warn"}">${escapeHtml(readinessText(run))}</span>
          </div>
          <div class="forecast-source-meta">
            <span>结果类型</span><strong>${escapeHtml(sourceType)}</strong>
            <span>计算尺度</span><strong>${escapeHtml(profileLabel(runProfileValue(run)))}</strong>
            <span>状态时间</span><strong>${escapeHtml(stateTime || "未记录")}</strong>
            ${suggestedStart ? `<span>建议起报</span><strong>${escapeHtml(suggestedStart.replace("T", " "))}</strong>` : ""}
            ${sourceStateTime ? `<span>来源状态</span><strong>${escapeHtml(sourceStateTime)}</strong>` : ""}
            <span>目标函数</span><strong>${escapeHtml(objective)}</strong>
            <span>参数来源</span><strong title="${escapeHtml(parameterSource.detail)}">${escapeHtml(parameterSource.value)}</strong>
            <span>预报气象</span><strong title="${escapeHtml(archiveDetail)}">${escapeHtml(archiveText)}</strong>
          </div>
          ${forecastParameterContextHtml(run)}
          <small>${escapeHtml(run.workspace_name || runWorkspaceName(run) || "未关联工作区")}</small>
        </div>
      `,
      hintText: ready
        ? `预报运行将读取源结果的参数与末端状态，不重新率定；建议从 ${suggestedStart ? suggestedStart.replace("T", " ") : "源结果状态后一时间步"} 起报。若要从更晚时间起报，需要先补充历史气象强迫滚动更新状态。`
        : "该源结果不能直接用于预报，请优先使用新版率定、手调结果或已保存起报状态的预报结果。",
      hintClassName: `hint-box ${ready ? "status-ok" : "status-warn"}`,
      ready,
      suggestedStart,
    };
  }

  function restartStateRows(meta = {}, helpers = {}) {
    const shortPath = helpers.shortPath || defaultShortPath;
    const timeRangeText = helpers.timeRangeText || ((start, end) => [start, end].filter(Boolean).join(" ~ ") || "—");
    const parameterSourceSummary = helpers.forecastParameterSourceSummary || ((source, fallback) => forecastParameterSourceSummary(source, fallback, helpers));
    const archiveSummaryText = helpers.forecastArchiveSummaryText || ((archive, fallback) => forecastArchiveSummaryText(archive, fallback, helpers));
    const archiveDetailText = helpers.forecastArchiveDetailText || ((archive, fallback) => forecastArchiveDetailText(archive, fallback, helpers));
    const archiveVariableItems = helpers.forecastArchiveVariableItems || (archive => forecastArchiveVariableItems(archive, helpers));
    const initial = meta?.initial_state || {};
    const forecast = meta?.forecast_result || {};
    const rows = [];
    if (initial?.state_snapshot_available || initial?.hot_start_supported || forecast?.enabled) {
      rows.push([
        "起报状态",
        initial?.hot_start_enabled || forecast?.enabled ? "可用" : "未启用",
        initial?.state_snapshot_file ? `起报状态文件：${initial.state_snapshot_file}` : "当前结果未记录可用于预报的起报状态",
      ]);
      rows.push([
        "状态时刻",
        initial?.state_snapshot_time || forecast?.forecast_end || "—",
        initial?.state_snapshot_routing_state ? "包含汇流上一时刻记忆" : "未记录汇流记忆",
      ]);
    }
    if (forecast?.enabled) {
      rows.push([
        "预报来源",
        forecast?.source_run_name || "源结果",
        forecast?.source_run_path ? shortPath(forecast.source_run_path) : "读取源结果参数与起报状态",
      ]);
      const parameterSource = parameterSourceSummary(
        forecast?.source_parameter_summary || meta?.source_parameter_summary || {},
        meta,
      );
      rows.push([
        "参数来源",
        parameterSource.value,
        parameterSource.detail,
      ]);
      rows.push([
        "预报时段",
        timeRangeText(forecast?.forecast_start, forecast?.forecast_end, meta?.time_config?.time_step_hours || 24),
        "不重新率定参数，直接接续未来气象输入",
      ]);
      const archive = forecast?.forecast_input_archive || meta?.data_sources?.forecast_input_archive || {};
      rows.push([
        "预报气象",
        archiveSummaryText(archive),
        archiveDetailText(archive),
      ]);
      archiveVariableItems(archive).forEach(item => {
        rows.push([
          item.label,
          item.value,
          item.detail,
        ]);
      });
    }
    return rows;
  }

  function setHint(message, status = "") {
    const hint = document.getElementById("forecast-result-hint");
    if (!hint) return;
    hint.textContent = message || "";
    hint.className = `hint-box ${status}`.trim();
  }

  function clearChart(message = "当前没有可显示的预报过程线。") {
    const chart = document.getElementById("forecast-result-chart");
    if (!chart) return;
    if (window.Plotly) {
      try { window.Plotly.purge(chart); } catch {}
    }
    chart.innerHTML = message ? `<div class="hint-box">${message}</div>` : "";
  }

  function renderForecastResultEmpty(message) {
    const summary = document.getElementById("forecast-result-summary");
    if (summary) summary.innerHTML = "";
    clearChart("当前没有可显示的预报过程线。");
    setHint(message || "完成连续状态预报后，将在这里查看过程线、起报依据和输入资料。", "status-warn");
  }

  function renderForecastResultLoading(message) {
    const summary = document.getElementById("forecast-result-summary");
    if (summary) summary.innerHTML = "";
    clearChart("");
    setHint(message || "正在读取预报结果。");
  }

  function defaultStatusClass(status) {
    const key = String(status || "").toLowerCase();
    return key === "ok" ? "status-ok" : key === "fail" ? "status-fail" : "status-warn";
  }

  function defaultStatusLabel(status) {
    const key = String(status || "").toLowerCase();
    if (key === "ok") return "通过";
    if (key === "fail") return "未通过";
    return "需复核";
  }

  function defaultShortPath(value) {
    const text = String(value || "").replace(/\\/g, "/");
    return text ? text.replace(/^.*\/([^/]+)$/, "$1") : "—";
  }

  function textOrDash(value, fallback = "—") {
    const text = String(value ?? "").trim();
    return text || fallback;
  }

  function rangeText(start, end) {
    const left = String(start || "").trim();
    const right = String(end || "").trim();
    if (left && right) return `${left} 至 ${right}`;
    return left || right || "未完整填写";
  }

  function isOkStatus(status) {
    return String(status || "").toLowerCase() === "ok";
  }

  function stepText(count) {
    const number = Number(count || 0);
    return Number.isFinite(number) && number > 0 ? `${number} 个时间步` : "等待完整时段";
  }

  function variableLabel(key, fallback) {
    return fallback || ({ prec: "降水", temp: "气温", evap: "潜在蒸散发" }[key] || key || "气象变量");
  }

  function variableDetailText(item = {}) {
    if (item.first_time || item.last_time) return rangeText(item.first_time, item.last_time);
    if (item.path) return "目录已选择，等待按预报窗口核对";
    return "未选择目录";
  }

  function variableOverview(variables = [], expectedSteps = 0) {
    const checked = variables.filter(item => item && typeof item === "object");
    if (!checked.length) return { value: "尚未检查气象驱动", detail: "填写 P/T/PET 目录后自动核对", status: "warn" };
    const complete = checked.every(item => isOkStatus(item.status));
    const fail = checked.some(item => String(item.status || "").toLowerCase() === "fail");
    const counts = checked.map(item => {
      const label = variableLabel(item.key, item.label);
      const covered = Number(item.covered_steps ?? item.valid_time_steps ?? 0);
      const expected = Number(item.expected_steps ?? expectedSteps ?? 0);
      return expected > 0 ? `${label}${covered}/${expected}` : `${label}${Number(item.valid_time_steps || 0)}步`;
    }).join("，");
    return {
      value: complete ? "三类气象驱动完整" : fail ? "气象驱动需补齐" : "气象驱动需复核",
      detail: counts || "按预报窗口核对降水、气温和潜在蒸散发",
      status: complete ? "ok" : fail ? "fail" : "warn",
    };
  }

  function renderTechnicalDetails(rows = [], escapeHtml = defaultEscapeHtml, title = "技术细节") {
    const cleanRows = rows
      .map(row => [String(row?.[0] || "").trim(), String(row?.[1] || "").trim()])
      .filter(([label, value]) => label && value);
    if (!cleanRows.length) return "";
    return `
      <details class="forecast-technical-details">
        <summary>${escapeHtml(title)}</summary>
        <dl>
          ${cleanRows.map(([label, value]) => `
            <dt>${escapeHtml(label)}</dt>
            <dd title="${escapeHtml(value)}">${escapeHtml(value)}</dd>
          `).join("")}
        </dl>
      </details>
    `;
  }

  function forecastInputTechnicalRows(check = {}) {
    const source = check.source || {};
    const output = check.output || {};
    const variables = Array.isArray(check.variables) ? check.variables : [];
    const rows = [];
    if (source.source_run_name) rows.push(["源结果目录名", source.source_run_name]);
    if (source.source_run) rows.push(["源结果路径", source.source_run]);
    if (output.result_detail || output.result_dir) rows.push(["结果目录预览", output.result_detail || output.result_dir]);
    if (output.archive_detail || output.manifest_path) rows.push(["输入归档清单", output.archive_detail || output.manifest_path]);
    variables.forEach(item => {
      if (item?.path) rows.push([`${variableLabel(item.key, item.label)}目录`, item.path]);
    });
    return rows;
  }

  function renderForecastInputSummary(check = null, stateLabel = "", helpers = {}) {
    const host = document.getElementById("forecast-input-summary");
    if (!host) return;
    if (stateLabel === "loading") {
      host.innerHTML = '<div class="hint-box">正在核对预报气象目录。</div>';
      return;
    }
    if (!check) {
      host.innerHTML = '<div class="hint-box status-warn">选择源结果并填写预报时段后，系统将在这里核对 P/T/PET 目录覆盖。</div>';
      return;
    }
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const focusStatusClass = helpers.focusStatusClass || defaultStatusClass;
    const focusStatusLabel = helpers.focusStatusLabel || defaultStatusLabel;
    const formatNumber = helpers.formatNumber || ((value, digits = 0) => Number(value).toFixed(digits));
    const shortPath = helpers.shortPath || defaultShortPath;
    const renderParameterContextHtml = helpers.renderParameterContextHtml || (() => "");
    const renderStationScopeSummary = helpers.renderStationScopeSummary || (() => "");
    const status = String(check.status || "warn").toLowerCase();
    const cls = focusStatusClass(status);
    const variables = Array.isArray(check.variables) ? check.variables : [];
    const source = check.source || {};
    const windowInfo = check.window || {};
    const output = check.output || {};
    const expectedSteps = Number(windowInfo.expected_steps || 0);
    const meteoOverview = variableOverview(variables, expectedSteps);
    const sourceState = textOrDash(source.source_state_time || "");
    const suggestedStart = textOrDash(source.expected_forecast_start || windowInfo.forecast_start || "", "");
    const rows = [
      {
        label: "起报依据",
        value: source.state_available ? (suggestedStart ? `${sourceState} 接续 ${suggestedStart}` : sourceState) : "缺少保存状态",
        detail: "读取源结果末端状态，不重新初始化产流与汇流记忆",
        status: source.state_available ? "ok" : "fail",
      },
      {
        label: "预报时段",
        value: rangeText(windowInfo.forecast_start, windowInfo.forecast_end),
        detail: stepText(expectedSteps),
        status: expectedSteps > 0 ? "ok" : "warn",
      },
      {
        label: "参数来源",
        value: source.parameter_count ? `源结果参数（${source.parameter_count} 项）` : "缺少参数",
        detail: "预报沿用源结果保存的最优参数",
        status: source.parameter_count ? "ok" : "fail",
      },
      {
        label: "气象资料",
        value: meteoOverview.value,
        detail: meteoOverview.detail,
        status: meteoOverview.status,
      },
      {
        label: "结果输出",
        value: output.result_label || "运行时新建预报结果目录",
        detail: "完成后可查看过程线并导出 Excel",
        status: expectedSteps > 0 ? "ok" : "warn",
      },
      {
        label: "输入归档",
        value: expectedSteps > 0 ? "仅归档预报窗口内栅格" : "待形成预报窗口",
        detail: "完整路径收纳在技术细节中",
        status: expectedSteps > 0 ? "ok" : "warn",
      },
    ];
    const messages = [
      ...(Array.isArray(check.errors) ? check.errors.slice(0, 3).map(item => ({ item, status: "fail" })) : []),
      ...(Array.isArray(check.warnings) ? check.warnings.slice(0, 3).map(item => ({ item, status: "warn" })) : []),
    ];
    const messageHtml = messages.length
      ? `<ul class="event-window-issues">${messages.map(({ item, status: itemStatus }) => `<li class="${focusStatusClass(itemStatus)}">${escapeHtml(item)}</li>`).join("")}</ul>`
      : "";
    const parameterContext = check.parameter_context || check.source?.parameter_context || null;
    const parameterContextHtml = parameterContext ? renderParameterContextHtml({
      parameter_context: parameterContext,
      workspace_name: parameterContext.source_workspace || check.source?.source_run_name || "",
      workspace_config: parameterContext.source_workspace_config || "",
      optimized_param_count: check.source?.parameter_count || parameterContext.parameter_count || 0,
      calibration_profile: parameterContext.calibration_profile || "",
      time_step_hours: parameterContext.time_step_hours || check.window?.time_step_hours || "",
      effective_objective_mode: parameterContext.objective_mode || "",
    }) : "";
    const stationPrecipHtml = check.station_precip?.enabled
      ? renderStationScopeSummary(check.station_precip, {
        escapeHtml,
        focusStatusClass,
        focusStatusLabel,
        formatNumber,
      })
      : "";
    host.innerHTML = `
      <div class="hint-box forecast-input-box ${cls}">
        <div class="forecast-input-head">
          <strong>${escapeHtml(check.headline || "预报气象输入检查")}</strong>
          <span class="status-badge ${cls}">${escapeHtml(focusStatusLabel(status))}</span>
        </div>
        <div class="forecast-input-grid forecast-input-overview">
          ${rows.map(item => `
            <div class="forecast-input-item">
              <span>${escapeHtml(item.label || "")}</span>
              <strong class="${focusStatusClass(item.status || "ok")}" title="${escapeHtml(item.detail || "")}">${escapeHtml(item.value || "—")}</strong>
              ${item.detail ? `<small>${escapeHtml(item.detail)}</small>` : ""}
            </div>
          `).join("")}
        </div>
        ${parameterContextHtml}
        ${stationPrecipHtml}
        <div class="forecast-input-grid">
          ${variables.map(item => `
            <div class="forecast-input-variable ${focusStatusClass(item.status || "warn")}">
              <span>${escapeHtml(item.label || "")}</span>
              <strong>${escapeHtml(item.summary || "未检查")}</strong>
              <small title="${escapeHtml(item.path || "")}">${escapeHtml(variableDetailText(item, shortPath))}</small>
            </div>
          `).join("")}
        </div>
        ${messageHtml}
        ${renderTechnicalDetails(forecastInputTechnicalRows(check), escapeHtml)}
      </div>
    `;
  }

  function renderForecastTaskInputCheckSummary(check = null, helpers = {}) {
    if (!check) return "";
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const focusStatusClass = helpers.focusStatusClass || defaultStatusClass;
    const focusStatusLabel = helpers.focusStatusLabel || defaultStatusLabel;
    const shortPath = helpers.shortPath || defaultShortPath;
    const status = String(check.status || "warn").toLowerCase();
    const cls = focusStatusClass(status);
    const source = check.source || {};
    const windowInfo = check.window || {};
    const output = check.output || {};
    const variables = Array.isArray(check.variables) ? check.variables : [];
    const issues = [
      ...(Array.isArray(check.errors) ? check.errors.slice(0, 2).map(item => ({ item, status: "fail" })) : []),
      ...(Array.isArray(check.warnings) ? check.warnings.slice(0, 2).map(item => ({ item, status: "warn" })) : []),
    ].slice(0, 3);
    const range = windowInfo.forecast_start && windowInfo.forecast_end
      ? `${windowInfo.forecast_start} 至 ${windowInfo.forecast_end}`
      : "预报时段未完整填写";
    const rows = [
      {
        label: "源状态",
        value: source.source_state_time || "未记录",
        detail: source.expected_forecast_start ? `建议起报：${source.expected_forecast_start}` : "",
        status: source.state_available ? "ok" : "fail",
      },
      {
        label: "预报窗口",
        value: range,
        detail: Number(windowInfo.expected_steps || 0) > 0 ? `${windowInfo.expected_steps} 个时间步` : "等待完整窗口",
        status: Number(windowInfo.expected_steps || 0) > 0 ? "ok" : "warn",
      },
      {
        label: "结果输出",
        value: output.result_label || "运行时新建预报结果目录",
        detail: "完成后可查看过程线并导出 Excel",
        status: Number(windowInfo.expected_steps || 0) > 0 ? "ok" : "warn",
      },
      {
        label: "输入归档",
        value: "仅归档预报窗口内栅格",
        detail: "完整路径收纳在技术细节中",
        status: Number(windowInfo.expected_steps || 0) > 0 ? "ok" : "warn",
      },
    ];
    return `
      <div class="forecast-task-input-check ${cls}">
        <div class="forecast-task-input-head">
          <strong>${escapeHtml(check.headline || "预报输入检查")}</strong>
          <span class="status-badge ${cls}">${escapeHtml(focusStatusLabel(status))}</span>
        </div>
        <div class="forecast-task-input-grid">
          ${rows.map(row => `
            <div class="forecast-task-input-item ${focusStatusClass(row.status || "warn")}">
              <span>${escapeHtml(row.label)}</span>
              <strong title="${escapeHtml(row.detail || row.value || "")}">${escapeHtml(row.value || "—")}</strong>
              ${row.detail ? `<small>${escapeHtml(shortPath(row.detail))}</small>` : ""}
            </div>
          `).join("")}
          ${variables.slice(0, 3).map(item => `
            <div class="forecast-task-input-item ${focusStatusClass(item.status || "warn")}">
              <span>${escapeHtml(item.label || "")}</span>
              <strong>${escapeHtml(item.summary || "未检查")}</strong>
              <small title="${escapeHtml(item.path || "")}">${escapeHtml(variableDetailText(item, shortPath))}</small>
            </div>
          `).join("")}
        </div>
        ${issues.length ? `
          <ul class="forecast-task-input-issues">
            ${issues.map(({ item, status: itemStatus }) => `<li class="${focusStatusClass(itemStatus)}">${escapeHtml(item)}</li>`).join("")}
          </ul>
        ` : ""}
        ${renderTechnicalDetails(forecastInputTechnicalRows(check), escapeHtml)}
      </div>
    `;
  }

  function forecastRestartTasks(tasks = [], options = {}) {
    const limit = Number(options.limit || 8);
    const items = Array.isArray(tasks) ? tasks : [];
    const sorted = items
      .filter(task => task?.task_type === "forecast_restart")
      .sort((a, b) => Number(b?.updated_at || 0) - Number(a?.updated_at || 0));
    return Number.isFinite(limit) && limit > 0 ? sorted.slice(0, limit) : sorted;
  }

  function renderForecastTaskCard(task, helpers = {}) {
    const taskView = helpers.taskView || window.HBVStudioTaskView || {};
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const formatDateTime = helpers.formatDateTime || textOrDash;
    const taskTypeLabel = helpers.taskTypeLabel || taskView.taskTypeLabel || (() => "任务");
    const taskStatusClass = helpers.taskStatusClass || taskView.taskStatusClass || (() => "status-warn");
    const taskStatusLabel = helpers.taskStatusLabel || taskView.taskStatusLabel || (status => String(status || "未知"));
    const taskPrimaryTitle = helpers.taskPrimaryTitle || taskView.taskPrimaryTitle || (item => item?.label || taskTypeLabel(item?.task_type));
    const taskSummaryLine = helpers.taskSummaryLine || ((item) => taskView.taskSummaryLine?.(item, helpers) || "");
    const renderTaskMilestones = helpers.renderTaskMilestones || ((item) => taskView.renderTaskMilestones?.(item, helpers) || "");
    const renderTaskActions = helpers.renderTaskActions || ((item) => taskView.renderTaskActions?.(item, helpers) || "");
    const taskDebugDetails = helpers.taskDebugDetails || ((item, options) => taskView.taskDebugDetails?.(item, options, helpers) || "");
    const isRunning = task?.status === "running";
    const summaryLine = taskSummaryLine(task);
    const summaryClass = task?.status === "completed" ? "status-ok" : task?.status === "failed" ? "status-fail" : "";
    const inputCheckHtml = renderForecastTaskInputCheckSummary(task?.forecast_input_check, helpers);
    return `
      <div class="list-item task-card ${isRunning ? "task-running" : ""}">
        <div class="task-card-topline">
          <span class="task-kicker">${escapeHtml(taskTypeLabel(task?.task_type))}</span>
          <span class="task-updated">最近更新 ${escapeHtml(formatDateTime(task?.updated_at))}</span>
          <span class="status-badge ${taskStatusClass(task?.status)}">${escapeHtml(taskStatusLabel(task?.status))}${isRunning ? "..." : ""}</span>
        </div>
        <div class="task-card-title">
          <strong>${escapeHtml(taskPrimaryTitle(task))}</strong>
          ${task?.forecast_end ? `<small class="task-meta-line">预报至 ${escapeHtml(task.forecast_end)}</small>` : ""}
        </div>
        ${renderTaskMilestones(task)}
        <div class="hint-box task-summary-box ${summaryClass}">${escapeHtml(summaryLine)}</div>
        ${inputCheckHtml}
        ${renderTaskActions(task)}
        ${taskDebugDetails(task, { lines: isRunning ? 80 : 40 })}
      </div>
    `;
  }

  function renderForecastTaskList(tasks = [], helpers = {}) {
    const items = forecastRestartTasks(tasks, { limit: helpers.limit || 8 });
    if (!items.length) return '<div class="hint-box">暂无连续状态预报任务。</div>';
    return items.map(task => renderForecastTaskCard(task, helpers)).join("");
  }

  function renderForecastSummary(data = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const runDisplayName = helpers.runDisplayName || (run => run?.name || run?.title || "连续状态预报结果");
    const shortPath = helpers.shortPath || defaultShortPath;
    const timeRangeText = helpers.timeRangeText || ((start, end) => [start, end].filter(Boolean).join(" 至 ") || "未记录");
    const forecastArchiveSummaryText = helpers.forecastArchiveSummaryText || (() => "未记录气象归档");
    const forecastArchiveDetailText = helpers.forecastArchiveDetailText || (() => "");
    const forecastParameterSourceSummary = helpers.forecastParameterSourceSummary || (() => ({ value: "源结果参数", detail: "" }));
    const profileLabel = helpers.profileLabel || (value => String(value || "未记录"));
    const metadata = data.metadata || {};
    const run = data.run || {};
    const forecast = metadata.forecast_result || {};
    const initial = metadata.initial_state || {};
    const archive = forecast.forecast_input_archive || metadata.data_sources?.forecast_input_archive || {};
    const parameterSource = forecastParameterSourceSummary(
      forecast.source_parameter_summary || metadata.source_parameter_summary || {},
      metadata,
    );
    const rows = [
      ["结果名称", runDisplayName(run), run.path ? "预报结果目录已生成" : ""],
      ["预报时段", timeRangeText(forecast.forecast_start || metadata.time_config?.forecast_start, forecast.forecast_end || metadata.time_config?.forecast_end, metadata.time_config?.time_step_hours || 24), `${profileLabel(metadata.calibration_profile)}，${metadata.time_config?.time_step_hours || 24} 小时步长`],
      ["起报状态", forecast.source_state_time || initial.source_state_snapshot_time || "未记录", forecast.source_snapshot_file ? `起报状态文件：${shortPath(forecast.source_snapshot_file)}` : "读取源结果保存状态"],
      ["参数来源", parameterSource.value || "源结果参数", parameterSource.detail || "预报不重新率定参数"],
      ["未来气象", forecastArchiveSummaryText(archive), forecastArchiveDetailText(archive)],
    ];
    const technicalRows = [
      run.path ? ["预报结果目录", run.path] : null,
      forecast.source_run_path ? ["源结果目录", forecast.source_run_path] : null,
      forecast.source_snapshot_file ? ["起报状态文件", forecast.source_snapshot_file] : null,
      archive.manifest_path ? ["输入归档清单", archive.manifest_path] : null,
    ].filter(Boolean);
    const summary = document.getElementById("forecast-result-summary");
    if (!summary) return;
    summary.innerHTML = `
      <div class="forecast-result-summary-grid">
        ${rows.map(row => `
          <div class="forecast-result-summary-item">
            <span>${escapeHtml(row[0])}</span>
            <strong title="${escapeHtml(row[2] || "")}">${escapeHtml(row[1] || "—")}</strong>
            ${row[2] ? `<small>${escapeHtml(row[2])}</small>` : ""}
          </div>
        `).join("")}
      </div>
      ${renderTechnicalDetails(technicalRows, escapeHtml, "结果技术细节")}
    `;
  }

  function renderForecastChart(data = {}) {
    const chart = document.getElementById("forecast-result-chart");
    if (!chart) return;
    const series = data.series || {};
    const dates = series.dates || [];
    if (!dates.length || !finiteSeries(series.q_sim)) {
      clearChart("当前预报结果缺少可绘制的模拟流量序列。");
      return;
    }
    if (!window.Plotly) {
      chart.innerHTML = '<div class="hint-box">图表组件未加载，预报数据仍可通过 Excel 导出或打开结果目录查看。</div>';
      return;
    }
    const colors = chartColors();
    const traces = [
      { x: dates, y: series.q_sim || [], name: "预报流量", mode: "lines", line: { color: colors.qSim, width: 2.1 } },
    ];
    [
      ["q_rain", "降雨产流", colors.qRain],
      ["q_snow", "融雪流量", colors.qSnow],
      ["q_ice", "裸冰融化流量", colors.qIce],
      ["q_boundary_inflow", "边界入流", colors.boundary],
    ].forEach(([key, label, color]) => {
      if (finiteSeries(series[key])) {
        traces.push({ x: dates, y: series[key], name: label, mode: "lines", line: { color, width: 1.35 } });
      }
    });
    const layout = {
      margin: { t: 10, r: 18, b: 40, l: 58 },
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      xaxis: { title: "日期" },
      yaxis: { title: "流量 m³/s" },
      legend: { orientation: "h", y: 1.14 },
    };
    try { window.Plotly.purge(chart); } catch {}
    chart.innerHTML = "";
    try {
      const plot = window.Plotly.newPlot(chart, traces, layout, { responsive: true });
      if (plot && typeof plot.catch === "function") plot.catch(() => {});
    } catch {}
  }

  function renderForecastResultDetail(data = {}, helpers = {}) {
    renderForecastSummary(data, helpers);
    renderForecastChart(data);
    setHint("预报结果已读取，可在本页复核过程线、起报依据和输入资料。", "status-ok");
  }

  window.HBVStudioForecastView = {
    forecastArchiveDetailText,
    forecastArchiveManifest,
    forecastArchiveSummaryText,
    forecastArchiveVariableItems,
    forecastArchiveVariables,
    forecastCandidateRuns,
    forecastCompletedResultState,
    forecastInputCheckDecision,
    forecastInputCheckError,
    forecastInputPayload,
    forecastInputType,
    forecastParameterSourceSummary,
    forecastResultButtonState,
    forecastResultDetailState,
    forecastResultExportPayload,
    forecastResultExportState,
    forecastResultExportSuccess,
    forecastResultLoadErrorState,
    forecastResultLoadStartState,
    forecastResultLoadSuccessState,
    forecastResultPanelState,
    forecastResultSelectionState,
    forecastRestartPreflight,
    forecastRestartPayload,
    forecastResultRuns,
    forecastRunReady,
    forecastRunReadinessText,
    forecastSelectedSourceRun,
    forecastSelectedResultRun,
    forecastSourceOptionsState,
    forecastSourceSelectionState,
    forecastSuggestedStart,
    forecastTimeComparable,
    formatForecastInputTime,
    parseForecastTime,
    pickForecastSourceRun,
    renderForecastSourceOptions,
    renderForecastSourceSummary,
    renderForecastResultOptions,
    forecastRestartTasks,
    renderForecastTaskCard,
    renderForecastResultEmpty,
    renderForecastResultLoading,
    renderForecastInputSummary,
    renderForecastTaskList,
    renderForecastTaskInputCheckSummary,
    renderForecastResultDetail,
    restartStateRows,
  };
})();
