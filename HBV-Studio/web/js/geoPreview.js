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

  function layerKey(layer) {
    const id = String(layer?.id || "").replace(/[^a-z0-9_-]/gi, "");
    return id || "generic";
  }

  function layerCssClass(layer) {
    const id = layerKey(layer);
    return id ? `geo-layer-${id}` : "geo-layer-generic";
  }

  function layerToggleClass(layer) {
    return `geo-layer-toggle-${layerKey(layer)}`;
  }

  function stationTypeMeta(type) {
    const key = String(type || "station").trim().toLowerCase();
    if (key === "rain") return { key, label: "雨量站", symbol: "△", radius: 5.4 };
    if (key === "hydrology") return { key, label: "水文站", symbol: "◇", radius: 5.6 };
    if (key === "outlet") return { key, label: "出口站", symbol: "★", radius: 6.4 };
    return { key: "station", label: "站点", symbol: "●", radius: 4.4 };
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

  function formatCoordinate(value, axis) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "";
    const suffix = axis === "lon" ? (numeric >= 0 ? "E" : "W") : (numeric >= 0 ? "N" : "S");
    return `${Math.abs(numeric).toFixed(3)}°${suffix}`;
  }

  function haversineKm(lon1, lat1, lon2, lat2) {
    const toRad = value => (Number(value) * Math.PI) / 180;
    const radiusKm = 6371.0088;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2
      + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return 2 * radiusKm * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0, 1 - a)));
  }

  function scaleLabel(bounds) {
    const centerLat = (bounds.south + bounds.north) / 2;
    const widthKm = haversineKm(bounds.west, centerLat, bounds.east, centerLat);
    if (!Number.isFinite(widthKm) || widthKm <= 0) return "";
    const scaleKm = Math.max(1, widthKm / 5);
    return scaleKm >= 100 ? `${Math.round(scaleKm)} km` : `${scaleKm.toFixed(scaleKm >= 10 ? 0 : 1)} km`;
  }

  function renderCoordinateFrame(bounds, escapeHtml) {
    const label = scaleLabel(bounds);
    return `
      <g class="geo-coordinate-frame" aria-hidden="true">
        <text class="geo-coordinate-label geo-coordinate-label-west" x="28" y="292">${escapeHtml(formatCoordinate(bounds.west, "lon"))}</text>
        <text class="geo-coordinate-label geo-coordinate-label-east" x="612" y="292" text-anchor="end">${escapeHtml(formatCoordinate(bounds.east, "lon"))}</text>
        <text class="geo-coordinate-label geo-coordinate-label-north" x="28" y="38">${escapeHtml(formatCoordinate(bounds.north, "lat"))}</text>
        <text class="geo-coordinate-label geo-coordinate-label-south" x="28" y="270">${escapeHtml(formatCoordinate(bounds.south, "lat"))}</text>
        ${label ? `
          <g class="geo-scale-bar">
            <line x1="484" y1="270" x2="604" y2="270"></line>
            <line x1="484" y1="265" x2="484" y2="274"></line>
            <line x1="604" y1="265" x2="604" y2="274"></line>
            <text x="544" y="263" text-anchor="middle">${escapeHtml(label)}</text>
          </g>
        ` : ""}
      </g>
    `;
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

  function trianglePath(x, y, radius) {
    return [
      `M${x.toFixed(1)},${(y - radius).toFixed(1)}`,
      `L${(x - radius).toFixed(1)},${(y + radius).toFixed(1)}`,
      `L${(x + radius).toFixed(1)},${(y + radius).toFixed(1)}`,
      "Z",
    ].join(" ");
  }

  function diamondPath(x, y, radius) {
    return [
      `M${x.toFixed(1)},${(y - radius).toFixed(1)}`,
      `L${(x + radius).toFixed(1)},${y.toFixed(1)}`,
      `L${x.toFixed(1)},${(y + radius).toFixed(1)}`,
      `L${(x - radius).toFixed(1)},${y.toFixed(1)}`,
      "Z",
    ].join(" ");
  }

  function starPath(x, y, radius) {
    const inner = radius * 0.48;
    const points = [];
    for (let i = 0; i < 10; i += 1) {
      const angle = -Math.PI / 2 + (i * Math.PI) / 5;
      const r = i % 2 === 0 ? radius : inner;
      points.push([
        (x + Math.cos(angle) * r).toFixed(1),
        (y + Math.sin(angle) * r).toFixed(1),
      ]);
    }
    return points.map((point, index) => `${index === 0 ? "M" : "L"}${point[0]},${point[1]}`).join(" ") + " Z";
  }

  function renderStationSymbol(point, layer, bounds, escapeHtml) {
    const [x, y] = projectPoint(point.coord, bounds);
    const label = point.label || point.id || layer.label || "站点";
    const meta = stationTypeMeta(point.station_type);
    const typeLabel = point.station_type_label || meta.label;
    const title = `${label} · ${typeLabel}`;
    const className = `geo-layer geo-layer-point ${layerCssClass(layer)} geo-station-type-${meta.key}`;
    if (meta.key === "rain") {
      return `<path class="${className}" d="${trianglePath(x, y, meta.radius)}"><title>${escapeHtml(title)}</title></path>`;
    }
    if (meta.key === "hydrology") {
      return `<path class="${className}" d="${diamondPath(x, y, meta.radius)}"><title>${escapeHtml(title)}</title></path>`;
    }
    if (meta.key === "outlet") {
      return `<path class="${className}" d="${starPath(x, y, meta.radius)}"><title>${escapeHtml(title)}</title></path>`;
    }
    return `<circle class="${className}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${meta.radius}"><title>${escapeHtml(title)}</title></circle>`;
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
        .map(point => renderStationSymbol(point, layer, bounds, escapeHtml))
        .join(""))
      .join("");
  }

  function renderLayerToggles(overview, escapeHtml) {
    const layers = Array.isArray(overview?.layers) ? overview.layers : [];
    const drawableLayers = layers.filter(layer => {
      if (layer?.status !== "ok") return false;
      if (layer.id === "dem") return true;
      if (layer.kind === "point") return Array.isArray(layer.points) && layer.points.length > 0;
      return Array.isArray(layer.rings) && layer.rings.length > 0;
    });
    if (!drawableLayers.length) return "";
    return `
      <div class="geo-layer-control-bar" role="group" aria-label="图层">
        ${drawableLayers.map(layer => `
          <label class="geo-layer-control ${layerCssClass(layer)}">
            <input class="geo-layer-toggle ${layerToggleClass(layer)}" type="checkbox" checked data-geo-layer-toggle="${escapeHtml(layerKey(layer))}">
            <span>${escapeHtml(layer.label || layer.id || "图层")}</span>
          </label>
        `).join("")}
      </div>
    `;
  }

  function renderStationTypeLegend(layer, escapeHtml) {
    const counts = layer?.metrics?.station_type_counts || {};
    const items = ["rain", "hydrology", "outlet", "station"]
      .map(type => {
        const count = Number(counts[type] || 0);
        if (!count) return "";
        const meta = stationTypeMeta(type);
        return `
          <span class="geo-station-type-item">
            <span class="geo-station-symbol geo-station-type-${meta.key}">${escapeHtml(meta.symbol)}</span>
            <span>${escapeHtml(meta.label)} ${escapeHtml(String(count))}</span>
          </span>
        `;
      })
      .filter(Boolean)
      .join("");
    return items ? `<div class="geo-station-type-legend">${items}</div>` : "";
  }

  function renderLegend(overview, escapeHtml) {
    const layers = Array.isArray(overview?.layers) ? overview.layers : [];
    return layers.map(layer => `
      <div class="geo-preview-legend-item">
        <span class="geo-preview-swatch ${layerCssClass(layer)}"></span>
        <div>
          <strong>${escapeHtml(layer.label || "")}</strong>
          <span class="status-badge ${layerStatusClass(layer)}">${escapeHtml(layer.status === "ok" ? layer.message || "已识别" : layer.message || "未识别")}</span>
          ${layer.id === "stations" ? renderStationTypeLegend(layer, escapeHtml) : ""}
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
            ${renderLayerToggles(overview, escapeHtml)}
            <svg class="geo-preview-svg" viewBox="0 0 640 300" role="img" aria-label="工作区空间预览">
              <rect class="geo-preview-frame" x="1" y="1" width="638" height="298" rx="4"></rect>
              ${hasDem ? '<rect class="geo-layer geo-layer-dem" x="26" y="26" width="588" height="248" rx="3"></rect>' : ""}
              ${renderLayerPaths(overview, bounds)}
              ${renderLayerPoints(overview, bounds, escapeHtml)}
              ${renderCoordinateFrame(bounds, escapeHtml)}
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
