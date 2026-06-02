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

  function formatPrepDisplayTitle(index, title) {
    const clean = String(title || "").replace(/^\d+\.\s*/, "").trim();
    return `${index}. ${clean}`;
  }

  function dependencyLabel(depId, visibleSteps, allSteps, helpers = {}) {
    const isGisStepId = helpers.isGisStepId || (() => false);
    if (isGisStepId(depId)) return "第 5 步地理数据";
    const step = (visibleSteps || []).find(item => item.id === depId)
      || (allSteps || []).find(item => item.id === depId);
    return String(step?.displayTitle || step?.title || depId).replace(/^\d+\.\s*/, "").trim();
  }

  function formatPrepBlockedMessage(status, visibleSteps, allSteps = [], helpers = {}) {
    const blockedBy = Array.isArray(status?.blocked_by) ? status.blocked_by : [];
    if (!blockedBy.length) return String(status?.message || "尚未检测。");
    const labels = blockedBy.map(depId => dependencyLabel(depId, visibleSteps, allSteps, helpers));
    return `依赖未满足：请先完成 ${labels.join("、")}。`;
  }

  function renderPrepStep(step, prepStatus, visibleSteps, allSteps, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const status = prepStatus?.[step.id] || {};
    const running = Boolean(status.running);
    const blocked = (status.blocked_by || []).length > 0;
    const text = running ? "执行中" : status.done ? "已完成" : blocked ? "依赖未满足" : status.manual ? "需补充资料" : "待执行";
    const statusClass = status.done ? "status-ok" : blocked ? "status-fail" : "status-warn";
    const canOverwrite = Boolean(step.supports_overwrite && status.done && !blocked && !step.manual && !running);
    const message = running
      ? String(status.message || "正在执行，请看下方日志。")
      : blocked
        ? formatPrepBlockedMessage(status, visibleSteps, allSteps, helpers)
        : String(status.message || "尚未检测。");
    const runButton = !step.manual
      ? `<button class="ghost-button" data-run-step="${escapeHtml(step.id)}" ${(blocked || running) ? "disabled" : ""}>${running ? "执行中..." : status.done ? "重新运行" : "运行此步"}</button>`
      : "";
    const overwriteButton = canOverwrite
      ? `<button class="ghost-button" data-run-step-overwrite="${escapeHtml(step.id)}">覆盖重跑</button>`
      : "";
    return `
      <div class="prep-step">
        <div class="prep-step-head">
          <div>
            <strong>${escapeHtml(step.displayTitle || step.title)}</strong>
            <div class="panel-note">${escapeHtml(step.displayDescription || step.description || "")}</div>
          </div>
          <span class="status-badge ${statusClass}">${escapeHtml(text)}</span>
        </div>
        <div class="hint-box">${escapeHtml(message)}</div>
        <div class="prep-step-actions">
          ${runButton}
          ${overwriteButton}
        </div>
      </div>`;
  }

  function renderPrepStepList(model = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    if (!model.workspaceSelected) {
      return `<div class="hint-box">${escapeHtml(model.emptyText || "先选择或创建工作区。")}</div>`;
    }
    const steps = Array.isArray(model.steps) ? model.steps : [];
    if (!steps.length) {
      return `<div class="hint-box">${escapeHtml(model.noStepsText || "当前工作区无需额外气象准备步骤。")}</div>`;
    }
    const allSteps = Array.isArray(model.allSteps) ? model.allSteps : [];
    const prepStatus = model.prepStatus || {};
    return steps.map(step => renderPrepStep(step, prepStatus, steps, allSteps, helpers)).join("");
  }

  function renderBootstrapStatus(items = [], helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    if (!Array.isArray(items) || !items.length) {
      return '<div class="hint-box">暂无 GIS 步骤状态信息。</div>';
    }
    return items.map(item => {
      const isDisabledOptional = item.optional && String(item.message || "").includes("未启用");
      const badge = isDisabledOptional ? "未启用" : item.done ? "已完成" : "待执行";
      const badgeClass = isDisabledOptional ? "" : item.done ? "status-ok" : "status-warn";
      return `
      <div class="bootstrap-item ${item.done ? "done" : ""}">
        <span class="status-badge ${badgeClass}">${escapeHtml(badge)}</span>
        <span>${escapeHtml(item.title || item.id)}</span>
        <small style="margin-left:auto;color:var(--muted)">${escapeHtml(item.message || "")}</small>
      </div>`;
    }).join("");
  }

  window.HBVStudioDataPrepView = {
    formatPrepDisplayTitle,
    formatPrepBlockedMessage,
    renderBootstrapStatus,
    renderPrepStepList,
  };
})();
