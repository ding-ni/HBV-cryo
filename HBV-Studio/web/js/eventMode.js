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

  function defaultStatusClass(status) {
    return status === "ok" ? "status-ok" : status === "fail" ? "status-fail" : "status-warn";
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

  function purposeLabel(value) {
    const key = String(value || "").trim().toLowerCase();
    if (key === "calibration") return "率定";
    if (key === "validation") return "验证";
    if (key === "diagnostic") return "诊断";
    return key || "未记录";
  }

  function initialStatePolicyLabel(value) {
    const key = String(value || "").trim().toLowerCase();
    if (key === "event_warmup" || key === "warmup" || key === "event_preheat") return "事件预热";
    if (key === "fixed_initial" || key === "fixed" || key === "default_initial") return "固定初值";
    if (key === "source_state" || key === "restart_state" || key === "snapshot") return "来源状态";
    if (key === "continuous_state" || key === "continuous" || key === "carryover") return "连续状态";
    return value ? String(value) : "事件预热";
  }

  function renderEventWindowSummary(eventInfo = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const statusClass = helpers.statusClass || defaultStatusClass;
    if (!eventInfo || !Number(eventInfo.event_count || 0)) return "";
    const events = Array.isArray(eventInfo.events) ? eventInfo.events : [];
    const counts = eventInfo.purpose_counts || {};
    const validCount = Number(eventInfo.valid_event_count || 0);
    const eventCount = Number(eventInfo.event_count || events.length);
    const hasErrors = Boolean((eventInfo.errors || []).length);
    const hasWarnings = Boolean((eventInfo.warnings || []).length || eventInfo.initial_state_warning);
    const status = validCount <= 0 || hasErrors ? "fail" : hasWarnings ? "warn" : "ok";
    const issueItems = [
      ...(Array.isArray(eventInfo.errors) ? eventInfo.errors.map(item => ({ item, cls: "status-fail" })) : []),
      ...(Array.isArray(eventInfo.warnings) ? eventInfo.warnings.map(item => ({ item, cls: "status-warn" })) : []),
    ];
    const rows = events.slice(0, 30).map(event => {
      const rowStatus = event.valid ? "ok" : "fail";
      const runWindow = `${event.run_start || "—"} ~ ${event.run_end || "—"}`;
      const scoreWindow = `${event.score_start || "—"} ~ ${event.score_end || "—"}`;
      return `
        <div class="event-window-row ${statusClass(rowStatus)}">
          <span><strong>${escapeHtml(event.name || event.event_id || "未命名事件")}</strong><small>${escapeHtml(event.event_id || "")}</small></span>
          <span>${escapeHtml(purposeLabel(event.purpose))}</span>
          <span>${escapeHtml(runWindow)}</span>
          <span>${escapeHtml(scoreWindow)}</span>
          <span>${escapeHtml(`${event.time_steps_run || 0}/${event.time_steps_score || 0}`)}</span>
          <span class="${statusClass(rowStatus)}">${escapeHtml(event.valid ? "有效" : "需修正")}</span>
        </div>
      `;
    }).join("");
    const more = events.length > 30
      ? `<div class="event-window-more">还有 ${events.length - 30} 场事件未展开，完整信息见输入检查返回结果。</div>`
      : "";
    const issues = issueItems.length
      ? `<ul class="event-window-issues">${issueItems.slice(0, 8).map(({ item, cls }) => `<li class="${cls}">${escapeHtml(item)}</li>`).join("")}</ul>`
      : "";
    const initialPolicy = eventInfo.initial_state_policy_label
      || initialStatePolicyLabel(eventInfo.initial_state_policy);
    const continuityText = eventInfo.state_continuity_between_events === true
      ? "事件之间传递状态"
      : "事件之间不传递状态";
    const initialNote = eventInfo.initial_state_note || continuityText;
    const initialWarning = eventInfo.initial_state_warning || "";
    return `
      <div class="event-window-summary">
        <div class="event-window-title">
          <strong>洪水事件表解析结果</strong>
          <span class="${statusClass(status)}">${escapeHtml(`${validCount}/${eventCount} 场有效；率定 ${counts.calibration || 0}、验证 ${counts.validation || 0}、诊断 ${counts.diagnostic || 0}`)}</span>
        </div>
        ${eventInfo.source_file ? `<div class="event-window-source">事件表：${escapeHtml(eventInfo.source_file)}</div>` : ""}
        <div class="event-window-policy">
          <strong>初始条件：${escapeHtml(initialPolicy)}</strong>
          <span>${escapeHtml(initialNote)}</span>
          ${initialWarning ? `<span class="status-warn">${escapeHtml(initialWarning)}</span>` : ""}
        </div>
        <div class="event-window-row event-window-head">
          <span>事件</span>
          <span>用途</span>
          <span>运行窗口</span>
          <span>评分窗口</span>
          <span>运行/评分步数</span>
          <span>结论</span>
        </div>
        ${rows}
        ${more}
        ${issues}
      </div>
    `;
  }

  window.HBVStudioEventMode = {
    floodEventEvaluation,
    eventChartEvents,
    initialStatePolicyLabel,
    renderFloodEventChart,
    renderEventWindowSummary,
  };
})();
