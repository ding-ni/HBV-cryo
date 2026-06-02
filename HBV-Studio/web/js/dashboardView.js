(function () {
  function emptyWorkspaceHint() {
    return '<div class="hint-box">还没有工作区。点击上方按钮新建流域项目，或从模板复制。</div>';
  }

  function emptyTemplateHint() {
    return '<div class="hint-box">未发现模板。</div>';
  }

  function renderWorkspaceCards(workspaces, helpers = {}) {
    const items = Array.isArray(workspaces) ? workspaces : [];
    if (!items.length) return emptyWorkspaceHint();

    const escapeHtml = helpers.escapeHtml;
    const profileBadge = helpers.profileBadge;
    const workspaceNextStepText = helpers.workspaceNextStepText;
    const shortPath = helpers.shortPath;
    const objectLabels = helpers.objectLabels || {};
    const selectedPath = String(helpers.selectedPath || "");

    return items.map(w => `
    <div class="workspace-card ${selectedPath === w.path ? "selected" : ""}" data-workspace-path="${escapeHtml(w.path)}">
      <div class="workspace-card-info" style="flex:1;min-width:0">
        <div class="list-item-head">
          <strong>${escapeHtml(w.flow_name || w.name)}</strong>
          <div style="display:flex;gap:6px;align-items:center">
            ${profileBadge(w.calibration_mode)}
            ${w.workflow?.ready_for_calibration
              ? '<span class="status-badge status-ok">可率定</span>'
              : w.workflow?.pending_validation
                ? '<span class="status-badge status-warn">待检查</span>'
                : '<span class="status-badge status-warn">待完善</span>'}
            <button class="delete-ws-btn" data-delete-path="${escapeHtml(w.path)}" title="删除工作区">&times;</button>
          </div>
        </div>
        <small>${escapeHtml(objectLabels[w.object_type] || "未定义对象")}</small>
        <small>${escapeHtml(`步骤 ${w.workflow?.completed_count || 0}/${w.workflow?.total_steps || 0} · 下一步 ${workspaceNextStepText(w.workflow)}${w.workflow?.missing_count ? ` · 缺项 ${w.workflow.missing_count}` : ""}`)}</small>
        <div class="workspace-card-meta">
          <span>配置位置</span><code>${escapeHtml(shortPath(w.display_path || w.path) || "待保存")}</code>
          <span>运行目录</span><code>${escapeHtml(shortPath(w.runtime_display_path || w.workspace_root || "") || "待第 1 步保存后生成")}</code>
        </div>
        <div class="workspace-card-actions">
          <button class="ghost-button" data-preview-workspace="${escapeHtml(w.path)}">目录结构</button>
          <button class="ghost-button" data-view-workspace-runs="${escapeHtml(w.path)}">查看结果</button>
          <button class="ghost-button" data-open-workspace="${escapeHtml(w.path)}">进入向导</button>
        </div>
      </div>
    </div>
  `).join("");
  }

  function workspaceCardsState(workspaces, helpers = {}) {
    const html = renderWorkspaceCards(workspaces, helpers);
    return {
      html,
      domUpdates: [{ selector: "#workspace-card-list", html }],
    };
  }

  function renderTemplates(templates, helpers = {}) {
    const items = Array.isArray(templates) ? templates : [];
    if (!items.length) return emptyTemplateHint();

    const escapeHtml = helpers.escapeHtml;
    const profileBadge = helpers.profileBadge;
    const objectLabels = helpers.objectLabels || {};

    return items.map(t => `
    <div class="list-item">
      <div class="list-item-head">
        <strong>${escapeHtml(t.title)}</strong>
        ${profileBadge(t.calibration_mode)}
      </div>
      <small>${escapeHtml(t.description || t.display_path)}</small>
      <small>${escapeHtml(objectLabels[t.object_type] || "未定义对象")}</small>
      <div class="action-row">
        <button class="ghost-button" data-template-instantiate="${escapeHtml(t.id)}">复制为工作区</button>
        ${t.id === "tuotuohe-daily-builtin" ? '<button class="ghost-button" data-template-sync="tuotuohe">同步历史数据</button>' : ""}
      </div>
    </div>
  `).join("");
  }

  function templateListState(templates, helpers = {}) {
    const html = renderTemplates(templates, helpers);
    return {
      html,
      domUpdates: [{ selector: "#template-list", html }],
    };
  }

  window.HBVStudioDashboardView = {
    renderTemplates,
    renderWorkspaceCards,
    templateListState,
    workspaceCardsState,
  };
})();
