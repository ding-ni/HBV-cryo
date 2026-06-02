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

  function defaultFocusStatusClass(status) {
    return status === "ok" ? "status-ok" : status === "fail" ? "status-fail" : "status-warn";
  }

  function defaultFocusStatusLabel(status) {
    return ({ ok: "通过", warn: "需复核", fail: "未通过" })[status] || "需复核";
  }

  function renderEngineeringFocusChecks(checks = [], options = {}, helpers = {}) {
    const items = Array.isArray(checks) ? checks : [];
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const focusStatusClass = helpers.focusStatusClass || defaultFocusStatusClass;
    const focusStatusLabel = helpers.focusStatusLabel || defaultFocusStatusLabel;
    const renderStationEventCoverage = helpers.renderStationEventCoverage || (() => "");
    const title = options.title || "专项检查";
    const emptyText = options.emptyText || "暂无专项检查。";
    if (!items.length) {
      return `<div class="hint-box">${escapeHtml(emptyText)}</div>`;
    }
    return `
    <div class="focus-check-grid">
      ${items.map(check => `
        <section class="focus-check-card">
          <div class="focus-check-head">
            <strong>${escapeHtml(check.title || title)}</strong>
            <span class="status-badge ${focusStatusClass(check.status)}">${escapeHtml(focusStatusLabel(check.status))}</span>
          </div>
          <div class="focus-check-summary">${escapeHtml(check.summary || "")}</div>
          <div class="focus-check-items">
            ${(check.items || []).map(item => `
              <div class="focus-check-item">
                <span class="focus-check-label">${escapeHtml(item.label || "")}</span>
                <span class="focus-check-value ${focusStatusClass(item.status)}">${escapeHtml(item.value || "—")}</span>
              </div>
            `).join("")}
          </div>
          ${renderStationEventCoverage(check, helpers)}
        </section>
      `).join("")}
    </div>
  `;
  }

  function engineeringFocusChecksState(selector, checks = [], options = {}, helpers = {}) {
    const html = renderEngineeringFocusChecks(checks, options, helpers);
    return {
      html,
      domUpdates: [{ selector, html }],
    };
  }

  window.HBVStudioEngineeringFocusView = {
    engineeringFocusChecksState,
    renderEngineeringFocusChecks,
  };
})();
