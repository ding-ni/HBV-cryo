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

  function layerBounds(layer, fallback) {
    const b = layer?.bounds || fallback || null;
    if (!b) return null;
    const west = Number(b.west);
    const south = Number(b.south);
    const east = Number(b.east);
    const north = Number(b.north);
    if (![west, south, east, north].every(Number.isFinite) || east <= west || north <= south) return null;
    return { west, south, east, north };
  }

  function imageCoordinates(bounds) {
    if (!bounds) return null;
    return [
      [bounds.west, bounds.north],
      [bounds.east, bounds.north],
      [bounds.east, bounds.south],
      [bounds.west, bounds.south],
    ];
  }

  function endpointUrl(endpoint, workspacePath, params = {}) {
    const query = new URLSearchParams();
    const ws = String(workspacePath || "").trim();
    if (ws) query.set("ws", ws);
    Object.entries(params).forEach(([key, value]) => {
      const text = String(value ?? "").trim();
      if (text) query.set(key, text);
    });
    const suffix = query.toString();
    return suffix ? `${endpoint}?${suffix}` : endpoint;
  }

  function overviewLayer(overview, id) {
    const layers = Array.isArray(overview?.layers) ? overview.layers : [];
    return layers.find(layer => layer?.id === id && layer?.status === "ok") || null;
  }

  function buildMapLibreLayerPlan(overview, workspacePath, options = {}) {
    const ws = workspacePath || overview?.config_path || "";
    const bounds = previewBounds(overview);
    const sources = {};
    const layers = [];
    const demLayer = overviewLayer(overview, "dem");
    const basinLayer = overviewLayer(overview, "basin");
    const zonesLayer = overviewLayer(overview, "elevation_zone");
    const glacierLayer = overviewLayer(overview, "glacier");
    const stationsLayer = overviewLayer(overview, "stations");
    const demBounds = layerBounds(demLayer, bounds);
    const demCoordinates = imageCoordinates(demBounds);

    if (demLayer && demCoordinates) {
      sources.dem = {
        type: "image",
        url: endpointUrl("/api/geo/dem", ws, { style: options.demStyle || "hillshade" }),
        coordinates: demCoordinates,
      };
      layers.push({ id: "dem", type: "raster", source: "dem", paint: { "raster-opacity": 0.88 } });
    }
    if (zonesLayer) {
      sources.elevation_zones = { type: "geojson", data: endpointUrl("/api/geo/elevation-zones", ws) };
      layers.push({
        id: "elevation-zones-fill",
        type: "fill",
        source: "elevation_zones",
        paint: { "fill-color": "#2563eb", "fill-opacity": 0.24 },
      });
    }
    if (glacierLayer) {
      sources.glacier = { type: "geojson", data: endpointUrl("/api/geo/glacier", ws) };
      layers.push({
        id: "glacier-fill",
        type: "fill",
        source: "glacier",
        paint: { "fill-color": "#06b6d4", "fill-opacity": 0.34 },
      });
      layers.push({
        id: "glacier-line",
        type: "line",
        source: "glacier",
        paint: { "line-color": "#0891b2", "line-width": 1.4 },
      });
    }
    if (basinLayer) {
      sources.basin = { type: "geojson", data: endpointUrl("/api/geo/basin", ws) };
      layers.push({
        id: "basin-fill",
        type: "fill",
        source: "basin",
        paint: { "fill-color": "#0e7490", "fill-opacity": 0.08 },
      });
      layers.push({
        id: "basin-line",
        type: "line",
        source: "basin",
        paint: { "line-color": "#0e7490", "line-width": 2 },
      });
    }
    if (stationsLayer) {
      sources.stations = { type: "geojson", data: endpointUrl("/api/geo/stations", ws) };
      layers.push({
        id: "stations",
        type: "circle",
        source: "stations",
        paint: {
          "circle-color": "#b91c1c",
          "circle-radius": 4.5,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.2,
        },
      });
    }
    return {
      version: 8,
      offline: true,
      bounds: bounds ? [[bounds.west, bounds.south], [bounds.east, bounds.north]] : null,
      sources,
      layers,
    };
  }

  function buildMapLibreStyle(overview, workspacePath, options = {}) {
    const plan = buildMapLibreLayerPlan(overview, workspacePath, options);
    return {
      version: 8,
      sources: plan.sources,
      layers: plan.layers,
    };
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
      .filter(layer => layer?.status === "ok" && layer.id !== "dem" && layer.kind !== "point")
      .map(layer => (layer.rings || [])
        .map(ring => pathFromRing(ring, bounds))
        .filter(Boolean)
        .slice(0, 14)
        .map(d => `<path class="geo-layer ${layerCssClass(layer)}" d="${d}"></path>`)
        .join(""))
      .join("");
  }

  function renderLayerPoints(overview, bounds, escapeHtml) {
    const layers = Array.isArray(overview?.layers) ? overview.layers : [];
    return layers
      .filter(layer => layer?.status === "ok" && layer.kind === "point")
      .map(layer => (layer.points || [])
        .slice(0, 120)
        .map(point => {
          const [x, y] = projectPoint(point.coord, bounds);
          const label = point.label || point.id || layer.label || "站点";
          return `<circle class="geo-layer geo-layer-point ${layerCssClass(layer)}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.2"><title>${escapeHtml(label)}</title></circle>`;
        })
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
    const stations = layers.find(layer => layer.id === "stations" && layer.status === "ok");
    const demStats = dem?.metrics?.stats || {};
    const tiles = [
      { label: "有效图层", value: `${Number(overview?.available_layer_count || 0)}/${layers.length || 5}` },
      { label: "流域要素", value: basin?.metrics?.feature_count != null ? String(basin.metrics.feature_count) : "未识别" },
      { label: "DEM 高程", value: demStats.min != null && demStats.max != null ? `${demStats.min} - ${demStats.max} m` : "未统计" },
      { label: "冰川图层", value: glacier ? "已识别" : "未配置" },
      { label: "站点", value: stations?.metrics?.station_count != null ? `${stations.metrics.station_count} 个` : "未配置" },
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
              ${renderLayerPoints(overview, bounds, escapeHtml)}
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
    buildMapLibreLayerPlan,
    buildMapLibreStyle,
    renderOverview,
  };
})();
