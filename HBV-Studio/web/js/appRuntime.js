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

  window.HBVStudioAppRuntime = {
    healthQueryState,
    quitRequestState,
    servicePillState,
    sidebarCountsState,
    windowUnloadRequestState,
  };
})();
