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

  function defaultSamePath(a, b) {
    return String(a || "") === String(b || "");
  }

  function filterGroup(label, options, attrName, isActive, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    return `
      <div class="results-filter-group">
        <span class="results-filter-label">${escapeHtml(label)}</span>
        ${(options || []).map(item => `
          <button class="phase-chip ${isActive(item) ? "active" : ""}" ${attrName}="${escapeHtml(item.value ?? item.path ?? "")}" ${item.disabled ? "disabled" : ""}>
            ${escapeHtml(item.label)}
          </button>
        `).join("")}
      </div>
    `;
  }

  function renderFilterToolbar(model = {}, helpers = {}) {
    const samePath = helpers.samePath || defaultSamePath;
    return [
      filterGroup(
        "工作区",
        model.workspaceOptions || [],
        "data-run-filter-path",
        item => samePath(item.path || "", model.selectedWorkspacePath || "") || (!item.path && !model.selectedWorkspacePath),
        helpers
      ),
      filterGroup(
        "率定方案",
        model.profileOptions || [],
        "data-run-filter-profile",
        item => String(item.value || "") === String(model.selectedProfile || ""),
        helpers
      ),
      filterGroup(
        "结果阶段",
        model.stageOptions || [],
        "data-run-filter-type",
        item => String(item.value || "") === String(model.selectedType || ""),
        helpers
      ),
      filterGroup(
        "手调能力",
        model.editabilityOptions || [],
        "data-run-filter-editability",
        item => String(item.value || "all") === String(model.selectedEditability || "all"),
        helpers
      ),
    ].join("");
  }

  function resultsFilterHint(model = {}) {
    const breakdown = String(model.breakdown || "").trim();
    const totalRuns = Number(model.totalRuns || 0);
    const shownCount = Number(model.shownCount || 0);
    const suffix = breakdown ? ` 其中 ${breakdown}。` : "";
    if (!model.filtersActive) {
      return {
        text: `当前显示全部结果，共 ${totalRuns} 组。${suffix}`,
        className: "hint-box",
      };
    }
    const workspaceText = model.workspaceText || "全部工作区";
    const profileText = model.profileText || "全部尺度";
    const stageText = model.stageText || "全部阶段";
    const abilityText = model.abilityText || "全部手调能力";
    return {
      text: `当前筛选：${workspaceText} / ${profileText} / ${stageText} / ${abilityText}，共 ${shownCount} 组。${suffix}`,
      className: shownCount ? "hint-box status-ok" : "hint-box status-warn",
    };
  }

  function renderMetricStrip(items = [], helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    return (items || []).map(item => `
      <div class="metric-tile">
        <span>${escapeHtml(item.l)}</span>
        <strong>${escapeHtml(item.v)}</strong>
      </div>
    `).join("");
  }

  function renderRunExportFields(fields = [], helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    return (fields || []).map(field => `
      <label class="phase-chip" style="cursor:pointer">
        <input type="checkbox" data-run-export-field="${escapeHtml(field.key)}" ${field.checked ? "checked" : ""} style="margin-right:6px">
        ${escapeHtml(field.label)}
      </label>
    `).join("");
  }

  window.HBVStudioResultsView = {
    renderFilterToolbar,
    renderMetricStrip,
    renderRunExportFields,
    resultsFilterHint,
  };
})();
