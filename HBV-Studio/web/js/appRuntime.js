(function () {
  function jsonBody(payload = {}) {
    return JSON.stringify(payload && typeof payload === "object" ? payload : {});
  }

  function windowUnloadRequestState(payload = {}) {
    const body = jsonBody(payload);
    return {
      ready: true,
      method: "POST",
      requestPath: "/api/app/window-unload",
      payload: payload && typeof payload === "object" ? payload : {},
      body,
      contentType: "application/json",
      headers: { "Content-Type": "application/json" },
      keepalive: true,
    };
  }

  function quitRequestState() {
    return {
      ready: true,
      requestPath: "/api/app/quit",
      payload: {},
    };
  }

  function healthQueryState() {
    return {
      ready: true,
      healthPath: "/api/health",
    };
  }

  function servicePillState(ok, message = "") {
    const connected = Boolean(ok);
    const text = String(message || "");
    const className = `service-pill ${connected ? "connected" : "error"}`;
    return {
      connected,
      text,
      className,
      domUpdates: [{ selector: "#service-pill", text, className }],
    };
  }

  function itemCount(value) {
    return Array.isArray(value) ? value.length : 0;
  }

  function sidebarCountsState(model = {}) {
    const counts = {
      templates: itemCount(model.templates),
      workspaces: itemCount(model.workspaces),
      runs: itemCount(model.runs),
      tasks: itemCount(model.tasks),
    };
    return {
      counts,
      domUpdates: [
        { selector: "#count-templates", text: String(counts.templates) },
        { selector: "#count-workspaces", text: String(counts.workspaces) },
        { selector: "#count-runs", text: String(counts.runs) },
        { selector: "#count-tasks", text: String(counts.tasks) },
      ],
    };
  }

  function defaultShortPath(value = "") {
    if (!value) return "—";
    return String(value).replace(/\\/g, "/").replace(/^.*\/([^/]+)$/, "$1");
  }

  function defaultProfileLabel(value = "") {
    return value === "hourly" ? "小时尺度" : value === "daily" ? "日尺度" : "未选择";
  }

  function workflowStatusText(workflow = null) {
    if (!workflow) return "未检查";
    const completed = workflow.completed_count || 0;
    const total = workflow.total_steps || 0;
    if (workflow.ready_for_calibration) return `可率定 · ${completed}/${total}`;
    if (workflow.pending_validation) return `待检查 · ${completed}/${total}`;
    return `未就绪 · ${completed}/${total}`;
  }

  function sidebarContextState(model = {}, helpers = {}) {
    const currentWorkspace = model.currentWorkspace || null;
    const workspacePath = String(model.workspacePath || "");
    const workflow = model.workflow || null;
    const objectLabels = helpers.objectLabels || {};
    const workspaceLabelByPath = typeof helpers.workspaceLabelByPath === "function"
      ? helpers.workspaceLabelByPath
      : value => String(value || "");
    const shortPath = typeof helpers.shortPath === "function" ? helpers.shortPath : defaultShortPath;
    const profileLabel = typeof helpers.profileLabel === "function" ? helpers.profileLabel : defaultProfileLabel;
    const workspaceNextStepText = typeof helpers.workspaceNextStepText === "function"
      ? helpers.workspaceNextStepText
      : () => "—";

    const workspaceText = currentWorkspace
      ? (String(currentWorkspace?.["流域名称"] || "").trim() || workspaceLabelByPath(workspacePath) || shortPath(workspacePath))
      : "未选择";
    const profileText = profileLabel(currentWorkspace?.["率定模式"]);
    const objectText = objectLabels[currentWorkspace?.["项目对象"]] || "未选择";
    const workflowText = workflowStatusText(workflow);
    const nextStepText = workspaceNextStepText(workflow);

    const context = {
      workspaceText,
      profileText,
      objectText,
      workflowText,
      nextStepText,
    };
    return {
      context,
      domUpdates: [
        { selector: "#sidebar-current-workspace", text: workspaceText },
        { selector: "#sidebar-current-profile", text: profileText },
        { selector: "#sidebar-current-object", text: objectText },
        { selector: "#sidebar-current-workflow", text: workflowText },
        { selector: "#sidebar-next-step", text: nextStepText },
      ],
    };
  }

  function viewSelectionState(view = "", viewMeta = {}) {
    const requestedView = String(view || "").trim();
    const selectedView = viewMeta && Object.prototype.hasOwnProperty.call(viewMeta, requestedView)
      ? requestedView
      : "dashboard";
    const meta = viewMeta?.[selectedView] || {};
    const title = String(meta.title || "");
    const subtitle = String(meta.subtitle || "");
    return {
      requestedView,
      selectedView,
      title,
      subtitle,
      domUpdates: [
        { selector: "#page-title", text: title },
        { selector: "#page-subtitle", text: subtitle },
      ],
    };
  }

  window.HBVStudioAppRuntime = {
    healthQueryState,
    quitRequestState,
    servicePillState,
    sidebarContextState,
    sidebarCountsState,
    viewSelectionState,
    windowUnloadRequestState,
  };
})();
