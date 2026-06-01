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

  function layerStatusClass(layer) {
    if (layer?.status === "ok") return "status-ok";
    if (layer?.status === "missing") return "status-warn";
    return "status-fail";
  }

  function layerCssClass(layer) {
    const id = String(layer?.id || "").replace(/[^a-z0-9_-]/gi, "");
    return id ? `geo-layer-${id}` : "geo-layer-generic";
  }

  function previewBounds(overview) {
    const b = overview?.focus_bounds || overview?.bounds || null;
    if (!b) return null;
    const west = Number(b.west);
    const south = Number(b.south);
    const east = Number(b.east);
    const north = Number(b.north);
    if (![west, south, east, north].every(Number.isFinite) || east <= west || north <= south) return null;
    return { west, south, east, north };
  }

  function projectPoint(point, bounds, width = 640, height = 300, pad = 26) {
    const lon = Number(point?.[0]);
    const lat = Number(point?.[1]);
    const x = pad + ((lon - bounds.west) / (bounds.east - bounds.west)) * (width - pad * 2);
    const y = height - pad - ((lat - bounds.south) / (bounds.north - bounds.south)) * (height - pad * 2);
    return [Number.isFinite(x) ? x : pad, Number.isFinite(y) ? y : height - pad];
  }

  function pathFromRing(ring, bounds) {
    const points = Array.isArray(ring?.points) ? ring.points : [];
    if (points.length < 2) return "";
    return points.map((point, index) => {
      const [x, y] = projectPoint(point, bounds);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ") + " Z";
  }

  function renderLayerPaths(overview, bounds) {
    const layers = Array.isArray(overview?.layers) ? overview.layers : [];
    return layers
      .filter(layer => layer?.status === "ok" && layer.id !== "dem")
      .map(layer => (layer.rings || [])
        .map(ring => pathFromRing(ring, bounds))
        .filter(Boolean)
        .slice(0, 14)
        .map(d => `<path class="geo-layer ${layerCssClass(layer)}" d="${d}"></path>`)
        .join(""))
      .join("");
  }

  function renderLegend(overview, escapeHtml) {
    const layers = Array.isArray(overview?.layers) ? overview.layers : [];
    return layers.map(layer => `
      <div class="geo-preview-legend-item">
        <span class="geo-preview-swatch ${layerCssClass(layer)}"></span>
        <div>
          <strong>${escapeHtml(layer.label || "")}</strong>
          <span class="status-badge ${layerStatusClass(layer)}">${escapeHtml(layer.status === "ok" ? layer.message || "已识别" : layer.message || "未识别")}</span>
        </div>
      </div>
    `).join("");
  }

  function renderMetricTiles(overview, escapeHtml) {
    const layers = Array.isArray(overview?.layers) ? overview.layers : [];
    const dem = layers.find(layer => layer.id === "dem" && layer.status === "ok");
    const basin = layers.find(layer => layer.id === "basin" && layer.status === "ok");
    const glacier = layers.find(layer => layer.id === "glacier" && layer.status === "ok");
    const demStats = dem?.metrics?.stats || {};
    const tiles = [
      { label: "有效图层", value: `${Number(overview?.available_layer_count || 0)}/${layers.length || 4}` },
      { label: "流域要素", value: basin?.metrics?.feature_count != null ? String(basin.metrics.feature_count) : "未识别" },
      { label: "DEM 高程", value: demStats.min != null && demStats.max != null ? `${demStats.min} - ${demStats.max} m` : "未统计" },
      { label: "冰川图层", value: glacier ? "已识别" : "未配置" },
    ];
    return tiles.map(tile => `
      <div class="geo-preview-metric">
        <span>${escapeHtml(tile.label)}</span>
        <strong>${escapeHtml(tile.value)}</strong>
      </div>
    `).join("");
  }

  function renderOverview(overview, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    if (!overview) return "";
    const bounds = previewBounds(overview);
    const layers = Array.isArray(overview.layers) ? overview.layers : [];
    if (!bounds || !layers.length) {
      return `
        <section class="geo-preview-card">
          <div class="geo-preview-head">
            <div><strong>空间预览</strong><span>当前工作区</span></div>
            <span class="status-badge status-warn">暂无可绘制图层</span>
          </div>
        </section>
      `;
    }
    const hasDem = layers.some(layer => layer.id === "dem" && layer.status === "ok");
    return `
      <section class="geo-preview-card" data-geo-layer-count="${escapeHtml(String(overview.available_layer_count || 0))}">
        <div class="geo-preview-head">
          <div><strong>空间预览</strong><span>${escapeHtml(overview.flow_name || "当前工作区")}</span></div>
          <span class="status-badge ${Number(overview.available_layer_count || 0) >= 3 ? "status-ok" : "status-warn"}">
            ${escapeHtml(String(overview.available_layer_count || 0))} 类图层
          </span>
        </div>
        <div class="geo-preview-body">
          <div class="geo-preview-map">
            <svg class="geo-preview-svg" viewBox="0 0 640 300" role="img" aria-label="工作区空间预览">
              <rect class="geo-preview-frame" x="1" y="1" width="638" height="298" rx="4"></rect>
              ${hasDem ? '<rect class="geo-layer geo-layer-dem" x="26" y="26" width="588" height="248" rx="3"></rect>' : ""}
              ${renderLayerPaths(overview, bounds)}
            </svg>
          </div>
          <div class="geo-preview-side">
            <div class="geo-preview-metrics">${renderMetricTiles(overview, escapeHtml)}</div>
            <div class="geo-preview-legend">${renderLegend(overview, escapeHtml)}</div>
          </div>
        </div>
      </section>
    `;
  }

  window.HBVStudioGeoPreview = {
    renderOverview,
  };
})();
