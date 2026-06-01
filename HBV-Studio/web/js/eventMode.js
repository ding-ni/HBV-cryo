(function () {
  function defaultEscapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

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

  function chartColors() {
    return window.HBVStudioChartPalette?.chartColors?.() || {
      qSim: "#0e7490",
      residual: "#b91c1c",
      temp: "#ef4444",
    };
  }

  function defaultStatusClass(status) {
    return status === "ok" ? "status-ok" : status === "fail" ? "status-fail" : "status-warn";
  }

  function defaultShortPath(value) {
    const text = String(value || "").replace(/\\/g, "/");
    return text ? text.replace(/^.*\/([^/]+)$/, "$1") : "";
  }

  function floodEventEvaluation(meta = {}) {
    return meta?.flood_event_evaluation || meta?.diagnostics?.flood_event_evaluation || {};
  }

  function floodEventStatusText(evaluation = {}) {
    if (!evaluation?.enabled) return "未启用";
    const valid = Number(evaluation.valid_event_count || 0);
    const total = Number(evaluation.event_count || 0);
    const mode = evaluation.objective_enabled ? "事件目标函数" : "事件诊断";
    return `${mode}：${valid}/${total} 场有效`;
  }

  function floodEventObjectiveText(evaluation = {}, helpers = {}) {
    const formatNumber = helpers.formatNumber || defaultFormatNumber;
    const score = evaluation?.summary?.all?.mean_diagnostic_objective;
    return Number.isFinite(Number(score)) ? formatNumber(score, 4) : "—";
  }

  function floodEventRows(meta = {}, helpers = {}) {
    const formatMetricValue = helpers.formatMetricValue || defaultFormatMetricValue;
    const initialPolicyLabel = helpers.initialStatePolicyLabel || initialStatePolicyLabel;
    const evaluation = floodEventEvaluation(meta);
    if (!evaluation?.enabled) return [];
    const rows = [
      ["事件评价", floodEventStatusText(evaluation), ""],
      ["事件目标值", floodEventObjectiveText(evaluation, helpers), "数值越小表示洪水过程偏差越小"],
    ];
    const eventMode = meta?.event_mode || meta?.time_config?.event_runtime || {};
    if (eventMode?.enabled) {
      const modeText = eventMode.runtime_mode === "independent_event_windows" ? "事件窗口独立运行" : "事件窗口资料";
      const initialPolicy = eventMode.initial_state_policy_label
        || initialPolicyLabel(eventMode.initial_state_policy)
        || eventMode.initial_state_policy
        || "事件预热";
      rows.push([
        "事件资料模式",
        `${modeText}，${Number(eventMode.event_count || 0)} 场`,
        `初始条件：${initialPolicy}`,
      ]);
    }
    const events = Array.isArray(evaluation.events) ? evaluation.events : [];
    events.slice(0, 12).forEach(event => {
      const name = event?.name || "未命名事件";
      const value = [
        `洪峰 ${formatMetricValue(event?.peak_error_percent, 2, "%")}`,
        `峰现 ${formatMetricValue(event?.peak_time_error_hours, 1, " h")}`,
        `洪量 ${formatMetricValue(event?.volume_error_percent, 2, "%")}`,
      ].join(" / ");
      const detail = [
        `NSE ${formatMetricValue(event?.nse, 4)}`,
        `KGE ${formatMetricValue(event?.kge, 4)}`,
      ].join("，");
      rows.push([String(name), value, detail]);
    });
    if (events.length > 12) {
      rows.push(["更多事件", `还有 ${events.length - 12} 场`, "完整事件表见结果目录 flood_events.csv"]);
    }
    return rows;
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
      formatMetricValue(event?.nse, 4),
      formatMetricValue(event?.kge, 4),
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
    const hoverSuffix = "<br>NSE %{customdata[0]}<br>KGE %{customdata[1]}<extra></extra>";
    const colors = chartColors();
    const traces = [
      {
        x: names,
        y: eventChartValues(events, "peak_error_percent", finiteNumber),
        customdata,
        name: "洪峰误差 %",
        type: "bar",
        marker: { color: colors.residual },
        hovertemplate: "%{x}<br>洪峰误差 %{y:.2f}%" + hoverSuffix,
      },
      {
        x: names,
        y: eventChartValues(events, "volume_error_percent", finiteNumber),
        customdata,
        name: "洪量误差 %",
        type: "bar",
        marker: { color: colors.qSim },
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
        line: { color: colors.temp, width: 2 },
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
    try {
      const plot = window.Plotly.newPlot(host, traces, layout, plotCfg);
      if (plot && typeof plot.catch === "function") plot.catch(() => {});
    } catch {}
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
    const shortPath = helpers.shortPath || defaultShortPath;
    if (!eventInfo || !Number(eventInfo.event_count || 0)) return "";
    const events = Array.isArray(eventInfo.events) ? eventInfo.events : [];
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
      const eventWindow = `${event.score_start || event.run_start || "—"} ~ ${event.score_end || event.run_end || "—"}`;
      return `
        <div class="event-window-row ${statusClass(rowStatus)}">
          <span><strong>${escapeHtml(event.name || event.event_id || "未命名事件")}</strong><small>${escapeHtml(event.event_id || "")}</small></span>
          <span>${escapeHtml(eventWindow)}</span>
          <span class="${statusClass(rowStatus)}">${escapeHtml(event.valid ? "有效" : "需修正")}</span>
        </div>
      `;
    }).join("");
    const more = events.length > 30
      ? `<div class="event-window-more">还有 ${events.length - 30} 场事件未展开，可在事件明细表中继续核对。</div>`
      : "";
    const issues = issueItems.length
      ? `<ul class="event-window-issues">${issueItems.slice(0, 8).map(({ item, cls }) => `<li class="${cls}">${escapeHtml(item)}</li>`).join("")}</ul>`
      : "";
    return `
      <div class="event-window-summary">
        <div class="event-window-title">
          <strong>洪水事件表</strong>
          <span class="${statusClass(status)}">${escapeHtml(`${validCount}/${eventCount} 场有效`)}</span>
        </div>
        ${eventInfo.source_file ? `<div class="event-window-source" title="${escapeHtml(eventInfo.source_file)}">事件表：${escapeHtml(shortPath(eventInfo.source_file) || "已读取")}</div>` : ""}
        <div class="event-window-source">推荐表头：编号、开始时间、结束时间。事件之间允许资料间断。</div>
        <div class="event-window-row event-window-head">
          <span>事件</span>
          <span>洪水时段</span>
          <span>结论</span>
        </div>
        ${rows}
        ${more}
        ${issues}
      </div>
    `;
  }

  function renderEventForcingCoverage(coverage = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const statusClass = helpers.statusClass || defaultStatusClass;
    if (!coverage?.enabled) return "";
    const events = Array.isArray(coverage.events) ? coverage.events : [];
    const status = String(coverage.status || "warn").toLowerCase();
    const rows = events.slice(0, 30).map(event => {
      const variables = event.variables || {};
      const variableText = ["prec", "temp", "evap"].map(key => {
        const item = variables[key] || {};
        const label = item.label || key;
        const value = `${Number(item.covered_steps || 0)}/${Number(item.expected_steps || 0)}`;
        const missing = Number(item.missing_steps || 0);
        return missing > 0 ? `${label} ${value}，缺 ${missing}` : `${label} ${value}`;
      }).join("；");
      const conclusion = event.status === "ok" ? "完整" : `缺测：${variableText}`;
      return `
        <div class="event-window-row ${statusClass(event.status || "warn")}">
          <span><strong>${escapeHtml(event.name || event.event_id || "未命名事件")}</strong><small>${escapeHtml(event.event_id || "")}</small></span>
          <span>${escapeHtml(`${event.run_start || "—"} ~ ${event.run_end || "—"}`)}</span>
          <span class="${statusClass(event.status || "warn")}">${escapeHtml(conclusion)}</span>
        </div>
      `;
    }).join("");
    const more = events.length > 30
      ? `<div class="event-window-more">还有 ${events.length - 30} 场事件未展开。</div>`
      : "";
    return `
      <div class="event-window-summary">
        <div class="event-window-title">
          <strong>事件内气象覆盖</strong>
          <span class="${statusClass(status)}">${escapeHtml(`${Number(coverage.complete_event_count || 0)}/${Number(coverage.event_count || 0)} 场完整`)}</span>
        </div>
        <div class="event-window-source">只检查每场洪水内部气象资料；事件之间允许间断。</div>
        <div class="event-window-row event-window-head">
          <span>事件</span>
          <span>洪水时段</span>
          <span>结论</span>
        </div>
        ${rows || '<div class="hint-box status-warn">尚未形成可检查的洪水事件。</div>'}
        ${more}
      </div>
    `;
  }

  function renderEventObservationCoverage(coverage = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const statusClass = helpers.statusClass || defaultStatusClass;
    if (!coverage?.enabled) return "";
    const events = Array.isArray(coverage.events) ? coverage.events : [];
    const status = String(coverage.status || "warn").toLowerCase();
    const rows = events.slice(0, 30).map(event => {
      const expected = Number(event.expected_steps || 0);
      const covered = Number(event.covered_steps || 0);
      const missing = Number(event.missing_steps || 0);
      const ratio = expected > 0 ? `${((covered / expected) * 100).toFixed(1)}%` : "—";
      const preview = Array.isArray(event.missing_preview) && event.missing_preview.length
        ? `；缺测示例：${event.missing_preview.slice(0, 3).join("、")}`
        : "";
      const conclusion = event.status === "ok" ? "完整" : `${event.status === "fail" ? "需补齐" : "需复核"}：覆盖率 ${ratio}${missing > 0 ? `，缺 ${missing}` : ""}${preview}`;
      return `
        <div class="event-window-row ${statusClass(event.status || "warn")}">
          <span><strong>${escapeHtml(event.name || event.event_id || "未命名事件")}</strong><small>${escapeHtml(event.event_id || "")}</small></span>
          <span>${escapeHtml(`${event.score_start || "—"} ~ ${event.score_end || "—"}`)}</span>
          <span class="${statusClass(event.status || "warn")}">${escapeHtml(conclusion)}</span>
        </div>
      `;
    }).join("");
    const more = events.length > 30
      ? `<div class="event-window-more">还有 ${events.length - 30} 场事件未展开。</div>`
      : "";
    return `
      <div class="event-window-summary">
        <div class="event-window-title">
          <strong>事件流量覆盖</strong>
          <span class="${statusClass(status)}">${escapeHtml(`${Number(coverage.complete_event_count || 0)}/${Number(coverage.event_count || 0)} 场完整`)}</span>
        </div>
        <div class="event-window-source">只检查每场洪水内部实测流量；事件之间允许间断。</div>
        <div class="event-window-row event-window-head">
          <span>事件</span>
          <span>洪水时段</span>
          <span>结论</span>
        </div>
        ${rows || '<div class="hint-box status-warn">尚未形成可检查的洪水事件。</div>'}
        ${more}
      </div>
    `;
  }

  window.HBVStudioEventMode = {
    floodEventEvaluation,
    floodEventObjectiveText,
    floodEventRows,
    floodEventStatusText,
    eventChartEvents,
    initialStatePolicyLabel,
    renderFloodEventChart,
    renderEventWindowSummary,
    renderEventForcingCoverage,
    renderEventObservationCoverage,
  };
})();
