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
    forecastParameterSourceSummary,
    renderForecastResultEmpty,
    renderForecastResultLoading,
    renderForecastInputSummary,
    renderForecastTaskInputCheckSummary,
    renderForecastResultDetail,
    restartStateRows,
  };
})();
