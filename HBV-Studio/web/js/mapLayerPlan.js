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
        paint: {
          "fill-color": ["match", ["get", "zone"], "low", "#7fcdbb", "mid", "#38bdf8", "high", "#2563eb", "#64748b"],
          "fill-opacity": 0.24,
        },
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

  window.HBVStudioMapLayerPlan = {
    buildMapLibreLayerPlan,
    buildMapLibreStyle,
  };
})();
