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

  function formatNumber(value, digits = 3) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "\u2014";
    return Number(value).toFixed(digits);
  }

  function finiteNumber(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function formatDateTime(value) {
    if (!value) return "\u2014";
    const date = new Date(Number(value) * 1000 || value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function shortPath(value = "") {
    if (!value) return "\u2014";
    return String(value || "").replace(/\\/g, "/").replace(/^.*\/([^/]+)$/, "$1");
  }

  function slashPath(value = "") {
    return String(value || "").replace(/\\/g, "/");
  }

  function normalizePath(value = "") {
    return slashPath(value).trim().toLowerCase();
  }

  function samePath(leftValue = "", rightValue = "") {
    const left = normalizePath(leftValue);
    const right = normalizePath(rightValue);
    return Boolean(left && right && left === right);
  }

  function formatDurationSeconds(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "\u2014";
    const total = Math.max(0, Math.round(Number(value)));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
    if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
    return `${seconds}s`;
  }

  function profileLabel(value = "") {
    return value === "hourly" ? "小时尺度" : value === "daily" ? "日尺度" : "未选择";
  }

  function profileBadge(value = "") {
    return `<span class="status-badge">${profileLabel(value)}</span>`;
  }

  function focusStatusLabel(status = "") {
    return ({ ok: "通过", warn: "注意", fail: "未通过" })[String(status || "").toLowerCase()] || "待检查";
  }

  function focusStatusClass(status = "") {
    return status === "ok" ? "status-ok" : status === "fail" ? "status-fail" : "status-warn";
  }

  function pollingScheduleState(model = {}) {
    const hasRunningTasks = Boolean(model.hasRunningTasks || model.hasRunning);
    const currentView = String(model.currentView || "");
    const runRefreshViews = new Set(["dashboard", "forecast", "results"]);
    return {
      hasRunningTasks,
      currentView,
      immediateTaskRefreshDelayMs: hasRunningTasks ? 1500 : 0,
      nextTaskPollDelayMs: hasRunningTasks ? 3000 : 8000,
      shouldRefreshRuns: hasRunningTasks || runRefreshViews.has(currentView),
      nextRunPollDelayMs: hasRunningTasks ? 12000 : 20000,
    };
  }

  function toastState(message = "", isError = false) {
    const error = Boolean(isError);
    return {
      text: String(message ?? ""),
      isError: error,
      borderColor: error ? "rgba(181,69,56,0.32)" : "rgba(20,79,84,0.28)",
      visibleClass: "visible",
      autoHideDelayMs: 2800,
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

  function licenseBannerState(license = null) {
    const info = license && typeof license === "object" ? license : null;
    if (!info) {
      return {
        visible: false,
        text: "",
        className: "license-banner",
        domUpdates: [{ selector: "#license-banner", text: "", className: "license-banner", visible: false }],
      };
    }
    const expired = Boolean(info.expired);
    const warning = Boolean(info.warning);
    const show = expired || warning;
    const message = String(info.message || "");
    const detail = String(info.detail || "");
    const text = detail ? `${message} ${detail}` : message;
    const tone = expired ? "expired" : warning ? "warn" : "";
    const className = tone ? `license-banner ${tone}` : "license-banner";
    return {
      visible: show,
      text,
      className,
      domUpdates: [
        {
          selector: "#license-banner",
          text: show ? text : "",
          className,
          visible: show,
        },
      ],
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

  function viewNavigationState(model = {}) {
    const currentView = String(model.currentView || "");
    const targetView = String(model.targetView || "");
    const workspacePath = String(model.workspacePath || "").trim();
    const shouldSaveWizardStep = currentView === "wizard" && targetView !== "wizard" && Boolean(workspacePath);
    const requiresCalibrationReadiness = shouldSaveWizardStep && targetView === "calibration";
    return {
      currentView,
      targetView,
      workspacePath,
      shouldSaveWizardStep,
      requiresCalibrationReadiness,
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
    finiteNumber,
    formatDateTime,
    formatDurationSeconds,
    formatNumber,
    focusStatusClass,
    focusStatusLabel,
    healthQueryState,
    pollingScheduleState,
    profileBadge,
    profileLabel,
    quitRequestState,
    servicePillState,
    licenseBannerState,
    sidebarContextState,
    sidebarCountsState,
    normalizePath,
    samePath,
    shortPath,
    slashPath,
    toastState,
    viewNavigationState,
    viewSelectionState,
    windowUnloadRequestState,
  };
})();
