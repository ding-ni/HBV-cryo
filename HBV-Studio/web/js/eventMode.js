(function () {
  function defaultFiniteNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function defaultFormatNumber(value, digits = 4) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "—";
  }

  function defaultFormatMetricValue(value, digits = 4, suffix = "") {
    const number = Number(value);
    return Number.isFinite(number) ? `${defaultFormatNumber(number, digits)}${suffix}` : "—";
  }

  function floodEventEvaluation(meta = {}) {
    return meta?.flood_event_evaluation || meta?.diagnostics?.flood_event_evaluation || {};
  }

  function eventChartName(event = {}, index = 0) {
    const name = String(event?.name || "").trim();
    if (name) return name;
    const start = event?.event_start || event?.window_start_used || event?.score_start || "";
    const dateText = start ? String(start).slice(0, 10) : "";
    return dateText ? `事件${index + 1} ${dateText}` : `事件${index + 1}`;
  }

  function eventChartEvents(meta = {}, finiteNumber = defaultFiniteNumber) {
    const evaluation = floodEventEvaluation(meta);
    if (!evaluation?.enabled || !Array.isArray(evaluation.events)) return [];
    const chartKeys = [
      "peak_error_percent",
      "volume_error_percent",
      "peak_time_error_hours",
      "high_flow_weighted_nse",
      "recession_slope_error_percent",
      "nse",
      "kge",
    ];
    return evaluation.events
      .filter(event => event && typeof event === "object")
      .map((event, index) => ({ ...event, _chartName: eventChartName(event, index) }))
      .filter(event => chartKeys.some(key => finiteNumber(event?.[key]) !== null));
  }

  function eventChartValues(events, key, finiteNumber = defaultFiniteNumber) {
    return events.map(event => {
      const value = finiteNumber(event?.[key]);
      return value === null ? null : value;
    });
  }

  function eventChartCustomData(events, formatMetricValue = defaultFormatMetricValue) {
    return events.map(event => [
      event?.used_in_objective ? "参与目标函数" : "诊断事件",
      formatMetricValue(event?.nse, 4),
      formatMetricValue(event?.kge, 4),
      formatMetricValue(event?.high_flow_weighted_nse, 4),
      formatMetricValue(event?.recession_slope_error_percent, 2, "%"),
    ]);
  }

  function setEmptyEventChart(host, panel, message = "") {
    if (window.Plotly) {
      try { window.Plotly.purge(host); } catch {}
    }
    if (panel) panel.style.display = message ? "" : "none";
    host.innerHTML = message ? `<div class="hint-box">${message}</div>` : "";
  }

  function renderFloodEventChart(meta = {}, plotCfg = {}, helpers = {}) {
    const panel = document.getElementById("flood-event-chart-panel");
    const host = document.getElementById("flood-event-chart");
    if (!host) return;
    const evaluation = floodEventEvaluation(meta);
    if (!evaluation?.enabled) {
      setEmptyEventChart(host, panel);
      return;
    }

    const finiteNumber = helpers.finiteNumber || defaultFiniteNumber;
    const formatMetricValue = helpers.formatMetricValue || defaultFormatMetricValue;
    const events = eventChartEvents(meta, finiteNumber);
    if (!events.length) {
      setEmptyEventChart(host, panel, "当前结果未记录可绘制的逐场洪水事件指标，完整事件表见结果目录 flood_events.csv。");
      return;
    }

    if (panel) panel.style.display = "";
    if (!window.Plotly) {
      host.innerHTML = '<div class="hint-box">图表组件未加载，逐场指标可在洪水事件评价摘要或结果目录 flood_events.csv 中查看。</div>';
      return;
    }

    const names = events.map(event => event._chartName);
    const customdata = eventChartCustomData(events, formatMetricValue);
    const hoverSuffix = "<br>类型 %{customdata[0]}<br>NSE %{customdata[1]}<br>KGE %{customdata[2]}<br>高流量NSE %{customdata[3]}<br>退水误差 %{customdata[4]}<extra></extra>";
    const traces = [
      {
        x: names,
        y: eventChartValues(events, "peak_error_percent", finiteNumber),
        customdata,
        name: "洪峰误差 %",
        type: "bar",
        marker: { color: "#b36a28" },
        hovertemplate: "%{x}<br>洪峰误差 %{y:.2f}%" + hoverSuffix,
      },
      {
        x: names,
        y: eventChartValues(events, "volume_error_percent", finiteNumber),
        customdata,
        name: "洪量误差 %",
        type: "bar",
        marker: { color: "#1d6d74" },
        hovertemplate: "%{x}<br>洪量误差 %{y:.2f}%" + hoverSuffix,
      },
      {
        x: names,
        y: eventChartValues(events, "peak_time_error_hours", finiteNumber),
        customdata,
        name: "峰现误差 h",
        type: "scatter",
        mode: "lines+markers",
        yaxis: "y2",
        line: { color: "#7c5c99", width: 2 },
        marker: { size: 7 },
        hovertemplate: "%{x}<br>峰现误差 %{y:.1f} h" + hoverSuffix,
      },
    ];
    const layout = {
      margin: { t: 10, r: 58, b: names.length > 5 ? 82 : 50, l: 58 },
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      barmode: "group",
      legend: { orientation: "h", y: 1.14 },
      xaxis: { title: "洪水事件", tickangle: names.length > 5 ? -25 : 0, automargin: true },
      yaxis: { title: "相对误差 %", zeroline: true, zerolinecolor: "rgba(36,52,65,0.28)" },
      yaxis2: { title: "峰现误差 h", overlaying: "y", side: "right", zeroline: false },
    };
    try { window.Plotly.purge(host); } catch {}
    host.innerHTML = "";
    window.Plotly.newPlot(host, traces, layout, plotCfg);
  }

  window.HBVStudioEventMode = {
    floodEventEvaluation,
    eventChartEvents,
    renderFloodEventChart,
  };
})();
