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
    renderForecastResultDetail,
  };
})();
