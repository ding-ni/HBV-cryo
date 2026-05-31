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

  window.HBVStudioStationPrecip = {
    renderTaskScopeSummary,
    renderEventCoverageMatrix,
  };
})();
