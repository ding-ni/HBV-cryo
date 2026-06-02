(function () {
  function defaultEscapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function defaultStatusClass(status) {
    return status === "ok" ? "status-ok" : status === "fail" ? "status-fail" : "status-warn";
  }

  function defaultStatusLabel(status) {
    return status === "ok" ? "通过" : status === "fail" ? "不通过" : "提示";
  }

  function defaultFormatNumber(value, digits = 1) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "—";
  }

  function coveragePercent(value, formatNumber) {
    const ratio = Number(value);
    return Number.isFinite(ratio) ? `${formatNumber(ratio * 100, 1)}%` : "未覆盖";
  }

  function stationCountText(item = {}, formatNumber = defaultFormatNumber) {
    const minCount = Number(item.available_station_min ?? item.min_available_station_count);
    const meanCount = Number(item.available_station_mean ?? item.mean_available_station_count);
    if (!Number.isFinite(minCount)) return "未形成";
    if (!Number.isFinite(meanCount)) return `最少 ${minCount}`;
    return `最少 ${minCount}，平均 ${formatNumber(meanCount, 1)}`;
  }

  function stationPrecipModeLabel(mode) {
    return ({
      grid_only: "格点直接使用",
      grid_plus_station_bias: "格点 + 站点偏差订正",
      thiessen_station_only: "纯泰森多边形插值",
    })[String(mode || "").toLowerCase()] || "格点直接使用";
  }

  function stationPrecipModeDescription(mode) {
    if (mode === "grid_plus_station_bias") {
      return "用站点实测降水修正格点降水，生成逐栅格降水。";
    }
    if (mode === "thiessen_station_only") {
      return "用站点降水直接生成面降水，适合站点资料主导的任务。";
    }
    return "不启用站点订正或泰森分配，降水输入来自当前格点数据源。";
  }

  function stationPrecipCheckFromValidation(validation) {
    const checks = validation?.focus_checks || [];
    return checks.find(check => String(check?.id || "").toLowerCase() === "station_precip")
      || checks.find(check => String(check?.title || "").includes("站点降水"))
      || null;
  }

  function renderPrecipStrategyStatusCards(options = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const shortPath = helpers.shortPath || (value => value || "");
    const mode = options.mode || "grid_only";
    const stationPrec = options.stationPrec || "";
    const stationMeta = options.stationMeta || "";
    const needsStation = mode !== "grid_only";
    const stationReady = Boolean(stationPrec && stationMeta);
    const statusClass = !needsStation ? "status-ok" : stationReady ? "status-ok" : "status-warn";
    const statusText = !needsStation ? "未启用站点资料" : stationReady ? "站点资料已登记" : "待登记站点资料";
    return `
      <div class="workflow-signal-card ${statusClass}">
        <strong>${escapeHtml(stationPrecipModeLabel(mode))}</strong>
        <span>${escapeHtml(statusText)}</span>
        <small>${escapeHtml(stationPrecipModeDescription(mode))}</small>
      </div>
      <div class="workflow-signal-card ${needsStation ? (stationPrec ? "status-ok" : "status-warn") : ""}">
        <strong>站点降水表</strong>
        <span>${escapeHtml(needsStation ? (stationPrec ? shortPath(stationPrec) : "未选择") : "不需要")}</span>
        <small>提供逐时或逐日站点降水。</small>
      </div>
      <div class="workflow-signal-card ${needsStation ? (stationMeta ? "status-ok" : "status-warn") : ""}">
        <strong>站点空间信息</strong>
        <span>${escapeHtml(needsStation ? (stationMeta ? shortPath(stationMeta) : "未选择") : "不需要")}</span>
        <small>提供站号、经度、纬度。</small>
      </div>
    `;
  }

  function stationPrecipFallbackCheck(options = {}, helpers = {}) {
    const shortPath = helpers.shortPath || (value => value || "");
    const mode = options.mode || "grid_only";
    const stationPrec = options.stationPrec || "";
    const stationMeta = options.stationMeta || "";
    const needsStation = mode !== "grid_only";
    const status = !needsStation ? "ok" : (stationPrec && stationMeta ? "warn" : "fail");
    const summary = !needsStation
      ? "当前为格点基线模式，输入检查不会执行站点降水订正专项分析。"
      : (stationPrec && stationMeta
        ? "站点降水资料已登记，输入检查会判断资料是否可用。"
        : "当前降水方案需要站点降水表和站点空间信息，资料未完整登记。");
    return {
      title: "站点降水专项检查",
      summary,
      status,
      items: [
        { label: "降水方案", value: stationPrecipModeLabel(mode), status: needsStation ? "ok" : "warn" },
        {
          label: "站点降水表",
          value: stationPrec ? shortPath(stationPrec) : (needsStation ? "缺失" : "不需要"),
          status: !needsStation || stationPrec ? "ok" : "fail",
        },
        {
          label: "站点空间信息",
          value: stationMeta ? shortPath(stationMeta) : (needsStation ? "缺失" : "不需要"),
          status: !needsStation || stationMeta ? "ok" : "fail",
        },
      ],
    };
  }

  function renderTaskScopeSummary(check = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const focusStatusClass = helpers.focusStatusClass || defaultStatusClass;
    const focusStatusLabel = helpers.focusStatusLabel || defaultStatusLabel;
    const scope = check.task_context || {};
    if (!scope || !scope.headline) return "";
    const status = String(scope.status || check.status || "warn");
    const items = Array.isArray(scope.items) ? scope.items.slice(0, 6) : [];
    const stationRange = scope.station_time_range || {};
    const stationRangeText = stationRange.start || stationRange.end
      ? `${stationRange.start || "—"} 至 ${stationRange.end || "—"}`
      : "";
    return `
      <div class="station-scope-summary ${focusStatusClass(status)}">
        <div class="station-scope-head">
          <strong>站点降水检查口径</strong>
          <span class="status-badge ${focusStatusClass(status)}">${escapeHtml(focusStatusLabel(status))}</span>
        </div>
        <div class="station-scope-headline">${escapeHtml(scope.headline)}</div>
        <div class="station-scope-detail">${escapeHtml(scope.detail || "")}</div>
        <div class="station-scope-items">
          ${items.map(item => `
            <div class="station-scope-item">
              <span>${escapeHtml(item.label || "")}</span>
              <strong class="${focusStatusClass(item.status)}">${escapeHtml(item.value || "—")}</strong>
            </div>
          `).join("")}
          ${stationRangeText ? `
            <div class="station-scope-item">
              <span>站点资料范围</span>
              <strong>${escapeHtml(stationRangeText)}</strong>
            </div>
          ` : ""}
        </div>
      </div>
    `;
  }

  function renderEventCoverageMatrix(check = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const focusStatusClass = helpers.focusStatusClass || defaultStatusClass;
    const focusStatusLabel = helpers.focusStatusLabel || defaultStatusLabel;
    const formatNumber = helpers.formatNumber || defaultFormatNumber;
    const events = Array.isArray(check.event_coverage) ? check.event_coverage : [];
    if (!events.length) return "";
    const summary = check.event_coverage_summary || {};
    const okCount = Number(summary.ok_count ?? events.filter(item => item.status === "ok").length);
    const eventCount = Number(summary.event_count ?? events.length);
    const problemEvents = events.filter(item => String(item.status || "warn") !== "ok");
    const rows = problemEvents.slice(0, 8).map(item => {
      const status = String(item.status || "warn");
      const eventName = item.name || item.event_id || "未命名事件";
      const eventId = item.event_id && item.name ? `（${item.event_id}）` : "";
      const zeroSteps = Number(item.zero_available_steps || 0);
      const maxZero = Number(item.max_consecutive_zero_steps || 0);
      const coverage = coveragePercent(item.coverage_ratio, formatNumber);
      const stationText = stationCountText(item, formatNumber);
      const issueText = zeroSteps > 0 ? `${coverage}；${stationText}；无站点 ${zeroSteps} 步，最长连续 ${maxZero}` : `${coverage}；${stationText}`;
      return `
        <div class="event-coverage-row ${focusStatusClass(status)}">
          <span><strong>${escapeHtml(eventName)}</strong><small>${escapeHtml(eventId)}</small></span>
          <span>${escapeHtml(issueText)}</span>
          <span class="${focusStatusClass(status)}">${escapeHtml(focusStatusLabel(status))}</span>
        </div>
      `;
    }).join("");
    const more = problemEvents.length > 8
      ? `<div class="event-coverage-more">还有 ${problemEvents.length - 8} 场需复核。</div>`
      : "";
    return `
      <div class="event-coverage-matrix">
        <div class="event-coverage-title">
          <strong>洪水事件站点覆盖</strong>
          <span>${escapeHtml(`${okCount}/${eventCount} 场可用`)}</span>
        </div>
        <div class="event-coverage-more">仅列出需复核的洪水事件；全部通过时不展开明细。</div>
        ${rows ? `
          <div class="event-coverage-row event-coverage-head">
            <span>事件</span>
            <span>站点资料</span>
            <span>结论</span>
          </div>
        ` : ""}
        ${rows}
        ${more}
      </div>
    `;
  }

  function renderStationEventCoverage(check = {}, helpers = {}) {
    return `${renderTaskScopeSummary(check, helpers)}${renderEventCoverageMatrix(check, helpers)}`;
  }

  window.HBVStudioStationPrecip = {
    stationPrecipCheckFromValidation,
    stationPrecipModeDescription,
    stationPrecipModeLabel,
    renderPrecipStrategyStatusCards,
    stationPrecipFallbackCheck,
    renderTaskScopeSummary,
    renderEventCoverageMatrix,
    renderStationEventCoverage,
  };
})();
