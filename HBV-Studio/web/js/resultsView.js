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

  function defaultFormatNumber(value, digits = 4) {
    const num = Number(value);
    return Number.isFinite(num) ? num.toFixed(digits) : "—";
  }

  function defaultMetricValue(value, digits = 2, suffix = "") {
    const num = Number(value);
    return Number.isFinite(num) ? `${num.toFixed(digits)}${suffix}` : "—";
  }

  function defaultHydrologySummaryValue(summary = {}, key, fallback = "—") {
    const value = summary?.[key];
    return value === undefined || value === null || value === "" ? fallback : value;
  }

  function renderRunCard(run = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const samePath = helpers.samePath || defaultSamePath;
    const formatNumber = helpers.formatNumber || defaultFormatNumber;
    const formatMetricValue = helpers.formatMetricValue || defaultMetricValue;
    const hydrologySummaryValue = helpers.hydrologySummaryValue || defaultHydrologySummaryValue;
    const runWorkspaceName = helpers.runWorkspaceName || (() => "未命名工作区");
    const runTypeBadge = helpers.runTypeBadge || (() => "");
    const objectiveVersionBadge = helpers.objectiveVersionBadge || (() => "");
    const runDisplayName = helpers.runDisplayName || (item => item?.display_name || item?.name || "未命名结果");
    const runDisplaySubtitle = helpers.runDisplaySubtitle || (() => "");
    const selectedRunPath = String(helpers.selectedRunPath || "");
    const runWorkspaceFilterPath = String(helpers.runWorkspaceFilterPath || "");
    const hydro = run.hydrology_summary || {};
    return `
    <article class="list-item run-card ${selectedRunPath && samePath(selectedRunPath, run.path) ? "selected" : ""}" data-run-path="${escapeHtml(run.path)}">
      <div class="run-card-topline">
        <span class="run-card-kicker">${escapeHtml(runWorkspaceName(run))}</span>
        <div class="run-card-badges">
          ${runTypeBadge(run)}
          ${objectiveVersionBadge(run)}
          ${run.studio_compatible ? '<span class="status-badge status-ok">可继续手调</span>' : '<span class="status-badge status-warn">仅查看</span>'}
        </div>
      </div>
      <div class="list-item-head run-card-head">
        <div class="run-card-titlebox">
          <strong>${escapeHtml(runDisplayName(run))}</strong>
          ${runDisplaySubtitle(run) ? `<small class="run-card-subtitle">${escapeHtml(runDisplaySubtitle(run))}</small>` : ""}
        </div>
        <div class="run-card-score">
          <span>NSE 率定 / 验证</span>
          <strong>${escapeHtml(`${formatNumber(run?.nse_cal, 4)} / ${formatNumber(run?.nse_val, 4)}`)}</strong>
          <small>${escapeHtml(`PBIAS ${formatMetricValue(run?.pbias_cal, 2, "%")} / ${formatMetricValue(run?.pbias_val, 2, "%")}`)}</small>
        </div>
      </div>
      <div class="run-card-meta">
        <span class="run-meta-pill">${escapeHtml(hydrologySummaryValue(hydro, "workflow_label_zh", "单流程参数率定"))}</span>
        <span class="run-meta-pill">${escapeHtml(hydrologySummaryValue(hydro, "objective_label_zh", "综合水文目标函数"))}</span>
        <span class="run-meta-pill">${escapeHtml(hydrologySummaryValue(hydro, "flow_status_zh", "径流拟合未达标"))}</span>
      </div>
      <div class="workspace-card-actions run-card-actions">
        ${run.workspace_config && !samePath(run.workspace_config, runWorkspaceFilterPath) ? `<button class="ghost-button" data-filter-run-workspace="${escapeHtml(run.workspace_config)}">只看本工作区</button>` : ""}
        <button class="ghost-button" data-rename-run="${escapeHtml(run.path)}">${run.has_custom_title ? "修改标题" : "命名结果"}</button>
        <button class="ghost-button" data-open-run-dir="${escapeHtml(run.path)}">打开目录</button>
        <button class="ghost-button" data-delete-run="${escapeHtml(run.path)}">删除</button>
      </div>
    </article>
  `;
  }

  function renderRunCards(runs = [], helpers = {}) {
    const items = Array.isArray(runs) ? runs : [];
    return items.map(run => renderRunCard(run, helpers)).join("");
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
    renderRunCard,
    renderRunCards,
    renderRunExportFields,
    resultsFilterHint,
  };
})();
