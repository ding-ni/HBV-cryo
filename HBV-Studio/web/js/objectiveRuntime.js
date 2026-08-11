(function () {
  function objectiveLabel(value = "") {
    return ({
      auto: "自动选择",
      daily_unified_professional_v1: "统一日尺度专业目标函数",
      flood_event_calibration_v1: "场次洪水目标函数",
      weighted_multi_criteria: "旧版多指标目标函数（历史结果）",
      weighted_daily_universal: "旧版日尺度加权目标函数（历史结果）",
      single_objective_nse: "单指标纳什效率系数",
    })[String(value || "").toLowerCase()] || String(value || "未设置");
  }

  function effectiveObjectiveMode(meta = {}) {
    const normalizedMode = String(meta?.effective_objective_mode || meta?.optimization?.effective_objective_mode || "").trim().toLowerCase();
    if (normalizedMode) return normalizedMode;
    const profileMode = String(meta?.objective_profile?.type || meta?.objective?.type || "").trim().toLowerCase();
    if (profileMode) return profileMode;
    return String(meta?.optimization?.objective_mode || "").trim().toLowerCase();
  }

  function requestedObjectiveMode(meta = {}) {
    return String(meta?.requested_objective_mode || meta?.optimization?.requested_objective_mode || meta?.optimization?.objective_mode || "").trim().toLowerCase();
  }

  function objectiveDetail(meta = {}) {
    const mode = effectiveObjectiveMode(meta) || meta?.objective_family || meta?.objective_profile?.type || meta?.objective?.type;
    const normalized = String(mode || "").toLowerCase();
    if (normalized === "daily_unified_professional_v1") {
      return "流量拟合优先，结合融雪、融冰、洪峰和退水过程进行综合评价";
    }
    if (normalized === "flood_event_calibration_v1") {
      return "按场次洪水窗口评价洪峰流量、峰现时间、洪量、退水过程和高流量过程；连续状态多场洪水保持事件间状态连续";
    }
    if (new Set(["weighted_daily_universal", "weighted_multi_criteria"]).has(normalized)) {
      return "历史结果，仅作兼容查看，建议用当前口径重算后再解释冰雪融水过程";
    }
    return "";
  }

  function objectiveSummary(meta = {}) {
    return [objectiveLabel(effectiveObjectiveMode(meta) || "—"), objectiveDetail(meta)].filter(Boolean).join(" · ");
  }

  window.HBVStudioObjectiveRuntime = {
    effectiveObjectiveMode,
    objectiveDetail,
    objectiveLabel,
    objectiveSummary,
    requestedObjectiveMode,
  };
})();
