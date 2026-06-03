(function () {
  function emptyWorkspaceHint() {
    return '<div class="hint-box">还没有工作区。点击上方按钮新建流域项目，或从模板复制。</div>';
  }

  function emptyTemplateHint() {
    return '<div class="hint-box">未发现模板。</div>';
  }

  function defaultSamePath(a, b) {
    const left = String(a || "").trim();
    const right = String(b || "").trim();
    return Boolean(left && right && left === right);
  }

  function workspaceByPath(workspaces = [], path = "", helpers = {}) {
    const items = Array.isArray(workspaces) ? workspaces : [];
    const targetPath = String(path || "").trim();
    if (!targetPath) return null;

    const samePath = typeof helpers.samePath === "function" ? helpers.samePath : defaultSamePath;
    return items.find(item => samePath(item?.path, targetPath)) || null;
  }

  function workspaceExists(workspaces = [], path = "", helpers = {}) {
    return Boolean(workspaceByPath(workspaces, path, helpers));
  }

  function dashboardLayoutStaleState(workspaces = [], selectedPath = "", helpers = {}) {
    const path = String(selectedPath || "").trim();
    const stale = Boolean(path) && !workspaceExists(workspaces, path, helpers);
    return {
      stale,
      statePatch: stale
        ? {
            dashboardLayoutPath: "",
            dashboardWorkspaceLayout: null,
            dashboardGeoOverview: null,
          }
        : {},
    };
  }

  function workspaceLoadQueryState(model = {}) {
    const path = String(model.path || model.configPath || "").trim();
    return {
      ready: Boolean(path),
      message: path ? "" : "请选择工作区。",
      path,
      workspacePath: `/api/workspace?path=${encodeURIComponent(path)}`,
    };
  }

  function dashboardLoadQueryState() {
    return {
      dashboardPath: "/api/dashboard",
      fallbackPaths: {
        templates: "/api/templates",
        workspaces: "/api/workspaces",
        runs: "/api/runs",
        tasks: "/api/tasks",
      },
      fallbackOrder: ["templates", "workspaces", "runs", "tasks"],
    };
  }

  function dashboardDataState(data = {}) {
    return {
      statePatch: {
        templates: Array.isArray(data?.templates) ? data.templates : [],
        workspaces: Array.isArray(data?.workspaces) ? data.workspaces : [],
        runs: Array.isArray(data?.runs) ? data.runs : [],
        tasks: Array.isArray(data?.tasks) ? data.tasks : [],
      },
    };
  }

  function dashboardFallbackState(settled = []) {
    const valueAt = index => (
      settled[index]?.status === "fulfilled" && Array.isArray(settled[index]?.value?.data)
        ? settled[index].value.data
        : []
    );
    return {
      statePatch: {
        templates: valueAt(0),
        workspaces: valueAt(1),
        runs: valueAt(2),
        tasks: valueAt(3),
      },
      allFailed: settled.every(item => item?.status !== "fulfilled"),
    };
  }

  function templateListQueryState() {
    return {
      templatesPath: "/api/templates",
    };
  }

  function templateListDataState(data = []) {
    const templates = Array.isArray(data) ? data : [];
    return {
      templates,
      statePatch: { templates },
    };
  }

  function workspaceListQueryState() {
    return {
      workspacesPath: "/api/workspaces",
    };
  }

  function workspaceListDataState(data = []) {
    const workspaces = Array.isArray(data) ? data : [];
    return {
      workspaces,
      statePatch: { workspaces },
    };
  }

  function templateInstantiateRequestState(model = {}) {
    const templateId = String(model.templateId || model.id || "").trim();
    const workspaceName = String(model.workspaceName || model.name || "").trim();
    let reason = "";
    let message = "";
    if (!templateId) {
      reason = "missing-template";
      message = "请选择要复制的模板。";
    } else if (!workspaceName) {
      reason = "missing-name";
      message = "请输入工作区名称。";
    }
    return {
      ready: !reason,
      reason,
      message,
      templateId,
      workspaceName,
      requestPath: "/api/template/instantiate",
      payload: {
        template_id: templateId,
        workspace_name: workspaceName,
      },
    };
  }

  function templateInstantiateSuccessState(data = {}, helpers = {}) {
    const shortPath = helpers.shortPath || (value => String(value || ""));
    const workspacePath = String(data?.workspace_path || data?.path || "");
    return {
      workspacePath,
      toastText: `已复制模板：${shortPath(workspacePath)}`,
    };
  }

  function templateSyncRequestState() {
    return {
      ready: true,
      requestPath: "/api/template/sync-tuotuohe",
      payload: {},
    };
  }

  function templateSyncSuccessState(data = {}) {
    const label = String(data?.task?.label || data?.label || "同步任务").trim() || "同步任务";
    return {
      label,
      toastText: `已启动：${label}`,
    };
  }

  function workspaceDeleteRequestState(model = {}) {
    const path = String(model.path || model.deletePath || "").trim();
    const name = String(model.name || "").trim();
    const displayName = name || path;
    return {
      ready: Boolean(path),
      reason: path ? "" : "missing-workspace",
      message: path ? "" : "请选择要删除的工作区。",
      path,
      name,
      requestPath: "/api/workspace/delete",
      payload: { path },
      confirmText: displayName
        ? `确定要删除工作区「${displayName}」吗？此操作仅删除配置文件，不会删除运行目录中的数据。`
        : "确定要删除该工作区吗？此操作仅删除配置文件，不会删除运行目录中的数据。",
      toastText: "已删除工作区",
    };
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
    const samePath = typeof helpers.samePath === "function" ? helpers.samePath : defaultSamePath;

    return items.map(w => `
    <div class="workspace-card ${samePath(selectedPath, w.path) ? "selected" : ""}" data-workspace-path="${escapeHtml(w.path)}">
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
    dashboardDataState,
    dashboardFallbackState,
    dashboardLayoutStaleState,
    dashboardLoadQueryState,
    renderTemplates,
    renderWorkspaceCards,
    templateInstantiateRequestState,
    templateInstantiateSuccessState,
    templateListDataState,
    templateListQueryState,
    templateListState,
    templateSyncRequestState,
    templateSyncSuccessState,
    workspaceByPath,
    workspaceCardsState,
    workspaceDeleteRequestState,
    workspaceExists,
    workspaceListDataState,
    workspaceListQueryState,
    workspaceLoadQueryState,
  };
})();
