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

  window.HBVStudioAppRuntime = {
    healthQueryState,
    quitRequestState,
    windowUnloadRequestState,
  };
})();
