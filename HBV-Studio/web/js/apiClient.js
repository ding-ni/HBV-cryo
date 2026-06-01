(function () {
  const connectionError = "未连接到 HBV-Studio 本地服务，请使用 python HBV-Studio/launch.py 启动。";

  function responseSnippet(text) {
    return String(text || "").replace(/\s+/g, " ").trim().slice(0, 120);
  }

  async function parseApiResponse(response) {
    const text = await response.text();
    let payload;
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      const snippet = responseSnippet(text);
      throw new Error(`本地服务返回了无法识别的内容：${response.status}${snippet ? `，响应片段：${snippet}` : ""}`);
    }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `请求失败：${response.status}`);
    }
    return payload;
  }

  async function apiGet(path) {
    let response;
    try {
      response = await fetch(path);
    } catch {
      throw new Error(connectionError);
    }
    return parseApiResponse(response);
  }

  async function apiPost(path, body) {
    let response;
    try {
      response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      throw new Error(connectionError);
    }
    return parseApiResponse(response);
  }

  function createLatestRequestGuard() {
    let activeToken = 0;
    return {
      next() {
        activeToken += 1;
        return activeToken;
      },
      cancel() {
        activeToken += 1;
        return activeToken;
      },
      isActive(token) {
        return token === activeToken;
      },
    };
  }

  window.HBVStudioApiClient = {
    apiGet,
    apiPost,
    createLatestRequestGuard,
  };
})();
