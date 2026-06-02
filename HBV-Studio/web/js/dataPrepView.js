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

  function inputCheckReadyHeadline(stage = "calibration") {
    if (stage === "calibration") return "所有率定所需数据已就位，可以进入率定！";
    if (stage === "quick_test") return "输入预核算所需数据已就位，可以进行限定时段前向计算。";
    return "所有手调/重算所需运行时数据已就位，可以继续前向重算。";
  }

  function renderInputCheckItems(items = [], helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const renderIssueJumpButton = helpers.renderIssueJumpButton || (() => "");
    return (Array.isArray(items) ? items : []).map(item => (
      `<li>${escapeHtml(item)}${renderIssueJumpButton(item, 7)}</li>`
    )).join("");
  }

  function renderInputCheckRecommendations(advice = {}, ready = false, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const inferIssueTarget = helpers.inferIssueTarget || (() => null);
    const recommendations = Array.isArray(advice?.recommendations) ? advice.recommendations : [];
    if (!recommendations.length) return "";
    const items = recommendations.slice(0, 4).map(item => {
      const target = inferIssueTarget(item.detail, item.target_step || 7);
      const stepBtn = target
        ? ` <button class="ghost-button" data-go-step="${escapeHtml(target.step)}" data-go-selector="${escapeHtml(target.selector || "")}" style="padding:4px 10px;font-size:12px">定位</button>`
        : "";
      return `<li><strong>${escapeHtml(item.title)}</strong>：${escapeHtml(item.detail)}${stepBtn}</li>`;
    }).join("");
    return `<div class="hint-box ${ready ? "status-ok" : "status-warn"}" style="margin-bottom:12px"><strong>智能建议：</strong><ul>${items}</ul></div>`;
  }

  function renderInputCheckDetailTable(detailData = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const groups = {};
    for (const item of (Array.isArray(detailData?.summary) ? detailData.summary : [])) {
      const groupName = item.group || "其他";
      if (!groups[groupName]) groups[groupName] = [];
      groups[groupName].push(item);
    }
    let html = '<div class="check-detail-table">';
    for (const [groupName, items] of Object.entries(groups)) {
      html += `<div class="check-group-title">${escapeHtml(groupName)}</div>`;
      for (const item of items) {
        const okClass = item.ok === true ? "status-ok" : item.ok === false ? "status-fail" : "";
        html += `<div class="check-row ${okClass}">
          <span class="check-label">${escapeHtml(item.label)}</span>
          <span class="check-value">${escapeHtml(String(item.value))}</span>
        </div>`;
      }
    }
    html += "</div>";
    return html;
  }

  function renderInputCheckResults(model = {}, helpers = {}) {
    const renderValidationEventSections = helpers.renderValidationEventSections || (() => "");
    const renderEngineeringFocusChecks = helpers.renderEngineeringFocusChecks || (() => "");
    const validation = model.validation || {};
    const comp = model.comp || {
      ready: Boolean(validation.valid),
      missing: validation.missing || [],
      warnings: validation.warnings || [],
    };
    const stage = String(model.stage || "calibration");
    const detail = Boolean(model.detail);
    const detailData = model.detailData || null;
    const advice = model.advice || null;

    let html = "";
    html += renderValidationEventSections(validation);

    if (comp.ready) {
      html += `<div class="hint-box status-ok" style="margin-bottom:12px"><strong>${inputCheckReadyHeadline(stage)}</strong></div>`;
    } else {
      const missingItems = renderInputCheckItems(comp.missing || [], helpers);
      html += `<div class="hint-box status-fail" style="margin-bottom:12px"><strong>以下数据缺失或配置不完整：</strong><ul>${missingItems || "<li>请完成前序步骤</li>"}</ul></div>`;
    }

    if (Array.isArray(comp.warnings) && comp.warnings.length > 0) {
      const warnItems = renderInputCheckItems(comp.warnings, helpers);
      html += `<div class="hint-box status-warn" style="margin-bottom:12px"><strong>注意事项：</strong><ul>${warnItems}</ul></div>`;
    }

    if (Array.isArray(validation.focus_checks) && validation.focus_checks.length) {
      html += `<div style="margin-bottom:12px"><strong style="display:block;margin-bottom:8px">专项工程检查</strong>${renderEngineeringFocusChecks(validation.focus_checks, { title: "专项工程检查" })}</div>`;
    }

    if (detail && stage === "calibration" && Array.isArray(detailData?.reasonableness_checks) && detailData.reasonableness_checks.length) {
      html += `<div style="margin-bottom:12px"><strong style="display:block;margin-bottom:8px">数值合理性检查</strong>${renderEngineeringFocusChecks(detailData.reasonableness_checks, { title: "数值合理性检查", emptyText: "暂无数值合理性检查。" })}</div>`;
    }

    if (detail && stage === "calibration") {
      html += renderInputCheckRecommendations(advice, comp.ready, helpers);
    }

    if (detail && detailData) {
      html += renderInputCheckDetailTable(detailData, helpers);
    } else {
      html += '<div class="hint-box">当前显示的是输入检查概览。需要逐项明细时，再点击“运行检查”。</div>';
    }

    return html;
  }

  window.HBVStudioDataPrepView = {
    formatPrepDisplayTitle,
    formatPrepBlockedMessage,
    renderBootstrapStatus,
    renderInputCheckResults,
    renderPrepStepList,
  };
})();
