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
    const shortPath = helpers.shortPath || (value => String(value || ""));
    const renderParameterContextHtml = helpers.renderParameterContextHtml || (() => "");
    const renderStationScopeSummary = helpers.renderStationScopeSummary || (() => "");
    const status = String(check.status || "warn").toLowerCase();
    const cls = focusStatusClass(status);
    const items = Array.isArray(check.items) ? check.items : [];
    const variables = Array.isArray(check.variables) ? check.variables : [];
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
        <div class="forecast-input-grid">
          ${items.map(item => `
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
              <small>${escapeHtml(item.first_time && item.last_time ? `${item.first_time} 至 ${item.last_time}` : (item.path ? shortPath(item.path) : "未选择目录"))}</small>
            </div>
          `).join("")}
        </div>
        ${messageHtml}
      </div>
    `;
  }

  function renderForecastTaskInputCheckSummary(check = null, helpers = {}) {
    if (!check) return "";
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const focusStatusClass = helpers.focusStatusClass || defaultStatusClass;
    const focusStatusLabel = helpers.focusStatusLabel || defaultStatusLabel;
    const shortPath = helpers.shortPath || (value => String(value || ""));
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
        detail: output.result_detail || output.result_parent || "",
        status: Number(windowInfo.expected_steps || 0) > 0 ? "ok" : "warn",
      },
      {
        label: "输入归档",
        value: output.archive_label || "结果目录下的 forecast_inputs",
        detail: output.archive_detail || output.manifest_path || "",
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
              <small>${escapeHtml(item.first_time && item.last_time ? `${item.first_time} 至 ${item.last_time}` : shortPath(item.path || "未选择目录"))}</small>
            </div>
          `).join("")}
        </div>
        ${issues.length ? `
          <ul class="forecast-task-input-issues">
            ${issues.map(({ item, status: itemStatus }) => `<li class="${focusStatusClass(itemStatus)}">${escapeHtml(item)}</li>`).join("")}
          </ul>
        ` : ""}
      </div>
    `;
  }

  function renderForecastSummary(data = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const runDisplayName = helpers.runDisplayName || (run => run?.name || run?.title || "连续状态预报结果");
    const shortPath = helpers.shortPath || (value => String(value || ""));
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
      ["结果名称", runDisplayName(run), run.path ? shortPath(run.path) : ""],
      ["预报时段", timeRangeText(forecast.forecast_start || metadata.time_config?.forecast_start, forecast.forecast_end || metadata.time_config?.forecast_end, metadata.time_config?.time_step_hours || 24), `${profileLabel(metadata.calibration_profile)}，${metadata.time_config?.time_step_hours || 24} 小时步长`],
      ["起报状态", forecast.source_state_time || initial.source_state_snapshot_time || "未记录", forecast.source_snapshot_file ? `起报状态文件：${shortPath(forecast.source_snapshot_file)}` : "读取源结果保存状态"],
      ["参数来源", parameterSource.value || "源结果参数", parameterSource.detail || "预报不重新率定参数"],
      ["未来气象", forecastArchiveSummaryText(archive), forecastArchiveDetailText(archive)],
    ];
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
    const traces = [
      { x: dates, y: series.q_sim || [], name: "预报流量", mode: "lines", line: { color: "#1d6d74", width: 2.1 } },
    ];
    [
      ["q_rain", "降雨产流", "#317f95"],
      ["q_snow", "融雪流量", "#8aa9b7"],
      ["q_ice", "裸冰融化流量", "#2d7c52"],
      ["q_boundary_inflow", "边界入流", "#7c5c99"],
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
    window.Plotly.newPlot(chart, traces, layout, { responsive: true });
  }

  function renderForecastResultDetail(data = {}, helpers = {}) {
    renderForecastSummary(data, helpers);
    renderForecastChart(data);
    setHint("预报结果已读取，可在本页复核过程线、起报依据和输入资料。", "status-ok");
  }

  window.HBVStudioForecastView = {
    renderForecastResultEmpty,
    renderForecastResultLoading,
    renderForecastInputSummary,
    renderForecastTaskInputCheckSummary,
    renderForecastResultDetail,
  };
})();
