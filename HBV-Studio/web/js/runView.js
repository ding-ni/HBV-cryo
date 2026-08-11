(function () {
  const RUN_TYPE_LABELS = Object.freeze({
    manual_starter: "手调起点",
    manual_result: "手调结果",
    forecast_restart: "连续状态预报",
    calibration: "正式率定",
    legacy: "历史结果",
  });
  const CURRENT_OBJECTIVE_FAMILY = "daily_unified_professional_v1";
  const CURRENT_HOURLY_OBJECTIVE_FAMILY = "hourly_alpine_qtp_v1";
  const CURRENT_OBJECTIVE_FAMILIES = new Set([
    CURRENT_OBJECTIVE_FAMILY,
    CURRENT_HOURLY_OBJECTIVE_FAMILY,
  ]);
  const FLOOD_EVENT_OBJECTIVE_FAMILY = "flood_event_calibration_v1";
  const LEGACY_OBJECTIVE_FAMILIES = new Set(["weighted_daily_universal", "weighted_multi_criteria"]);

  function defaultEscapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function defaultFormatDateTime(value) {
    if (!value) return "\u2014";
    const date = new Date(Number(value) * 1000 || value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function defaultShortPath(value) {
    if (!value) return "\u2014";
    return String(value).replace(/\\/g, "/").replace(/^.*\/([^/]+)$/, "$1");
  }

  function runTypeValue(run) {
    const direct = String(run?.run_type || "").trim().toLowerCase();
    if (direct) return direct;
    return run?.studio_compatible ? "calibration" : "legacy";
  }

  function runTypeLabel(value, fallback = "") {
    const key = String(value || "").trim().toLowerCase();
    return RUN_TYPE_LABELS[key] || fallback || "结果";
  }

  function isGeneratedRunName(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    return /^hbv_(cryo|forecast|manual|calib|run)(_|$)/i.test(text)
      || /_\d{8}_\d{6}(_|$)/.test(text);
  }

  function runWorkspaceName(run, helpers = {}) {
    const workspaceLabelByPath = helpers.workspaceLabelByPath || defaultShortPath;
    return String(run?.workspace_name || "").trim() || workspaceLabelByPath(run?.workspace_config);
  }

  function runTimeText(run, helpers = {}) {
    const formatDateTime = helpers.formatDateTime || defaultFormatDateTime;
    return String(run?.run_time_label || run?.run_time || "").trim() || formatDateTime(run?.updated_at);
  }

  function runDisplayName(run, helpers = {}) {
    const explicit = String(run?.result_title || run?.display_name || "").trim();
    if (explicit && !isGeneratedRunName(explicit)) {
      return explicit.replace(/状态接续预报/g, "连续状态预报").trim();
    }
    const rawName = String(run?.name || "").trim();
    if (rawName && !isGeneratedRunName(rawName)) {
      return rawName.replace(/状态接续预报/g, "连续状态预报").trim();
    }
    const workspace = runWorkspaceName(run, helpers);
    const type = runTypeLabel(runTypeValue(run), "结果");
    const time = runTimeText(run, helpers);
    return [workspace && workspace !== "未命名工作区" ? workspace : "", type, time]
      .filter(Boolean)
      .join(" · ") || "未命名结果";
  }

  function compactTimeText(value, stepHours = 24) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (stepHours <= 1.5) return text.replace("T", " ");
    return text.slice(0, 10);
  }

  function timeRangeText(start, end, stepHours = 24) {
    const left = compactTimeText(start, stepHours);
    const right = compactTimeText(end, stepHours);
    if (left && right) return `${left} ~ ${right}`;
    return left || right || "\u2014";
  }

  function forecastFriendlyRunName(run, helpers = {}) {
    const raw = runDisplayName(run, helpers);
    if (raw && !isGeneratedRunName(raw)) return raw;
    const type = runTypeLabel(runTypeValue(run));
    const stepHours = Number(run?.time_step_hours || run?.time_config?.time_step_hours || 24);
    const forecastRange = timeRangeText(run?.time_config?.forecast_start, run?.time_config?.forecast_end, stepHours);
    if (runTypeValue(run) === "forecast_restart" && forecastRange !== "\u2014") {
      return `${type} · ${forecastRange}`;
    }
    const workspace = runWorkspaceName(run, helpers);
    if (workspace && workspace !== "未命名工作区") return `${workspace} · ${type}`;
    const stateTime = run?.state_snapshot_time || run?.time_config?.valid_end || run?.time_config?.calib_end || "";
    return stateTime ? `${type} · 状态 ${compactTimeText(stateTime, stepHours)}` : type;
  }

  function readableRunReferenceName(value, fallback = "") {
    const raw = String(value || "").trim();
    if (!raw) return String(fallback || "").trim();
    return isGeneratedRunName(raw) ? String(fallback || "").trim() : raw;
  }

  function runDisplaySubtitle(run) {
    const text = String(run?.display_subtitle || "").trim();
    if (!text) return "";
    const directoryName = text.replace(/^目录名[:：]\s*/i, "").trim();
    if (isGeneratedRunName(directoryName)) return "";
    return text;
  }

  function runEditabilityLabel(run) {
    return run?.studio_compatible ? "可继续手调" : "仅查看";
  }

  function runMetricsText(run) {
    const cfg = run?.time_config || {};
    const stepHours = Number(cfg.time_step_hours || run?.time_step_hours || 24);
    const start = String(cfg.warmup_start || cfg.calib_start || "").trim();
    const end = String(cfg.valid_end || cfg.calib_end || "").trim();
    if (!start && !end) return "";
    return `全时段${cfg.warmup_start ? "（含预热）" : ""}：${timeRangeText(start, end, stepHours)}`;
  }

  function runTypeBadge(run, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const label = runTypeLabel(runTypeValue(run), String(run?.run_type_label || "").trim());
    return `<span class="status-badge status-type">${escapeHtml(label)}</span>`;
  }

  function objectiveFamilyKey(metaOrRun = {}) {
    return String(
      metaOrRun?.recorded_objective_family
      || metaOrRun?.objective_family
      || metaOrRun?.effective_objective_mode
      || metaOrRun?.optimization?.effective_objective_mode
      || metaOrRun?.objective_profile?.type
      || metaOrRun?.objective?.type
      || ""
    ).trim().toLowerCase();
  }

  function objectiveVersionStatus(metaOrRun = {}, options = {}) {
    const family = objectiveFamilyKey(metaOrRun);
    const currentFamily = String(options.currentObjectiveFamily || CURRENT_OBJECTIVE_FAMILY).toLowerCase();
    const currentFamilies = new Set(CURRENT_OBJECTIVE_FAMILIES);
    currentFamilies.add(currentFamily);
    for (const value of options.currentObjectiveFamilies || []) {
      const normalized = String(value || "").trim().toLowerCase();
      if (normalized) currentFamilies.add(normalized);
    }
    const eventFamily = String(options.floodEventObjectiveFamily || FLOOD_EVENT_OBJECTIVE_FAMILY).toLowerCase();
    const legacyFamilies = options.legacyObjectiveFamilies || LEGACY_OBJECTIVE_FAMILIES;
    if (currentFamilies.has(family)) {
      const isHourly = family === CURRENT_HOURLY_OBJECTIVE_FAMILY;
      return {
        state: "current",
        label: "当前口径",
        value: isHourly ? "当前小时尺度综合评价口径" : "当前日尺度综合评价口径",
        detail: isHourly
          ? "该结果使用当前小时尺度高寒区综合评价口径，可用于小时径流拟合与冰雪融水过程复核。"
          : "该结果使用当前统一日尺度水文评价口径，可用于径流拟合与冰雪融水过程复核。",
        badgeClass: "status-ok",
      };
    }
    if (family === eventFamily) {
      return {
        state: "current",
        label: "场次洪水口径",
        value: "场次洪水评价结果",
        detail: "该结果按场次洪水窗口评价；连续状态工作流在场次之间连续传递模型状态，逐场独立工作流仅用于具有可靠初始状态的专项模拟。",
        badgeClass: "status-ok",
      };
    }
    if (legacyFamilies.has(family)) {
      return {
        state: "legacy",
        label: "历史口径",
        value: "历史计算结果",
        detail: "该结果来自旧版计算口径，适合兼容查看；冰雪融水解释应以当前口径重新计算结果为准。",
        badgeClass: "status-warn",
      };
    }
    return {
      state: "unknown",
      label: "口径未明",
      value: "评价口径未记录",
      detail: "结果未记录评价口径，冰雪融水解释仅作兼容查看。",
      badgeClass: "status-warn",
    };
  }

  function objectiveVersionBadge(run, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const status = objectiveVersionStatus(run, helpers);
    return `<span class="status-badge ${status.badgeClass}">${escapeHtml(status.label)}</span>`;
  }

  window.HBVStudioRunView = {
    compactTimeText,
    forecastFriendlyRunName,
    isGeneratedRunName,
    objectiveFamilyKey,
    objectiveVersionBadge,
    objectiveVersionStatus,
    readableRunReferenceName,
    runDisplayName,
    runDisplaySubtitle,
    runEditabilityLabel,
    runMetricsText,
    runTimeText,
    runTypeBadge,
    runTypeLabel,
    runTypeValue,
    runWorkspaceName,
    timeRangeText,
  };
})();
