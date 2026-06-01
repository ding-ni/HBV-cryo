(function () {
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

  function clampOpacity(value, fallback = 1) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return fallback;
    return Math.max(0, Math.min(1, numeric));
  }

  function roundedOpacity(value) {
    return Math.round(clampOpacity(value, 0) * 1000) / 1000;
  }

  function layerControlState(options, id) {
    const controls = options?.layerControls || {};
    const state = controls[id] || {};
    return {
      visible: state.visible !== false,
      opacity: clampOpacity(state.opacity, 1),
    };
  }

  function layerLayout(control) {
    return { visibility: control.visible ? "visible" : "none" };
  }

  function layerOpacity(baseOpacity, control) {
    return roundedOpacity(baseOpacity * control.opacity);
  }

  function pushLayerControl(controls, id, layer, styleLayerIds, control) {
    controls.push({
      id,
      label: layer?.label || id,
      styleLayerIds,
      visible: control.visible,
      opacity: control.opacity,
    });
  }

  function buildMapLibreLayerPlan(overview, workspacePath, options = {}) {
    const ws = workspacePath || overview?.config_path || "";
    const bounds = previewBounds(overview);
    const sources = {};
    const layers = [];
    const layerControls = [];
    const demLayer = overviewLayer(overview, "dem");
    const basinLayer = overviewLayer(overview, "basin");
    const zonesLayer = overviewLayer(overview, "elevation_zone");
    const glacierLayer = overviewLayer(overview, "glacier");
    const stationsLayer = overviewLayer(overview, "stations");
    const demBounds = layerBounds(demLayer, bounds);
    const demCoordinates = imageCoordinates(demBounds);

    if (demLayer && demCoordinates) {
      const control = layerControlState(options, "dem");
      sources.dem = {
        type: "image",
        url: endpointUrl("/api/geo/dem", ws, { style: options.demStyle || "hillshade" }),
        coordinates: demCoordinates,
      };
      layers.push({
        id: "dem",
        type: "raster",
        source: "dem",
        layout: layerLayout(control),
        paint: { "raster-opacity": layerOpacity(0.88, control) },
      });
      pushLayerControl(layerControls, "dem", demLayer, ["dem"], control);
    }
    if (zonesLayer) {
      const control = layerControlState(options, "elevation_zone");
      sources.elevation_zones = { type: "geojson", data: endpointUrl("/api/geo/elevation-zones", ws) };
      layers.push({
        id: "elevation-zones-fill",
        type: "fill",
        source: "elevation_zones",
        layout: layerLayout(control),
        paint: {
          "fill-color": ["match", ["get", "zone"], "low", "#7fcdbb", "mid", "#38bdf8", "high", "#2563eb", "#64748b"],
          "fill-opacity": layerOpacity(0.24, control),
        },
      });
      pushLayerControl(layerControls, "elevation_zone", zonesLayer, ["elevation-zones-fill"], control);
    }
    if (glacierLayer) {
      const control = layerControlState(options, "glacier");
      sources.glacier = { type: "geojson", data: endpointUrl("/api/geo/glacier", ws) };
      layers.push({
        id: "glacier-fill",
        type: "fill",
        source: "glacier",
        layout: layerLayout(control),
        paint: { "fill-color": "#06b6d4", "fill-opacity": layerOpacity(0.34, control) },
      });
      layers.push({
        id: "glacier-line",
        type: "line",
        source: "glacier",
        layout: layerLayout(control),
        paint: { "line-color": "#0891b2", "line-width": 1.4, "line-opacity": layerOpacity(1, control) },
      });
      pushLayerControl(layerControls, "glacier", glacierLayer, ["glacier-fill", "glacier-line"], control);
    }
    if (basinLayer) {
      const control = layerControlState(options, "basin");
      sources.basin = { type: "geojson", data: endpointUrl("/api/geo/basin", ws) };
      layers.push({
        id: "basin-fill",
        type: "fill",
        source: "basin",
        layout: layerLayout(control),
        paint: { "fill-color": "#0e7490", "fill-opacity": layerOpacity(0.08, control) },
      });
      layers.push({
        id: "basin-line",
        type: "line",
        source: "basin",
        layout: layerLayout(control),
        paint: { "line-color": "#0e7490", "line-width": 2, "line-opacity": layerOpacity(1, control) },
      });
      pushLayerControl(layerControls, "basin", basinLayer, ["basin-fill", "basin-line"], control);
    }
    if (stationsLayer) {
      const control = layerControlState(options, "stations");
      sources.stations = { type: "geojson", data: endpointUrl("/api/geo/stations", ws) };
      layers.push({
        id: "stations",
        type: "circle",
        source: "stations",
        layout: layerLayout(control),
        paint: {
          "circle-color": [
            "match",
            ["get", "station_type"],
            "rain",
            "#2563eb",
            "hydrology",
            "#0e7490",
            "outlet",
            "#dc2626",
            "#475569",
          ],
          "circle-radius": [
            "match",
            ["get", "station_type"],
            "outlet",
            6.2,
            "hydrology",
            5.2,
            "rain",
            4.6,
            4.2,
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.2,
          "circle-opacity": layerOpacity(1, control),
          "circle-stroke-opacity": layerOpacity(1, control),
        },
      });
      pushLayerControl(layerControls, "stations", stationsLayer, ["stations"], control);
    }
    return {
      version: 8,
      offline: true,
      bounds: bounds ? [[bounds.west, bounds.south], [bounds.east, bounds.north]] : null,
      sources,
      layers,
      layerControls,
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

  window.HBVStudioMapLayerPlan = {
    buildMapLibreLayerPlan,
    buildMapLibreStyle,
  };
})();
