(function () {
  const CHART_COLORS = Object.freeze({
    qObs: "#1e293b",
    qSim: "#0e7490",
    qRain: "#2563eb",
    qSnow: "#38bdf8",
    qIce: "#06b6d4",
    boundary: "#64748b",
    residual: "#b91c1c",
    precip: "#2563eb",
    temp: "#ef4444",
  });

  function chartColors() {
    return CHART_COLORS;
  }

  window.HBVStudioChartPalette = {
    chartColors,
  };
})();
